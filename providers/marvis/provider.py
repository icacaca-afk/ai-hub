"""Marvis Provider — GUI Bridge Provider (V0.4)

通过 Windows UIA 操控 Marvis 桌面 AI 助手。
Marvis 是桌面 GUI 应用，没有 CLI 和公开 API。
"""
from __future__ import annotations

from core.provider import Provider, ProviderMetadata
from core.task import Task
from core.bridge import Bridge
from .bridge import MarvisBridge


class MarvisProvider(Provider):
    """Marvis 桌面 AI Provider。

    Marvis 只提供 GUI 界面，不能通过 CLI 或 API 交互。
    通过 Windows UIA 自动化操作 GUI 输入框和输出区域。
    """

    metadata = ProviderMetadata(
        name="marvis",
        display_name="Marvis",
        description="Marvis desktop AI assistant (GUI automation via UIA)",
        capabilities=[
            "code.generate",
            "general.chat",
            "text.summarize",
            "text.translate",
        ],
        priority=30,          # 低于 CLI 和 API（GUI 慢且不稳定）
        fallback=["demo"],    # Marvis 不可用时回退到 Demo
        quota_type="daily",
        quota_total=200,
    )

    bridge: Bridge = MarvisBridge(app_name="Marvis")

    def health(self) -> bool:
        """健康检查：窗口存在且有输入框。"""
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        """GUI 认证由应用自身管理，窗口存在即已登录。"""
        return self.bridge.check_available()

    def quota_left(self) -> int:
        """GUI 应用无明确 quota 概念，默认返回 total。"""
        return self.metadata.quota_total

    def supports(self, capability: str) -> bool:
        return capability in self.metadata.capabilities

    def select_bridge(self, task: Task) -> Bridge:
        """选择 MarvisBridge。"""
        return self.bridge
