# AI Hub — SQLiteExecutionStore
# V0.9.5: ExecutionEvent 持久化到 SQLite（EventBus 的独立 Consumer）
# V0.9.7: query_events(...) 统一查询接口（ADR-0020）
#
# ADR-0018 (ChatGPT 审核通过 10.0/10):
#   - EventBus 的独立 Consumer（不继承 TraceCollector）
#   - 长连接 + WAL mode + synchronous=NORMAL
#   - 普通 INSERT（非 OR REPLACE，符合 immutable 原则）
#   - Storage Failure ≠ Execution Failure：handle() 内 catch 所有 sqlite 异常，log 不 re-raise
#
# ADR-0020 (ChatGPT 审核通过 9.95/10):
#   - query_events(...) 统一查询接口（6 个 Optional 过滤 + limit）
#   - provider 参数支持 str | list[str]（ChatGPT Q7 调整）
#   - get_events / list_plans / has 保留向后兼容（Convenience API）
#   - list_plans 内部基于 query_events 派生（ChatGPT Q2 明确）
#
# 与 TraceCollector 的关系（ADR-0018 + ChatGPT 反馈）：
#   - TraceCollector: 进程内环形缓冲（Current Process Only），答「当前进程怎么发生的？」
#   - SQLiteExecutionStore: 持久化（跨进程），答「历史发生过什么？」
#   - 二者作为独立 Consumer 同时订阅 EventBus，互不干扰。
#
# 不修改 core/ + router/ + providers/ + planner/trace_collector.py + event_bus.py + execution_event.py
#
# API Stability: Experimental

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from planner.event_bus import EventBus
from planner.execution_event import ExecutionEvent


_log = logging.getLogger(__name__)


def _resolve_db_path(custom: Optional[str | Path] = None) -> Path:
    """解析 DB 路径。

    优先级（ADR-0018）：
      1. custom 参数（显式传入）
      2. AI_HUB_DB_PATH 环境变量
      3. workspace 优先：``Path.cwd() / ".ai-hub" / "execution.db"``
    """
    if custom is not None:
        return Path(custom)
    env_path = os.environ.get("AI_HUB_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path.cwd() / ".ai-hub" / "execution.db"


class SQLiteExecutionStore:
    """ExecutionEvent SQLite 持久化（V0.9.5）+ 统一查询接口（V0.9.7）。

    EventBus 的独立 Consumer（不继承 ``InMemoryTraceCollector``）。

    设计要点（ADR-0018 + ChatGPT 反馈）：
    - **长连接**：``__init__`` 时 connect，``close()`` 时关闭，不每 event 新连接。
    - **WAL mode**：``PRAGMA journal_mode=WAL`` + ``synchronous=NORMAL``。
    - **普通 INSERT**：非 ``OR REPLACE``，符合 immutable 原则；重复 ``event_id``
      触发 ``IntegrityError`` 被 catch + warning。
    - **Storage Failure ≠ Execution Failure**：``handle()`` 内 catch 所有 sqlite
      异常，log 但不 re-raise（持久化失败不影响执行主流程）。

    V0.9.7 查询接口（ADR-0020）：
    - ``query_events(...)`` 是唯一查询入口，所有 CLI（history / stats）基于它
    - ``get_events`` / ``list_plans`` / ``has`` 保留为 Convenience API（向后兼容）
    - ``list_plans`` 内部基于 ``query_events`` 派生（ChatGPT Q2 明确）
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        path = _resolve_db_path(db_path)
        # 确保父目录存在（workspace 优先：./.ai-hub/）
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = path
        # 长连接 + 跨线程访问（CLI 单进程但 check_same_thread=False 更宽容）
        self._conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
        self._init_db()
        self._bus: EventBus | None = None
        # 预绑定 handle 方法（同 TraceCollector 模式，避免 bound method 每次新建对象）
        self._handle_bound = self.handle

    # ── 初始化 ──

    def _init_db(self) -> None:
        """建表 + 索引 + PRAGMA。"""
        conn = self._conn
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_events (
                event_id   TEXT PRIMARY KEY,
                type       TEXT NOT NULL,
                plan_id    TEXT NOT NULL,
                timestamp  TEXT NOT NULL,
                step_id    TEXT,
                provider   TEXT,
                latency_ms INTEGER,
                data       TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_events_plan_id "
            "ON execution_events(plan_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_events_type "
            "ON execution_events(type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_execution_events_timestamp "
            "ON execution_events(timestamp)"
        )
        conn.commit()

    # ── EventBus Consumer 接口（同 TraceCollector 模式） ──

    def attach(self, bus: EventBus) -> None:
        """订阅 EventBus。如已 attach 过，会先 detach。"""
        if self._bus is not None:
            self.detach()
        self._bus = bus
        bus.subscribe(None, self._handle_bound)

    def detach(self) -> None:
        """取消订阅。"""
        if self._bus is not None:
            self._bus.unsubscribe(self._handle_bound)
            self._bus = None

    def handle(self, event: ExecutionEvent) -> None:
        """EventBus 回调：普通 INSERT。

        Storage Failure ≠ Execution Failure：所有 sqlite 异常被 catch，
        log 但不 re-raise（持久化失败不影响执行主流程）。
        """
        try:
            self._conn.execute(
                "INSERT INTO execution_events "
                "(event_id, type, plan_id, timestamp, step_id, provider, latency_ms, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.type,
                    event.plan_id,
                    event.timestamp,
                    event.step_id,
                    event.provider,
                    event.latency_ms,
                    json.dumps(event.data, ensure_ascii=False),
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            # 重复 event_id（PK 冲突）：immutable 原则下不覆盖，仅 warning
            _log.warning(
                "SQLiteExecutionStore duplicate event_id=%s type=%s: %s",
                event.event_id, event.type, exc,
            )
        except sqlite3.DatabaseError as exc:
            # 其他 DB 错误：log 但不 re-raise（Storage Failure ≠ Execution Failure）
            _log.error(
                "SQLiteExecutionStore insert failed event_id=%s type=%s: %s",
                event.event_id, event.type, exc,
            )

    # ── 查询接口 ──
    # V0.9.7：query_events() 是唯一查询入口（ADR-0020 决策 1）
    # get_events / list_plans / has 是 Convenience API（向后兼容）

    def query_events(
        self,
        plan_id: str | None = None,
        event_type: str | None = None,
        provider: str | list[str] | None = None,
        step_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[ExecutionEvent]:
        """统一查询接口（ADR-0018 原则 C 落地 + ADR-0020 决策 1）。

        所有参数 Optional，组合过滤（AND 语义）。返回 list[ExecutionEvent]（按 timestamp 升序）。

        ChatGPT Q7 调整（ADR-0020）：provider 参数支持 str | list[str] | None。
        - CLI 当前仍只传单 provider（--provider openai_api）
        - 但接口已为未来 API 场景（provider=["a", "b"]）预留

        Args:
            plan_id: 按 plan_id 过滤
            event_type: 按 event type 过滤（plan_started / step_finished / ...）
            provider: 按 provider 过滤，支持单值或多值列表（多值走 IN 子句）
            step_id: 按 step_id 过滤
            since: ISO 8601 timestamp 下界（含）
            until: ISO 8601 timestamp 上界（含）
            limit: 最多返回 N 条（None = 不限）

        Returns:
            list[ExecutionEvent]（按 timestamp 升序）

        Examples:
            query_events(plan_id="plan-abc")              # 某 plan 的全部 events
            query_events(event_type="provider_finished")  # 所有 provider_finished
            query_events(provider="openai_api")           # 单 provider
            query_events(provider=["openai_api", "openai_compatible"])  # 多 provider
            query_events(since="2026-07-17T00:00:00Z")    # 某时刻之后
            query_events(plan_id="plan-abc", event_type="step_finished")  # 组合过滤
        """
        clauses: list[str] = []
        params: list[Any] = []
        if plan_id is not None:
            clauses.append("plan_id = ?")
            params.append(plan_id)
        if event_type is not None:
            clauses.append("type = ?")
            params.append(event_type)
        if provider is not None:
            # ChatGPT Q7: 支持 str | list[str]
            if isinstance(provider, str):
                clauses.append("provider = ?")
                params.append(provider)
            else:
                # list[str] → IN (?, ?, ...)
                if not provider:
                    # 空列表：返回空结果（不可能匹配任何 provider）
                    return []
                placeholders = ", ".join("?" * len(provider))
                clauses.append(f"provider IN ({placeholders})")
                params.extend(provider)
        if step_id is not None:
            clauses.append("step_id = ?")
            params.append(step_id)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            "SELECT event_id, type, plan_id, timestamp, step_id, provider, "
            f"latency_ms, data FROM execution_events{where} "
            "ORDER BY timestamp ASC"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_events(self, plan_id: str) -> list[ExecutionEvent]:
        """Convenience API：等价于 ``query_events(plan_id=plan_id)``。

        向后兼容 V0.9.5 接口。新代码应优先使用 ``query_events()``。
        """
        return self.query_events(plan_id=plan_id)

    def list_plans(self, limit: int = 20) -> list[dict[str, Any]]:
        """Convenience API：列出最近 N 个 plan execution（按 started DESC）。

        内部基于 ``query_events(event_type="plan_started")`` 派生（ChatGPT Q2 明确）。
        不是独立查询系统，是 ``query_events()`` 的 helper。

        额外派生 ``status`` / ``step_count``（从 plan_started/plan_finished
        /planner_finished events 派生）。
        """
        # 通过 query_events 拿 plan_started events（落地 ADR-0018 原则 C）
        plan_started_events = self.query_events(event_type="plan_started")
        # query_events 返回升序，list_plans 需要 started DESC，反转后取 limit
        plan_started_events_sorted = sorted(
            plan_started_events, key=lambda e: e.timestamp, reverse=True
        )[:limit]

        results: list[dict[str, Any]] = []
        for event in plan_started_events_sorted:
            plan_id = event.plan_id
            started = event.timestamp
            # 对每个 plan，用聚合 SQL 拿 finished/event_count（高效，单次 SQL）
            row = self._conn.execute(
                "SELECT MAX(timestamp), COUNT(*) FROM execution_events WHERE plan_id=?",
                (plan_id,),
            ).fetchone()
            finished = row[0] if row else None
            event_count = int(row[1]) if row else 0
            results.append(
                {
                    "plan_id": plan_id,
                    "started": started,
                    "finished": finished,
                    "event_count": event_count,
                    "status": self._derive_status(plan_id),
                    "step_count": self._derive_step_count(plan_id),
                }
            )
        return results

    def has(self, plan_id: str) -> bool:
        """是否有该 plan_id 的 event。

        保留单条 SQL EXISTS 实现（比 query_events 拉 events 更高效）。
        """
        row = self._conn.execute(
            "SELECT 1 FROM execution_events WHERE plan_id=? LIMIT 1",
            (plan_id,),
        ).fetchone()
        return row is not None

    # ── 派生字段 ──

    def _derive_status(self, plan_id: str) -> str:
        """从 plan_finished event 派生 status。"""
        row = self._conn.execute(
            "SELECT data FROM execution_events "
            "WHERE plan_id=? AND type='plan_finished' LIMIT 1",
            (plan_id,),
        ).fetchone()
        if row is None:
            return "unknown"
        try:
            data = json.loads(row[0]) if row[0] else {}
            return str(data.get("status", "unknown"))
        except (json.JSONDecodeError, TypeError):
            return "unknown"

    def _derive_step_count(self, plan_id: str) -> int:
        """从 planner_finished event 派生 step_count，回退统计 distinct step_id。"""
        row = self._conn.execute(
            "SELECT data FROM execution_events "
            "WHERE plan_id=? AND type='planner_finished' LIMIT 1",
            (plan_id,),
        ).fetchone()
        if row is not None:
            try:
                data = json.loads(row[0]) if row[0] else {}
                if "step_count" in data:
                    return int(data["step_count"])
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        # 回退：统计 distinct step_id
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT step_id) FROM execution_events "
            "WHERE plan_id=? AND step_id IS NOT NULL",
            (plan_id,),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # ── 序列化 ──

    def _row_to_event(self, row: tuple) -> ExecutionEvent:
        data_raw = row[7]
        try:
            data = json.loads(data_raw) if data_raw else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        return ExecutionEvent(
            event_id=row[0],
            type=row[1],
            plan_id=row[2],
            timestamp=row[3],
            step_id=row[4],
            provider=row[5],
            latency_ms=row[6],
            data=data,
        )

    # ── 生命周期 ──

    @property
    def db_path(self) -> Path:
        """DB 文件路径（供 CLI JSON 输出等使用）。"""
        return self._db_path

    def close(self) -> None:
        """关闭连接。"""
        try:
            self._conn.close()
        except Exception as exc:  # noqa: BLE001 — close 幂等，忽略二次关闭
            _log.debug("SQLiteExecutionStore close error: %s", exc)

    def __enter__(self) -> "SQLiteExecutionStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
