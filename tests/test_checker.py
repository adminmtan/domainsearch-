from unittest.mock import patch, MagicMock
import requests
from checker import check_domains, check_domains_with_errors


def _mock_resp(status_code: int, payload):
    fake = MagicMock()
    fake.status_code = status_code
    fake.text = str(payload)[:200]
    fake.json.return_value = payload
    return fake


def test_check_domains_parses_available():
    """Happy path: whois endpoint returns status='available'."""
    with patch(
        "checker.requests.get",
        return_value=_mock_resp(200, {"domain": "foo.com", "status": "available"}),
    ):
        result = check_domains(["foo.com"])
    assert result == {"foo.com": "available"}


def test_check_domains_parses_registered():
    with patch(
        "checker.requests.get",
        return_value=_mock_resp(200, {"domain": "foo.com", "status": "registered"}),
    ):
        result = check_domains(["foo.com"])
    assert result == {"foo.com": "registered"}


def test_check_domains_http_error_returns_unknown_with_reason():
    """Bug from user: every domain came back [unknown] with NO error info.

    The old checker silently swallowed 404s. New checker must surface the
    status code + response snippet so users can see WHY a domain is unknown.
    """
    with patch(
        "checker.requests.get",
        return_value=_mock_resp(404, "404 page not found"),
    ):
        statuses, errors = check_domains_with_errors(["foo.com"])
    assert statuses == {"foo.com": "unknown"}
    assert "foo.com" in errors
    assert "HTTP 404" in errors["foo.com"]


def test_check_domains_timeout_returns_unknown_with_reason():
    with patch("checker.requests.get", side_effect=requests.Timeout):
        statuses, errors = check_domains_with_errors(["foo.com"], timeout=0.1)
    assert statuses == {"foo.com": "unknown"}
    assert "timeout" in errors["foo.com"].lower()


def test_check_domains_invalid_json_returns_unknown_with_reason():
    bad_json = MagicMock()
    bad_json.status_code = 200
    bad_json.text = "<html>not json</html>"
    bad_json.json.side_effect = ValueError("not JSON")
    with patch("checker.requests.get", return_value=bad_json):
        statuses, errors = check_domains_with_errors(["foo.com"])
    assert statuses == {"foo.com": "unknown"}
    assert "JSON" in errors["foo.com"] or "json" in errors["foo.com"]


def test_check_domains_unexpected_status_value_returns_unknown_with_reason():
    """dmcheck sometimes returns extra states; we don't crash, we tell user."""
    with patch(
        "checker.requests.get",
        return_value=_mock_resp(200, {"domain": "foo.com", "status": "maybe"}),
    ):
        statuses, errors = check_domains_with_errors(["foo.com"])
    assert statuses == {"foo.com": "unknown"}
    assert "unexpected status" in errors["foo.com"]


def test_check_domains_uses_per_domain_whois_endpoint():
    """The bug: checker hit /api/check (404). Fix: hit /api/whois/<domain>."""
    with patch(
        "checker.requests.get",
        return_value=_mock_resp(200, {"domain": "foo.com", "status": "available"}),
    ) as mock_get:
        check_domains(["foo.com"])
    called_url = mock_get.call_args.args[0]
    assert called_url == "https://dmcheck.app/api/whois/foo.com"


def test_check_domains_dedupes_input():
    """Duplicate domains in the list should result in one request each."""
    with patch(
        "checker.requests.get",
        return_value=_mock_resp(200, {"domain": "foo.com", "status": "available"}),
    ) as mock_get:
        statuses, errors = check_domains_with_errors(["foo.com", "foo.com", "bar.com"])
    assert statuses == {"foo.com": "available", "bar.com": "available"}
    # 2 unique domains → 2 requests
    assert mock_get.call_count == 2


def test_check_domains_parallel_uses_threadpool():
    """Sequential N requests would take N * RTT. We must parallelize."""
    import time
    # Each "request" sleeps 0.5s. With 3 domains, sequential = 1.5s, parallel ~0.5s.
    def slow(*a, **kw):
        time.sleep(0.5)
        return _mock_resp(200, {"domain": a[0].split("/")[-1], "status": "available"})
    with patch("checker.requests.get", side_effect=slow):
        t0 = time.time()
        statuses, _ = check_domains_with_errors(["a.com", "b.com", "c.com"], timeout=5.0)
        elapsed = time.time() - t0
    assert statuses == {"a.com": "available", "b.com": "available", "c.com": "available"}
    # Parallel: should be well under 1.5s (sequential); allow 1.2s for safety.
    assert elapsed < 1.2, f"requests ran sequentially? took {elapsed:.2f}s"


def test_check_domains_one_failure_does_not_kill_batch():
    """A single network error must not poison other domains' results."""
    def side_effect(url, **kw):
        if "foo" in url:
            raise requests.ConnectionError("refused")
        return _mock_resp(200, {"domain": url.split("/")[-1], "status": "registered"})
    with patch("checker.requests.get", side_effect=side_effect):
        statuses, errors = check_domains_with_errors(["foo.com", "bar.com"])
    assert statuses == {"foo.com": "unknown", "bar.com": "registered"}
    assert "foo.com" in errors
    assert "bar.com" not in errors


def test_check_domains_empty_input():
    """No domains → empty results, no requests fired."""
    with patch("checker.requests.get") as mock_get:
        statuses, errors = check_domains_with_errors([])
    assert statuses == {}
    assert errors == {}
    assert mock_get.call_count == 0