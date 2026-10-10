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

import time
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


# 原地重试参数：每个 unknown 域名最多重试 2 次，退避 1s/3s。
# 总调用次数 = 1（原始）+ 2（重试）= 3 次。
# 设计理由：dmcheck 偶发超时（限流/网络抖动）很常见；给一两次机会基本能救回来，
# 仍然失败说明这个域名本轮拿不到结果，保留 unknown 让用户可见，不要无限拖。
IN_PLACE_RETRY_DELAYS_S: tuple[float, ...] = (1.0, 3.0)


def retry_unknown_domains(
    domains: list[str],
    *,
    timeout: float = REQUEST_TIMEOUT,
    delays: tuple[float, ...] = IN_PLACE_RETRY_DELAYS_S,
    sleep: "callable" = time.sleep,
    tlds: list[str] | None = None,
    check_fn: "callable" = check_domains_with_errors,
) -> tuple[dict[str, DomainStatus], dict[str, str], int]:
    """对一组域名做原地重试，只针对 status == "unknown" 的域名。

    每个 (domain, delay) 独立调用一次 ``check_fn`` 并行发起；
    每个 delay 前先 ``sleep(delay)``，作为退避。

    Args:
        domains: 待重试的完整域名（必须已确认上一轮是 unknown）
        timeout: 每次请求超时
        delays:  重试前等待时长元组（长度 = 最大重试次数）
        sleep:   注入用的 sleep 函数，便于测试时禁用
        tlds:    透传给 check_fn（默认 None）
        check_fn: 注入的检测函数（默认 check_domains_with_errors），
                 便于测试时 mock（app.py 会传 app.check_domains_with_errors
                 以便测试 mock 上层时同时覆盖 retry 路径）

    Returns:
        (new_statuses, new_errors, attempts_performed) where:
            new_statuses: 已解析到的覆盖原 unknown，仍未解析到的保持 "unknown"
            new_errors:   仍失败的带错误信息；成功的清除
            attempts_performed: 实际发起的 dmcheck 轮次数（即 len(delays) 或更少）
    """
    new_statuses: dict[str, DomainStatus] = {}
    new_errors: dict[str, str] = {}
    attempts = 0
    if not domains:
        return new_statuses, new_errors, 0

    pending = list(domains)
    for delay in delays:
        sleep(delay)
        attempts += 1
        if not pending:
            break
        # 走注入的 check_fn（与初次检测同路径），便于测试 mock 统一
        rt_statuses, rt_errors = check_fn(
            pending, tlds=tlds, timeout=timeout,
        )
        for d in pending:
            status = rt_statuses.get(d, "unknown")
            new_statuses[d] = status
            err = rt_errors.get(d)
            if err:
                new_errors[d] = err
            else:
                # 成功的清除旧 unknown 错误（如果有）
                new_errors.pop(d, None)
        # 本轮已解析的不进入下一轮（节省调用）
        pending = [d for d in pending if new_statuses.get(d, "unknown") == "unknown"]

    return new_statuses, new_errors, attempts