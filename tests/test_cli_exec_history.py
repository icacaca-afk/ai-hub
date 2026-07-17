# tests/test_cli_exec_history.py
# V0.9.5 — `ai-hub exec-history` CLI 测试（ADR-0018）
#
# 覆盖：
# - 空 DB 输出（list 模式）
# - --plan <plan_id> timeline（人类可读）
# - --json 输出（list + timeline）
# - --limit N
# - 不存在的 plan_id 错误处理（exit 1）
# - exec-history 命令已注册到 main usage
#
# 测试隔离：单元测试注入 tmp_path store；subprocess 测试用 AI_HUB_DB_PATH env

import json
import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _run_cli(*args, timeout=30, db_path=None):
    """运行 ai-hub CLI 命令（subprocess），可用 db_path 隔离 DB。"""
    cmd = [sys.executable, "-m", "cli.main"] + list(args)
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    if db_path is not None:
        env["AI_HUB_DB_PATH"] = str(db_path)
    r = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=PROJECT_ROOT, env=env, timeout=timeout,
    )
    return r.returncode, r.stdout or "", r.stderr or ""


def _make_events(plan_id: str, count: int = 8) -> list:
    """构造 N 个 event（参考 test_cli_trace.py）。"""
    from planner.execution_event import ExecutionEvent

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
def _isolated_history_store(tmp_path):
    """每个测试用独立 tmp_path store，注入 cli.history._HistoryHolder。"""
    from cli import history as history_module
    from planner.sqlite_execution_store import SQLiteExecutionStore

    db = tmp_path / "exec.db"
    store = SQLiteExecutionStore(db_path=str(db))
    history_module._HistoryHolder.store = store
    yield store
    store.close()
    # 重置 holder，避免影响后续测试
    history_module._HistoryHolder.store = None


# ── list 模式 ──

class TestCmdExecHistoryList:
    """ai-hub exec-history（list 模式）。"""

    def test_list_empty_human(self, _isolated_history_store, capsys):
        """空 DB list：人类可读 + 提示。"""
        from cli.history import cmd_exec_history

        cmd_exec_history([])
        out = capsys.readouterr().out

        assert "AI Hub Execution History" in out
        assert "v0.9.6" in out
        assert "SQLite" in out
        assert "Recent Executions: 0" in out
        assert "no executions" in out.lower()

    def test_list_empty_json(self, _isolated_history_store, capsys):
        """空 DB list --json：count=0。"""
        from cli.history import cmd_exec_history

        cmd_exec_history(["--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["version"] == "0.9.6"
        assert data["source"] == "sqlite"
        assert data["count"] == 0
        assert data["executions"] == []
        assert "db_path" in data

    def test_list_with_plans_human(self, _isolated_history_store, capsys):
        """有 executions list：人类可读列表。"""
        from cli.history import cmd_exec_history

        for e in _make_events("p-001", count=8):
            _isolated_history_store.handle(e)
        for e in _make_events("p-002", count=3):
            _isolated_history_store.handle(e)

        cmd_exec_history([])
        out = capsys.readouterr().out

        assert "Recent Executions: 2" in out
        assert "p-001" in out
        assert "p-002" in out
        # 状态图标 + status 大写
        assert "SUCCESS" in out

    def test_list_with_plans_json(self, _isolated_history_store, capsys):
        """有 executions list --json：结构化列表。"""
        from cli.history import cmd_exec_history

        for e in _make_events("p-001", count=8):
            _isolated_history_store.handle(e)

        cmd_exec_history(["--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["count"] == 1
        ex = data["executions"][0]
        assert ex["plan_id"] == "p-001"
        assert ex["event_count"] == 8
        assert ex["status"] == "success"
        assert ex["step_count"] == 1

    def test_list_limit(self, _isolated_history_store, capsys):
        """--limit N 限制条数。"""
        from cli.history import cmd_exec_history

        for i in range(5):
            _isolated_history_store.handle(
                __import__("planner.execution_event", fromlist=["ExecutionEvent"]).ExecutionEvent(
                    type="plan_started", plan_id=f"p-{i}"
                )
            )

        cmd_exec_history(["--limit", "3"])
        out = capsys.readouterr().out
        assert "Recent Executions: 3" in out

        # JSON 模式也支持 --limit
        cmd_exec_history(["--limit", "2", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["count"] == 2


# ── timeline 模式（--plan） ──

class TestCmdExecHistoryTimeline:
    """ai-hub exec-history --plan <plan_id>（timeline 模式）。"""

    def test_timeline_human(self, _isolated_history_store, capsys):
        """--plan 已知 plan_id → Timeline 人类可读。"""
        from cli.history import cmd_exec_history

        for e in _make_events("p-001", count=8):
            _isolated_history_store.handle(e)

        cmd_exec_history(["--plan", "p-001"])
        out = capsys.readouterr().out

        assert "AI Hub Execution History" in out
        assert "Plan: p-001" in out
        assert "Events: 8" in out
        # 8 个 event 类型都应出现
        for event_type in ["plan_started", "planner_started", "planner_finished",
                           "step_started", "provider_selected", "provider_finished",
                           "step_finished", "plan_finished"]:
            assert event_type in out

    def test_timeline_json(self, _isolated_history_store, capsys):
        """--plan --json → Timeline JSON。"""
        from cli.history import cmd_exec_history

        for e in _make_events("p-002", count=6):
            _isolated_history_store.handle(e)

        cmd_exec_history(["--plan", "p-002", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["version"] == "0.9.6"
        assert data["source"] == "sqlite"
        assert data["plan_id"] == "p-002"
        assert data["event_count"] == 6
        assert len(data["events"]) == 6

    def test_timeline_json_event_fields(self, _isolated_history_store, capsys):
        """JSON 输出含 event 全字段。"""
        from cli.history import cmd_exec_history

        for e in _make_events("p-003", count=3):
            _isolated_history_store.handle(e)

        cmd_exec_history(["--plan", "p-003", "--json"])
        data = json.loads(capsys.readouterr().out)

        first = data["events"][0]
        assert first["type"] == "plan_started"
        assert "event_id" in first
        assert "timestamp" in first
        assert first["plan_id"] == "p-003"

    def test_timeline_unknown_plan_exits_1(self, _isolated_history_store, capsys):
        """--plan 不存在：exit 1 + 错误提示。"""
        from cli.history import cmd_exec_history

        with pytest.raises(SystemExit) as exc_info:
            cmd_exec_history(["--plan", "nonexistent-plan-id"])
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "not found" in combined.lower()

    def test_timeline_unknown_plan_hint(self, _isolated_history_store, capsys):
        """--plan 不存在：给出 exec-history 提示。"""
        from cli.history import cmd_exec_history

        with pytest.raises(SystemExit):
            cmd_exec_history(["--plan", "nope"])

        captured = capsys.readouterr()
        assert "exec-history" in captured.err


# ── subprocess 测试（边界） ──

class TestExecHistorySubprocess:
    """subprocess 路径：用 AI_HUB_DB_PATH 隔离 DB。"""

    def test_list_empty_subprocess(self, tmp_path):
        """subprocess 跑 exec-history（空 DB）：exit 0。"""
        db = tmp_path / "exec.db"
        rc, out, err = _run_cli("exec-history", db_path=db, timeout=15)
        assert rc == 0
        assert "AI Hub Execution History" in out
        assert "no executions" in out.lower()

    def test_list_empty_json_subprocess(self, tmp_path):
        """subprocess 跑 exec-history --json（空 DB）。"""
        db = tmp_path / "exec.db"
        rc, out, err = _run_cli("exec-history", "--json", db_path=db, timeout=15)
        assert rc == 0
        data = json.loads(out)
        assert data["version"] == "0.9.6"
        assert data["count"] == 0

    def test_unknown_plan_subprocess(self, tmp_path):
        """subprocess 跑 exec-history --plan 未知 id：exit 1。"""
        db = tmp_path / "exec.db"
        rc, out, err = _run_cli("exec-history", "--plan", "nonexistent", db_path=db, timeout=15)
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower()


# ── exec-history 命令注册到 main ──

class TestExecHistoryRegistration:
    """exec-history 命令注册到 cli/main.py。"""

    def test_exec_history_in_usage(self, tmp_path):
        """main usage 包含 exec-history。"""
        db = tmp_path / "exec.db"
        rc, out, err = _run_cli(db_path=db, timeout=10)
        assert rc == 0
        assert "exec-history" in out

    def test_exec_history_available_command(self, tmp_path):
        """exec-history 是可用命令（不在 unknown command 列表）。"""
        db = tmp_path / "exec.db"
        rc, out, err = _run_cli("exec-history", db_path=db, timeout=15)
        assert rc == 0  # 成功执行，非 unknown command

    def test_history_command_still_works(self, tmp_path):
        """原 history 命令仍正常（exec-history 不影响 history）。"""
        rc, out, err = _run_cli("history", timeout=15)
        # history 命令即使无记录也 exit 0
        assert rc == 0
