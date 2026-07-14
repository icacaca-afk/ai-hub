# AI Hub — Health-aware Router
# V0.7: 基于健康状态的 Provider 过滤
#
# 继承现有 Router（router/router.py 冻结），在 route() 中加 Health Filter：
#   1. 获取候选 Provider 列表
#   2. Health 过滤：跳过 unavailable，degraded 排到后面
#   3. Quota 过滤：跳过额度耗尽的
#   4. healthy 优先，degraded 兜底
#
# ADR-0009: HealthAwareRouter intentionally duplicates routing selection
# flow because Router core is frozen (ADR-0008). Future refactoring may
# introduce RouterPolicy pipeline.
#
# API Stability: Experimental

from __future__ import annotations

from typing import Optional

from core.provider import Provider
from core.registry import CapabilityRegistry
from core.task import Task
from core.health_registry import HealthRegistry
from router.router import Router


class HealthAwareRouter(Router):
    """Health-aware 路由器。

    继承 Router，在 route() 中插入 Health Filter。
    execute() 完全继承父类，不改执行链。

    新增参数：
        health_registry: HealthRegistry 实例（默认 None → 内部创建）

    路由优先级：
        1. capability match（来自 CapabilityRegistry）
        2. health status（unavailable 跳过，degraded 降组）
        3. priority（静态，不与健康状态混合）
        4. quota（跳过额度耗尽的）

    API Stability: Experimental
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        quota_manager: Optional[object] = None,
        health_registry: Optional[HealthRegistry] = None,
    ):
        super().__init__(registry, quota_manager)
        self.health = health_registry or HealthRegistry()
        self.last_route_reason: dict = {}

    def route(self, task: Task) -> Provider | None:
        """为 Task 选择最合适的 Provider（Health-aware）。

        流程：
        1. 按 capability 查找候选 Provider（priority 降序）
        2. Health 过滤：unavailable → 跳过，degraded → 分到兜底组
        3. Quota 过滤：跳过额度耗尽的
        4. healthy 组优先，degraded 组兜底
        5. 如果全部不可用 → 尝试 fallback 链 → None

        注意：unknown 算可用（不阻断未实现 health() 的 Provider）
        """
        caps = task.capabilities
        candidates = self.registry.find_available_by_any(caps)

        # ── Health 过滤 ──
        healthy_group: list[Provider] = []
        degraded_group: list[Provider] = []
        skipped: list[str] = []

        for p in candidates:
            report = self.health.get(p)  # Lazy: TTL 缓存，过期才刷新

            if report.is_unavailable:
                skipped.append(f"{p.name} (unavailable: {report.message})")
                continue

            if report.is_degraded:
                degraded_group.append(p)
            else:
                # healthy + unknown 都算可用
                healthy_group.append(p)

        # ── Quota 过滤 + 选择 ──
        # healthy 组优先
        for p in healthy_group:
            if self.quota is None or not self.quota.exhausted(p.name):
                self.last_route_reason = {
                    "selected": p.name,
                    "group": "healthy",
                    "skipped": skipped,
                }
                return p

        # degraded 组兜底
        for p in degraded_group:
            if self.quota is None or not self.quota.exhausted(p.name):
                self.last_route_reason = {
                    "selected": p.name,
                    "group": "degraded",
                    "skipped": skipped,
                }
                return p

        # ── Fallback 链（与父类一致） ──
        all_matches = self.registry.find_by_any_capability(caps)
        for p in all_matches:
            for fb_name in p.fallback:
                fb = self.registry.get(fb_name)
                if fb and fb.available():
                    if self.quota is None or not self.quota.exhausted(fb.name):
                        # Fallback 不做 health 过滤（已经是兜底了）
                        self.last_route_reason = {
                            "selected": fb.name,
                            "group": "fallback",
                            "skipped": skipped,
                        }
                        return fb

        self.last_route_reason = {
            "selected": None,
            "reason": "all providers unavailable or exhausted",
            "skipped": skipped,
        }
        return None
