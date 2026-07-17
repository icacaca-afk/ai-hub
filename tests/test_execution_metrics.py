# tests/test_execution_metrics.py
# V0.9.4 — ExecutionMetrics 数据类测试（ADR-0017）
#
# 覆盖：
# - 字段默认值（latency_ms=0, token_in=0, token_out=0, cost_usd=0.0, retry_count=0）
# - 字段可测量（不含 status / provider / error）
# - to_dict() 序列化
# - add() 聚合（Plan 层 metrics）
# - 与 ExecutionResult 解耦

import json
import pytest

from planner.execution_metrics import ExecutionMetrics


class TestExecutionMetricsDefaults:
    """字段默认值。"""

    def test_default_all_zero(self):
        """未指定时所有可测量字段为 0。"""
        m = ExecutionMetrics()
        assert m.latency_ms == 0
        assert m.token_in == 0
        assert m.token_out == 0
        assert m.cost_usd == 0.0
        assert m.retry_count == 0

    def test_only_measurable_fields(self):
        """Metrics 只含可测量字段（ChatGPT 强建议）。"""
        m = ExecutionMetrics()
        # 不应有 status / provider / error 这些字段（不是 Metrics）
        assert not hasattr(m, "status")
        assert not hasattr(m, "provider")
        assert not hasattr(m, "error")

    def test_field_assignment(self):
        """显式赋值。"""
        m = ExecutionMetrics(latency_ms=200, token_in=100, token_out=50, cost_usd=0.01, retry_count=2)
        assert m.latency_ms == 200
        assert m.token_in == 100
        assert m.token_out == 50
        assert m.cost_usd == 0.01
        assert m.retry_count == 2


class TestExecutionMetricsToDict:
    """to_dict() 序列化。"""

    def test_to_dict_default(self):
        m = ExecutionMetrics()
        d = m.to_dict()
        assert d == {
            "latency_ms": 0,
            "token_in": 0,
            "token_out": 0,
            "cost_usd": 0.0,
            "retry_count": 0,
        }

    def test_to_dict_with_values(self):
        m = ExecutionMetrics(latency_ms=200, token_in=100)
        d = m.to_dict()
        assert d["latency_ms"] == 200
        assert d["token_in"] == 100
        assert d["token_out"] == 0
        assert d["cost_usd"] == 0.0
        assert d["retry_count"] == 0

    def test_to_dict_is_json_serializable(self):
        m = ExecutionMetrics(latency_ms=200, cost_usd=0.0123)
        json_str = json.dumps(m.to_dict())
        parsed = json.loads(json_str)
        assert parsed["latency_ms"] == 200
        assert parsed["cost_usd"] == 0.0123


class TestExecutionMetricsAdd:
    """add() 聚合（Plan 层 metrics）。"""

    def test_add_latency(self):
        """两个 step 的 latency 累加。"""
        a = ExecutionMetrics(latency_ms=100)
        b = ExecutionMetrics(latency_ms=200)
        a.add(b)
        assert a.latency_ms == 300

    def test_add_tokens(self):
        """tokens 累加。"""
        a = ExecutionMetrics(token_in=10, token_out=5)
        b = ExecutionMetrics(token_in=20, token_out=15)
        a.add(b)
        assert a.token_in == 30
        assert a.token_out == 20

    def test_add_cost(self):
        """cost 累加。"""
        a = ExecutionMetrics(cost_usd=0.01)
        b = ExecutionMetrics(cost_usd=0.005)
        a.add(b)
        assert a.cost_usd == pytest.approx(0.015)

    def test_add_retry(self):
        """retry 累加。"""
        a = ExecutionMetrics(retry_count=1)
        b = ExecutionMetrics(retry_count=2)
        a.add(b)
        assert a.retry_count == 3

    def test_add_multiple_step_aggregation(self):
        """模拟 Plan 聚合 3 步的 metrics。"""
        plan_metrics = ExecutionMetrics()
        for step_latency in [100, 200, 150]:
            step_m = ExecutionMetrics(latency_ms=step_latency)
            plan_metrics.add(step_m)
        assert plan_metrics.latency_ms == 450

    def test_add_does_not_affect_source(self):
        """add 不修改源（除了 self）。"""
        a = ExecutionMetrics(latency_ms=100)
        b = ExecutionMetrics(latency_ms=200)
        a.add(b)
        # b 保持不变
        assert b.latency_ms == 200
