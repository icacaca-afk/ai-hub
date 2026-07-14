# AI Hub — HealthRegistry
# Provider 健康状态缓存中心
#
# 缓存策略：Lazy Refresh + TTL
# - 不启动 Background Thread（ai-hub 非长驻服务）
# - 每次 get(provider) 时检查缓存是否过期，过期则重新检查
# - 如果以后 ai-hub 变成 daemon server，再引入 HealthScheduler
#
# Router 不直接调 provider.health()，而是通过 HealthRegistry 获取状态。
# 这保证了 Router 的路由逻辑不膨胀，Health 是独立关注点。
#
# API Stability: Experimental（V0.6 新增）

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from core.health import HealthReport, HealthChecker, TTL_DEFAULTS


class HealthRegistry:
    """Provider 健康状态缓存。

    用法：
        hr = HealthRegistry()
        report = hr.get(provider)       # 缓存/刷新
        status_map = hr.get_all(providers)  # 批量获取
        report = hr.refresh(provider)   # 强制刷新

    Lazy Refresh 逻辑：
        1. 缓存存在且未过期 → 返回缓存
        2. 缓存过期或不存在 → 调用 HealthChecker.check() → 存入缓存 → 返回
    """

    def __init__(self, ttl_map: Optional[dict[str, int]] = None):
        self._cache: dict[str, HealthReport] = {}
        self._checker = HealthChecker()
        self._ttl_map = ttl_map or TTL_DEFAULTS

    # ── 查询（Lazy Refresh） ──

    def get(self, provider: "Provider | object") -> HealthReport:
        """获取 Provider 健康状态（自动判断是否刷新）。

        Lazy Refresh：缓存过期时自动重新检查。
        """
        name = getattr(provider, "name", "unknown")

        # 检查缓存
        if name in self._cache:
            cached = self._cache[name]
            if not cached.is_expired():
                return cached

        # 缓存过期或不存在 → 刷新
        return self.refresh(provider)

    def get_all(self, providers: list, lazy: bool = True) -> dict[str, HealthReport]:
        """批量获取所有 Provider 的健康状态。

        Args:
            providers: Provider 实例列表
            lazy: True = Lazy Refresh（默认），False = 强制全量刷新

        Returns:
            {provider_name: HealthReport} 字典
        """
        if not lazy:
            return self.refresh_all(providers)

        result = {}
        for p in providers:
            result[p.name] = self.get(p)
        return result

    # ── 刷新 ──

    def refresh(self, provider: "Provider | object") -> HealthReport:
        """强制刷新一个 Provider 的健康状态。"""
        report = self._checker.check(provider)

        # 如果 Provider 没有指定 TTL，根据类型推断
        if report.ttl_seconds == 120:  # 还是默认值，尝试推断
            provider_type = self._infer_type(provider)
            report.ttl_seconds = self._ttl_map.get(provider_type, 120)

        self._cache[report.provider] = report
        return report

    def refresh_all(self, providers: list) -> dict[str, HealthReport]:
        """强制刷新所有 Provider。"""
        result = {}
        for p in providers:
            result[p.name] = self.refresh(p)
        return result

    # ── 缓存管理 ──

    def invalidate(self, provider_name: str) -> None:
        """手动失效某个 Provider 的缓存。"""
        self._cache.pop(provider_name, None)

    def invalidate_all(self) -> None:
        """清空所有缓存。"""
        self._cache.clear()

    def is_cached(self, provider_name: str) -> bool:
        """检查缓存是否有效（存在且未过期）。"""
        if provider_name not in self._cache:
            return False
        return not self._cache[provider_name].is_expired()

    # ── 状态汇总 ──

    def summary(self, providers: list) -> dict:
        """生成健康状态汇总。

        Returns:
            {
                "healthy": 3,
                "degraded": 0,
                "unknown": 1,
                "unavailable": 1,
                "total": 5,
                "reports": {provider_name: HealthReport, ...}
            }
        """
        reports = self.get_all(providers)
        counts = {"healthy": 0, "degraded": 0, "unknown": 0, "unavailable": 0}
        for r in reports.values():
            counts.setdefault(r.status, 0)
            counts[r.status] += 1
        counts["total"] = len(reports)

        return {
            "healthy": counts.get("healthy", 0),
            "degraded": counts.get("degraded", 0),
            "unknown": counts.get("unknown", 0),
            "unavailable": counts.get("unavailable", 0),
            "total": len(reports),
            "reports": {k: v.to_dict() for k, v in reports.items()},
        }

    # ── 内部 ──

    def _infer_type(self, provider) -> str:
        """推断 Provider 类型（用于 TTL 推断）。

        优先级：
        1. ProviderMetadata.health_type — 显式声明（V0.6 新增）
        2. Provider name 推断 — 按名称特征匹配
        3. 默认 "api"
        """
        # 1. 显式声明
        meta = getattr(provider, "metadata", None)
        if meta and getattr(meta, "health_type", ""):
            return meta.health_type

        # 2. 名称推断
        provider_name = getattr(provider, "name", "").lower()
        if "browser" in provider_name or "web" in provider_name:
            return "browser"
        elif "mcp" in provider_name:
            return "mcp"
        elif "cli" in provider_name or "qoder" in provider_name:
            return "cli"
        else:
            return "api"
