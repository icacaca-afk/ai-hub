# AI Hub — Router（V0.0.5 重构）
#
# 路由链路：
#   Task → 关键词匹配 → Capability → Registry → Provider → Bridge → 执行
#
# 核心变更：
# - 不再按 task_type 查找，改为按 capability 查找
# - 支持一个任务匹配多个 capability，选出所有匹配的 Provider
# - Router 代码不再硬编码任务类型，新增 capability 不需要改 Router

from __future__ import annotations

from core.provider import Provider
from core.registry import ProviderRegistry
from core.result import Result
from core.capabilities import classify


class Router:
    """规则路由器。

    Task → Capability → Registry → Provider
    """

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def route(self, task: str) -> tuple[list[str], Provider | None]:
        """为任务选择最合适的 Provider。

        Args:
            task: 用户的任务描述

        Returns:
            (capabilities, provider) 元组。
            如果没有可用 Provider，provider 为 None。
        """
        caps = classify(task)
        candidates = self.registry.find_available_by_any(caps)

        if candidates:
            return caps, candidates[0]

        # 所有候选都不可用，尝试 fallback
        all_matches = self.registry.find_by_any_capability(caps)
        for p in all_matches:
            for fb_name in p.fallback:
                fb = self.registry.get(fb_name)
                if fb and fb.available():
                    return caps, fb

        return caps, None

    def execute(self, task: str) -> Result:
        """路由并执行任务。"""
        caps, provider = self.route(task)

        if provider is None:
            return Result(
                provider="none",
                status="failed",
                output="",
                error=f"No available provider for capabilities: {caps}",
                metadata={"capabilities": caps},
            )

        return provider.execute(task)
