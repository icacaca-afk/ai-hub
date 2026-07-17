# tests/test_cli_plan.py
# V0.9.1 — CLI plan command tests
#
# 覆盖（ADR-0014）：
# - 正常多步任务：分解 + 执行 + 聚合输出（单元测试，monkeypatch FakeExecutor）
# - 单步任务（不可切分）：退化场景
# - 空输入：exit 1 + 错误提示（subprocess）
# - --json 标志：exit 0 + 提示信息（subprocess，未实现 ≠ 错误）
# - 输出格式：Planner 类名 / Status 全大写 / Step header
# - Plan 命令独立于 ask（不自动切换）
#
# 测试策略（参考 test_cli_score_integration.py）：
# - subprocess 测试：只测不触发真实 Provider 执行的路径（参数校验 / --json / usage）
# - 单元测试（monkeypatch + capsys）：测执行路径，注入 FakeExecutor 避免卡住

import subprocess
import sys
import os
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.result import Result
from core.task import Task


def _run_cli(*args, timeout=30):
    """运行 ai-hub CLI 命令（subprocess）。"""
    cmd = [sys.executable, "-m", "cli.main"] + list(args)
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    r = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=PROJECT_ROOT, env=env, timeout=timeout,
    )
    return r.returncode, r.stdout or "", r.stderr or ""


# ── FakeExecutor（避免触发真实 Provider） ──

class _FakeExecutor:
    """测试用 Fake PlanExecutor，execute() 返回预设 Result。

    避免真实 ScoreRouter 路由到 gemini_cli/openai_api 导致 subprocess 超时。
    """

    def __init__(self, *args, **kwargs):
        self.last_plan = None

    def execute(self, task: Task) -> Result:
        # 模拟 RuleBasedPlanner 切分 "hello then world" → 2 步
        return Result(
            provider="planner",
            status="success",
            output="[Step 0: hello]\nok1\n\n[Step 1: world]\nok2",
            metadata={
                "plan_id": "fake-plan-001",
                "task_id": task.task_id,
                "plan": {
                    "status": "success",
                    "steps": 2,
                    "success": 2,
                    "failed": 0,
                },
                "runtime": {
                    "planner": "RuleBasedPlanner",
                    "router": "ScoreRouter",
                },
            },
        )


class _FakeExecutorSingleStep:
    """单步场景的 Fake。"""

    def __init__(self, *args, **kwargs):
        self.last_plan = None

    def execute(self, task: Task) -> Result:
        return Result(
            provider="planner",
            status="success",
            output="[Step 0: hello]\nhello back",
            metadata={
                "plan_id": "fake-plan-002",
                "task_id": task.task_id,
                "plan": {"status": "success", "steps": 1, "success": 1, "failed": 0},
                "runtime": {"planner": "RuleBasedPlanner", "router": "ScoreRouter"},
            },
        )


# ── 单元测试：执行路径（monkeypatch + capsys） ──

class TestCliPlanExecution:
    """ai-hub plan 执行路径测试（单元测试，注入 FakeExecutor）。"""

    def test_plan_multistep_success(self, monkeypatch, capsys):
        """多步任务：分解 + 执行 + 聚合，输出含关键段落。"""
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "then", "world"])
        captured = capsys.readouterr()

        assert "AI Hub Plan" in captured.out
        assert "Task:" in captured.out
        assert "Planner:" in captured.out
        assert "Status:" in captured.out
        assert "Output:" in captured.out

    def test_plan_single_step(self, monkeypatch, capsys):
        """单步任务（不可切分）：退化场景，仍正常执行。"""
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutorSingleStep)

        plan_module.cmd_plan(["hello"])
        captured = capsys.readouterr()

        assert "Status:" in captured.out
        assert "(1/1)" in captured.out  # 1 step, 1 success

    def test_plan_shows_planner_class_name(self, monkeypatch, capsys):
        """Planner 行显示类名（RuleBasedPlanner），非 snake_case。"""
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "then", "world"])
        captured = capsys.readouterr()

        assert "RuleBasedPlanner" in captured.out

    def test_plan_status_uppercase(self, monkeypatch, capsys):
        """Status 状态全大写（SUCCESS / PARTIAL / FAILED）。"""
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "then", "world"])
        captured = capsys.readouterr()

        assert "SUCCESS" in captured.out

    def test_plan_output_has_step_headers(self, monkeypatch, capsys):
        """Output 段含 [Step i: ...] header。"""
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "then", "world"])
        captured = capsys.readouterr()

        assert "[Step 0:" in captured.out
        assert "[Step 1:" in captured.out

    def test_plan_version_in_output(self, monkeypatch, capsys):
        """输出含 v0.9.1 版本标识。"""
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello"])
        captured = capsys.readouterr()

        assert "v0.9.1" in captured.out

    def test_plan_consumes_only_result_not_executor_internals(self, monkeypatch, capsys):
        """CLI 只消费 Result，不访问 Planner 内部（ADR-0014 架构约束）。

        FakeExecutor.last_plan 设为 None（模拟「不可访问」），
        cmd_plan 仍能正常输出，证明它不依赖 Plan 内部对象。
        """
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "then", "world"])
        captured = capsys.readouterr()

        # 即使 last_plan=None，输出仍完整（Planner/Status/Output 全来自 Result.metadata）
        assert "RuleBasedPlanner" in captured.out
        assert "SUCCESS" in captured.out
        assert "(2/2)" in captured.out

    def test_plan_partial_status_display(self, monkeypatch, capsys):
        """partial 状态显示为 PARTIAL + 失败数提示。"""
        from cli import plan as plan_module

        class _FakePartial(_FakeExecutor):
            def execute(self, task):
                return Result(
                    provider="planner",
                    status="partial",
                    output="[Step 0: a]\nok\n[Step 1: b]\n",
                    error="step-1 (fake): boom",
                    metadata={
                        "plan_id": "p-partial",
                        "task_id": task.task_id,
                        "plan": {"status": "partial", "steps": 2, "success": 1, "failed": 1},
                        "runtime": {"planner": "RuleBasedPlanner", "router": "ScoreRouter"},
                    },
                )

        monkeypatch.setattr(plan_module, "PlanExecutor", _FakePartial)
        plan_module.cmd_plan(["a", "then", "b"])
        captured = capsys.readouterr()

        assert "PARTIAL" in captured.out
        assert "(1/2)" in captured.out
        assert "1 step(s) failed" in captured.out


# ── subprocess 测试：不触发执行的路径 ──

class TestCliPlanEdgeCases:
    """ai-hub plan 边界场景测试（subprocess，不触发真实 Provider）。"""

    def test_plan_empty_input(self):
        """空输入：exit 1 + 错误提示。"""
        rc, out, err = _run_cli("plan", "", timeout=30)
        assert rc == 1, f"exit={rc} stdout={out}"
        combined = out + err
        assert "empty" in combined.lower() or "usage" in combined.lower()

    def test_plan_no_args(self):
        """无参数：exit 1 + usage 提示。"""
        rc, out, err = _run_cli("plan", timeout=30)
        assert rc == 1, f"exit={rc} stdout={out}"
        assert "Usage" in out

    def test_plan_json_flag_exit_zero(self):
        """--json 标志：未实现，exit 0 + 提示信息（未实现 ≠ 错误）。"""
        rc, out, err = _run_cli("plan", "hello then world", "--json", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        assert "JSON output will be available" in out
        assert "V0.9.3" in out

    def test_plan_json_flag_only(self):
        """只有 --json 无任务：exit 1 + usage（--json 不掩盖参数缺失）。"""
        rc, out, err = _run_cli("plan", "--json", timeout=30)
        assert rc == 1, f"exit={rc} stdout={out}"
        assert "Usage" in out


class TestCliPlanIndependence:
    """ai-hub plan 与 ask 职责分离测试（ADR-0014）。"""

    def test_plan_registered_in_main(self):
        """plan 命令已注册到 commands dict。"""
        rc, out, err = _run_cli(timeout=10)
        assert "plan" in out

    def test_ask_and_plan_both_listed(self):
        """ask 与 plan 都出现在 usage 中，职责分离。"""
        rc, out, err = _run_cli(timeout=10)
        assert "ask" in out
        assert "plan" in out

    def test_plan_output_distinct_from_ask(self, monkeypatch, capsys):
        """plan 命令输出标识为 'AI Hub Plan'，与 ask 输出格式不同。"""
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "then", "world"])
        captured = capsys.readouterr()

        # plan 输出含 "AI Hub Plan"
        assert "AI Hub Plan" in captured.out
        # 注意：ask 命令输出不含此标识（由 cmd_ask 实现决定，此处只验证 plan 侧）


class TestCliPlanMetadataContract:
    """CLI 输出符合 metadata 分层契约（ADR-0014）。"""

    def test_plan_output_consistent_with_metadata(self, monkeypatch, capsys):
        """输出格式符合 metadata 分层契约。"""
        from cli import plan as plan_module
        monkeypatch.setattr(plan_module, "PlanExecutor", _FakeExecutor)

        plan_module.cmd_plan(["hello", "then", "world"])
        captured = capsys.readouterr()

        # Planner 行的值 = metadata.runtime.planner
        assert "RuleBasedPlanner" in captured.out
        # Status 行格式：(success/total)
        assert "(" in captured.out and ")" in captured.out
        assert "/" in captured.out
