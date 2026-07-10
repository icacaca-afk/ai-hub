# AI Hub — Provider Registry
# 维护所有已注册的 Provider 实例
#
# 职责：
# 1. 注册 Provider 实例
# 2. 按 task_type 查找候选 Provider
# 3. 提供 Provider 列表查询

from __future__ import annotations

from typing import Dict, List

from core.provider import Provider


class ProviderRegistry:
    """Provider 注册中心。

    所有 Provider 实例启动时注册到这里。
    Router 通过 Registry 查找候选 Provider。
    """

    def __init__(self):
        self._providers: Dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        """注册一个 Provider 实例。

        Args:
            provider: Provider 实例
        """
        if provider.name in self._providers:
            raise ValueError(f"Provider '{provider.name}' is already registered")
        self._providers[provider.name] = provider

    def get(self, name: str) -> Provider | None:
        """按名称获取 Provider。"""
        return self._providers.get(name)

    def all(self) -> List[Provider]:
        """返回所有已注册的 Provider。"""
        return list(self._providers.values())

    def find_by_task_type(self, task_type: str) -> List[Provider]:
        """找出支持某任务类型的所有 Provider。

        Args:
            task_type: 任务类型，如 "coding", "search"

        Returns:
            支持该任务类型的 Provider 列表，按 priority 降序排列。
        """
        candidates = [p for p in self._providers.values() if p.supports(task_type)]
        return sorted(candidates, key=lambda p: p.priority, reverse=True)

    def find_available(self, task_type: str) -> List[Provider]:
        """找出支持某任务类型且当前可用的 Provider。

        Args:
            task_type: 任务类型

        Returns:
            可用的 Provider 列表，按 priority 降序排列。
        """
        candidates = self.find_by_task_type(task_type)
        return [p for p in candidates if p.available()]
