# tests/test_cli_trace.py
# V0.9.4 — `ai-hub trace` CLI 测试（ADR-0017）
#
# 覆盖：
# - `ai-hub trace <plan_id>` Timeline 人类可读
# - `ai-hub trace <plan_id> --json` Timeline JSON
# - `ai-hub trace --list` 列出 traced plans
# - `ai-hub trace --list --json` 列表 JSON
# - plan_id 不存在：exit 1 + 错误提示
# - 无参数：exit 1 + usage
# - inspect 共享 trace 关联（Trace: Available/No Trace）
# - trace 命令已注册到 main usage

import json
import sys
import os
import subprocess

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _run_cli(*args, timeout=30):
    cmd = [sys.executable, "-m", "cli.main"] + list(args)
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    r = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=PROJECT_ROOT, env=env, timeout=timeout,
    )
    return r.returncode, r.stdout or "", r.stderr or ""


# ── Test Fixtures ──

def _make_events(plan_id: str, count: int = 5) -> list:
    """构造 N 个 event（模拟一次 plan 执行）。"""
    from planner.execution_event import ExecutionEvent

    events = [
        ExecutionEvent(type="plan_started", plan_id=plan_id, data={"task_id": f"task-{plan_id}"}),
        ExecutionEvent(type="planner_started", plan_id=plan_id, data={"planner": "RuleBasedPlanner"}),
        ExecutionEvent(type="planner_finished", plan_id=plan_id, data={"step_count": 1}),
        ExecutionEvent(type="step_started", plan_id=plan_id, step_id="step-0", data={"index": 0, "content_preview": "hello"}),
    ]
    if count >= 5:
        events.append(
            ExecutionEvent(type="provider_selected", plan_id=plan_id, step_id="step-0", provider="ScoreRouter")
        )
    if count >= 6:
        events.append(
            ExecutionEvent(type="provider_finished", plan_id=plan_id, step_id="step-0", provider="fake", latency_ms=200, data={"status": "success"})
        )
    if count >= 7:
        events.append(
            ExecutionEvent(type="step_finished", plan_id=plan_id, step_id="step-0", data={"status": "success", "latency_ms": 200})
        )
    if count >= 8:
        events.append(
            ExecutionEvent(type="plan_finished", plan_id=plan_id, data={"status": "success", "steps": 1, "success": 1, "failed": 0})
        )
    return events[:count]


@pytest.fixture
def _isolated_trace_collector(monkeypatch):
    """每个测试用独立 TraceCollector，注入 cli.trace._TraceHolder。"""
    from cli import trace as trace_module
    from planner.trace_collector import InMemoryTraceCollector

    fresh = InMemoryTraceCollector()
    trace_module._TraceHolder.collector = fresh
    return fresh


# ── 单元测试：cmd_trace 基本行为 ──

class TestCmdTraceBasic:
    """cmd_trace 基本行为。"""

    def test_trace_no_args_shows_usage(self, capsys):
        """无参数：exit 1 + usage。"""
        from cli.trace import cmd_trace

        with pytest.raises(SystemExit) as exc_info:
            cmd_trace([])
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Usage" in captured.out
        assert "trace" in captured.out

    def test_trace_unknown_plan_id(self, _isolated_trace_collector, capsys):
        """plan_id 不存在：exit 1 + 错误提示。"""
        from cli.trace import cmd_trace

        with pytest.raises(SystemExit) as exc_info:
            cmd_trace(["nonexistent-plan-id"])
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "not found" in combined.lower() or "not found" in combined

    def test_trace_existing_plan_human(self, _isolated_trace_collector, capsys):
        """已知 plan_id → Timeline 人类可读。"""
        from cli.trace import cmd_trace

        events = _make_events("p-001", count=8)
        for e in events:
            _isolated_trace_collector.handle(e)

        cmd_trace(["p-001"])
        out = capsys.readouterr().out

        assert "AI Hub Trace" in out
        assert "p-001" in out
        assert "Events: 8" in out
        # 8 个 event 类型都应出现
        for event_type in ["plan_started", "planner_started", "planner_finished",
                           "step_started", "provider_selected", "provider_finished",
                           "step_finished", "plan_finished"]:
            assert event_type in out

    def test_trace_existing_plan_json(self, _isolated_trace_collector, capsys):
        """已知 plan_id --json → Timeline JSON。"""
        from cli.trace import cmd_trace

        events = _make_events("p-002", count=3)
        for e in events:
            _isolated_trace_collector.handle(e)

        cmd_trace(["p-002", "--json"])
        out = capsys.readouterr().out

        data = json.loads(out)
        assert data["version"] == "0.9.4"
        assert data["plan_id"] == "p-002"
        assert data["event_count"] == 3
        assert len(data["events"]) == 3

    def test_trace_json_event_fields(self, _isolated_trace_collector, capsys):
        """JSON 输出含 event 全字段。"""
        from cli.trace import cmd_trace

        events = _make_events("p-003", count=6)
        for e in events:
            _isolated_trace_collector.handle(e)

        cmd_trace(["p-003", "--json"])
        data = json.loads(capsys.readouterr().out)

        first = data["events"][0]
        assert first["type"] == "plan_started"
        assert "event_id" in first
        assert "timestamp" in first
        assert first["plan_id"] == "p-003"


# ── trace --list ──

class TestCmdTraceList:
    """ai-hub trace --list 模式。"""

    def test_list_human_empty(self, _isolated_trace_collector, capsys):
        """空 collector --list：人类可读 + 提示。"""
        from cli.trace import cmd_trace

        cmd_trace(["--list"])
        out = capsys.readouterr().out

        assert "AI Hub Trace" in out
        assert "Traced Plans: 0/10" in out
        assert "no traces" in out.lower() or "(no traces" in out

    def test_list_human_with_plans(self, _isolated_trace_collector, capsys):
        """有 traces --list：人类可读列表。"""
        from cli.trace import cmd_trace

        for e in _make_events("a", count=3):
            _isolated_trace_collector.handle(e)
        for e in _make_events("b", count=5):
            _isolated_trace_collector.handle(e)

        cmd_trace(["--list"])
        out = capsys.readouterr().out

        # 最近在前：b, a
        assert "b" in out
        assert "a" in out
        assert "2/10" in out
        assert "events=5" in out  # b
        assert "events=3" in out  # a

    def test_list_json_empty(self, _isolated_trace_collector, capsys):
        """空 collector --list --json：count=0。"""
        from cli.trace import cmd_trace

        cmd_trace(["--list", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["version"] == "0.9.4"
        assert data["count"] == 0
        assert data["traced_plans"] == []

    def test_list_json_with_plans(self, _isolated_trace_collector, capsys):
        """有 traces --list --json：结构化列表。"""
        from cli.trace import cmd_trace

        for e in _make_events("x", count=2):
            _isolated_trace_collector.handle(e)
        for e in _make_events("y", count=4):
            _isolated_trace_collector.handle(e)

        cmd_trace(["--list", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["count"] == 2
        # 最近在前：y, x
        assert data["traced_plans"] == ["y", "x"]


# ── trace 与 PlanStore 关系（解耦 + 关联） ──

class TestCmdTraceShared:
    """trace 与 inspect 共享 TraceCollector。"""

    def test_inspect_shows_trace_available(self, monkeypatch, capsys):
        """inspect 显示 Trace: Available（当 plan 有 trace）。"""
        from cli import plan as plan_module
        from cli import trace as trace_module
        from planner.trace_collector import InMemoryTraceCollector
        from cli.inspect import cmd_inspect

        # 替换 fresh store + trace
        fresh_store = plan_module.PlanStore()
        fresh_trace = InMemoryTraceCollector()
        monkeypatch.setattr(plan_module, "_PLAN_STORE", fresh_store)
        trace_module._TraceHolder.collector = fresh_trace

        from planner.plan import Plan, Step
        from planner.execution_metrics import ExecutionMetrics
        plan = Plan(
            plan_id="p-shared-001",
            task_id="task-p-shared-001",
            steps=[Step(step_id="s-0", content="hi")],
            status="success",
            metadata={"planner": "RuleBasedPlanner", "router": "ScoreRouter", "schema_version": "1"},
            aggregate_metrics=ExecutionMetrics(latency_ms=200),
        )
        fresh_store.save(plan)

        # 注入 trace event
        from planner.execution_event import ExecutionEvent
        fresh_trace.handle(ExecutionEvent(type="plan_started", plan_id="p-shared-001"))

        cmd_inspect(["p-shared-001"])
        out = capsys.readouterr().out
        assert "Trace: Available" in out
        assert "p-shared-001" in out  # hint

    def test_inspect_shows_trace_no_trace(self, monkeypatch, capsys):
        """inspect 显示 Trace: No Trace（当 plan 无 trace）。"""
        from cli import plan as plan_module
        from cli import trace as trace_module
        from planner.trace_collector import InMemoryTraceCollector
        from cli.inspect import cmd_inspect

        fresh_store = plan_module.PlanStore()
        fresh_trace = InMemoryTraceCollector()
        monkeypatch.setattr(plan_module, "_PLAN_STORE", fresh_store)
        trace_module._TraceHolder.collector = fresh_trace

        from planner.plan import Plan, Step
        plan = Plan(
            plan_id="p-no-trace",
            task_id="task-p-no-trace",
            steps=[Step(step_id="s-0", content="hi")],
            status="success",
            metadata={"planner": "RuleBasedPlanner", "schema_version": "1"},
        )
        fresh_store.save(plan)

        cmd_inspect(["p-no-trace"])
        out = capsys.readouterr().out
        assert "Trace: No Trace" in out


# ── subprocess 测试（边界） ──

class TestTraceSubprocess:
    """subprocess 路径：usage / 错误退出码。"""

    def test_trace_no_args_subprocess(self):
        """subprocess 跑 trace 无参数：exit 1。"""
        rc, out, err = _run_cli("trace", timeout=15)
        assert rc == 1
        assert "Usage" in out

    def test_trace_list_subprocess(self):
        """subprocess 跑 trace --list：exit 0（无 trace 时）。"""
        rc, out, err = _run_cli("trace", "--list", timeout=15)
        assert rc == 0
        assert "AI Hub Trace" in out

    def test_trace_unknown_subprocess(self):
        """subprocess 跑 trace 未知 id：exit 1。"""
        rc, out, err = _run_cli("trace", "nonexistent-id", timeout=15)
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "not found" in combined


# ── trace 命令注册到 main ──

class TestTraceRegistration:
    """trace 命令注册到 cli/main.py。"""

    def test_trace_in_usage(self):
        """main usage 包含 trace。"""
        rc, out, err = _run_cli(timeout=10)
        assert rc == 0
        assert "trace" in out

    def test_trace_help_text_includes_list(self):
        """trace 自己的 usage 包含 --list 提示。"""
        rc, out, err = _run_cli("trace", timeout=10)
        # 无参数时输出 usage
        assert rc == 1
        assert "--list" in out
