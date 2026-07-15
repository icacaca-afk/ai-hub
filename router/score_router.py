# AI Hub — Score-based Router
# V0.8: 基于评分的 Provider 选择
#
# 继承 HealthAwareRouter，在 route() 中用 Score Engine 替代 priority 排序：
#   1. Health Filter（继承 V0.7 逻辑）
#   2. Score Engine：capability_match + health + priority + latency + quota
#   3. 最高分 Provider 选中
#
# ADR-0011: ScoreRouter extends HealthAwareRouter. Score weights are static
# in V0.8.0. Dynamic weights / LLM judgment deferred to V0.9+.
#
# API Stability: Experimental

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.provider import Provider
from core.registry import CapabilityRegistry
from core.task import Task
from core.health_registry import HealthRegistry
from router.health_router import HealthAwareRouter


# ── Score 权重（V0.8.0 静态） ──
WEIGHT_CAPABILITY = 40.0
WEIGHT_HEALTH = 25.0
WEIGHT_PRIORITY = 20.0
WEIGHT_LATENCY = 10.0
WEIGHT_QUOTA = 5.0

# health → score 映射
HEALTH_SCORES = {
    "healthy": 100.0,
    "unknown": 60.0,
    "degraded": 30.0,
    "unavailable": 0.0,
}


@dataclass
class ProviderScore:
    """Provider 评分明细。"""
    provider_name: str
    capability_score: float = 0.0
    health_score: float = 0.0
    priority_score: float = 0.0
    latency_score: float = 0.0
    quota_score: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.capability_score * WEIGHT_CAPABILITY
            + self.health_score * WEIGHT_HEALTH
            + self.priority_score * WEIGHT_PRIORITY
            + self.latency_score * WEIGHT_LATENCY
            + self.quota_score * WEIGHT_QUOTA
        ) / (
            WEIGHT_CAPABILITY
            + WEIGHT_HEALTH
            + WEIGHT_PRIORITY
            + WEIGHT_LATENCY
            + WEIGHT_QUOTA
        )

    def to_dict(self) -> dict:
        return {
            "provider": self.provider_name,
            "capability": round(self.capability_score, 1),
            "health": round(self.health_score, 1),
            "priority": round(self.priority_score, 1),
            "latency": round(self.latency_score, 1),
            "quota": round(self.quota_score, 1),
            "total": round(self.total, 1),
        }


class ScoreRouter(HealthAwareRouter):
    """评分路由器。

    继承 HealthAwareRouter，route() 中用 Score Engine 排序。

    评分公式：
        total = (capability×40 + health×25 + priority×20 + latency×10 + quota×5) / 100

    V0.8.0 范围：
        - 静态权重
        - latency 从 HealthReport.latency_ms 读取（有则评分，无则默认 50）
        - 不做 LLM 判断 / 自动学习 / Prompt 分类

    API Stability: Experimental
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        quota_manager: Optional[object] = None,
        health_registry: Optional[HealthRegistry] = None,
    ):
        super().__init__(registry, quota_manager, health_registry)
        self.last_scores: list[ProviderScore] = []

    def route(self, task: Task) -> Provider | None:
        """为 Task 选择得分最高的 Provider。"""
        caps = task.capabilities
        candidates = self.registry.find_available_by_any(caps)
        reports = self.health.get_all(candidates, lazy=True)

        # ── Health 过滤（与 HealthAwareRouter 一致） ──
        available: list[Provider] = []
        skipped: list[str] = []

        for p in candidates:
            r = reports.get(p.name)
            if r and r.is_unavailable:
                skipped.append(f"{p.name} (unavailable: {r.message})")
                continue
            available.append(p)

        if not available:
            # Fallback 链
            all_matches = self.registry.find_by_any_capability(caps)
            for p in all_matches:
                for fb_name in p.fallback:
                    fb = self.registry.get(fb_name)
                    if fb and fb.available():
                        if self.quota is None or not self.quota.exhausted(fb.name):
                            self.last_route_reason = {
                                "selected": fb.name,
                                "strategy": "fallback",
                                "reason": "no_healthy_provider",
                                "skipped": skipped,
                            }
                            self.last_scores = []
                            return fb
            self.last_route_reason = {
                "selected": None,
                "strategy": "none",
                "reason": "all_providers_unavailable_or_exhausted",
                "skipped": skipped,
            }
            self.last_scores = []
            return None

        # ── Score 计算 ──
        scores: list[tuple[Provider, ProviderScore]] = []
        for p in available:
            score = self._score_provider(p, caps, reports.get(p.name))
            # Quota 过滤：额度耗尽的不参与评分
            if self.quota and self.quota.exhausted(p.name):
                skipped.append(f"{p.name} (quota exhausted)")
                continue
            scores.append((p, score))

        if not scores:
            self.last_route_reason = {
                "selected": None,
                "strategy": "none",
                "reason": "all_providers_quota_exhausted",
                "skipped": skipped,
            }
            self.last_scores = []
            return None

        # ── 按总分排序，选最高 ──
        scores.sort(key=lambda x: x[1].total, reverse=True)
        self.last_scores = [s for _, s in scores]

        best_provider, best_score = scores[0]

        self.last_route_reason = {
            "selected": best_provider.name,
            "strategy": "score",
            "reason": "highest_score",
            "score": round(best_score.total, 1),
            "skipped": skipped,
        }
        return best_provider

    def _score_provider(
        self,
        provider: Provider,
        task_caps: list[str],
        health_report: Optional[object] = None,
    ) -> ProviderScore:
        """计算单个 Provider 的评分。"""
        score = ProviderScore(provider_name=provider.name)

        # 1. Capability score: 匹配的 capability 数量占比
        provider_caps = set(provider.metadata.capabilities)
        matched = len(set(task_caps) & provider_caps)
        total_requested = len(task_caps) if task_caps else 1
        score.capability_score = (matched / total_requested) * 100.0

        # 2. Health score
        if health_report:
            score.health_score = HEALTH_SCORES.get(health_report.status, 60.0)
        else:
            score.health_score = 60.0  # unknown

        # 3. Priority score: 归一化到 0-100
        max_priority = 100  # 假设最大 priority 为 100
        score.priority_score = min(provider.metadata.priority / max_priority * 100.0, 100.0)

        # 4. Latency score: 低于 1s = 100, 高于 10s = 0, 线性插值
        if health_report and health_report.latency_ms is not None:
            latency_s = health_report.latency_ms / 1000.0
            if latency_s <= 1.0:
                score.latency_score = 100.0
            elif latency_s >= 10.0:
                score.latency_score = 0.0
            else:
                score.latency_score = 100.0 * (1.0 - (latency_s - 1.0) / 9.0)
        else:
            score.latency_score = 50.0  # 无延迟数据，给中间分

        # 5. Quota score: 有额度 = 100, 无额度 = 0
        if self.quota and self.quota.exhausted(provider.name):
            score.quota_score = 0.0
        else:
            score.quota_score = 100.0

        return score
