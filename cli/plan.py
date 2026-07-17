# AI Hub — CLI plan
# V0.9.1: Planner CLI 入口
#
# 用法：
#   ai-hub plan "<复合任务描述>"
#   ai-hub plan "<task>" --json   (V0.9.3 实现，当前打印提示并 exit 0)
#
# 链路：Task → Planner → PlanExecutor → Router → Aggregate Result
# CLI 只消费 Result（output/artifacts/metadata），不访问 Planner 内部对象（ADR-0014）。
#
# API Stability: Experimental

from __future__ import annotations

import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.task import Task
from core.quota import QuotaManager
from core.health_registry import HealthRegistry
from router.score_router import ScoreRouter
from planner.executor import PlanExecutor
from planner.rule_based_planner import RuleBasedPlanner
from planner.llm_planner import LLMPlanner


def _build_registry():
    """构建 CapabilityRegistry（与 cli/main.py 一致）。"""
    from core.registry import CapabilityRegistry
    registry = CapabilityRegistry()

    from providers.demo.provider import DemoProvider
    registry.register(DemoProvider())

    from providers.gemini.provider import GeminiCLIProvider
    registry.register(GeminiCLIProvider())

    from providers.stub.provider import StubProvider
    registry.register(StubProvider())

    from providers.openai_api.provider import OpenAIAPIProvider
    registry.register(OpenAIAPIProvider())

    from providers.qoder.provider import QoderProvider
    registry.register(QoderProvider())

    from providers.fake_browser.provider import FakeBrowserProvider
    registry.register(FakeBrowserProvider())

    from providers.web_ai.provider import WebAIProvider
    registry.register(WebAIProvider())

    return registry


def cmd_plan(args: list[str]) -> None:
    """执行复合任务：分解 → 多步执行 → 聚合。

    用法：
      ai-hub plan "<task>"          人类可读输出（RuleBasedPlanner）
      ai-hub plan "<task>" --llm    使用 LLMPlanner 语义分解（V0.9.2）
      ai-hub plan "<task>" --json   V0.9.3 实现（当前 exit 0 + 提示）
    """
    if not args:
        print('Usage: ai-hub plan "<composite task description>" [--llm] [--json]')
        sys.exit(1)

    json_output = "--json" in args
    use_llm = "--llm" in args
    task_args = [a for a in args if a not in ("--json", "--llm")]
    if not task_args:
        print('Usage: ai-hub plan "<composite task description>" [--llm] [--json]')
        sys.exit(1)

    # --json 占位：未实现 ≠ 错误，exit 0（ADR-0014）
    if json_output:
        print("JSON output will be available in V0.9.3 with explain-plan")
        sys.exit(0)

    text = " ".join(task_args)
    if not text.strip():
        print("Error: task description is empty")
        sys.exit(1)

    # 构建 Runtime（与 cmd_ask 一致）
    registry = _build_registry()
    quota = QuotaManager()
    hr = HealthRegistry()
    router = ScoreRouter(registry, quota_manager=quota, health_registry=hr)

    # Planner 选择：--llm 用 LLMPlanner（共享同一 Router），否则 RuleBasedPlanner（ADR-0015）
    if use_llm:
        planner = LLMPlanner(router=router)
    else:
        planner = RuleBasedPlanner()

    executor = PlanExecutor(router=router, planner=planner)

    task = Task.from_text(text)

    # 执行（PlanExecutor 内部完成分解 + 路由 + 聚合）
    result = executor.execute(task)

    # ── 输出（只消费 Result，不访问 executor.last_plan） ──
    print("AI Hub Plan — v0.9.1")
    print()
    print("Task:")
    print(f"  {text}")
    print()

    # Planner / Router 信息统一来自 metadata.runtime（ADR-0014）
    runtime = result.metadata.get("runtime", {})
    planner_name = runtime.get("planner", "unknown")
    print(f"Planner:")
    print(f"  {planner_name}")
    print()

    # Steps 概览（从 metadata.plan 读取，不遍历 Plan 内部）
    plan_meta = result.metadata.get("plan", {})
    plan_status = plan_meta.get("status", "unknown")
    step_total = plan_meta.get("steps", 0)
    step_success = plan_meta.get("success", 0)
    step_failed = plan_meta.get("failed", 0)

    # 状态图标映射
    status_icon = {"success": "✓", "failed": "✗", "partial": "⚠"}.get(plan_status, "?")
    status_upper = plan_status.upper() if plan_status != "unknown" else "UNKNOWN"

    print("Status:")
    print(f"  {status_icon} {status_upper} ({step_success}/{step_total})")
    if step_failed > 0:
        print(f"    ({step_failed} step(s) failed)")
    print()

    # Output（已含 [Step i: ...] header，由 PlanExecutor 聚合）
    print("Output:")
    print(result.output)
    print()

    # Artifacts
    if result.artifacts:
        print("Artifacts:")
        for a in result.artifacts:
            print(f"  - {a}")
        print()

    # Error
    if result.error:
        print(f"Error: {result.error}", file=sys.stderr)
        if result.status == "failed":
            sys.exit(1)


if __name__ == "__main__":
    cmd_plan(sys.argv[1:])
