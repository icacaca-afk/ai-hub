# tests/test_cli_inspect.py
# V0.9.3 — `ai-hub inspect` CLI 测试
#
# 覆盖（ADR-0016）：
# - `ai-hub inspect <plan_id>` 人类可读输出
# - `ai-hub inspect <plan_id> --json` JSON 输出
# - `ai-hub inspect --list` 列出最近 plan
# - `ai-hub inspect --list --json` 列表 JSON
# - plan_id 不存在：exit 1 + 错误提示
# - 无参数：exit 1 + usage
# - inspect 集成 PlanStore（通过 cli.plan.get_plan_store() 共享）
# - inspect 命令已注册到 main usage

import json
import sys
import os
import subprocess

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _run_cli(*args, timeout=30):
    """运行 ai-hub CLI 命令（subprocess）。"""
    cmd = [sys.executable, "-m", "cli.main"] + list(args)
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    r = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=PROJECT_ROOT, env=env, timeout=timeout,
    )
    return r.returncode, r.stdout or "", r.stderr or ""


# ── Test Fixtures ──

def _make_plan(plan_id: str, status: str = "success", step_count: int = 1) -> "Plan":
    from planner.plan import Plan, Step

    steps = [Step(step_id=f"step-{i}", content=f"step-{i}-content") for i in range(step_count)]
    return Plan(
        plan_id=plan_id,
        task_id=f"task-{plan_id}",
        steps=steps,
        status=status,
        metadata={"planner": "RuleBasedPlanner", "schema_version": "1"},
    )


@pytest.fixture
def _isolated_plan_store(monkeypatch):
    """每个测试用独立的 PlanStore（max_size=10），注入到 cli.plan._PLAN_STORE。"""
    from cli import plan as plan_module
    from planner.plan_store import PlanStore

    fresh = PlanStore(max_size=10)
    monkeypatch.setattr(plan_module, "_PLAN_STORE", fresh)
    return fresh


@pytest.fixture
def _small_plan_store(monkeypatch):
    """max_size=3 的小型 store（用于环形缓冲测试）。"""
    from cli import plan as plan_module
    from planner.plan_store import PlanStore

    fresh = PlanStore(max_size=3)
    monkeypatch.setattr(plan_module, "_PLAN_STORE", fresh)
    return fresh


# ── 单元测试：inspect 共享 PlanStore ──

class TestCmdInspectBasic:
    """cmd_inspect 基本行为。"""

    def test_inspect_no_args_shows_usage(self, capsys):
        """无参数：exit 1 + usage。"""
        from cli.inspect import cmd_inspect

        with pytest.raises(SystemExit) as exc_info:
            cmd_inspect([])
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Usage" in captured.out
        assert "inspect" in captured.out

    def test_inspect_unknown_plan_id(self, _isolated_plan_store, capsys):
        """plan_id 不存在：exit 1 + 错误提示。"""
        from cli.inspect import cmd_inspect

        with pytest.raises(SystemExit) as exc_info:
            cmd_inspect(["nonexistent-plan-id"])
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "not found" in combined.lower() or "not found" in combined

    def test_inspect_existing_plan_human(self, _isolated_plan_store, capsys):
        """已知 plan_id → 人类可读输出。"""
        from cli.inspect import cmd_inspect

        plan = _make_plan("p-001", status="success", step_count=2)
        _isolated_plan_store.save(plan)

        cmd_inspect(["p-001"])
        out = capsys.readouterr().out

        assert "AI Hub Inspect" in out
        assert "p-001" in out
        assert "Planner" in out
        assert "Schema Version" in out
        assert "Steps" in out

    def test_inspect_existing_plan_json(self, _isolated_plan_store, capsys):
        """已知 plan_id --json → 合法 JSON。"""
        from cli.inspect import cmd_inspect

        plan = _make_plan("p-002", status="success", step_count=1)
        _isolated_plan_store.save(plan)

        cmd_inspect(["p-002", "--json"])
        out = capsys.readouterr().out

        data = json.loads(out)
        assert data["version"] == "0.9.3"
        assert data["plan"]["plan_id"] == "p-002"
        assert "steps" in data["plan"]
        assert data["plan"]["metadata"]["schema_version"] == "1"

    def test_inspect_json_includes_plan_to_dict(self, _isolated_plan_store, capsys):
        """JSON 输出含 plan.to_dict() 全部字段。"""
        from cli.inspect import cmd_inspect

        plan = _make_plan("p-003", status="partial", step_count=2)
        _isolated_plan_store.save(plan)

        cmd_inspect(["p-003", "--json"])
        data = json.loads(capsys.readouterr().out)

        plan_dict = data["plan"]
        assert plan_dict["plan_id"] == "p-003"
        assert plan_dict["task_id"] == "task-p-003"
        assert plan_dict["status"] == "partial"
        assert len(plan_dict["steps"]) == 2


# ── inspect --list ──

class TestCmdInspectList:
    """ai-hub inspect --list 模式。"""

    def test_list_human_empty(self, _isolated_plan_store, capsys):
        """空 store --list：人类可读 + 提示。"""
        from cli.inspect import cmd_inspect

        cmd_inspect(["--list"])
        out = capsys.readouterr().out

        assert "AI Hub Inspect" in out
        assert "Recent Plans" in out
        assert "0/10" in out

    def test_list_human_with_plans(self, _isolated_plan_store, capsys):
        """有 plan --list：人类可读列表。"""
        from cli.inspect import cmd_inspect

        _isolated_plan_store.save(_make_plan("a"))
        _isolated_plan_store.save(_make_plan("b"))
        _isolated_plan_store.save(_make_plan("c", status="failed"))

        cmd_inspect(["--list"])
        out = capsys.readouterr().out

        # 最近在前：c, b, a
        assert "c" in out
        assert "b" in out
        assert "a" in out
        assert "3/10" in out
        # 状态图标
        assert "FAILED" in out

    def test_list_json_empty(self, _isolated_plan_store, capsys):
        """空 store --list --json：count=0。"""
        from cli.inspect import cmd_inspect

        cmd_inspect(["--list", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["version"] == "0.9.3"
        assert data["count"] == 0
        assert data["plans"] == []

    def test_list_json_with_plans(self, _isolated_plan_store, capsys):
        """有 plan --list --json：结构化列表。"""
        from cli.inspect import cmd_inspect

        _isolated_plan_store.save(_make_plan("x"))
        _isolated_plan_store.save(_make_plan("y", status="partial", step_count=3))

        cmd_inspect(["--list", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["count"] == 2
        plans = data["plans"]
        # 最近在前：y, x
        assert plans[0]["plan_id"] == "y"
        assert plans[1]["plan_id"] == "x"
        # 元字段
        assert plans[0]["status"] == "partial"
        assert plans[0]["step_count"] == 3
        assert plans[0]["task_id"] == "task-y"

    def test_list_respects_ring_buffer(self, _small_plan_store, capsys):
        """--list 反映环形缓冲（max_size=3 不会返回 4 个）。"""
        from cli.inspect import cmd_inspect

        # max_size=3 存 5 个
        for i in range(5):
            _small_plan_store.save(_make_plan(f"p{i}"))

        cmd_inspect(["--list"])
        out = capsys.readouterr().out

        # 弹出最早的 p0, p1；保留 p2, p3, p4
        assert "p4" in out
        assert "p2" in out
        assert "p0" not in out
        assert "p1" not in out
        assert "3/3" in out


# ── inspect 集成 PlanStore 行为 ──

class TestCmdInspectSharedStore:
    """cmd_inspect 与 cmd_plan 共享 PlanStore 单例。"""

    def test_inspect_sees_plan_saved_via_plan_module(self, monkeypatch, capsys):
        """通过 cli.plan 的 PlanStore 保存后，inspect 能查到。"""
        from cli import plan as plan_module
        from planner.plan_store import PlanStore
        from cli.inspect import cmd_inspect

        # 替换为 fresh store
        fresh = PlanStore(max_size=10)
        monkeypatch.setattr(plan_module, "_PLAN_STORE", fresh)

        # 直接 save（模拟 plan 执行完后）
        fresh.save(_make_plan("shared-plan-001"))

        # inspect 查询
        cmd_inspect(["shared-plan-001"])
        out = capsys.readouterr().out
        assert "shared-plan-001" in out

    def test_get_plan_store_singleton(self):
        """get_plan_store() 每次返回同一实例。"""
        from cli.plan import get_plan_store

        s1 = get_plan_store()
        s2 = get_plan_store()
        assert s1 is s2


# ── subprocess 测试（边界） ──

class TestInspectSubprocess:
    """subprocess 路径：usage / 错误退出码。"""

    def test_inspect_no_args_subprocess(self):
        """subprocess 跑 inspect 无参数：exit 1。"""
        rc, out, err = _run_cli("inspect", timeout=15)
        assert rc == 1
        assert "Usage" in out

    def test_inspect_list_subprocess(self):
        """subprocess 跑 inspect --list：exit 0（无 plan 时）。"""
        # 注意：subprocess 是新进程，PlanStore 是空
        rc, out, err = _run_cli("inspect", "--list", timeout=15)
        assert rc == 0
        assert "AI Hub Inspect" in out

    def test_inspect_unknown_subprocess(self):
        """subprocess 跑 inspect 未知 id：exit 1。"""
        rc, out, err = _run_cli("inspect", "nonexistent-id", timeout=15)
        assert rc == 1
        combined = out + err
        assert "not found" in combined.lower() or "not found" in combined


# ── inspect 命令注册到 main ──

class TestInspectRegistration:
    """inspect 命令注册到 cli/main.py。"""

    def test_inspect_in_usage(self):
        """main usage 包含 inspect。"""
        rc, out, err = _run_cli(timeout=10)
        assert rc == 0
        assert "inspect" in out

    def test_inspect_help_text(self):
        """inspect 自己的 usage 包含 --json / --list 提示。"""
        rc, out, err = _run_cli("inspect", timeout=10)
        # 无参数时输出 usage
        assert rc == 1
        assert "--json" in out
        assert "--list" in out
