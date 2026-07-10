# AI Hub — Router
# Task → 关键词 → Capability → CapabilityRegistry → Provider → Bridge → Result
#
# Router 不知道具体 Provider 的存在，只知道 Capability。
# Router 负责执行：调 provider.select_bridge(task) 拿到 Bridge，再调 bridge.run(task)。
# Provider 不实现 execute()。
#
# API Stability: Stable（外部接口不变，内部实现可升级为 AI 路由）

from __future__ import annotations

from typing import Optional

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

    def __init__(self, registry: CapabilityRegistry,
                 quota_manager: Optional[object] = None):
        self.registry = registry
        self.quota = quota_manager

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
            # QuotaManager 过滤：跳过额度耗尽的 Provider
            for p in candidates:
                if self.quota is None or not self.quota.exhausted(p.name):
                    return p

        # 所有候选都不可用，尝试 fallback
        all_matches = self.registry.find_by_any_capability(caps)
        for p in all_matches:
            for fb_name in p.fallback:
                fb = self.registry.get(fb_name)
                if fb and fb.available():
                    if self.quota is None or not self.quota.exhausted(fb.name):
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

        # 执行前检查配额
        if self.quota and self.quota.exhausted(provider.name):
            # 不应到达这里（route 已过滤），但防御性检查
            return Result(
                provider=provider.name,
                status="failed",
                output="",
                error=f"Quota exhausted for {provider.name}",
                metadata={"capabilities": task.capabilities, "task_id": task.task_id,
                           "fallback_reason": "quota_exhausted"},
            )

        # Provider 只负责选 Bridge，Router 负责执行
        bridge = provider.select_bridge(task)
        br = bridge.run(task)

        # 成功时扣减配额
        if br.success and self.quota:
            self.quota.ensure(provider.name, provider.metadata.quota_total,
                             provider.metadata.quota_type)
            self.quota.consume(provider.name, task_id=task.task_id)

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
