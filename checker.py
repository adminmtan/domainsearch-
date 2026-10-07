"""dmcheck.app client.

Queries domain availability via dmcheck.app. Falls back to "unknown" on any
network error so the caller can decide how to handle it.
"""
from __future__ import annotations

import requests
from typing import Literal

DomainStatus = Literal["available", "registered", "reserved", "unknown"]

# Note: actual dmcheck.app endpoint confirmed at implementation time.
# If the endpoint differs, adjust BASE_URL and the request shape below.
BASE_URL = "https://dmcheck.app/api/check"


def check_domains(domains: list[str], tlds: list[str] | None = None,
                  timeout: float = 5.0) -> dict[str, DomainStatus]:
    """Check availability of each full domain.

    Args:
        domains: full domain names like ["mythforge.com"].
        tlds:    unused by current dmcheck shape, kept for API compatibility
                 with the plan. Pass-through if present.
        timeout: request timeout in seconds.

    Returns:
        {domain: status} for every input domain. Unknown status on any failure.
    """
    # Dedupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            unique.append(d)

    result: dict[str, DomainStatus] = {d: "unknown" for d in unique}

    if not unique:
        return result

    try:
        resp = requests.get(
            BASE_URL,
            params={"domains": ",".join(unique)},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.Timeout, requests.RequestException, ValueError):
        return result

    results = data.get("results", []) if isinstance(data, dict) else []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        domain = entry.get("domain")
        status = entry.get("status")
        if isinstance(domain, str) and domain in result:
            if status in ("available", "registered", "reserved", "unknown"):
                result[domain] = status  # type: ignore[assignment]

    return result