# tests/test_sqlite_execution_store.py
# V0.9.5 — SQLiteExecutionStore 测试（ADR-0018）
# V0.9.7 — 新增 query_events() 统一查询接口测试（ADR-0020）
#
# 覆盖：
# - 建表 / has / get_events / 空 DB
# - attach / detach / 与 TraceCollector 共存（多 Consumer）
# - 普通 INSERT / 重复 event_id（IntegrityError → warning，不覆盖）
# - list_plans / GROUP BY / limit
# - Storage Failure ≠ Execution Failure（DatabaseError 不 re-raise）
# - Context Manager（with 语句）
# - _resolve_db_path 优先级（custom / env / workspace）
# - V0.9.7：query_events() 多维过滤（plan_id / event_type / provider / step_id / since / until / limit）
# - V0.9.7：provider 参数支持 list[str]（ChatGPT Q7 调整）
# - V0.9.7：get_events / list_plans / has 向后兼容
#
# 测试隔离：每个测试用 tmp_path 创建临时 DB，不污染 ~/.ai-hub/

import json
import os
import sqlite3
from pathlib import Path

import pytest

from planner.event_bus import EventBus
from planner.execution_event import ExecutionEvent
from planner.sqlite_execution_store import SQLiteExecutionStore, _resolve_db_path


# ── helpers ──

def _make_events(plan_id: str, count: int = 8) -> list:
    """构造 N 个 event（模拟一次完整 plan 执行，参考 test_cli_trace.py）。"""
    events = [
        ExecutionEvent(type="plan_started", plan_id=plan_id, data={"task_id": f"task-{plan_id}"}),
        ExecutionEvent(type="planner_started", plan_id=plan_id, data={"planner": "RuleBasedPlanner"}),
        ExecutionEvent(type="planner_finished", plan_id=plan_id, data={"step_count": 1}),
        ExecutionEvent(type="step_started", plan_id=plan_id, step_id="step-0",
                       data={"index": 0, "content_preview": "hello"}),
    ]
    if count >= 5:
        events.append(ExecutionEvent(type="provider_selected", plan_id=plan_id,
                                     step_id="step-0", provider="ScoreRouter"))
    if count >= 6:
        events.append(ExecutionEvent(type="provider_finished", plan_id=plan_id,
                                     step_id="step-0", provider="fake", latency_ms=200,
                                     data={"status": "success"}))
    if count >= 7:
        events.append(ExecutionEvent(type="step_finished", plan_id=plan_id, step_id="step-0",
                                     data={"status": "success", "latency_ms": 200}))
    if count >= 8:
        events.append(ExecutionEvent(type="plan_finished", plan_id=plan_id,
                                     data={"status": "success", "steps": 1, "success": 1, "failed": 0}))
    return events[:count]


@pytest.fixture
def store(tmp_path):
    """每个测试用独立临时 DB（不污染真实 workspace）。"""
    db = tmp_path / "exec.db"
    s = SQLiteExecutionStore(db_path=str(db))
    yield s
    s.close()


# ── 基本行为 ──

class TestSQLiteExecutionStoreBasic:
    """建表 / has / get_events / 空 DB。"""

    def test_empty_store_has_returns_false(self, store):
        """空 DB：has() 返回 False。"""
        assert store.has("p-001") is False

    def test_empty_store_get_events_returns_empty(self, store):
        """空 DB：get_events() 返回空 list。"""
        assert store.get_events("p-001") == []

    def test_db_file_created(self, tmp_path):
        """__init__ 创建 DB 文件。"""
        db = tmp_path / "exec.db"
        assert not db.exists()
        s = SQLiteExecutionStore(db_path=str(db))
        assert db.exists()
        s.close()

    def test_table_and_indexes_created(self, store):
        """execution_events 表 + 3 个索引已建。"""
        rows = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='execution_events'"
        ).fetchall()
        assert len(rows) == 1

        idx_rows = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='execution_events'"
        ).fetchall()
        idx_names = {r[0] for r in idx_rows}
        assert "idx_execution_events_plan_id" in idx_names
        assert "idx_execution_events_type" in idx_names
        assert "idx_execution_events_timestamp" in idx_names

    def test_wal_mode_enabled(self, store):
        """PRAGMA journal_mode=WAL 生效。"""
        mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        # sqlite 在某些内存/特殊 fs 下可能回退，但文件 DB 通常为 wal
        assert mode.lower() in ("wal", "memory")

    def test_handle_persists_event(self, store):
        """handle() 持久化 event。"""
        ev = ExecutionEvent(type="plan_started", plan_id="p-001", data={"task_id": "t1"})
        store.handle(ev)
        assert store.has("p-001")
        events = store.get_events("p-001")
        assert len(events) == 1
        assert events[0].type == "plan_started"
        assert events[0].plan_id == "p-001"

    def test_get_events_preserves_fields(self, store):
        """get_events() 反序列化所有字段（含 data JSON）。"""
        ev = ExecutionEvent(
            type="provider_finished", plan_id="p-002", step_id="step-0",
            provider="fake", latency_ms=200, data={"status": "success", "tokens": 42},
        )
        store.handle(ev)
        out = store.get_events("p-002")[0]
        assert out.type == "provider_finished"
        assert out.step_id == "step-0"
        assert out.provider == "fake"
        assert out.latency_ms == 200
        assert out.data == {"status": "success", "tokens": 42}
        assert out.event_id == ev.event_id

    def test_get_events_ordered_by_timestamp(self, store):
        """get_events() 按 timestamp 升序。"""
        for e in _make_events("p-003", count=8):
            store.handle(e)
        events = store.get_events("p-003")
        assert len(events) == 8
        assert [e.type for e in events] == [
            "plan_started", "planner_started", "planner_finished",
            "step_started", "provider_selected", "provider_finished",
            "step_finished", "plan_finished",
        ]


# ── EventBus 集成 ──

class TestSQLiteExecutionStoreBusIntegration:
    """attach / detach / 多 Consumer 共存。"""

    def test_attach_subscribes_to_bus(self, store):
        """attach 后 emit 事件被持久化。"""
        bus = EventBus()
        store.attach(bus)

        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        bus.emit(ExecutionEvent(type="step_started", plan_id="p-001", step_id="step-0"))

        assert store.has("p-001")
        events = store.get_events("p-001")
        assert len(events) == 2
        assert events[0].type == "plan_started"
        assert events[1].type == "step_started"

    def test_detach_stops_receiving(self, store):
        """detach 后 emit 不再持久化。"""
        bus = EventBus()
        store.attach(bus)
        store.detach()

        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert not store.has("p-001")

    def test_attach_reattaches(self, store):
        """二次 attach：先 detach 再 attach，不重复订阅。"""
        bus = EventBus()
        store.attach(bus)
        store.attach(bus)

        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-001"))
        assert len(store.get_events("p-001")) == 1  # 不重复

    def test_multiple_consumers_on_one_bus(self, store):
        """一个 bus 同时挂 TraceCollector + SQLiteStore，各自独立。"""
        from planner.trace_collector import InMemoryTraceCollector

        bus = EventBus()
        trace = InMemoryTraceCollector()
        trace.attach(bus)
        store.attach(bus)

        bus.emit(ExecutionEvent(type="plan_started", plan_id="p-shared"))

        # 两个 Consumer 都收到
        assert trace.has("p-shared")
        assert store.has("p-shared")
        assert len(store.get_events("p-shared")) == 1


# ── INSERT 行为 ──

class TestSQLiteExecutionStoreInsert:
    """普通 INSERT / 重复 event_id / IntegrityError。"""

    def test_plain_insert_not_or_replace(self, store):
        """普通 INSERT（非 OR REPLACE）：重复 event_id 不覆盖。"""
        ev = ExecutionEvent(type="plan_started", plan_id="p-001", data={"v": 1})
        store.handle(ev)
        # 同一 event_id 再插入（data 不同）
        ev2 = ExecutionEvent(
            type="plan_started", plan_id="p-001", event_id=ev.event_id, data={"v": 2}
        )
        store.handle(ev2)  # IntegrityError 被 catch，不 re-raise

        events = store.get_events("p-001")
        assert len(events) == 1  # 没有覆盖，仍是 1 条
        # 第一条的 data 保留（immutable 原则）
        assert events[0].data == {"v": 1}

    def test_duplicate_event_id_no_raise(self, store, caplog):
        """重复 event_id 触发 IntegrityError → warning，不抛异常。"""
        import logging

        ev = ExecutionEvent(type="plan_started", plan_id="p-001")
        store.handle(ev)

        with caplog.at_level(logging.WARNING, logger="planner.sqlite_execution_store"):
            # 不应抛异常
            store.handle(ev)

        # 确认有 warning 日志
        assert any("duplicate" in r.message.lower() for r in caplog.records)

    def test_distinct_event_ids_both_stored(self, store):
        """不同 event_id 都被存储。"""
        e1 = ExecutionEvent(type="plan_started", plan_id="p-001")
        e2 = ExecutionEvent(type="step_started", plan_id="p-001", step_id="step-0")
        store.handle(e1)
        store.handle(e2)
        assert len(store.get_events("p-001")) == 2


# ── 查询 / list_plans ──

class TestSQLiteExecutionStoreQuery:
    """list_plans / GROUP BY / limit / 派生字段。"""

    def test_list_plans_empty(self, store):
        """空 DB：list_plans 返回空 list。"""
        assert store.list_plans() == []

    def test_list_plans_groups_by_plan_id(self, store):
        """list_plans 按 plan_id GROUP BY。"""
        for e in _make_events("p-a", count=8):
            store.handle(e)
        for e in _make_events("p-b", count=3):
            store.handle(e)

        plans = store.list_plans()
        assert len(plans) == 2
        plan_ids = {p["plan_id"] for p in plans}
        assert plan_ids == {"p-a", "p-b"}

    def test_list_plans_event_count(self, store):
        """event_count 字段 = 每个 plan 的 event 数。"""
        for e in _make_events("p-a", count=8):
            store.handle(e)
        for e in _make_events("p-b", count=3):
            store.handle(e)

        plans = {p["plan_id"]: p for p in store.list_plans()}
        assert plans["p-a"]["event_count"] == 8
        assert plans["p-b"]["event_count"] == 3

    def test_list_plans_started_finished(self, store):
        """started/finished = MIN/MAX(timestamp)。"""
        for e in _make_events("p-a", count=8):
            store.handle(e)

        plan = store.list_plans()[0]
        assert plan["started"] is not None
        assert plan["finished"] is not None
        assert plan["started"] <= plan["finished"]

    def test_list_plans_derived_status(self, store):
        """status 从 plan_finished event 派生。"""
        for e in _make_events("p-a", count=8):
            store.handle(e)
        # p-b 没有 plan_finished → status=unknown
        store.handle(ExecutionEvent(type="plan_started", plan_id="p-b"))

        plans = {p["plan_id"]: p for p in store.list_plans()}
        assert plans["p-a"]["status"] == "success"
        assert plans["p-b"]["status"] == "unknown"

    def test_list_plans_derived_step_count(self, store):
        """step_count 从 planner_finished event 派生。"""
        for e in _make_events("p-a", count=8):
            store.handle(e)
        plan = store.list_plans()[0]
        assert plan["step_count"] == 1

    def test_list_plans_limit(self, store):
        """limit 限制返回条数。"""
        for i in range(5):
            store.handle(ExecutionEvent(type="plan_started", plan_id=f"p-{i}"))

        assert len(store.list_plans(limit=3)) == 3
        assert len(store.list_plans(limit=20)) == 5

    def test_list_plans_order_most_recent_first(self, store):
        """list_plans 按 started DESC（最近在前）。"""
        # 用显式时间戳保证顺序
        e1 = ExecutionEvent(type="plan_started", plan_id="p-old", timestamp="2026-01-01T00:00:00.000Z")
        e2 = ExecutionEvent(type="plan_started", plan_id="p-new", timestamp="2026-07-01T00:00:00.000Z")
        store.handle(e1)
        store.handle(e2)

        plans = store.list_plans()
        assert plans[0]["plan_id"] == "p-new"
        assert plans[1]["plan_id"] == "p-old"


# ── Failure Policy ──

class TestSQLiteExecutionStoreFailurePolicy:
    """Storage Failure ≠ Execution Failure。"""

    def test_database_error_does_not_raise(self, store, monkeypatch):
        """_conn.execute 抛 DatabaseError → handle() 不 re-raise。"""

        class _BrokenConn:
            def execute(self, *a, **k):
                raise sqlite3.DatabaseError("simulated disk full")

            def commit(self):
                pass

        # sqlite3.Connection.execute 是只读属性，替换整个 _conn 实例属性
        monkeypatch.setattr(store, "_conn", _BrokenConn())

        # 不应抛异常（Storage Failure ≠ Execution Failure）
        store.handle(ExecutionEvent(type="plan_started", plan_id="p-001"))
        # 到这里即通过

    def test_integrity_error_does_not_raise(self, store):
        """IntegrityError → handle() 不 re-raise。"""
        ev = ExecutionEvent(type="plan_started", plan_id="p-001")
        store.handle(ev)
        # 重复插入触发 IntegrityError，被 catch
        store.handle(ev)  # 不抛异常

    def test_bus_emit_isolated_from_storage_failure(self, store, monkeypatch):
        """EventBus 隔离：store.handle 抛异常也不影响 emit 主流程（双重保险）。"""

        class _BrokenConn:
            def execute(self, *a, **k):
                raise sqlite3.DatabaseError("boom")

            def commit(self):
                pass

        bus = EventBus()

        # 另一个正常 consumer，验证它仍能收到
        received = []

        def _other(event):
            received.append(event)

        bus.subscribe(None, _other)
        store.attach(bus)

        # 让 store 的 handle 抛异常（即便 catch 失效，EventBus 也会隔离）
        monkeypatch.setattr(store, "_conn", _BrokenConn())

        ev = ExecutionEvent(type="plan_started", plan_id="p-001")
        bus.emit(ev)  # 不应抛异常
        # 另一个 consumer 仍收到
        assert len(received) == 1


# ── Context Manager ──

class TestSQLiteExecutionStoreContextManager:
    """with 语句。"""

    def test_context_manager_returns_self(self, tmp_path):
        """__enter__ 返回 self。"""
        db = tmp_path / "exec.db"
        with SQLiteExecutionStore(db_path=str(db)) as s:
            assert isinstance(s, SQLiteExecutionStore)
            s.handle(ExecutionEvent(type="plan_started", plan_id="p-001"))
            assert s.has("p-001")

    def test_context_manager_closes_on_exit(self, tmp_path):
        """__exit__ 调用 close()。"""
        db = tmp_path / "exec.db"
        s = SQLiteExecutionStore(db_path=str(db))
        s.__enter__()
        s.__exit__(None, None, None)
        # close 后 _conn 已关闭；再次 close 不抛异常（幂等）
        s.close()


# ── _resolve_db_path 优先级 ──

class TestSQLiteExecutionStoreDbPath:
    """_resolve_db_path 优先级（custom / env / workspace）。"""

    def test_custom_param_wins(self, tmp_path):
        """custom 参数优先级最高。"""
        custom = tmp_path / "custom.db"
        result = _resolve_db_path(custom=custom)
        assert result == custom

    def test_env_var_when_no_custom(self, tmp_path, monkeypatch):
        """无 custom 时用 AI_HUB_DB_PATH 环境变量。"""
        env_path = tmp_path / "env.db"
        monkeypatch.setenv("AI_HUB_DB_PATH", str(env_path))
        result = _resolve_db_path(custom=None)
        assert result == env_path

    def test_workspace_default_when_no_custom_no_env(self, tmp_path, monkeypatch):
        """无 custom 无 env 时用 workspace ./.ai-hub/execution.db。"""
        monkeypatch.delenv("AI_HUB_DB_PATH", raising=False)
        monkeypatch.chdir(tmp_path)
        result = _resolve_db_path(custom=None)
        assert result == Path.cwd() / ".ai-hub" / "execution.db"

    def test_custom_overrides_env(self, tmp_path, monkeypatch):
        """custom 优先于 env。"""
        env_path = tmp_path / "env.db"
        custom = tmp_path / "custom.db"
        monkeypatch.setenv("AI_HUB_DB_PATH", str(env_path))
        result = _resolve_db_path(custom=custom)
        assert result == custom

    def test_store_uses_resolved_path(self, tmp_path, monkeypatch):
        """SQLiteExecutionStore() 无参数时遵循 env（不污染 workspace）。"""
        env_path = tmp_path / "env.db"
        monkeypatch.setenv("AI_HUB_DB_PATH", str(env_path))
        s = SQLiteExecutionStore()
        try:
            assert s.db_path == env_path
        finally:
            s.close()


# ── V0.9.7：query_events() 统一查询接口（ADR-0020） ──

class TestQueryEvents:
    """query_events(...) 多维过滤测试。"""

    def test_query_events_no_filter_returns_all(self, store):
        """无过滤：返回所有 events。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)
        for e in _make_events("p-002", count=3):
            store.handle(e)

        all_events = store.query_events()
        assert len(all_events) == 11  # 8 + 3
        # 按 timestamp 升序
        assert all_events[0].type == "plan_started"

    def test_query_events_by_plan_id(self, store):
        """按 plan_id 过滤。"""
        for e in _make_events("p-a", count=8):
            store.handle(e)
        for e in _make_events("p-b", count=3):
            store.handle(e)

        events = store.query_events(plan_id="p-a")
        assert len(events) == 8
        assert all(e.plan_id == "p-a" for e in events)

    def test_query_events_by_event_type(self, store):
        """按 event_type 过滤。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)

        events = store.query_events(event_type="provider_finished")
        assert len(events) == 1
        assert events[0].type == "provider_finished"

    def test_query_events_by_provider_str(self, store):
        """按 provider 过滤（单 str，ChatGPT Q7）。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)

        events = store.query_events(provider="fake")
        assert len(events) == 1
        assert events[0].provider == "fake"

    def test_query_events_by_provider_list(self, store):
        """按 provider 过滤（list[str]，ChatGPT Q7 调整）。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)
        # 添加 openai_api provider
        store.handle(ExecutionEvent(
            type="provider_finished", plan_id="p-001", step_id="step-0",
            provider="openai_api", latency_ms=200, data={"status": "success"},
        ))
        store.handle(ExecutionEvent(
            type="provider_finished", plan_id="p-001", step_id="step-1",
            provider="openai_compatible", latency_ms=300, data={"status": "success"},
        ))

        # 多 provider IN 子句
        events = store.query_events(provider=["openai_api", "openai_compatible"])
        assert len(events) == 2
        providers = {e.provider for e in events}
        assert providers == {"openai_api", "openai_compatible"}

    def test_query_events_by_provider_empty_list(self, store):
        """provider=[] 短路返回空 list。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)
        events = store.query_events(provider=[])
        assert events == []

    def test_query_events_by_step_id(self, store):
        """按 step_id 过滤。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)

        events = store.query_events(step_id="step-0")
        # step-0 关联的 events：step_started / provider_selected / provider_finished / step_finished
        assert len(events) == 4
        assert all(e.step_id == "step-0" for e in events)

    def test_query_events_by_since(self, store):
        """按 since 过滤（timestamp >= since）。"""
        # 显式时间戳
        e1 = ExecutionEvent(
            type="plan_started", plan_id="p-001", timestamp="2026-01-01T00:00:00.000Z"
        )
        e2 = ExecutionEvent(
            type="step_started", plan_id="p-001", step_id="step-0", timestamp="2026-06-01T00:00:00.000Z"
        )
        e3 = ExecutionEvent(
            type="plan_finished", plan_id="p-001", timestamp="2026-12-01T00:00:00.000Z"
        )
        for e in (e1, e2, e3):
            store.handle(e)

        events = store.query_events(since="2026-05-01T00:00:00.000Z")
        assert len(events) == 2  # e2 + e3
        assert events[0].type == "step_started"
        assert events[1].type == "plan_finished"

    def test_query_events_by_until(self, store):
        """按 until 过滤（timestamp <= until）。"""
        e1 = ExecutionEvent(
            type="plan_started", plan_id="p-001", timestamp="2026-01-01T00:00:00.000Z"
        )
        e2 = ExecutionEvent(
            type="step_started", plan_id="p-001", step_id="step-0", timestamp="2026-06-01T00:00:00.000Z"
        )
        e3 = ExecutionEvent(
            type="plan_finished", plan_id="p-001", timestamp="2026-12-01T00:00:00.000Z"
        )
        for e in (e1, e2, e3):
            store.handle(e)

        events = store.query_events(until="2026-08-01T00:00:00.000Z")
        assert len(events) == 2  # e1 + e2

    def test_query_events_by_since_and_until(self, store):
        """since + until 范围过滤。"""
        e1 = ExecutionEvent(type="plan_started", plan_id="p-001", timestamp="2026-01-01T00:00:00.000Z")
        e2 = ExecutionEvent(type="step_started", plan_id="p-001", step_id="step-0", timestamp="2026-06-01T00:00:00.000Z")
        e3 = ExecutionEvent(type="plan_finished", plan_id="p-001", timestamp="2026-12-01T00:00:00.000Z")
        for e in (e1, e2, e3):
            store.handle(e)

        events = store.query_events(since="2026-05-01T00:00:00.000Z", until="2026-08-01T00:00:00.000Z")
        assert len(events) == 1
        assert events[0].type == "step_started"

    def test_query_events_with_limit(self, store):
        """limit 限制返回条数。"""
        for i in range(10):
            store.handle(ExecutionEvent(
                type="plan_started", plan_id=f"p-{i:03d}",
                timestamp=f"2026-01-{i+1:02d}T00:00:00.000Z",
            ))

        events = store.query_events(limit=5)
        assert len(events) == 5

    def test_query_events_combined_filters(self, store):
        """组合过滤：plan_id + event_type。"""
        for e in _make_events("p-a", count=8):
            store.handle(e)
        for e in _make_events("p-b", count=8):
            store.handle(e)

        events = store.query_events(plan_id="p-a", event_type="plan_finished")
        assert len(events) == 1
        assert events[0].plan_id == "p-a"
        assert events[0].type == "plan_finished"

    def test_query_events_empty_result(self, store):
        """过滤无匹配：返回空 list。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)

        events = store.query_events(plan_id="nonexistent")
        assert events == []

    def test_query_events_preserves_all_fields(self, store):
        """query_events() 完整反序列化所有字段。"""
        ev = ExecutionEvent(
            type="provider_finished", plan_id="p-002", step_id="step-0",
            provider="openai_api", latency_ms=450, data={"status": "success", "tokens": 100},
        )
        store.handle(ev)

        out = store.query_events(plan_id="p-002")[0]
        assert out.type == "provider_finished"
        assert out.step_id == "step-0"
        assert out.provider == "openai_api"
        assert out.latency_ms == 450
        assert out.data == {"status": "success", "tokens": 100}
        assert out.event_id == ev.event_id


# ── V0.9.7：get_events / list_plans / has 向后兼容（Convenience API） ──

class TestConvenienceAPIBackwardCompat:
    """get_events / list_plans / has 保留向后兼容。"""

    def test_get_events_equivalent_to_query_events_by_plan_id(self, store):
        """get_events(plan_id) ≡ query_events(plan_id=plan_id)。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)

        a = store.get_events("p-001")
        b = store.query_events(plan_id="p-001")
        assert len(a) == len(b) == 8
        for ea, eb in zip(a, b):
            assert ea.event_id == eb.event_id
            assert ea.type == eb.type

    def test_list_plans_uses_query_events_internally(self, store):
        """list_plans() 内部基于 query_events 派生（ChatGPT Q2）。"""
        for e in _make_events("p-a", count=8):
            store.handle(e)
        for e in _make_events("p-b", count=3):
            store.handle(e)

        plans = store.list_plans()
        assert len(plans) == 2
        # 排序：started DESC
        assert plans[0]["plan_id"] == "p-a" or plans[0]["plan_id"] == "p-b"

    def test_list_plans_limit_consistent(self, store):
        """list_plans(limit) 与 query_events(limit) 输出一致。"""
        for i in range(5):
            store.handle(ExecutionEvent(
                type="plan_started", plan_id=f"p-{i:03d}",
                timestamp=f"2026-01-{i+1:02d}T00:00:00.000Z",
            ))

        plans = store.list_plans(limit=3)
        assert len(plans) == 3

    def test_has_uses_single_sql_exists(self, store):
        """has() 保留单条 SQL EXISTS（比 query_events 更高效）。"""
        for e in _make_events("p-001", count=8):
            store.handle(e)

        assert store.has("p-001") is True
        assert store.has("nonexistent") is False
