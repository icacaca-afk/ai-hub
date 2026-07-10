# AI Hub — QODER Provider（使用 CLIBridge）
#
# 通信方式：CLI (subprocess)
# Bridge: CLIBridge
# 前提：已安装 QODER CLI 并登录。

from __future__ import annotations

from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge


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
        fallback=["gemini_cli", "demo"],
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

    _quota_remaining: int = 80

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return self.bridge.check_auth()

    def quota_left(self) -> int:
        return self._quota_remaining
