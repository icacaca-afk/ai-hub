# tests/test_cli_plan_json.py
# V0.9.3 — `ai-hub plan --json` 真正实现测试
#
# 覆盖（ADR-0016）：
# - --json 输出是合法 JSON
# - JSON schema 包含 version / task / plan / metadata
# - metadata.schema_version == "1"
# - metadata.plan / metadata.runtime 子键结构
# - 与 --json 不冲突的多步执行路径
# - 边界：空任务 / --json-only
#
# 测试用 FakeExecutor 避免真实 Provider 卡住。

import json
import pytest

from core.result import Result
from core.task import Task


# ── FakeExecutor ──

class _FakeQuota:
    """测试用 Fake QuotaManager（避免真实 sqlite db）。"""

    def __init__(self, *args, **kwargs):
        pass


class _FakeRegistry:
    """测试用 Fake CapabilityRegistry。"""

    def all(self):
        return []


class _FakeRouter:
    """测试用 Fake ScoreRouter。"""

    def __init__(self, *args, **kwargs):
        self.last_scores = []


class _FakeHealth:
    """测试用 Fake HealthRegistry。"""

    def __init__(self, *args, **kwargs):
        pass


def _patch_plan_module_deps(monkeypatch):
    """Patch cmd_plan 的所有真实依赖。"""
    from cli import plan as plan_module

    monkeypatch.setattr(plan_module, "QuotaManager", _FakeQuota)
    monkeypatch.setattr(plan_module, "HealthRegistry", _FakeHealth)
    monkeypatch.setattr(plan_module, "ScoreRouter", _FakeRouter)
    monkeypatch.setattr(plan_module, "_build_registry", lambda: _FakeRegistry())


class _FakeExecutor:
    """测试用 Fake PlanExecutor，execute() 返回预设 Result（带 schema_version 字段）。"""

    def __init__(self, *args, **kwargs):
        self.last_plan = None
        self.plan_store = kwargs.get("plan_store")

    def execute(self, task: Task) -> Result:
        # 模拟 PlanExecutor + PlanStore 集成：执行后 save plan
        from planner.plan import Plan
        plan = Plan(
            plan_id="fake-plan-001",
            task_id=task.task_id,
            steps=[],
            status="success",
            metadata={"planner": "RuleBasedPlanner"},
        )
        if self.plan_store is not None:
            self.plan_store.save(plan)
        return Result(
            provider="planner",
            status="success",
            output="[Step 0: hello]\nok1\n\n[Step 1: world]\nok2",
            metadata={
                "plan_id": "fake-plan-001",
                "task_id": task.task_id,
                "plan": {"status": "success", "steps": 2, "success": 2, "failed": 0},
                "runtime": {"planner": "RuleBasedPlanner", "router": "ScoreRouter"},
                "schema_version": "1",
            },
        )


class TestCliPlanJson:
    """ai-hub plan --json 真正实现测试（单元测试，注入 FakeExecutor）。"""

    def test_json_output_is_valid_json(self, monkeypatch, capsys):
        """--json 输出是合法 JSON。"""
        from cli import plan as plan_module
        _patch_plan_module_deps(monkeypatch)
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "then", "world", "--json"])
        captured = capsys.readouterr()

        # 整个 stdout 应该是 JSON（可能末尾有换行）
        data = json.loads(captured.out)
        assert isinstance(data, dict)

    def test_json_schema_top_level(self, monkeypatch, capsys):
        """顶层 schema 包含 version / task / plan。"""
        from cli import plan as plan_module
        _patch_plan_module_deps(monkeypatch)
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["version"] == "0.9.4"
        assert "task" in data
        assert "plan" in data
        assert data["task"]["text"] == "hello"

    def test_json_metadata_includes_schema_version(self, monkeypatch, capsys):
        """metadata 顶层含 schema_version="1"（ADR-0016）。"""
        from cli import plan as plan_module
        _patch_plan_module_deps(monkeypatch)
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["plan"]["metadata"]["schema_version"] == "1"

    def test_json_metadata_layered_structure(self, monkeypatch, capsys):
        """metadata 分层结构：plan.* / runtime.* + schema_version（ADR-0014 兼容）。"""
        from cli import plan as plan_module
        _patch_plan_module_deps(monkeypatch)
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "--json"])
        data = json.loads(capsys.readouterr().out)

        meta = data["plan"]["metadata"]
        # 顶层稳定标识
        assert "plan_id" in meta
        assert "task_id" in meta
        # plan 子键
        assert "plan" in meta
        assert meta["plan"]["status"] == "success"
        assert meta["plan"]["steps"] == 2
        # runtime 子键
        assert meta["runtime"]["planner"] == "RuleBasedPlanner"
        # schema_version
        assert meta["schema_version"] == "1"

    def test_json_plan_id_matches_metadata(self, monkeypatch, capsys):
        """JSON 顶层 plan_id 与 metadata.plan_id 一致。"""
        from cli import plan as plan_module
        _patch_plan_module_deps(monkeypatch)
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "--json"])
        data = json.loads(capsys.readouterr().out)

        # FakeExecutor 写死 plan_id="fake-plan-001"
        assert data["plan"]["plan_id"] == "fake-plan-001"
        assert data["plan"]["metadata"]["plan_id"] == "fake-plan-001"

    def test_json_output_preserves_unicode(self, monkeypatch, capsys):
        """中文任务描述正确序列化。"""
        from cli import plan as plan_module
        _patch_plan_module_deps(monkeypatch)
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["总结", "PDF", "然后翻译", "--json"])
        data = json.loads(capsys.readouterr().out)

        assert data["task"]["text"] == "总结 PDF 然后翻译"

    def test_json_and_llm_compatible(self, monkeypatch, capsys):
        """--json 和 --llm 标志可同时使用。"""
        from cli import plan as plan_module
        _patch_plan_module_deps(monkeypatch)
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "--llm", "--json"])
        captured = capsys.readouterr()

        data = json.loads(captured.out)
        assert data["version"] == "0.9.4"

    def test_no_human_output_when_json(self, monkeypatch, capsys):
        """--json 模式不应输出人类可读文本。"""
        from cli import plan as plan_module
        _patch_plan_module_deps(monkeypatch)
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "--json"])
        captured = capsys.readouterr()

        # 人类可读标识不应出现
        assert "AI Hub Plan" not in captured.out
        # 应该是 JSON
        data = json.loads(captured.out)
        assert "version" in data


class TestCliPlanJsonEdgeCases:
    """边界场景（subprocess，不触发真实 Provider）。"""

    def test_json_with_empty_input_fails(self):
        """--json 空任务 → exit 1。"""
        import subprocess
        import sys
        import os

        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [sys.executable, "-m", "cli.main", "plan", "", "--json"]
        env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=PROJECT_ROOT, env=env)
        assert r.returncode == 1
        assert "empty" in (r.stdout + r.stderr).lower() or "Usage" in (r.stdout + r.stderr)

    def test_json_flag_only_no_task(self):
        """只有 --json 无任务 → exit 1。"""
        import subprocess
        import sys
        import os

        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [sys.executable, "-m", "cli.main", "plan", "--json"]
        env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=PROJECT_ROOT, env=env)
        assert r.returncode == 1
        assert "Usage" in r.stdout


class TestCliPlanJsonUsage:
    """usage 文本反映 V0.9.3 --json 已实现。"""

    def test_usage_includes_json(self):
        """无参数时 usage 行包含 --json 提示。"""
        import subprocess
        import sys
        import os

        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [sys.executable, "-m", "cli.main"]
        env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=PROJECT_ROOT, env=env)
        assert r.returncode == 0
        # usage 应含 --json / inspect
        assert "--json" in r.stdout
        assert "inspect" in r.stdout
