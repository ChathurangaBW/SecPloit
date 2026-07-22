from __future__ import annotations

import pytest

from runner.browser_cli import safe_url, same_origin, slug


def test_safe_url_accepts_http_and_strips_fragment() -> None:
    assert safe_url("http://dvwa/login.php#form") == "http://dvwa/login.php"


def test_safe_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="Credentials"):
        safe_url("http://admin:password@dvwa/")


def test_safe_url_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="http or https"):
        safe_url("file:///etc/passwd")


def test_same_origin_is_strict_about_port_and_scheme() -> None:
    assert same_origin("http://dvwa/a", "http://dvwa/b")
    assert not same_origin("http://dvwa/a", "https://dvwa/b")
    assert not same_origin("http://dvwa/a", "http://dvwa:8080/b")


def test_slug_is_stable_and_path_derived() -> None:
    first = slug("http://dvwa/vulnerabilities/sqli/?id=1")
    second = slug("http://dvwa/vulnerabilities/sqli/?id=1")
    assert first == second
    assert first.startswith("vulnerabilities_sqli-")
