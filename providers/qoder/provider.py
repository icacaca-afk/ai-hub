# AI Hub — QODER Provider（使用 CLIBridge）
#
# 通信方式：CLI (subprocess)
# Bridge: CLIBridge
# 前提：已安装 QODER CLI 并登录。

from __future__ import annotations

from typing import Any

from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge
from core.result import Result


class QoderProvider(Provider):
    """QODER Provider，使用 CLIBridge。"""

    metadata = ProviderMetadata(
        name="qoder",
        display_name="QODER",
        description="阿里 Agentic 编程平台",
        version="0.0.1",
        capabilities=[
            "code.generate",
            "code.debug",
            "code.refactor",
            "code.review",
        ],
        priority=100,
        fallback=["gemini_cli", "openai_api"],
        quota_type="daily",
        quota_total=80,
        quota_auto_detect=False,
    )

    bridge = CLIBridge(
        command="qoder",
        auth_command="qoder auth status",
        version_command="qoder --version",
        timeout=300,
    )

    # 额度状态（运行时维护）
    _quota_remaining: int = 80

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return self.bridge.check_auth()

    def quota_left(self) -> int:
        return self._quota_remaining

    def execute(self, task: str, context: dict[str, Any] | None = None) -> Result:
        br = self._run_bridge(task)

        # 扣减额度
        if br.success and self._quota_remaining > 0:
            self._quota_remaining -= 1

        result = self._bridge_to_result(br, self.name)
        result.metadata["model"] = "qoder-default"
        result.metadata["quota_remaining"] = self._quota_remaining
        return result
