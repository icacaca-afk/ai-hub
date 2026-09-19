"""Security and fail-closed contracts for 9Router configuration."""

from __future__ import annotations

import pytest

from providers.nine_router.config import NineRouterConfig


_ENV_KEYS = (
    "NINE_ROUTER_ENABLED",
    "NINE_ROUTER_BASE_URL",
    "NINE_ROUTER_MODEL",
    "NINE_ROUTER_API_KEY",
    "NINE_ROUTER_ALLOW_NO_AUTH",
    "NINE_ROUTER_TOKEN_SAVER",
    "NINE_ROUTER_TIMEOUT",
)


@pytest.fixture(autouse=True)
def clean_nine_router_environment(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _enable(monkeypatch, **values: str) -> None:
    monkeypatch.setenv("NINE_ROUTER_ENABLED", "1")
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_disabled_defaults_are_safe_and_network_free():
    config = NineRouterConfig.from_env()

    assert config.enabled is False
    assert config.base_url == "http://127.0.0.1:20128/v1"
    assert config.model == ""
    assert config.api_key == ""
    assert config.allow_no_auth is False
    assert config.token_saver is False
    assert config.timeout == 300.0
    assert config.is_loopback is True
    assert config.authentication_allowed is False


def test_enabled_requires_explicit_model(monkeypatch):
    _enable(monkeypatch, NINE_ROUTER_API_KEY="test-key")

    with pytest.raises(ValueError, match="NINE_ROUTER_MODEL"):
        NineRouterConfig.from_env()


def test_enabled_requires_key_without_explicit_loopback_no_auth(monkeypatch):
    _enable(monkeypatch, NINE_ROUTER_MODEL="provider/model")

    with pytest.raises(ValueError, match="NINE_ROUTER_API_KEY"):
        NineRouterConfig.from_env()


def test_loopback_no_auth_requires_both_loopback_and_opt_in(monkeypatch):
    _enable(
        monkeypatch,
        NINE_ROUTER_MODEL="provider/model",
        NINE_ROUTER_ALLOW_NO_AUTH="1",
    )

    config = NineRouterConfig.from_env()

    assert config.is_loopback is True
    assert config.authentication_allowed is True
    assert config.api_key == ""


def test_remote_no_auth_opt_in_is_rejected(monkeypatch):
    _enable(
        monkeypatch,
        NINE_ROUTER_BASE_URL="https://router.example/v1",
        NINE_ROUTER_MODEL="provider/model",
        NINE_ROUTER_ALLOW_NO_AUTH="1",
    )

    with pytest.raises(ValueError, match="NINE_ROUTER_API_KEY"):
        NineRouterConfig.from_env()


def test_remote_endpoint_requires_https(monkeypatch):
    _enable(
        monkeypatch,
        NINE_ROUTER_BASE_URL="http://router.example/v1",
        NINE_ROUTER_MODEL="provider/model",
        NINE_ROUTER_API_KEY="test-key",
    )

    with pytest.raises(ValueError, match="HTTPS"):
        NineRouterConfig.from_env()


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@router.example/v1",
        "https://router.example/v1?model=secret",
        "https://router.example/v1#fragment",
    ],
)
def test_url_rejects_userinfo_query_and_fragment(monkeypatch, url):
    _enable(
        monkeypatch,
        NINE_ROUTER_BASE_URL=url,
        NINE_ROUTER_MODEL="provider/model",
        NINE_ROUTER_API_KEY="test-key",
    )

    with pytest.raises(ValueError, match="userinfo|query|fragment"):
        NineRouterConfig.from_env()


def test_token_saver_defaults_off_and_requires_explicit_opt_in(monkeypatch):
    _enable(
        monkeypatch,
        NINE_ROUTER_MODEL="provider/model",
        NINE_ROUTER_API_KEY="test-key",
    )
    assert NineRouterConfig.from_env().token_saver is False

    monkeypatch.setenv("NINE_ROUTER_TOKEN_SAVER", "1")
    assert NineRouterConfig.from_env().token_saver is True

    monkeypatch.setenv("NINE_ROUTER_TOKEN_SAVER", "true")
    assert NineRouterConfig.from_env().token_saver is False


@pytest.mark.parametrize("timeout", ["0", "-1", "301", "not-a-number"])
def test_timeout_must_be_positive_and_bounded(monkeypatch, timeout):
    _enable(
        monkeypatch,
        NINE_ROUTER_MODEL="provider/model",
        NINE_ROUTER_API_KEY="test-key",
        NINE_ROUTER_TIMEOUT=timeout,
    )

    with pytest.raises(ValueError, match="NINE_ROUTER_TIMEOUT"):
        NineRouterConfig.from_env()


def test_remote_https_with_key_is_valid(monkeypatch):
    _enable(
        monkeypatch,
        NINE_ROUTER_BASE_URL="https://router.example/v1/",
        NINE_ROUTER_MODEL="combo/reviewers",
        NINE_ROUTER_API_KEY="test-key",
        NINE_ROUTER_TIMEOUT="12.5",
    )

    config = NineRouterConfig.from_env()

    assert config.base_url == "https://router.example/v1"
    assert config.model == "combo/reviewers"
    assert config.is_loopback is False
    assert config.authentication_allowed is True
    assert config.timeout == 12.5


def test_loopback_detection_covers_ipv4_range_and_ipv6(monkeypatch):
    for url in ("http://127.0.0.2:20128/v1", "http://[::1]:20128/v1"):
        monkeypatch.setenv("NINE_ROUTER_BASE_URL", url)
        config = NineRouterConfig.from_env()
        assert config.is_loopback is True
