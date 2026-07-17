# tests/test_event_bus.py
# V0.9.4 — EventBus 测试（ADR-0017）
#
# 覆盖：
# - subscribe / emit 基本流程
# - 多个订阅者
# - 订阅者异常隔离（try/except）
# - subscribe(event_type, callback) 接口预留（V0.9.4 内部不按 event_type 过滤）
# - clear() 测试用
# - subscriber_count

import pytest

from planner.event_bus import EventBus
from planner.execution_event import ExecutionEvent


class TestEventBusBasic:
    """EventBus 基本流程。"""

    def test_empty_bus(self):
        """空 bus。"""
        bus = EventBus()
        assert bus.subscriber_count() == 0

    def test_subscribe_and_emit(self):
        """订阅 + emit 触发回调。"""
        bus = EventBus()
        received = []

        def handler(event: ExecutionEvent) -> None:
            received.append(event)

        bus.subscribe(None, handler)
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))

        assert len(received) == 1
        assert received[0].type == "plan_started"

    def test_multiple_subscribers(self):
        """多个订阅者都被调用。"""
        bus = EventBus()
        results = {"h1": [], "h2": [], "h3": []}

        bus.subscribe(None, lambda e: results["h1"].append(e))
        bus.subscribe(None, lambda e: results["h2"].append(e))
        bus.subscribe(None, lambda e: results["h3"].append(e))

        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))

        assert len(results["h1"]) == 1
        assert len(results["h2"]) == 1
        assert len(results["h3"]) == 1

    def test_emit_to_empty_bus_is_noop(self):
        """空 bus emit 不抛异常。"""
        bus = EventBus()
        # 不应抛异常
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))

    def test_emit_multiple_events(self):
        """多次 emit 累积。"""
        bus = EventBus()
        received = []

        bus.subscribe(None, lambda e: received.append(e))
        for i in range(5):
            bus.emit(ExecutionEvent(type="step_started", plan_id=f"p-{i}"))

        assert len(received) == 5


class TestEventBusEventTypeAPI:
    """subscribe(event_type, callback) 接口预留。"""

    def test_subscribe_with_event_type(self):
        """subscribe(event_type, callback) 接口（V0.9.4 内部暂不过滤）。"""
        bus = EventBus()
        received = []

        # 即便传 event_type="plan_started"，V0.9.4 内部仍会调用所有订阅者
        bus.subscribe("plan_started", lambda e: received.append(e))
        bus.emit(ExecutionEvent(type="step_started", plan_id="p-001"))

        # V0.9.4 设计：不按 event_type 过滤（接口预留）
        assert len(received) == 1
        assert received[0].type == "step_started"

    def test_subscribe_with_event_type_v1_will_filter(self):
        """V0.9.4 当前不按 event_type 过滤（未来升级时再加）。"""
        # 这是 V0.9.4 的明确设计：V0.9.5+ EventBus 增强时才按 event_type 过滤
        bus = EventBus()
        received = []

        bus.subscribe("plan_started", lambda e: received.append(e))
        # 触发一个 step_started 事件
        bus.emit(ExecutionEvent(type="step_started", plan_id="p-001"))

        # V0.9.4: 仍触发（设计：内部不过滤）
        # V0.9.5+: 会过滤（订阅"plan_started"但 emit "step_started" → 不触发）
        assert len(received) == 1  # V0.9.4 行为

    def test_subscribe_with_none_type(self):
        """subscribe(None, callback) 表示订阅所有（V0.9.4 唯一行为）。"""
        bus = EventBus()
        received = []

        bus.subscribe(None, lambda e: received.append(e))
        bus.emit(ExecutionEvent(type="any_type", plan_id="p-001"))

        assert len(received) == 1


class TestEventBusExceptionIsolation:
    """订阅者异常隔离（ADR-0017 D2 关键要求）。"""

    def test_subscriber_exception_does_not_break_emit(self):
        """一个订阅者抛异常，其他订阅者仍执行。"""
        bus = EventBus()
        results = {"h1": None, "h2": None, "h3": None}

        def bad_handler(event):
            results["h1"] = "started"
            raise ValueError("intentional error")

        def good_handler(event):
            results["h2"] = "ok"

        def last_handler(event):
            results["h3"] = "ok"

        bus.subscribe(None, bad_handler)
        bus.subscribe(None, good_handler)
        bus.subscribe(None, last_handler)

        # 不应抛异常（异常被 try/except 隔离）
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))

        assert results["h1"] == "started"
        assert results["h2"] == "ok"  # 即使 h1 抛异常，h2 仍执行
        assert results["h3"] == "ok"

    def test_subscriber_exception_logged_not_raised(self, caplog):
        """订阅者异常被记录到 log（不抛给 emit 调用方）。"""
        import logging
        bus = EventBus()

        def bad_handler(event):
            raise RuntimeError("test exception")

        bus.subscribe(None, bad_handler)

        with caplog.at_level(logging.WARNING):
            bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))

        # 不抛异常
        # log 含 warning
        assert any("subscriber raised exception" in r.message for r in caplog.records)

    def test_multiple_exceptions_all_isolated(self):
        """多个订阅者都抛异常，emit 仍继续。"""
        bus = EventBus()

        def bad1(event):
            raise ValueError("e1")

        def bad2(event):
            raise ValueError("e2")

        bus.subscribe(None, bad1)
        bus.subscribe(None, bad2)

        # 不应抛异常
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))


class TestEventBusUtils:
    """工具方法。"""

    def test_subscriber_count(self):
        """subscriber_count 反映订阅者数量。"""
        bus = EventBus()
        assert bus.subscriber_count() == 0
        bus.subscribe(None, lambda e: None)
        assert bus.subscriber_count() == 1
        bus.subscribe(None, lambda e: None)
        assert bus.subscriber_count() == 2

    def test_clear_removes_all_subscribers(self):
        """clear() 清空所有订阅者。"""
        bus = EventBus()
        received = []
        bus.subscribe(None, lambda e: received.append(e))
        assert bus.subscriber_count() == 1

        bus.clear()
        assert bus.subscriber_count() == 0

        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert received == []

    def test_subscribe_non_callable_raises(self):
        """subscribe 非 callable 抛 TypeError。"""
        bus = EventBus()
        with pytest.raises(TypeError):
            bus.subscribe(None, "not a function")


class TestEventBusCallableTypes:
    """subscribe 接受不同 callable 类型。"""

    def test_subscribe_lambda(self):
        bus = EventBus()
        received = []
        bus.subscribe(None, lambda e: received.append(e.type))
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert received == ["plan_started"]

    def test_subscribe_instance_method(self):
        bus = EventBus()
        received = []

        class Handler:
            def __call__(self, event):
                received.append(event)

        bus.subscribe(None, Handler())
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert len(received) == 1

    def test_subscribe_bound_method(self):
        bus = EventBus()
        received = []

        class Subscriber:
            def handle(self, event):
                received.append(event)

        sub = Subscriber()
        bus.subscribe(None, sub.handle)
        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert len(received) == 1
