# tests/test_plan_store.py
# V0.9.3 — PlanStore 单元测试
#
# 覆盖（ADR-0016）：
# - 基础 CRUD：save / get / list_recent
# - 环形缓冲：超 max_size 弹出最早
# - 重复 save：移到队尾（更新语义）
# - 边界：max_size=1 / 0（应抛异常）/ 负数
# - list_recent limit 截断

import pytest

from planner.plan import Plan, Step
from planner.plan_store import PlanStore


def _make_plan(plan_id: str) -> Plan:
    return Plan(
        plan_id=plan_id,
        task_id=f"task-{plan_id}",
        steps=[Step(step_id="step-0", content="hi")],
        status="success",
    )


class TestPlanStoreBasic:
    """基础 CRUD。"""

    def test_save_and_get(self):
        store = PlanStore()
        plan = _make_plan("p1")
        store.save(plan)
        assert store.get("p1") is plan

    def test_get_nonexistent_returns_none(self):
        store = PlanStore()
        assert store.get("missing") is None

    def test_size_property(self):
        store = PlanStore()
        assert store.size == 0
        store.save(_make_plan("p1"))
        assert store.size == 1
        store.save(_make_plan("p2"))
        assert store.size == 2

    def test_max_size_property(self):
        store = PlanStore(max_size=5)
        assert store.max_size == 5


class TestPlanStoreRingBuffer:
    """环形缓冲行为。"""

    def test_evict_oldest_when_full(self):
        """满了之后插入新的，弹出最早。"""
        store = PlanStore(max_size=3)
        store.save(_make_plan("p1"))
        store.save(_make_plan("p2"))
        store.save(_make_plan("p3"))
        store.save(_make_plan("p4"))  # 触发弹出

        assert store.size == 3
        assert store.get("p1") is None  # 最早被弹出
        assert store.get("p2") is not None
        assert store.get("p3") is not None
        assert store.get("p4") is not None

    def test_save_existing_id_moves_to_end(self):
        """重复 save 同一 plan_id 移到队尾。"""
        store = PlanStore(max_size=3)
        p1 = _make_plan("p1")
        p2 = _make_plan("p2")
        p3 = _make_plan("p3")
        store.save(p1)
        store.save(p2)
        store.save(p3)

        # 重新 save p1，移到队尾
        p1_updated = _make_plan("p1")
        store.save(p1_updated)

        # list_recent 顺序：p1（最近，刚被移到队尾）, p3, p2
        recent = store.list_recent(limit=10)
        assert [p.plan_id for p in recent] == ["p1", "p3", "p2"]

    def test_save_existing_does_not_evict(self):
        """重复 save 同一 plan_id 不应触发环形弹出。"""
        store = PlanStore(max_size=2)
        store.save(_make_plan("p1"))
        store.save(_make_plan("p2"))
        store.save(_make_plan("p1"))  # 重复

        assert store.size == 2
        assert store.get("p1") is not None
        assert store.get("p2") is not None


class TestPlanStoreListRecent:
    """list_recent 行为。"""

    def test_list_recent_returns_newest_first(self):
        store = PlanStore()
        store.save(_make_plan("p1"))
        store.save(_make_plan("p2"))
        store.save(_make_plan("p3"))

        recent = store.list_recent(limit=10)
        assert [p.plan_id for p in recent] == ["p3", "p2", "p1"]

    def test_list_recent_respects_limit(self):
        store = PlanStore()
        for i in range(5):
            store.save(_make_plan(f"p{i}"))

        recent = store.list_recent(limit=3)
        assert len(recent) == 3
        # 最近 3 个：p4, p3, p2
        assert [p.plan_id for p in recent] == ["p4", "p3", "p2"]

    def test_list_recent_zero_returns_empty(self):
        store = PlanStore()
        store.save(_make_plan("p1"))
        assert store.list_recent(limit=0) == []

    def test_list_recent_negative_returns_empty(self):
        store = PlanStore()
        store.save(_make_plan("p1"))
        assert store.list_recent(limit=-1) == []

    def test_list_recent_on_empty_store(self):
        store = PlanStore()
        assert store.list_recent(limit=10) == []


class TestPlanStoreEdgeCases:
    """边界与异常。"""

    def test_max_size_zero_raises(self):
        with pytest.raises(ValueError, match="max_size must be > 0"):
            PlanStore(max_size=0)

    def test_max_size_negative_raises(self):
        with pytest.raises(ValueError, match="max_size must be > 0"):
            PlanStore(max_size=-1)

    def test_clear(self):
        store = PlanStore()
        store.save(_make_plan("p1"))
        store.save(_make_plan("p2"))
        store.clear()
        assert store.size == 0
        assert store.get("p1") is None

    def test_max_size_one_ring_buffer(self):
        """max_size=1 退化场景。"""
        store = PlanStore(max_size=1)
        store.save(_make_plan("p1"))
        store.save(_make_plan("p2"))

        assert store.size == 1
        assert store.get("p1") is None
        assert store.get("p2") is not None
