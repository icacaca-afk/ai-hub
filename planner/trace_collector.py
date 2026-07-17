# AI Hub — InMemoryTraceCollector
# V0.9.4: 进程内 Trace 收集器（订阅 EventBus，存最近 N 个 plan 的 events）
#
# ADR-0017 D7（ChatGPT 审核强建议）：
#   - 与 PlanStore 完全解耦：
#     PlanStore 存 Plan（业务），TraceCollector 存 events（过程）
#   - 不要统一 Store。建立关联：
#     TraceCollector.has(plan_id)  ← V0.9.4 强制实现
#   - inspect 显示 "Trace: Available/No Trace"
#
# ChatGPT 关键评价（D5）：
#   PlanStore 回答「发生了什么？」
#   Trace 回答「怎么发生的？」
#
# 不持久化（V0.9.4）。V0.9.5+ 引入 SQLite ExecutionStore 时，本类可由子类化替换。
#
# 不修改 core/ + router/ + providers/（Core Freeze）。
#
# API Stability: Experimental

from __future__ import annotations

import logging
from collections import OrderedDict

from planner.event_bus import EventBus
from planner.execution_event import ExecutionEvent


_log = logging.getLogger(__name__)


# V0.9.4 默认 Trace 容量
DEFAULT_TRACE_SIZE: int = 10


class InMemoryTraceCollector:
    """进程内 Trace 收集器（V0.9.4）。

    订阅 EventBus，存最近 N 个 plan 的 events（环形缓冲）。

    与 PlanStore 的区别（ChatGPT 强建议）：
    - PlanStore: plan 业务
    - TraceCollector: plan 执行过程

    V0.9.4 不持久化。V0.9.5+ 持久化由子类化或替换为 SQLite 实现。
    """

    def __init__(self, max_plans: int = DEFAULT_TRACE_SIZE) -> None:
        """
        Args:
            max_plans: 最多保存多少个 plan 的 events（环形缓冲）
        """
        if max_plans <= 0:
            raise ValueError(f"max_plans must be > 0, got {max_plans}")

        # OrderedDict 保持插入顺序；环形缓冲用 popitem(last=False)
        self._events: OrderedDict[str, list[ExecutionEvent]] = OrderedDict()
        self._max = max_plans
        self._bus: EventBus | None = None
        # 预绑定 handle 方法（避免每次访问 self.handle 创建新 bound method 对象）
        self._handle_bound = self.handle
        # 预缓存 handler id（id() 在 bound method 跨调用时不稳定，但函数 id 稳定）
        # 用 self.handle 函数本身的 id 不行（bound method 的 id 每次都变）
        # 解决方案：用 (self, "handle") 元组作为 key
        self._handler_key = (id(self), "handle")

    def attach(self, bus: EventBus) -> None:
        """订阅 EventBus。

        V0.9.4 订阅所有 event_type（传 None 给 subscribe()）。
        如已 attach 过，会先 unsubscribe。
        """
        if self._bus is not None:
            self.detach()
        self._bus = bus
        bus.subscribe(None, self._handle_bound)

    def detach(self) -> None:
        """取消订阅（V0.9.4：使用 EventBus.unsubscribe）。"""
        if self._bus is not None:
            self._bus.unsubscribe(self._handle_bound)
            self._bus = None

    def handle(self, event: ExecutionEvent) -> None:
        """EventBus 回调：存到对应 plan_id 的 events 列表。"""
        plan_id = event.plan_id
        if plan_id not in self._events:
            # 环形缓冲：满则弹出最早
            if len(self._events) >= self._max:
                self._events.popitem(last=False)
            self._events[plan_id] = []
        # append 顺序保留（events 按 emit 时间）
        self._events[plan_id].append(event)

    def has(self, plan_id: str) -> bool:
        """是否有该 plan_id 的 trace（ChatGPT 强建议 D5：建立关联）。"""
        return plan_id in self._events

    def get_trace(self, plan_id: str) -> list[ExecutionEvent]:
        """获取某 plan_id 的全部 events（按时间顺序）。

        Args:
            plan_id: Plan 唯一标识

        Returns:
            events 列表（可能为空）
        """
        return list(self._events.get(plan_id, []))

    def list_traced_plans(self) -> list[str]:
        """列出所有被 trace 的 plan_id（按 trace 顺序，最近在前）。"""
        return list(reversed(self._events.keys()))

    def clear(self) -> None:
        """清空所有 events（测试用）。"""
        self._events.clear()

    @property
    def size(self) -> int:
        """已 trace 的 plan 数。"""
        return len(self._events)

    @property
    def max_size(self) -> int:
        """最大 plan 数。"""
        return self._max
