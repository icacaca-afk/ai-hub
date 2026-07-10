# AI Hub — CapabilityRegistry
# Provider 注册与查询中心
#
# 维护 Capability → Provider 的映射。
# Router 通过 CapabilityRegistry 查找 Provider，不直接持有 Provider 列表。
#
# API Stability: Stable

from __future__ import annotations

from typing import Dict, List

from core.provider import Provider


class CapabilityRegistry:
    """Provider 注册中心。

    所有 Provider 实例启动时注册到这里。
    Router 通过 CapabilityRegistry 按 capability 查找候选 Provider。

    API Stability: Stable
    """

    def __init__(self):
        self._providers: Dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"Provider '{provider.name}' is already registered")
        self._providers[provider.name] = provider

    def get(self, name: str) -> Provider | None:
        return self._providers.get(name)

    def all(self) -> List[Provider]:
        return list(self._providers.values())

    def find_by_capability(self, capability: str) -> List[Provider]:
        """找出支持某能力标签的所有 Provider，按 priority 降序排列。"""
        candidates = [p for p in self._providers.values() if p.supports(capability)]
        return sorted(candidates, key=lambda p: p.priority, reverse=True)

    def find_available(self, capability: str) -> List[Provider]:
        """找出支持某能力且当前可用的 Provider。"""
        candidates = self.find_by_capability(capability)
        return [p for p in candidates if p.available()]

    def find_by_any_capability(self, capabilities: list[str]) -> List[Provider]:
        """找出支持给定能力列表中任意一个的 Provider（去重，按 priority 降序）。"""
        seen: set[str] = set()
        result: list[Provider] = []
        for cap in capabilities:
            for p in self.find_by_capability(cap):
                if p.name not in seen:
                    seen.add(p.name)
                    result.append(p)
        return sorted(result, key=lambda p: p.priority, reverse=True)

    def find_available_by_any(self, capabilities: list[str]) -> List[Provider]:
        """找出支持给定能力列表中任意一个且当前可用的 Provider。"""
        all_matches = self.find_by_any_capability(capabilities)
        return [p for p in all_matches if p.available()]
