# AI Hub — Demo Provider
# 用于验证端到端流程，不调用任何真实 AI 平台
#
# 用法：
#   ai-hub ask "你好"
#   → DemoProvider.execute("你好")
#   → Result(provider="demo", status="success", output="Hello AI Hub! ...")

from __future__ import annotations

from typing import Any

from core.provider import Provider
from core.result import Result


class DemoProvider(Provider):
    """Fake Provider，用于验证骨架是否跑通。

    不依赖任何外部服务，永远返回成功。
    接入第一个真实 Provider 后可以移除。
    """

    name = "demo"
    display_name = "Demo"
    description = "Fake provider for skeleton validation"
    version = "0.0.1"

    capabilities = ["general"]
    task_types = ["general", "coding", "analysis", "search", "file_ops"]

    priority = 0
    fallback: list[str] = []

    def health(self) -> bool:
        return True

    def authenticated(self) -> bool:
        return True

    def quota_left(self) -> int:
        return -1  # 无限制

    def quota_info(self) -> dict[str, Any]:
        return {
            "type": "unlimited",
            "total": -1,
            "remaining": -1,
            "reset_at": None,
            "auto_detect": False,
        }

    def execute(self, task: str, context: dict[str, Any] | None = None) -> Result:
        return Result(
            provider=self.name,
            status="success",
            output=f"Hello AI Hub!\n\nYou said: {task}\n\n(This is a demo response. Replace with a real provider.)",
            error=None,
            metadata={
                "duration_ms": 0,
                "tokens_used": 0,
                "quota_remaining": -1,
                "model": "demo-fake",
            },
        )
