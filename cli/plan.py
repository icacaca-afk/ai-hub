# AI Hub — CLI plan
# V0.9.1: Planner CLI 入口
# V0.9.2: 新增 --llm 标志
# V0.9.3: --json 真正实现（结构化输出）+ PlanStore 集成
#
# 用法：
#   ai-hub plan "<复合任务描述>"                    人类可读输出
#   ai-hub plan "<task>" --llm                     使用 LLMPlanner 语义分解
#   ai-hub plan "<task>" --json                    输出结构化 JSON（V0.9.3）
#
# 链路：Task → Planner → PlanExecutor → Router → Aggregate Result
# CLI 只消费 Result（output/artifacts/metadata），不访问 Planner 内部对象（ADR-0014）。
#
# V0.9.3 新增：执行完的 Plan 自动存入进程内 PlanStore（环形缓冲 N=10），
# 可用 `ai-hub inspect <plan_id>` 查看详情。
#
# API Stability: Experimental

from __future__ import annotations

import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.task import Task
from core.quota import QuotaManager
from core.health_registry import HealthRegistry
from router.score_router import ScoreRouter
from planner.executor import PlanExecutor
from planner.plan_store import PlanStore, DEFAULT_STORE_SIZE
from planner.rule_based_planner import RuleBasedPlanner
from planner.llm_planner import LLMPlanner


# V0.9.3: 进程内 PlanStore（环形缓冲 N=10），供 cmd_inspect 查询
# 单进程单线程，CLI 不暴露调整接口
# 运行时缓存，不持久化（ChatGPT 审核建议明示）
_PLAN_STORE = PlanStore(max_size=DEFAULT_STORE_SIZE)


def get_plan_store() -> PlanStore:
    """暴露 PlanStore 给 cli/inspect.py 使用（V0.9.3）。"""
    return _PLAN_STORE


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
      ai-hub plan "<task>" --json   结构化 JSON 输出（V0.9.3）
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

    # V0.9.3: 注入 PlanStore（执行完自动 save，inspect 可查）
    executor = PlanExecutor(router=router, planner=planner, plan_store=_PLAN_STORE)

    task = Task.from_text(text)

    # 执行（PlanExecutor 内部完成分解 + 路由 + 聚合）
    result = executor.execute(task)

    # V0.9.3: --json 真正实现
    if json_output:
        _print_json_output(task, result)
        if result.status == "failed":
            sys.exit(1)
        return

    # 人类可读输出（V0.9.1 不变）
    _print_human_output(text, result)

    if result.error and result.status == "failed":
        sys.exit(1)


def _print_json_output(task: Task, result) -> None:
    """V0.9.3: 输出结构化 JSON（ADR-0016 schema）。"""
    # 安全序列化：Result.metadata 是 dict，Result.to_dict() 处理嵌套
    payload = {
        "version": "0.9.3",
        "task": {
            "text": task.content,
            "task_id": task.task_id,
        },
        "plan": {
            "plan_id": result.metadata.get("plan_id", ""),
            "task_id": result.metadata.get("task_id", task.task_id),
            "status": result.metadata.get("plan", {}).get("status", "unknown"),
            "output": result.output,
            "artifacts": result.artifacts,
            "error": result.error,
            "metadata": result.metadata,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_human_output(text: str, result) -> None:
    """V0.9.3 人类可读输出（保持 V0.9.1 格式，版本号升级）。"""
    print("AI Hub Plan — v0.9.3")
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

    # schema_version
    schema_version = result.metadata.get("schema_version", "?")
    print(f"Schema Version:")
    print(f"  {schema_version}")
    print()

    # Output
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


if __name__ == "__main__":
    cmd_plan(sys.argv[1:])
