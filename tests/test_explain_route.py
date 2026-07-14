# Tests for ai-hub explain-route CLI command (V0.7.1)
#
# 覆盖：
# - 基本路由解释输出
# - 无候选 Provider 场景
# - health 状态影响展示
# - skipped Provider 记录
# - --help / 无参数提示

import subprocess
import sys
import os

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _run_explain_route(task_text: str) -> tuple[int, str, str]:
    """运行 explain-route 命令，返回 (exit_code, stdout, stderr)。"""
    result = subprocess.run(
        [sys.executable, "-m", "cli.main", "explain-route", task_text],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": PROJECT_ROOT},
        timeout=60,
    )
    return result.returncode, result.stdout or "", result.stderr or ""


class TestExplainRouteOutput:
    """explain-route 输出格式测试。"""

    def test_basic_output_has_sections(self):
        """输出包含 Task / Capabilities / Candidates / Decision 四个区块。"""
        code, out, err = _run_explain_route("write a hello world program")
        assert code == 0, f"exit={code}, stderr={err}"
        assert "Route Explanation" in out
        assert "Task:" in out
        assert "Capabilities:" in out
        assert "Candidates" in out
        assert "Decision:" in out

    def test_task_text_shown(self):
        """输出中显示 Task 原文。"""
        code, out, _ = _run_explain_route("sort a list of numbers")
        assert code == 0
        assert "sort a list of numbers" in out

    def test_capabilities_shown(self):
        """输出中显示识别到的 capability 标签。"""
        code, out, _ = _run_explain_route("write python code")
        assert code == 0
        # 应该至少有一个 capability
        assert "code" in out.lower() or "generate" in out.lower()

    def test_selected_provider_marked(self):
        """被选中的 Provider 标有 SELECTED 标记。"""
        code, out, _ = _run_explain_route("write a hello world program")
        assert code == 0
        assert "SELECTED" in out

    def test_health_status_shown(self):
        """每个候选 Provider 显示 health 状态。"""
        code, out, _ = _run_explain_route("write code")
        assert code == 0
        # 应该出现 health 相关字样
        assert "health:" in out

    def test_quota_shown(self):
        """每个候选 Provider 显示 quota 状态。"""
        code, out, _ = _run_explain_route("write code")
        assert code == 0
        assert "quota:" in out

    def test_priority_shown(self):
        """每个候选 Provider 显示 priority。"""
        code, out, _ = _run_explain_route("write code")
        assert code == 0
        assert "priority:" in out

    def test_bridge_shown(self):
        """每个候选 Provider 显示 bridge 类型。"""
        code, out, _ = _run_explain_route("write code")
        assert code == 0
        assert "bridge:" in out

    def test_group_shown_in_decision(self):
        """Decision 区块显示 group（healthy/degraded/fallback）。"""
        code, out, _ = _run_explain_route("write code")
        assert code == 0
        assert "Group:" in out


class TestExplainRouteEdgeCases:
    """边界情况测试。"""

    def test_no_args_shows_usage(self):
        """无参数时显示用法提示。"""
        result = subprocess.run(
            [sys.executable, "-m", "cli.main", "explain-route"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONPATH": PROJECT_ROOT},
            timeout=10,
        )
        assert result.returncode != 0
        assert "Usage" in (result.stdout or "")

    def test_unknown_capability_no_crash(self):
        """无法识别的 capability 也不应崩溃。"""
        code, out, err = _run_explain_route("zzzzz_unknown_task_type_xyz")
        # 可能没有候选 Provider，但不应崩溃
        # exit code 0 或 1 都可接受，关键是不能 Python traceback
        assert "Traceback" not in err
        assert "Route Explanation" in out or "No available" in out or "Selected:  (none)" in out

    def test_multiple_words_task(self):
        """多词任务描述正常工作。"""
        code, out, _ = _run_explain_route("write a python web server using flask")
        assert code == 0
        assert "write a python web server using flask" in out


class TestExplainRouteRegistered:
    """命令注册测试。"""

    def test_explain_route_in_main_help(self):
        """main 帮助中包含 explain-route。"""
        result = subprocess.run(
            [sys.executable, "-m", "cli.main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONPATH": PROJECT_ROOT},
            timeout=10,
        )
        assert "explain-route" in (result.stdout or "")
