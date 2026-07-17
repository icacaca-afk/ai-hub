# AI Hub — EventBus
# V0.9.4: 进程内事件总线（Single Source of Execution Truth 的分发器）
#
# ADR-0017 D2（ChatGPT 强建议）：
#   简单 list-of-callbacks 实现。
#   - subscribe(event_type, callback) 接口预留（V0.9.4 内部暂不过滤）
#   - emit 同步分发，订阅者异常 try/except 隔离
#   - 不引入 priority / wildcard / async / sticky event
#
# 角色：Plumbing 层。
#   PlanExecutor → emit → EventBus → subscribers[] (TraceCollector, MetricsCollector, ...)
#
# 不修改 core/ + router/ + providers/（Core Freeze）。
#
# API Stability: Experimental

from __future__ import annotations

import logging
from typing import Callable, Optional

from planner.execution_event import ExecutionEvent


_log = logging.getLogger(__name__)


# 订阅者类型
EventHandler = Callable[[ExecutionEvent], None]


class EventBus:
    """进程内事件总线（V0.9.4）。

    设计原则：
    - **同步**分发：emit() 立即调用所有订阅者（V0.9.4 单进程单线程）
    - **异常隔离**：单个订阅者抛异常不影响其他订阅者，也不影响 emit 主流程
    - **接口预留**：subscribe(event_type, callback) — V0.9.4 内部忽略 event_type

    不引入（ChatGPT 强建议）：
    - ❌ priority
    - ❌ wildcard
    - ❌ event hierarchy
    - ❌ async
    - ❌ sticky event

    这些 V0.9.5+ 需要时再升级。API 已预留。
    """

    def __init__(self) -> None:
        # list of (event_type, handler_id, handler) — handler_id 稳定（用 id() 比较）
        self._subscribers: list[tuple[Optional[str], int, EventHandler]] = []

    def subscribe(self, event_type: Optional[str], handler: EventHandler) -> None:
        """订阅事件。

        Args:
            event_type: 事件类型。None = 订阅所有；V0.9.4 内部暂不过滤。
            handler: 回调函数（同步执行）。
        """
        if not callable(handler):
            raise TypeError(f"handler must be callable, got {type(handler).__name__}")
        # 用 id(handler) 解决 bound method 每次新建对象的问题
        self._subscribers.append((event_type, id(handler), handler))

    def unsubscribe(self, handler: EventHandler) -> bool:
        """取消订阅（按 handler id）。

        V0.9.4 简化实现：按 handler 的 id() 移除。
        返回是否成功移除。
        """
        target_id = id(handler)
        for i, (event_type, hid, h) in enumerate(self._subscribers):
            if hid == target_id:
                del self._subscribers[i]
                return True
        return False

    def emit(self, event: ExecutionEvent) -> None:
        """同步分发事件。

        订阅者抛异常被 try/except 隔离（不影响主流程）。
        """
        for event_type, hid, handler in self._subscribers:
            # V0.9.4 内部不按 event_type 过滤（接口预留）
            # 未来如需过滤：if event_type is not None and event_type != event.type: continue
            try:
                handler(event)
            except Exception as exc:
                # 隔离：单个订阅者失败不影响其他订阅者
                _log.warning(
                    "EventBus subscriber raised exception: type=%s event_id=%s err=%s",
                    event.type, event.event_id, exc,
                    exc_info=False,
                )

    def subscriber_count(self) -> int:
        """订阅者数量（测试用）。"""
        return len(self._subscribers)

    def clear(self) -> None:
        """清空订阅者（测试用）。"""
        self._subscribers.clear()
