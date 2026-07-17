# tests/test_statistics.py
# V0.9.7 — ExecutionStatistics + ProviderStatistics + StatisticsCollector 测试（ADR-0020）
#
# 覆盖：
# - StatisticsCollector.compute() 从 events 派生
# - Read-Only Projection 原则（无副作用）
# - 空 events / 单 plan 全成功 / 单 plan 失败 / 多 plan 混合
# - 多 provider 聚合 / token/cost 累加
# - success_rate / avg_latency_ms / to_dict
# - ProviderStatistics.to_dict
# - ExecutionStatistics.to_dict
#
# 测试隔离：纯函数，构造 ExecutionEvent list，不接触 SQLite / EventBus

import pytest

from planner.execution_event import ExecutionEvent
from planner.statistics import (
    ExecutionStatistics,
    ProviderStatistics,
    StatisticsCollector,
)


# ── helpers ──

def _plan_events(
    plan_id: str,
    status: str = "success",
    started_ts: str = "2026-07-17T10:00:00.000Z",
    finished_ts: str = "2026-07-17T10:00:01.000Z",
    steps: int = 1,
    with_provider: bool = True,
    provider_name: str = "fake",
    provider_latency_ms: int = 200,
    server_metrics: dict | None = None,
) -> list:
    """构造一个完整 plan 的 events（参考 _make_events in test_sqlite_execution_store）。"""
    events = [
        ExecutionEvent(type="plan_started", plan_id=plan_id, timestamp=started_ts),
        ExecutionEvent(type="planner_started", plan_id=plan_id, timestamp=started_ts),
        ExecutionEvent(type="planner_finished", plan_id=plan_id, timestamp=started_ts, data={"step_count": steps}),
    ]
    for i in range(steps):
        step_started_ts = started_ts
        step_finished_ts = finished_ts
        events.append(ExecutionEvent(
            type="step_started", plan_id=plan_id, step_id=f"step-{i}",
            timestamp=step_started_ts, data={"index": i},
        ))
        if with_provider:
            events.append(ExecutionEvent(
                type="provider_selected", plan_id=plan_id, step_id=f"step-{i}",
                provider="ScoreRouter", timestamp=step_started_ts,
            ))
            data = {"status": status}
            if server_metrics is not None:
                data["server_metrics"] = server_metrics
            events.append(ExecutionEvent(
                type="provider_finished", plan_id=plan_id, step_id=f"step-{i}",
                provider=provider_name, timestamp=step_started_ts,
                latency_ms=provider_latency_ms, data=data,
            ))
        events.append(ExecutionEvent(
            type="step_finished", plan_id=plan_id, step_id=f"step-{i}",
            timestamp=step_finished_ts, data={"status": status, "latency_ms": provider_latency_ms},
        ))
    events.append(ExecutionEvent(
        type="plan_finished", plan_id=plan_id, timestamp=finished_ts,
        data={"status": status, "steps": steps, "success": steps if status == "success" else 0, "failed": 0 if status == "success" else 1},
    ))
    return events


# ── StatisticsCollector.compute() 基本行为 ──

class TestStatisticsCollectorBasic:
    """StatisticsCollector 基本派生行为。"""

    def test_empty_events_returns_empty_stats(self):
        """空 events：返回默认 ExecutionStatistics（0 字段）。"""
        stats = StatisticsCollector.compute([])
        assert stats.plan_total == 0
        assert stats.plan_success == 0
        assert stats.plan_failed == 0
        assert stats.step_total == 0
        assert stats.event_total == 0
        assert stats.providers == []
        assert stats.success_rate == 0.0
        assert stats.avg_plan_latency_ms == 0.0
        assert stats.avg_step_latency_ms == 0.0
        assert stats.total_cost_usd == 0.0
        assert stats.since is None
        assert stats.until is None

    def test_single_plan_success(self):
        """单 plan 全部成功。"""
        events = _plan_events("p-001", status="success", steps=2)
        stats = StatisticsCollector.compute(events)

        assert stats.plan_total == 1
        assert stats.plan_success == 1
        assert stats.plan_failed == 0
        assert stats.step_total == 2
        assert stats.success_rate == 1.0
        assert stats.event_total == len(events)
        assert stats.providers[0].calls == 2
        assert stats.providers[0].success_count == 2
        assert stats.providers[0].failed_count == 0
        assert stats.providers[0].avg_latency_ms == 200.0
        # plan_latency = 1s = 1000ms
        assert stats.avg_plan_latency_ms == 1000.0
        # step_latency = 200ms
        assert stats.avg_step_latency_ms == 200.0

    def test_single_plan_failed(self):
        """单 plan 全部失败。"""
        events = _plan_events("p-001", status="failed", steps=1)
        stats = StatisticsCollector.compute(events)

        assert stats.plan_total == 1
        assert stats.plan_success == 0
        assert stats.plan_failed == 1
        assert stats.success_rate == 0.0
        assert stats.providers[0].success_count == 0
        assert stats.providers[0].failed_count == 1

    def test_multiple_plans_mixed(self):
        """多 plan 混合成功/失败。"""
        events = []
        events.extend(_plan_events("p-001", status="success", steps=1))
        events.extend(_plan_events("p-002", status="failed", steps=1))
        events.extend(_plan_events("p-003", status="success", steps=2))

        stats = StatisticsCollector.compute(events)

        assert stats.plan_total == 3
        assert stats.plan_success == 2
        assert stats.plan_failed == 1
        assert stats.success_rate == 2 / 3


# ── Provider 维度 ──

class TestProviderStatistics:
    """Provider 聚合测试。"""

    def test_single_provider_aggregation(self):
        """单 provider 多次调用。"""
        events = _plan_events("p-001", status="success", steps=3)
        stats = StatisticsCollector.compute(events)
        assert len(stats.providers) == 1
        p = stats.providers[0]
        assert p.name == "fake"
        assert p.calls == 3
        assert p.avg_latency_ms == 200.0

    def test_multiple_providers_separate(self):
        """多 provider 分别聚合（按 calls 降序）。"""
        events = []
        events.extend(_plan_events("p-001", status="success", steps=2, provider_name="openai_api"))
        events.extend(_plan_events("p-002", status="success", steps=3, provider_name="openai_compatible"))
        events.extend(_plan_events("p-003", status="success", steps=1, provider_name="openai_api"))

        stats = StatisticsCollector.compute(events)
        assert len(stats.providers) == 2
        # 按 calls 降序
        assert stats.providers[0].name == "openai_api"
        assert stats.providers[0].calls == 3
        assert stats.providers[1].name == "openai_compatible"
        assert stats.providers[1].calls == 3

    def test_token_cost_accumulation(self):
        """token / cost 从 server_metrics 累加。"""
        events = _plan_events(
            "p-001", status="success", steps=2,
            server_metrics={"token_in": 100, "token_out": 50, "cost_usd": 0.001},
        )
        stats = StatisticsCollector.compute(events)
        p = stats.providers[0]
        # 2 steps × (100 in + 50 out) = 200 in, 100 out
        assert p.total_token_in == 200
        assert p.total_token_out == 100
        # 2 × $0.001 = $0.002
        assert abs(p.total_cost_usd - 0.002) < 1e-9
        # total_cost_usd 累加
        assert abs(stats.total_cost_usd - 0.002) < 1e-9

    def test_missing_server_metrics_handled_gracefully(self):
        """无 server_metrics 字段：token/cost = 0。"""
        events = _plan_events("p-001", status="success", steps=1)
        stats = StatisticsCollector.compute(events)
        p = stats.providers[0]
        assert p.total_token_in == 0
        assert p.total_token_out == 0
        assert p.total_cost_usd == 0.0

    def test_provider_avg_latency_zero_when_no_calls(self):
        """Provider 无调用：avg_latency_ms = 0.0。"""
        stats = ExecutionStatistics()
        p = ProviderStatistics(name="unused")
        assert p.calls == 0
        assert p.avg_latency_ms == 0.0


# ── Read-Only Projection 原则（ChatGPT 唯一补充原则） ──

class TestReadOnlyProjection:
    """StatisticsCollector MUST NOT mutate events（ChatGPT 唯一补充原则，0.05 分）。"""

    def test_compute_does_not_modify_input_events(self):
        """compute() 不修改入参 events。"""
        events = _plan_events("p-001", status="success", steps=1)
        # 记录原始 event_id 和 data
        original_snapshot = [
            (e.event_id, e.type, e.plan_id, e.timestamp, e.data.copy())
            for e in events
        ]
        StatisticsCollector.compute(events)

        # 验证 events 未被修改
        for e, snap in zip(events, original_snapshot):
            assert e.event_id == snap[0]
            assert e.type == snap[1]
            assert e.plan_id == snap[2]
            assert e.timestamp == snap[3]
            assert e.data == snap[4]

    def test_compute_does_not_modify_event_data(self):
        """compute() 不修改 event.data dict。"""
        events = _plan_events(
            "p-001", status="success", steps=1,
            server_metrics={"token_in": 100, "token_out": 50, "cost_usd": 0.001},
        )
        original_data = events[0].data.copy()
        StatisticsCollector.compute(events)
        # event.data 应保持不变
        assert events[0].data == original_data

    def test_compute_pure_function_same_input_same_output(self):
        """compute() 是纯函数：相同输入 → 相同输出。"""
        events = _plan_events("p-001", status="success", steps=1)
        stats1 = StatisticsCollector.compute(events)
        stats2 = StatisticsCollector.compute(events)

        # 数值字段相等
        assert stats1.plan_total == stats2.plan_total
        assert stats1.plan_success == stats2.plan_success
        assert stats1.providers[0].calls == stats2.providers[0].calls
        # to_dict 一致
        assert stats1.to_dict() == stats2.to_dict()


# ── ExecutionStatistics 字段 ──

class TestExecutionStatisticsFields:
    """ExecutionStatistics 字段派生测试。"""

    def test_time_range(self):
        """since/until = events[0] / events[-1] timestamp。"""
        events = _plan_events(
            "p-001",
            started_ts="2026-07-17T10:00:00.000Z",
            finished_ts="2026-07-17T10:00:01.000Z",
        )
        stats = StatisticsCollector.compute(events)
        assert stats.since == "2026-07-17T10:00:00.000Z"
        assert stats.until == "2026-07-17T10:00:01.000Z"

    def test_event_count(self):
        """event_total = 输入 events 数。"""
        events = _plan_events("p-001", status="success", steps=2)
        stats = StatisticsCollector.compute(events)
        assert stats.event_total == len(events)

    def test_step_count_dedup_by_step_id(self):
        """step_total 按 step_id 去重。"""
        events = _plan_events("p-001", status="success", steps=3)
        stats = StatisticsCollector.compute(events)
        assert stats.step_total == 3

    def test_avg_plan_latency_multiple_plans(self):
        """多 plan 平均 latency。"""
        events = []
        # Plan 1: 1s latency
        events.extend(_plan_events(
            "p-001", started_ts="2026-07-17T10:00:00.000Z",
            finished_ts="2026-07-17T10:00:01.000Z",
        ))
        # Plan 2: 2s latency
        events.extend(_plan_events(
            "p-002", started_ts="2026-07-17T11:00:00.000Z",
            finished_ts="2026-07-17T11:00:02.000Z",
        ))
        stats = StatisticsCollector.compute(events)
        # avg = (1000 + 2000) / 2 = 1500ms
        assert stats.avg_plan_latency_ms == 1500.0

    def test_success_rate_zero_when_no_plans(self):
        """无 plan：success_rate = 0.0。"""
        # 只有 step_started，没有 plan_finished
        events = [ExecutionEvent(type="step_started", plan_id="p-001", step_id="step-0")]
        stats = StatisticsCollector.compute(events)
        assert stats.plan_total == 0
        assert stats.success_rate == 0.0


# ── to_dict / JSON 可序列化 ──

class TestToDict:
    """to_dict 测试。"""

    def test_provider_to_dict(self):
        """ProviderStatistics.to_dict 包含全部字段。"""
        p = ProviderStatistics(
            name="openai_api", calls=10, success_count=8, failed_count=2,
            total_latency_ms=2000, total_token_in=1000, total_token_out=500,
            total_cost_usd=0.05,
        )
        d = p.to_dict()
        assert d["name"] == "openai_api"
        assert d["calls"] == 10
        assert d["success_count"] == 8
        assert d["failed_count"] == 2
        assert d["avg_latency_ms"] == 200.0
        assert d["total_token_in"] == 1000
        assert d["total_token_out"] == 500
        assert d["total_cost_usd"] == 0.05

    def test_execution_statistics_to_dict(self):
        """ExecutionStatistics.to_dict 包含全部字段（JSON 可序列化）。"""
        events = _plan_events(
            "p-001", status="success", steps=1,
            server_metrics={"token_in": 100, "token_out": 50, "cost_usd": 0.001},
        )
        stats = StatisticsCollector.compute(events)
        d = stats.to_dict()

        assert "since" in d
        assert "until" in d
        assert d["plans"]["total"] == 1
        assert d["plans"]["success"] == 1
        assert d["plans"]["success_rate"] == 1.0
        assert d["steps"]["total"] == 1
        assert d["events"]["total"] == len(events)
        assert len(d["providers"]) == 1
        assert d["providers"][0]["name"] == "fake"
        assert d["latency"]["avg_plan_ms"] == 1000.0
        assert d["latency"]["avg_step_ms"] == 200.0
        assert abs(d["total_cost_usd"] - 0.001) < 1e-9

    def test_to_dict_is_json_serializable(self):
        """to_dict 必须可 JSON 序列化（ADR-0018 原则 B）。"""
        import json
        events = _plan_events("p-001", status="success", steps=1)
        stats = StatisticsCollector.compute(events)
        # 不应抛异常
        json_str = json.dumps(stats.to_dict(), ensure_ascii=False)
        assert "providers" in json_str
