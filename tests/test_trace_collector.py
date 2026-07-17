# tests/test_trace_collector.py
# V0.9.4 — InMemoryTraceCollector 测试（ADR-0017）
#
# 覆盖：
# - 订阅 EventBus 收集 events
# - has(plan_id) 关联（ChatGPT 强建议 D5）
# - get_trace(plan_id) 按时间顺序
# - list_traced_plans() 最近在前
# - 环形缓冲（max_plans）
# - 与 PlanStore 解耦
# - DEFAULT_TRACE_SIZE 常量

import pytest

from planner.event_bus import EventBus
from planner.execution_event import ExecutionEvent
from planner.trace_collector import InMemoryTraceCollector, DEFAULT_TRACE_SIZE


class TestInMemoryTraceCollectorBasic:
    """基本行为。"""

    def test_empty_collector(self):
        c = InMemoryTraceCollector()
        assert c.size == 0
        assert c.max_size == DEFAULT_TRACE_SIZE
        assert c.has("p-001") is False

    def test_default_trace_size(self):
        """DEFAULT_TRACE_SIZE 常量。"""
        assert DEFAULT_TRACE_SIZE == 10

    def test_invalid_max_plans_raises(self):
        """max_plans <= 0 抛 ValueError。"""
        with pytest.raises(ValueError):
            InMemoryTraceCollector(max_plans=0)
        with pytest.raises(ValueError):
            InMemoryTraceCollector(max_plans=-1)

    def test_handle_stores_event(self):
        """handle() 存 event 到对应 plan_id。"""
        c = InMemoryTraceCollector()
        c.handle(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert c.has("p-001")
        assert c.size == 1
        events = c.get_trace("p-001")
        assert len(events) == 1
        assert events[0].type == "plan_started"

    def test_get_trace_returns_empty_list_for_unknown(self):
        """未知 plan_id 返回空 list（不抛异常）。"""
        c = InMemoryTraceCollector()
        assert c.get_trace("unknown") == []


class TestInMemoryTraceCollectorBusIntegration:
    """EventBus 集成。"""

    def test_attach_subscribes_to_bus(self):
        """attach 后 emit 事件会被收集。"""
        bus = EventBus()
        c = InMemoryTraceCollector()
        c.attach(bus)

        # emit 一个事件
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        bus.emit(ExecutionEvent(type="step_started", plan_id="p-001", step_id="step-0"))

        # collector 收到
        assert c.size == 1  # 1 个 plan
        assert c.has("p-001")
        events = c.get_trace("p-001")
        assert len(events) == 2
        assert events[0].type == "plan_started"
        assert events[1].type == "step_started"

    def test_detach_stops_receiving(self):
        """detach 后 emit 事件不被收集。"""
        bus = EventBus()
        c = InMemoryTraceCollector()
        c.attach(bus)
        c.detach()

        # detach 后 emit（bus 仍存在，但 collector 不再订阅）
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert c.size == 0

    def test_multiple_collectors_on_one_bus(self):
        """一个 bus 多个 collector 各自独立。"""
        bus = EventBus()
        c1 = InMemoryTraceCollector()
        c2 = InMemoryTraceCollector()
        c1.attach(bus)
        c2.attach(bus)

        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))

        # 两个 collector 都收到
        assert c1.size == 1
        assert c2.size == 1

    def test_attach_reattaches(self):
        """attach 二次时，先 detach 再 attach。"""
        bus = EventBus()
        c = InMemoryTraceCollector()
        c.attach(bus)
        c.attach(bus)  # 二次 attach

        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        # 二次 attach 不应导致重复（V0.9.4 简化实现：内部覆盖）
        # V0.9.4 实际：_bus 被覆盖为最新 bus，仍是 1 个订阅
        assert c.size == 1


class TestInMemoryTraceCollectorOrdering:
    """顺序与最近在前。"""

    def test_events_ordered_by_emit_time(self):
        """events 按 emit 时间顺序。"""
        c = InMemoryTraceCollector()
        c.handle(ExecutionEvent(type="plan_started", plan_id="p-001"))
        c.handle(ExecutionEvent(type="step_started", plan_id="p-001", step_id="s-0"))
        c.handle(ExecutionEvent(type="step_finished", plan_id="p-001", step_id="s-0"))

        events = c.get_trace("p-001")
        assert [e.type for e in events] == ["plan_started", "step_started", "step_finished"]

    def test_list_traced_plans_most_recent_first(self):
        """list_traced_plans 最近在前。"""
        c = InMemoryTraceCollector()
        for i in range(5):
            c.handle(ExecutionEvent(type="plan_started", plan_id=f"p{i}"))

        plans = c.list_traced_plans()
        # 最近在前：p4, p3, p2, p1, p0
        assert plans == ["p4", "p3", "p2", "p1", "p0"]


class TestInMemoryTraceCollectorRingBuffer:
    """环形缓冲。"""

    def test_max_plans_evicts_oldest(self):
        """max_plans 满后弹最早的。"""
        c = InMemoryTraceCollector(max_plans=3)
        for i in range(5):
            c.handle(ExecutionEvent(type="plan_started", plan_id=f"p{i}"))

        # 弹出 p0, p1；保留 p2, p3, p4
        assert c.size == 3
        assert not c.has("p0")
        assert not c.has("p1")
        assert c.has("p2")
        assert c.has("p3")
        assert c.has("p4")

    def test_same_plan_id_appends_does_not_evict(self):
        """同一 plan_id 多次事件不触发弹出。"""
        c = InMemoryTraceCollector(max_plans=3)
        c.handle(ExecutionEvent(type="plan_started", plan_id="p0"))
        c.handle(ExecutionEvent(type="step_started", plan_id="p0", step_id="s-0"))
        c.handle(ExecutionEvent(type="step_finished", plan_id="p0", step_id="s-0"))

        assert c.size == 1
        assert len(c.get_trace("p0")) == 3


class TestInMemoryTraceCollectorVsPlanStore:
    """TraceCollector 与 PlanStore 解耦（ChatGPT 强建议 D5）。"""

    def test_trace_collector_independent_from_plan_store(self):
        """TraceCollector 与 PlanStore 各自独立。"""
        from planner.plan_store import PlanStore

        trace = InMemoryTraceCollector()
        plans = PlanStore()

        # trace 收 event 但 plan 不存
        trace.handle(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert trace.has("p-001")
        assert plans.get("p-001") is None

        # 模拟：plan 保存但 trace 没记录
        from planner.plan import Plan
        plans.save(Plan(plan_id="p-002", task_id="t-002", steps=[]))
        assert trace.has("p-002") is False
        assert plans.get("p-002") is not None

    def test_has_method_for_association(self):
        """has(plan_id) 用于建立 Plan ↔ Trace 关联（ChatGPT D5）。"""
        c = InMemoryTraceCollector()
        # 默认 False
        assert c.has("p-001") is False
        # 存 event 后 True
        c.handle(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert c.has("p-001") is True


class TestInMemoryTraceCollectorClear:
    """clear()。"""

    def test_clear_empties_all_events(self):
        c = InMemoryTraceCollector()
        c.handle(ExecutionEvent(type="plan_started", plan_id="p-001"))
        c.handle(ExecutionEvent(type="plan_started", plan_id="p-002"))
        assert c.size == 2

        c.clear()
        assert c.size == 0
        assert not c.has("p-001")
        assert not c.has("p-002")
