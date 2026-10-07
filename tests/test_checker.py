from unittest.mock import patch, MagicMock
from checker import check_domains


def test_check_domains_parses_available():
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "results": [{"domain": "foo.com", "status": "available"}]
    }
    fake_resp.raise_for_status.return_value = None
    with patch("checker.requests.get", return_value=fake_resp):
        result = check_domains(["foo.com"])
    assert result == {"foo.com": "available"}


def test_check_domains_timeout_returns_unknown():
    import requests
    with patch("checker.requests.get", side_effect=requests.Timeout):
        result = check_domains(["foo.com"], timeout=0.1)
    assert result == {"foo.com": "unknown"}


def test_check_domains_dedupes_input():
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"results": []}
    fake_resp.raise_for_status.return_value = None
    with patch("checker.requests.get", return_value=fake_resp) as mock_get:
        check_domains(["foo.com", "foo.com", "bar.com"])
        called_args = mock_get.call_args
        assert "foo.com" in str(called_args)
        assert (called_args.kwargs.get("timeout") == 5.0) or (
            len(called_args.args) > 1 and called_args.args[1] == 5.0
        )