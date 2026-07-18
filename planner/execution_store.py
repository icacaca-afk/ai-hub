# AI Hub — ExecutionStore Protocol
# V1.0.3: ExecutionStore 抽象（ChatGPT ADR-0023 9.9/10 关键采纳）
#
# ChatGPT Q2 关键建议:
#   "Contract 最好不要绑定 SQLite.
#    因为 Runtime Contract 已经说过: Storage is Disposable.
#    Checkpoint 不应该知道底层: SQLite / Memory / Remote / S3 以后都应该可以."
#
# Runtime Contract 原则:
#   "Storage is Disposable": Storage is a Consumer, not a Workflow Engine.
#   任何持久化实现 (SQLite / Memory / Remote / S3) 都可以接入.
#
# 设计:
#   - Protocol 类 (不绑定具体实现)
#   - append(event) 接口: 接受 ExecutionEvent
#   - 未来可扩展 query / delete / close (V1.x)
#   - 0 修改 core/ + router/ + providers/ (Core Freeze)
#
# 实现:
#   - planner/sqlite_execution_store.py:SQLiteExecutionStore (V0.9.5 + V1.0.3 加 append 方法)
#   - 未来 MemoryStore / RemoteStore / S3Store: 各自实现
#
# API Stability: Experimental

from __future__ import annotations

from typing import Protocol, runtime_checkable

from planner.execution_event import ExecutionEvent


@runtime_checkable
class ExecutionStore(Protocol):
    """ExecutionStore Protocol（V1.0.3 新增）。

    Contract（来自 Runtime Contract "Storage is Disposable"）:
    - MUST accept ExecutionEvent
    - MUST NOT raise exception (Best Effort)
    - MAY be sync or async (sync for V1.0.3)
    - Storage Failure MUST NOT break Execution

    Implementations:
    - SQLiteExecutionStore (V0.9.5 + V1.0.3 加 append)
    - (future) MemoryExecutionStore
    - (future) RemoteExecutionStore
    - (future) S3ExecutionStore

    API Stability: Experimental
    """

    def append(self, event: ExecutionEvent) -> None:
        """追加一个 ExecutionEvent。

        Contract:
        - 接受 event: ExecutionEvent
        - 内部序列化 + 存储
        - 失败 MUST NOT 抛异常 (Best Effort)
        - 失败时 SHOULD 记录 logger.error
        """
        ...
