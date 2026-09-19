"""HTTP, safety, and failure contracts for the 9Router bridge."""

from __future__ import annotations

from contextlib import contextmanager
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading

import pytest

from core.task import Task
from providers.nine_router.config import NineRouterConfig
from providers.nine_router.provider import NineRouterBridge


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _record(self, body: bytes = b"") -> None:
        self.server.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )

    def _send(self, status: int, body: bytes, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._record()
        if self.path != "/v1/models":
            self._send(404, b'{"error":"not found"}')
            return
        if self.server.models_redirect:
            self._send(302, b"", Location=self.server.models_redirect)
            return
        if self.server.models_raw is not None:
            self._send(self.server.models_status, self.server.models_raw)
            return
        payload = {
            "object": "list",
            "data": [{"id": model} for model in self.server.models],
        }
        self._send(self.server.models_status, json.dumps(payload).encode("utf-8"))

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size)
        self._record(body)
        if self.path != "/v1/chat/completions":
            self._send(404, b'{"error":"not found"}')
            return
        if self.server.chat_raw is not None:
            self._send(self.server.chat_status, self.server.chat_raw)
            return
        request = json.loads(body.decode("utf-8"))
        payload = {
            "model": request["model"],
            "choices": [
                {"message": {"role": "assistant", "content": "routed answer"}}
            ],
        }
        self._send(self.server.chat_status, json.dumps(payload).encode("utf-8"))


@contextmanager
def _server(*, models=("approved/model",)):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.models = list(models)
    server.models_status = 200
    server.models_raw = None
    server.models_redirect = None
    server.chat_status = 200
    server.chat_raw = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _config(
    server=None,
    *,
    enabled=True,
    model="approved/model",
    api_key="dedicated-secret",
    allow_no_auth=False,
    token_saver=False,
    timeout=2.0,
):
    base_url = (
        f"http://127.0.0.1:{server.server_port}/v1"
        if server is not None
        else "http://127.0.0.1:20128/v1"
    )
    return NineRouterConfig(
        enabled=enabled,
        base_url=base_url,
        model=model,
        api_key=api_key,
        allow_no_auth=allow_no_auth,
        token_saver=token_saver,
        timeout=timeout,
    )


def _task() -> Task:
    return Task.from_text("hello 9Router")


def test_disabled_bridge_never_opens_network(monkeypatch):
    bridge = NineRouterBridge(NineRouterConfig.disabled())
    opened = False

    def fail_if_opened(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("network must not be opened")

    monkeypatch.setattr(bridge, "_open", fail_if_opened)

    result = bridge.run(_task())

    assert result.success is False
    assert "disabled" in result.error.lower()
    assert bridge.check_available() is False
    assert opened is False


def test_fixed_model_executes_without_using_first_model():
    with _server(models=("wrong/first", "approved/model")) as server:
        bridge = NineRouterBridge(_config(server))

        result = bridge.run(_task(), model="attacker/override")

    assert result.success is True
    assert result.output == "routed answer"
    assert [request["path"] for request in server.requests] == [
        "/v1/models",
        "/v1/chat/completions",
    ]
    payload = json.loads(server.requests[1]["body"])
    assert payload == {
        "model": "approved/model",
        "messages": [{"role": "user", "content": "hello 9Router"}],
        "stream": False,
    }
    assert server.requests[1]["headers"]["authorization"] == "Bearer dedicated-secret"
    assert server.requests[1]["headers"]["x-9router-token-saver"] == "off"


def test_missing_fixed_model_returns_structured_failure_without_post():
    with _server(models=("wrong/first",)) as server:
        result = NineRouterBridge(_config(server)).run(_task())

    assert result.success is False
    assert "approved/model" in result.error
    assert "not present" in result.error
    assert [request["method"] for request in server.requests] == ["GET"]


def test_combo_identifier_is_treated_as_an_exact_model_id():
    with _server(models=("provider/model", "combo/reviewers")) as server:
        bridge = NineRouterBridge(_config(server, model="combo/reviewers"))
        result = bridge.run(_task())

    assert result.success is True
    assert json.loads(server.requests[1]["body"])["model"] == "combo/reviewers"


def test_loopback_bypasses_http_and_https_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    with _server() as server:
        result = NineRouterBridge(_config(server)).run(_task())

    assert result.success is True


def test_token_saver_header_explicitly_turns_on():
    with _server() as server:
        result = NineRouterBridge(_config(server, token_saver=True)).run(_task())

    assert result.success is True
    assert server.requests[1]["headers"]["x-9router-token-saver"] == "on"


def test_redirect_is_rejected_without_forwarding_authorization():
    with _server() as destination, _server() as source:
        source.models_redirect = (
            f"http://127.0.0.1:{destination.server_port}/v1/models"
        )
        result = NineRouterBridge(_config(source)).run(_task())

    assert result.success is False
    assert "redirect" in result.error.lower() or "302" in result.error
    assert destination.requests == []


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_errors_are_bounded_and_structured(status):
    with _server() as server:
        server.chat_status = status
        server.chat_raw = json.dumps({"error": "gateway failed"}).encode("utf-8")
        result = NineRouterBridge(_config(server)).run(_task())

    assert result.success is False
    assert f"HTTP {status}" in result.error
    assert len(result.error) <= 2048
    assert result.raw is None


def test_error_text_redacts_api_key_and_is_at_most_2048_characters():
    secret = "super-secret-api-key"
    with _server() as server:
        server.chat_status = 500
        server.chat_raw = (secret + ("x" * 5000)).encode("utf-8")
        result = NineRouterBridge(_config(server, api_key=secret)).run(_task())

    assert result.success is False
    assert secret not in result.error
    assert "[REDACTED]" in result.error
    assert len(result.error) <= 2048
    assert result.raw is None


def test_empty_models_are_a_structured_failure():
    with _server(models=()) as server:
        result = NineRouterBridge(_config(server)).run(_task())

    assert result.success is False
    assert "no models" in result.error.lower()


def test_invalid_models_json_is_a_structured_failure():
    with _server() as server:
        server.models_raw = b"not-json"
        result = NineRouterBridge(_config(server)).run(_task())

    assert result.success is False
    assert "JSON" in result.error


def test_invalid_chat_json_is_a_structured_failure():
    with _server() as server:
        server.chat_raw = b"not-json"
        result = NineRouterBridge(_config(server)).run(_task())

    assert result.success is False
    assert "JSON" in result.error


def test_missing_chat_content_is_a_structured_failure():
    with _server() as server:
        server.chat_raw = b'{"choices":[]}'
        result = NineRouterBridge(_config(server)).run(_task())

    assert result.success is False
    assert "response" in result.error.lower()


def test_connection_failure_is_a_structured_failure():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    config = NineRouterConfig(
        enabled=True,
        base_url=f"http://127.0.0.1:{port}/v1",
        model="approved/model",
        api_key="dedicated-secret",
        allow_no_auth=False,
        token_saver=False,
        timeout=0.2,
    )

    result = NineRouterBridge(config).run(_task())

    assert result.success is False
    assert any(
        marker in result.error.lower()
        for marker in ("unavailable", "failed", "timeout", "timed out")
    )


def test_timeout_is_a_structured_failure(monkeypatch):
    bridge = NineRouterBridge(_config())

    def timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(bridge, "_open", timeout)
    result = bridge.run(_task())

    assert result.success is False
    assert "timeout" in result.error.lower() or "timed out" in result.error.lower()
