# AI Hub — Demo Provider（使用 FakeBridge）
#
# 用于骨架验证，不调用任何外部服务。
# 新增一个 Provider 只需要这么多代码。

from __future__ import annotations

from typing import Any

from core.provider import Provider, ProviderMetadata
from core.bridge import FakeBridge
from core.result import Result


class DemoProvider(Provider):
    """Demo Provider，使用 FakeBridge，用于验证骨架。"""

    metadata = ProviderMetadata(
        name="demo",
        display_name="Demo",
        description="Fake provider for skeleton validation",
        version="0.0.1",
        capabilities=[
            "code.generate",
            "text.summarize",
            "search.web",
            "file.organize",
            "general.chat",
        ],
        priority=0,
        fallback=[],
        quota_type="unlimited",
        quota_total=-1,
    )

    bridge = FakeBridge(response="Hello AI Hub! (Demo Provider)")

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return self.bridge.check_available()

    def quota_left(self) -> int:
        return -1

    def execute(self, task: str, context: dict[str, Any] | None = None) -> Result:
        br = self._run_bridge(task)
        result = self._bridge_to_result(br, self.name)
        result.metadata["quota_remaining"] = -1
        result.metadata["model"] = "demo-fake"
        return result
