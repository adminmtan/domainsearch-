"""dmcheck.app client.

Queries domain availability via dmcheck.app via its real per-domain whois
endpoint. Each call hits https://dmcheck.app/api/whois/<domain> which returns
a JSON object describing registration status.

Earlier this module hit `/api/check` which returns 404; the app would silently
fall back to "unknown" for every domain. That was a hidden bug for users. The
endpoints and shapes here are now verified against the dmcheck.app frontend
source (Oct 2026): `fetch('/api/whois/' + encodeURIComponent(domain))`.
"""
from __future__ import annotations

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

DomainStatus = Literal["available", "registered", "reserved", "unknown"]

BASE_URL = "https://dmcheck.app"
WHOIS_PATH = "/api/whois/"  # NB: trailing slash — concatenate with domain

# Max parallel requests. dmcheck.app is a Cloudflare-fronted whois service;
# we cap workers to avoid hammering the host with 50 concurrent requests.
MAX_WORKERS = 8

# Per-request timeout (seconds). Generous because whois can be slow.
REQUEST_TIMEOUT = 6.0

VALID_STATUSES = ("available", "registered", "reserved", "unknown")


def check_domains(domains: list[str], tlds: list[str] | None = None,
                  timeout: float = REQUEST_TIMEOUT) -> dict[str, DomainStatus]:
    """Check availability of each full domain.

    Args:
        domains: full domain names like ["mythforge.com"].
        tlds:    unused by current dmcheck shape, kept for API compatibility
                 with the plan. Pass-through if present.
        timeout: per-request timeout in seconds.

    Returns:
        {domain: status} for every input domain.

    Failure semantics:
        Any HTTP / network / parse error for a single domain falls back to
        "unknown" for THAT domain (not the whole batch). The reason for the
        fallback is captured by attaching it as a side-channel: see
        check_domains_with_errors() for the rich variant used by the SSE
        pipeline — the plain dict shape stays for backwards compatibility.
    """
    statuses, _errors = check_domains_with_errors(domains, tlds=tlds, timeout=timeout)
    return statuses


def check_domains_with_errors(
    domains: list[str],
    tlds: list[str] | None = None,
    timeout: float = REQUEST_TIMEOUT,
) -> tuple[dict[str, DomainStatus], dict[str, str]]:
    """Variant of check_domains() that also returns per-domain error reasons.

    Returns:
        (statuses, errors) where:
            statuses: {domain: DomainStatus} — "unknown" on any failure
            errors:   {domain: error_message} — only present for failed domains
    """
    seen: set[str] = set()
    unique: list[str] = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            unique.append(d)

    statuses: dict[str, DomainStatus] = {d: "unknown" for d in unique}
    errors: dict[str, str] = {}
    if not unique:
        return statuses, errors

    # Parallel per-domain requests. dmcheck.app expects one domain per call,
    # so we fan out and gather. ThreadPoolExecutor plays well with the
    # synchronous Flask generator (no event loop needed).
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(unique))) as ex:
        future_to_domain = {
            ex.submit(_check_one, d, timeout): d for d in unique
        }
        for fut in as_completed(future_to_domain):
            domain = future_to_domain[fut]
            try:
                status, err = fut.result()
            except Exception as e:  # never let one bad domain kill the batch
                status, err = "unknown", f"worker error: {type(e).__name__}: {e}"
            statuses[domain] = status
            if err:
                errors[domain] = err

    return statuses, errors


def _check_one(domain: str, timeout: float) -> tuple[DomainStatus, str]:
    """Hit dmcheck.app whois endpoint for a single domain.

    Returns (status, error_message). error_message is "" on success.
    """
    url = f"{BASE_URL}{WHOIS_PATH}{domain}"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.Timeout:
        return "unknown", f"timeout after {timeout}s"
    except requests.RequestException as e:
        return "unknown", f"network error: {type(e).__name__}: {e}"

    if resp.status_code != 200:
        # Surface the HTTP status so the user can see WHY a domain is unknown
        # (404 endpoint wrong, 403 blocked, 5xx upstream, etc.).
        snippet = resp.text[:120].replace("\n", " ")
        return "unknown", f"HTTP {resp.status_code}: {snippet}"

    try:
        data = resp.json()
    except ValueError as e:
        return "unknown", f"invalid JSON: {e}"

    if not isinstance(data, dict):
        return "unknown", "response is not a JSON object"

    status = data.get("status")
    if status not in VALID_STATUSES:
        # dmcheck sometimes returns extra states; fall back but tell the user.
        return "unknown", f"unexpected status value: {status!r}"

    return status, ""  # type: ignore[return-value]