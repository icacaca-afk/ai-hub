"""Thin, security-bounded 9Router Provider and HTTP bridge."""

from __future__ import annotations

import json
import socket
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from core.bridge import Bridge, BridgeResult
from core.health import HealthReport
from core.provider import Provider, ProviderMetadata
from core.task import Task
from providers.nine_router.config import NineRouterConfig


_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_ERROR_CHARS = 2048


class _RedirectRejected(HTTPRedirectHandler):
    """Reject redirects so credentials can never follow a Location header."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(
            req.full_url,
            code,
            f"redirect rejected: {newurl}",
            headers,
            fp,
        )


class NineRouterBridge(Bridge):
    """Non-streaming text bridge for one fixed 9Router model or Combo."""

    def __init__(self, config: NineRouterConfig):
        self.config = config
        handlers: list[Any] = [_RedirectRejected()]
        if config.is_loopback:
            handlers.insert(0, ProxyHandler({}))
        self._opener = build_opener(*handlers)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-9Router-Token-Saver": "on" if self.config.token_saver else "off",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _open(self, request: Request):
        return self._opener.open(request, timeout=self.config.timeout)

    @staticmethod
    def _read_text(response, limit: int = _MAX_RESPONSE_BYTES) -> str:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("9Router response exceeds the 1 MiB limit")
        return data.decode("utf-8", errors="replace")

    def _redact(self, value: str) -> str:
        if self.config.api_key:
            value = value.replace(self.config.api_key, "[REDACTED]")
        return value

    def _failure(self, message: str, start: float) -> BridgeResult:
        safe = self._redact(message)
        return BridgeResult(
            success=False,
            output="",
            error=safe[:_MAX_ERROR_CHARS],
            duration_ms=int((time.monotonic() - start) * 1000),
            raw=None,
        )

    def _load_json(self, response, *, operation: str) -> tuple[dict, str]:
        raw = self._read_text(response)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"9Router {operation} returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError(f"9Router {operation} returned a non-object JSON response")
        return payload, raw

    def list_models(self) -> list[str]:
        if not self.config.enabled:
            raise RuntimeError("9Router is disabled")
        request = Request(
            f"{self.config.base_url}/models",
            headers=self._headers(),
            method="GET",
        )
        with self._open(request) as response:
            payload, _ = self._load_json(response, operation="models endpoint")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("9Router models response is missing a data list")
        models = [
            item["id"]
            for item in data
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"]
        ]
        if not models:
            raise RuntimeError("9Router returned no models")
        return models

    @staticmethod
    def _extract_content(payload: dict) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("9Router response is missing assistant message content") from error
        if not isinstance(content, str):
            raise ValueError("9Router response assistant content must be text")
        return content

    def run(self, task: Task, **_kwargs) -> BridgeResult:
        start = time.monotonic()
        if not self.config.enabled:
            return self._failure("9Router is disabled", start)
        if not self.config.model:
            return self._failure("NINE_ROUTER_MODEL is required", start)
        if not self.config.authentication_allowed:
            return self._failure("9Router authentication is not allowed", start)

        try:
            models = self.list_models()
            if self.config.model not in models:
                return self._failure(
                    f"Configured 9Router model {self.config.model!r} is not present",
                    start,
                )

            body = json.dumps(
                {
                    "model": self.config.model,
                    "messages": [{"role": "user", "content": task.content}],
                    "stream": False,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            request = Request(
                f"{self.config.base_url}/chat/completions",
                data=body,
                headers=self._headers(),
                method="POST",
            )
            with self._open(request) as response:
                payload, raw = self._load_json(
                    response,
                    operation="chat completions endpoint",
                )
            return BridgeResult(
                success=True,
                output=self._extract_content(payload),
                duration_ms=int((time.monotonic() - start) * 1000),
                raw=raw,
            )
        except HTTPError as error:
            try:
                # Error bodies may be arbitrarily large. Read a bounded prefix
                # rather than rejecting the whole body and losing useful detail.
                detail = error.read(4096).decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            suffix = detail or str(error.reason)
            return self._failure(f"9Router HTTP {error.code}: {suffix}", start)
        except (TimeoutError, socket.timeout) as error:
            return self._failure(f"9Router timeout: {error}", start)
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                return self._failure(f"9Router timeout: {error.reason}", start)
            return self._failure(f"9Router unavailable: {error.reason}", start)
        except Exception as error:
            return self._failure(f"9Router request failed: {error}", start)

    def check_available(self) -> bool:
        if not self.config.enabled or not self.config.authentication_allowed:
            return False
        try:
            return self.config.model in self.list_models()
        except Exception:
            return False


class NineRouterProvider(Provider):
    """AI Hub declaration for the externally managed 9Router gateway."""

    manual_only = True

    metadata = ProviderMetadata(
        name="nine_router",
        display_name="9Router",
        description="Optional downstream OpenAI-compatible model gateway",
        version="0.1.0",
        capabilities=[
            "code.generate",
            "text.generate",
            "text.summarize",
            "text.translate",
            "general.chat",
        ],
        priority=0,
        fallback=["demo"],
        quota_type="unknown",
        quota_total=-1,
        health_type="api",
        cost_currency=None,
        cost_amount=0.0,
        cost_unit="upstream_managed",
        timeout=300,
    )

    bridge = NineRouterBridge(NineRouterConfig.disabled())

    def __init__(self):
        self._explicitly_selected = False
        self.configuration_error: str | None = None
        try:
            config = NineRouterConfig.from_env()
        except ValueError as error:
            self.configuration_error = str(error)
            config = NineRouterConfig.disabled()
        self.config = config
        self.bridge = NineRouterBridge(config)

    def mark_explicit_selection(self) -> None:
        self._explicitly_selected = True

    def available(self) -> bool:
        if not self._explicitly_selected:
            return False
        return super().available()

    def health(self) -> HealthReport:
        if self.configuration_error:
            return HealthReport.unavailable(self.name, self.configuration_error)
        if not self.config.enabled:
            return HealthReport.unavailable(self.name, "9Router is disabled")
        if not self.bridge.check_available():
            return HealthReport.unavailable(
                self.name,
                "9Router is unavailable or the configured model is absent",
            )
        return HealthReport(
            provider=self.name,
            status=HealthReport.DEGRADED,
            authenticated=self.authenticated(),
            quota_ok=None,
            message="9Router reachable; execution not yet verified",
        )

    def authenticated(self) -> bool:
        return self.config.enabled and self.config.authentication_allowed

    def quota_left(self) -> int:
        return -1
