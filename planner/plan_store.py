# AI Hub — PlanStore
# V0.9.3: 进程内 Plan 存储（环形缓冲）
#
# 职责（ADR-0016）：
#   - 提供进程内的 Plan 存储（CLI `ai-hub inspect` 用）
#   - 环形缓冲，默认 max_size=10
#   - 单线程（不引入锁），由 CLI 单进程顺序调用
#
# 不做（V0.9.4+ 推迟）：
#   - 持久化（SQLite / Memory Bus）
#   - 跨进程
#   - 索引 / 搜索 / 过滤
#
# API Stability: Experimental

from __future__ import annotations

from collections import OrderedDict

from planner.plan import Plan


class PlanStore:
    """进程内 Plan 存储（环形缓冲，最多 max_size 个）。

    V0.9.3 单进程单线程使用，不引入锁。
    V0.9.4+ 持久化或并发场景时，本类将由子类化或替换为持久化实现。

    API Stability: Experimental
    """

    def __init__(self, max_size: int = 10):
        """
        Args:
            max_size: 环形缓冲最大容量（默认 10）
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be > 0, got {max_size}")

        self._store: OrderedDict[str, Plan] = OrderedDict()
        self._max = max_size

    @property
    def max_size(self) -> int:
        return self._max

    @property
    def size(self) -> int:
        return len(self._store)

    def save(self, plan: Plan) -> None:
        """保存 Plan 到环形缓冲。

        行为：
        - 如果 plan_id 已存在：移到队尾（更新语义）
        - 如果已满：弹出最早插入的
        - 否则：追加到队尾
        """
        if plan.plan_id in self._store:
            self._store.move_to_end(plan.plan_id)
        else:
            if len(self._store) >= self._max:
                self._store.popitem(last=False)
            self._store[plan.plan_id] = plan

    def get(self, plan_id: str) -> Plan | None:
        """按 plan_id 查询 Plan。"""
        return self._store.get(plan_id)

    def list_recent(self, limit: int = 10) -> list[Plan]:
        """列出最近的 Plan（最近插入的在前）。

        Args:
            limit: 最多返回的 plan 数（不超过 self.size）
        """
        if limit <= 0:
            return []
        # values() 是按插入顺序，最近的在末尾
        all_plans = list(self._store.values())
        return all_plans[-limit:][::-1]

    def clear(self) -> None:
        """清空存储（测试用）。"""
        self._store.clear()
