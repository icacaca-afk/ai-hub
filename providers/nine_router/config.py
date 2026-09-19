"""Immutable, fail-closed configuration for the 9Router Provider."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from urllib.parse import urlparse


_DEFAULT_BASE_URL = "http://127.0.0.1:20128/v1"
_DEFAULT_TIMEOUT = 300.0
_MAX_TIMEOUT = 300.0


def _enabled(name: str) -> bool:
    """Return true only for the deliberately narrow opt-in value ``1``."""
    return os.environ.get(name, "").strip() == "1"


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class NineRouterConfig:
    """Validated settings used by one 9Router Provider instance."""

    enabled: bool
    base_url: str
    model: str
    api_key: str
    allow_no_auth: bool
    token_saver: bool
    timeout: float

    @classmethod
    def disabled(cls) -> "NineRouterConfig":
        """Return the network-free default used by existing installations."""
        return cls(
            enabled=False,
            base_url=_DEFAULT_BASE_URL,
            model="",
            api_key="",
            allow_no_auth=False,
            token_saver=False,
            timeout=_DEFAULT_TIMEOUT,
        )

    @classmethod
    def from_env(cls) -> "NineRouterConfig":
        """Parse and validate the process environment without doing network I/O."""
        if not _enabled("NINE_ROUTER_ENABLED"):
            return cls.disabled()

        base_url = os.environ.get("NINE_ROUTER_BASE_URL", _DEFAULT_BASE_URL).strip()
        base_url = base_url.rstrip("/")
        model = os.environ.get("NINE_ROUTER_MODEL", "").strip()
        api_key = os.environ.get("NINE_ROUTER_API_KEY", "").strip()
        allow_no_auth = _enabled("NINE_ROUTER_ALLOW_NO_AUTH")
        token_saver = _enabled("NINE_ROUTER_TOKEN_SAVER")

        try:
            timeout = float(os.environ.get("NINE_ROUTER_TIMEOUT", str(_DEFAULT_TIMEOUT)))
        except ValueError as error:
            raise ValueError(
                "NINE_ROUTER_TIMEOUT must be a number greater than 0 and at most 300"
            ) from error
        if not 0 < timeout <= _MAX_TIMEOUT:
            raise ValueError(
                "NINE_ROUTER_TIMEOUT must be greater than 0 and at most 300"
            )

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            raise ValueError("NINE_ROUTER_BASE_URL must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("NINE_ROUTER_BASE_URL must not contain userinfo")
        if parsed.params:
            raise ValueError("NINE_ROUTER_BASE_URL must not contain URL params")
        if parsed.query:
            raise ValueError("NINE_ROUTER_BASE_URL must not contain a query")
        if parsed.fragment:
            raise ValueError("NINE_ROUTER_BASE_URL must not contain a fragment")

        is_loopback = _is_loopback_host(parsed.hostname)
        if not is_loopback and parsed.scheme != "https":
            raise ValueError("NINE_ROUTER_BASE_URL must use HTTPS for non-loopback hosts")
        if not model:
            raise ValueError("NINE_ROUTER_MODEL is required when 9Router is enabled")
        if not api_key and not (is_loopback and allow_no_auth):
            raise ValueError(
                "NINE_ROUTER_API_KEY is required unless loopback no-auth is explicitly enabled"
            )

        return cls(
            enabled=True,
            base_url=base_url,
            model=model,
            api_key=api_key,
            allow_no_auth=allow_no_auth,
            token_saver=token_saver,
            timeout=timeout,
        )

    @property
    def is_loopback(self) -> bool:
        return _is_loopback_host(urlparse(self.base_url).hostname)

    @property
    def authentication_allowed(self) -> bool:
        return bool(self.api_key) or (self.is_loopback and self.allow_no_auth)
