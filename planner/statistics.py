# AI Hub — ExecutionStatistics + StatisticsCollector
# V0.9.7: 从 ExecutionEvent 派生统计（ADR-0020）
#
# ADR-0020 (ChatGPT 审核通过 9.95/10):
#   - StatisticsCollector 是纯计算类（不接触 SQLite / EventBus）
#   - 输入：list[ExecutionEvent]（来自 query_events()）
#   - 输出：ExecutionStatistics
#   - ChatGPT 唯一补充原则（0.05 分）：
#     StatisticsCollector MUST be a pure read-only projection.
#     - 绝不修改 ExecutionEvent
#     - 绝不补 ExecutionEvent
#     - 绝不缓存 ExecutionEvent
#     - 绝不写回 SQLite
#     这是 Event Sourcing 的重要原则：Analytics Never Mutates Events。
#
# 不修改 core/ + router/ + providers/ + planner/event_bus.py + execution_event.py
#
# API Stability: Experimental

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planner.execution_event import ExecutionEvent


def _parse_iso_timestamp(ts: str) -> datetime:
    """解析 ISO 8601 timestamp（支持 Z 后缀）。

    ExecutionEvent.timestamp 格式：``YYYY-MM-DDTHH:MM:SS.mmmZ``
    Python 3.10 的 fromisoformat 不支持 Z，需要替换为 +00:00。
    """
    # 替换 Z 后缀为 +00:00（UTC）
    normalized = ts.rstrip("Z") + "+00:00" if ts.endswith("Z") else ts
    return datetime.fromisoformat(normalized)


@dataclass
class ProviderStatistics:
    """单 Provider 的聚合统计（V0.9.7）。

    所有字段从 ``provider_finished`` events 派生：
    - calls: provider_finished events 数
    - success_count / failed_count: 按 data.status 分类
    - avg_latency_ms: 平均 latency（来自 event.latency_ms）
    - total_token_in / total_token_out: 来自 data.server_metrics
    - total_cost_usd: 来自 data.server_metrics.cost_usd
    """

    name: str
    calls: int = 0
    success_count: int = 0
    failed_count: int = 0
    total_latency_ms: int = 0
    total_token_in: int = 0
    total_token_out: int = 0
    total_cost_usd: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        """平均 latency（calls=0 时返回 0.0）。"""
        return self.total_latency_ms / self.calls if self.calls > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（JSON 可序列化）。"""
        return {
            "name": self.name,
            "calls": self.calls,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_token_in": self.total_token_in,
            "total_token_out": self.total_token_out,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


@dataclass
class ExecutionStatistics:
    """全局执行统计（从 ExecutionEvent 派生，V0.9.7）。

    所有字段从 ExecutionEvent 列表派生：
    - plan_total / plan_success / plan_failed: 从 plan_started / plan_finished 派生
    - step_total: 从 step_started（按 step_id 去重）派生
    - event_total: 输入 events 总数
    - providers: 从 provider_finished 按 provider 名聚合
    - avg_plan_latency_ms: 从 plan_started → plan_finished 时间差派生
    - avg_step_latency_ms: 从 step_finished.data.latency_ms 派生
    - total_cost_usd: 所有 provider 的 cost_usd 之和
    - since / until: events 的时间范围（首末 timestamp）
    """

    # 时间范围
    since: str | None = None
    until: str | None = None
    # Plan 维度
    plan_total: int = 0
    plan_success: int = 0
    plan_failed: int = 0
    # Step 维度
    step_total: int = 0
    # Event 维度
    event_total: int = 0
    # Provider 维度
    providers: list[ProviderStatistics] = field(default_factory=list)
    # Latency
    total_plan_latency_ms: float = 0.0
    plan_latency_count: int = 0
    total_step_latency_ms: float = 0.0
    step_latency_count: int = 0
    # Cost
    total_cost_usd: float = 0.0

    @property
    def avg_plan_latency_ms(self) -> float:
        """平均 Plan latency（ms）。"""
        return (
            self.total_plan_latency_ms / self.plan_latency_count
            if self.plan_latency_count > 0
            else 0.0
        )

    @property
    def avg_step_latency_ms(self) -> float:
        """平均 Step latency（ms）。"""
        return (
            self.total_step_latency_ms / self.step_latency_count
            if self.step_latency_count > 0
            else 0.0
        )

    @property
    def success_rate(self) -> float:
        """Plan 成功率（0.0 ~ 1.0，plan_total=0 时返回 0.0）。"""
        return self.plan_success / self.plan_total if self.plan_total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（JSON 可序列化）。"""
        return {
            "since": self.since,
            "until": self.until,
            "plans": {
                "total": self.plan_total,
                "success": self.plan_success,
                "failed": self.plan_failed,
                "success_rate": round(self.success_rate, 4),
            },
            "steps": {"total": self.step_total},
            "events": {"total": self.event_total},
            "providers": [p.to_dict() for p in self.providers],
            "latency": {
                "avg_plan_ms": round(self.avg_plan_latency_ms, 2),
                "avg_step_ms": round(self.avg_step_latency_ms, 2),
            },
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


class StatisticsCollector:
    """从 ExecutionEvent 列表派生 ExecutionStatistics（V0.9.7）。

    纯计算类，不接触 SQLite / EventBus。

    ⚠️ ChatGPT 唯一建议补充的原则（ADR-0020 决策 5，0.05 分）：

    **StatisticsCollector MUST be a pure read-only projection.**

    - 绝不修改 ExecutionEvent
    - 绝不补 ExecutionEvent
    - 绝不缓存 ExecutionEvent
    - 绝不写回 SQLite

    这是 Event Sourcing 的重要原则：Analytics Never Mutates Events。

    输入：``list[ExecutionEvent]``（来自 ``query_events()``）
    输出：``ExecutionStatistics``
    """

    @staticmethod
    def compute(events: list[ExecutionEvent]) -> ExecutionStatistics:
        """从 events 派生统计（Pure Read-Only Projection）。

        本方法无副作用：
        - 不修改入参 events
        - 不接触任何 Store / EventBus
        - 不缓存
        - 不写回

        识别的 event 类型：
        - ``plan_started`` → plan_total（按 plan_id 去重）
        - ``plan_finished`` → plan_success / plan_failed + plan_latency
        - ``step_started`` → step_total（按 step_id 去重）
        - ``step_finished`` → step_latency（来自 data.latency_ms）
        - ``provider_finished`` → provider stats（calls / latency / token / cost）

        Args:
            events: ExecutionEvent 列表（来自 query_events()）

        Returns:
            ExecutionStatistics
        """
        stats = ExecutionStatistics()

        if not events:
            return stats

        # 时间范围（events 已按 timestamp 升序）
        stats.since = events[0].timestamp
        stats.until = events[-1].timestamp
        stats.event_total = len(events)

        # 用于去重和配对
        seen_plan_ids: set[str] = set()
        seen_step_ids: set[str] = set()
        plan_started_ts: dict[str, str] = {}  # plan_id → started timestamp
        provider_stats: dict[str, ProviderStatistics] = {}

        for event in events:
            t = event.type

            if t == "plan_started":
                # plan_total 按 plan_id 去重
                if event.plan_id not in seen_plan_ids:
                    seen_plan_ids.add(event.plan_id)
                    stats.plan_total += 1
                # 记录 started timestamp 用于 latency 计算
                plan_started_ts[event.plan_id] = event.timestamp

            elif t == "plan_finished":
                # 从 data 派生 status
                status = str(event.data.get("status", "unknown"))
                if status == "success":
                    stats.plan_success += 1
                elif status == "failed":
                    stats.plan_failed += 1
                # 计算 plan latency（如果有配对的 plan_started）
                started_ts = plan_started_ts.get(event.plan_id)
                if started_ts is not None:
                    try:
                        delta_ms = (
                            _parse_iso_timestamp(event.timestamp)
                            - _parse_iso_timestamp(started_ts)
                        ).total_seconds() * 1000.0
                        stats.total_plan_latency_ms += delta_ms
                        stats.plan_latency_count += 1
                    except (ValueError, TypeError):
                        pass  # timestamp 解析失败，跳过 latency 计算

            elif t == "step_started":
                # step_total 按 step_id 去重
                if event.step_id is not None and event.step_id not in seen_step_ids:
                    seen_step_ids.add(event.step_id)
                    stats.step_total += 1

            elif t == "step_finished":
                # step latency 从 data.latency_ms 派生（V0.9.4 已发射）
                latency = event.data.get("latency_ms")
                if isinstance(latency, (int, float)) and latency >= 0:
                    stats.total_step_latency_ms += float(latency)
                    stats.step_latency_count += 1

            elif t == "provider_finished":
                # 按 provider 名聚合
                provider_name = event.provider or "unknown"
                if provider_name not in provider_stats:
                    provider_stats[provider_name] = ProviderStatistics(name=provider_name)
                ps = provider_stats[provider_name]
                ps.calls += 1

                # status
                status = str(event.data.get("status", "unknown"))
                if status == "success":
                    ps.success_count += 1
                elif status == "failed":
                    ps.failed_count += 1

                # latency
                if event.latency_ms is not None:
                    ps.total_latency_ms += int(event.latency_ms)

                # server_metrics（V0.9.6 派生）
                sm = event.data.get("server_metrics", {}) or {}
                token_in = sm.get("token_in", 0)
                token_out = sm.get("token_out", 0)
                cost = sm.get("cost_usd", 0.0)
                if isinstance(token_in, (int, float)):
                    ps.total_token_in += int(token_in)
                if isinstance(token_out, (int, float)):
                    ps.total_token_out += int(token_out)
                if isinstance(cost, (int, float)):
                    ps.total_cost_usd += float(cost)

        # 聚合 provider 列表（按 calls 降序，便于 CLI 展示）
        stats.providers = sorted(
            provider_stats.values(), key=lambda p: p.calls, reverse=True
        )

        # total_cost_usd = 所有 provider 的 cost 之和
        stats.total_cost_usd = sum(p.total_cost_usd for p in stats.providers)

        return stats
