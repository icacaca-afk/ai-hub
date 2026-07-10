# AI Hub — Router
# Task → 关键词 → Capability → CapabilityRegistry → Provider → Bridge → Result
#
# Router 不知道具体 Provider 的存在，只知道 Capability。
# Router 负责执行：调 provider.select_bridge(task) 拿到 Bridge，再调 bridge.run(task)。
# Provider 不实现 execute()。
#
# API Stability: Stable（外部接口不变，内部实现可升级为 AI 路由）

from __future__ import annotations

from core.provider import Provider
from core.registry import CapabilityRegistry
from core.result import Result
from core.task import Task
from core.bridge import BridgeResult


class Router:
    """规则路由器。

    Task → Capability → CapabilityRegistry → Provider → Bridge → 执行 → Result

    API Stability: Stable
    """

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def route(self, task: Task) -> Provider | None:
        """为 Task 选择最合适的 Provider。

        Args:
            task: Task 对象

        Returns:
            Provider 实例，如果没有可用 Provider 则返回 None。
        """
        caps = task.capabilities
        candidates = self.registry.find_available_by_any(caps)

        if candidates:
            return candidates[0]

        # 所有候选都不可用，尝试 fallback
        all_matches = self.registry.find_by_any_capability(caps)
        for p in all_matches:
            for fb_name in p.fallback:
                fb = self.registry.get(fb_name)
                if fb and fb.available():
                    return fb

        return None

    def execute(self, task: Task) -> Result:
        """路由并执行任务。

        链路：route → select_bridge → bridge.run → Result

        Args:
            task: Task 对象

        Returns:
            Result 对象。
        """
        provider = self.route(task)

        if provider is None:
            return Result(
                provider="none",
                status="failed",
                output="",
                error=f"No available provider for capabilities: {task.capabilities}",
                metadata={"capabilities": task.capabilities, "task_id": task.task_id},
            )

        # Provider 只负责选 Bridge，Router 负责执行
        bridge = provider.select_bridge(task)
        br = bridge.run(task)

        # Router 负责 BridgeResult → Result 转换
        return Result(
            provider=provider.name,
            status="success" if br.success else "failed",
            output=br.output,
            error=br.error,
            artifacts=br.artifacts,
            metadata={
                "duration_ms": br.duration_ms,
                "capabilities": task.capabilities,
                "task_id": task.task_id,
                "bridge": type(bridge).__name__,
                "quota_remaining": provider.quota_left(),
            },
        )
