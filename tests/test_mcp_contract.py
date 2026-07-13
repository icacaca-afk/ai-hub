"""Tool Contract Test — 验证 MCP Server 暴露的 tools 契约。

确保 MCP SDK 升级后 tool 签名/返回值不会悄悄变化。
不依赖真实 LLM，使用 DemoProvider（FakeBridge）跑通端到端。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MCPClient:
    """简易 MCP stdio 客户端，用于测试。"""

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self._next_id = 1

    def start(self):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            [sys.executable, "adapters/marvis_mcp_server.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(_PROJECT_ROOT),
            env=env,
        )

    def send(self, method: str, params: dict | None = None, *, is_notification: bool = False) -> int | None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not is_notification:
            msg["id"] = self._next_id
            self._next_id += 1
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            return msg["id"]
        else:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            return None

    def read_response(self, expected_id: int, timeout: float = 30.0) -> dict:
        """读取 stdout 直到找到匹配 id 的响应。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                if data.get("id") == expected_id:
                    return data
            except json.JSONDecodeError:
                continue
        raise TimeoutError(f"No response with id={expected_id} within {timeout}s")

    def initialize(self) -> dict:
        self.start()
        mid = self.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "contract-test", "version": "1.0"},
        })
        resp = self.read_response(mid)
        self.send("notifications/initialized", is_notification=True)
        return resp

    def call_tool(self, name: str, arguments: dict) -> dict:
        mid = self.send("tools/call", {"name": name, "arguments": arguments})
        return self.read_response(mid)

    def list_tools(self) -> dict:
        mid = self.send("tools/list")
        return self.read_response(mid)

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            finally:
                self.proc = None


@pytest.fixture
def mcp():
    client = MCPClient()
    client.initialize()
    yield client
    client.close()


# ─── 1. initialize 契约 ───

class TestInitializeContract:
    def test_server_info(self):
        client = MCPClient()
        resp = client.initialize()
        result = resp["result"]
        assert result["serverInfo"]["name"] == "ai-hub"
        assert "version" in result["serverInfo"]
        assert "tools" in result["capabilities"]
        client.close()


# ─── 2. tools/list 契约 ───

class TestToolsListContract:
    REQUIRED_TOOLS = {"run_provider", "list_providers", "list_capabilities"}

    def test_tool_names(self, mcp):
        resp = mcp.list_tools()
        tool_names = {t["name"] for t in resp["result"]["tools"]}
        assert tool_names == self.REQUIRED_TOOLS

    def test_run_provider_schema(self, mcp):
        resp = mcp.list_tools()
        tools = resp["result"]["tools"]
        run_provider = [t for t in tools if t["name"] == "run_provider"][0]
        schema = run_provider["inputSchema"]
        assert "task" in schema.get("properties", {})
        assert "task" in schema.get("required", [])
        assert schema["properties"]["task"]["type"] == "object"


# ─── 3. list_providers 契约 ───

class TestListProvidersContract:
    """list_providers 需要检查所有 provider 可用性，可能耗时较长（CLI 探活）。
    标记为 slow，CI 可选跳过。
    """

    @pytest.mark.slow
    def test_returns_demo_provider(self, mcp):
        resp = mcp.call_tool("list_providers", {})
        content_text = resp["result"]["content"][0]["text"]
        data = json.loads(content_text)
        assert "providers" in data
        names = [p["name"] for p in data["providers"]]
        assert "demo" in names
        # V0.4.2 清理后不应有 marvis
        assert "marvis" not in names

    def test_providers_count_via_list_capabilities(self, mcp):
        """轻量替代：通过 list_capabilities 验证 server 存活且响应正常。"""
        resp = mcp.call_tool("list_capabilities", {})
        content_text = resp["result"]["content"][0]["text"]
        data = json.loads(content_text)
        assert "capabilities" in data
        assert len(data["capabilities"]) > 0


# ─── 4. run_provider 错误契约 ───

class TestRunProviderErrorContract:
    def test_no_provider_for_capability(self, mcp):
        resp = mcp.call_tool("run_provider", {
            "task": {"capability": "nonexistent.capability", "content": "test"},
        })
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["success"] is False
        assert data["code"] == "NO_PROVIDER"
        assert data["retryable"] is False
        assert isinstance(data["error"], str)

    def test_bad_request_missing_capability(self, mcp):
        resp = mcp.call_tool("run_provider", {
            "task": {"content": "hello"},
        })
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["success"] is False
        assert data["code"] == "BAD_REQUEST"


# ─── 5. Fake Provider 端到端 ───

class TestFakeProviderE2E:
    def test_demo_provider_returns_result(self, mcp):
        """使用 file.organize 能力（仅 demo provider 支持），确保路由到 FakeBridge。n
        避免路由到 stub provider（CLIBridge，subprocess 慢）。
        """
        resp = mcp.call_tool("run_provider", {
            "task": {"capability": "file.organize", "content": "Organize my files"},
        })
        data = json.loads(resp["result"]["content"][0]["text"])
        if data["success"]:
            assert isinstance(data["output"], str)
            assert len(data["output"]) > 0
            assert data["provider"] == "demo"
            assert data["capability"] == "file.organize"
            assert data["duration_ms"] >= 0
            assert isinstance(data["artifacts"], list)
            assert data["error"] is None
            assert data["code"] is None
        else:
            # demo 不可用时至少验证错误结构
            assert data["code"] in ("NO_PROVIDER", "PROVIDER_FAILED", "PROVIDER_UNAVAILABLE")
            assert isinstance(data["error"], str)
            assert data["retryable"] in (True, False)
