# AI Hub — Gemini CLI Provider（使用 CLIBridge）
#
# 演示 CLIBridge 的用法。
# 接入任何 CLI 类 AI 工具都参考此模板。
#
# 通信方式：CLI (subprocess)
# Bridge: CLIBridge

from __future__ import annotations

from typing import Any

from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge
from core.result import Result


class GeminiCLIProvider(Provider):
    """Gemini CLI Provider，使用 CLIBridge。

    前提：已安装 gemini CLI 并登录。
    """

    metadata = ProviderMetadata(
        name="gemini_cli",
        display_name="Gemini CLI",
        description="Google Gemini 命令行工具",
        version="0.0.1",
        capabilities=[
            "code.generate",
            "search.web",
            "text.summarize",
            "text.translate",
            "general.chat",
        ],
        priority=80,
        fallback=["openai_api", "demo"],
        quota_type="unlimited",
        quota_total=-1,
    )

    bridge = CLIBridge(
        command="gemini",
        auth_command="gemini auth status",
        version_command="gemini --version",
        timeout=300,
    )

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return self.bridge.check_auth()

    def quota_left(self) -> int:
        return -1  # Gemini CLI 目前无明确限制

    def execute(self, task: str, context: dict[str, Any] | None = None) -> Result:
        br = self._run_bridge(task)
        result = self._bridge_to_result(br, self.name)
        result.metadata["model"] = "gemini-cli"
        result.metadata["quota_remaining"] = self.quota_left()
        return result
