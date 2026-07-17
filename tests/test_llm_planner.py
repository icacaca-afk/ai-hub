# tests/test_llm_planner.py
# V0.9.2 — LLMPlanner 单元测试
#
# 覆盖（ADR-0015）：
# - 正常分解：LLM 返回合法 JSON → 生成 Plan
# - JSON 解析：纯 JSON / ```json 包裹 / 混杂文本
# - 降级链：LLM 失败 / JSON 非法 / 空步骤 → 降级 RuleBasedPlanner
# - PlanValidator 集成：未知 capability / 自依赖 / 超限截断
# - Router 共享：LLMPlanner 与 PlanExecutor 用同一 Router 实例
#
# 测试用 FakeRouter 返回预设 JSON，不依赖真实 Provider。

import json
import pytest

from core.task import Task
from core.result import Result
from planner.plan import Plan, Step
from planner.llm_planner import LLMPlanner
from planner.rule_based_planner import RuleBasedPlanner


# ── FakeRouter ──

class _FakeRouter:
    """测试用 Fake Router，execute() 返回预设 Result。

    避免 LLMPlanner 调真实 Provider 导致卡住。
    """

    def __init__(self, output: str = "", status: str = "success", error: str | None = None):
        self.output = output
        self.status = status
        self.error = error
        self.execute_count = 0

    def execute(self, task: Task) -> Result:
        self.execute_count += 1
        return Result(
            provider="fake_llm",
            status=self.status,
            output=self.output,
            error=self.error,
        )


class _TestRouter:
    """记录调用次数但不返回有效内容的 Router（用于验证调用）。"""

    def __init__(self):
        self.called = 0

    def execute(self, task: Task) -> Result:
        self.called += 1
        return Result(provider="test", status="success", output="")


# ── 测试数据：合法 JSON ──

_VALID_JSON = json.dumps([
    {"content": "总结 PDF", "capabilities": ["text.summarize"], "depends_on": []},
    {"content": "翻译成英文", "capabilities": ["text.translate"], "depends_on": ["step-0"]},
])

_VALID_JSON_FENCED = '```json\n' + _VALID_JSON + '\n```'

_VALID_JSON_WITH_PROSE = '好的，我来分解：\n' + _VALID_JSON + '\n以上是分解结果。'


class TestLLMPlannerDecompose:
    """LLMPlanner.decompose() 正常路径。"""

    def test_valid_json_returns_plan(self):
        """LLM 返回合法 JSON → 正确生成 Plan。"""
        router = _FakeRouter(output=_VALID_JSON)
        planner = LLMPlanner(router=router)

        task = Task.from_text("总结 PDF 然后翻译成英文")
        plan = planner.decompose(task)

        assert len(plan.steps) == 2
        assert plan.steps[0].content == "总结 PDF"
        assert plan.steps[1].content == "翻译成英文"
        assert plan.steps[1].depends_on == ["step-0"]
        assert plan.steps[0].capabilities == ["text.summarize"]
        assert plan.steps[1].capabilities == ["text.translate"]

    def test_fenced_json_extracted(self):
        """LLM 返回 ```json 包裹的 JSON → 正确提取。"""
        router = _FakeRouter(output=_VALID_JSON_FENCED)
        planner = LLMPlanner(router=router)

        task = Task.from_text("test")
        plan = planner.decompose(task)

        assert len(plan.steps) == 2

    def test_json_with_surrounding_prose(self):
        """LLM 返回夹杂文本的 JSON → 正确提取数组部分。"""
        router = _FakeRouter(output=_VALID_JSON_WITH_PROSE)
        planner = LLMPlanner(router=router)

        task = Task.from_text("test")
        plan = planner.decompose(task)

        assert len(plan.steps) == 2

    def test_step_ids_renumbered(self):
        """LLM 返回的 step_id 被重编号为 step-0/step-1。"""
        json_with_ids = json.dumps([
            {"content": "a", "step_id": "weird-1"},
            {"content": "b", "step_id": "another"},
        ])
        router = _FakeRouter(output=json_with_ids)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("test"))
        assert plan.steps[0].step_id == "step-0"
        assert plan.steps[1].step_id == "step-1"

    def test_router_called_once(self):
        """decompose() 只调 Router 一次（不算 Step 执行）。"""
        router = _FakeRouter(output=_VALID_JSON)
        planner = LLMPlanner(router=router)

        planner.decompose(Task.from_text("test"))
        assert router.execute_count == 1

    def test_plan_metadata_records_llm(self):
        """Plan.metadata 记录 planner=llm。"""
        router = _FakeRouter(output=_VALID_JSON)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("test"))
        assert plan.metadata.get("planner") == "llm"
        assert plan.metadata.get("version") == "0.9.2"


class TestLLMPlannerFallback:
    """LLMPlanner 降级链测试。"""

    def test_llm_empty_output_fallback(self):
        """LLM 返回空 → 降级 RuleBasedPlanner。"""
        router = _FakeRouter(output="")
        planner = LLMPlanner(router=router)

        task = Task.from_text("hello then world")  # RuleBased 可切分
        plan = planner.decompose(task)

        # 降级后走 RuleBasedPlanner，应能切分
        assert len(plan.steps) == 2
        assert plan.metadata.get("planner") == "rule_based"

    def test_llm_failed_status_fallback(self):
        """LLM 执行失败 → 降级 RuleBasedPlanner。"""
        router = _FakeRouter(output="", status="failed", error="timeout")
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("hello then world"))
        assert plan.metadata.get("planner") == "rule_based"

    def test_invalid_json_fallback(self):
        """LLM 返回非 JSON → 降级 RuleBasedPlanner。"""
        router = _FakeRouter(output="这不是 JSON")
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("hello then world"))
        assert plan.metadata.get("planner") == "rule_based"

    def test_json_not_array_fallback(self):
        """LLM 返回 JSON 但不是数组 → 降级。"""
        router = _FakeRouter(output='{"not": "an array"}')
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("hello then world"))
        assert plan.metadata.get("planner") == "rule_based"

    def test_empty_steps_after_cleaning_fallback(self):
        """所有 step 都无效 → 降级。"""
        # 所有 step 都缺 content
        bad_json = json.dumps([
            {"content": "", "capabilities": []},
            {"content": "   ", "capabilities": []},
        ])
        router = _FakeRouter(output=bad_json)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("hello then world"))
        assert plan.metadata.get("planner") == "rule_based"

    def test_exception_during_decompose_fallback(self):
        """decompose 过程中抛异常 → 降级（不向上抛）。"""

        class _ExplodingRouter:
            def execute(self, task):
                raise RuntimeError("boom")

        planner = LLMPlanner(router=_ExplodingRouter())

        plan = planner.decompose(Task.from_text("hello then world"))
        assert plan.metadata.get("planner") == "rule_based"

    def test_fallback_produces_valid_plan(self):
        """降级后的 Plan 仍是合法的（可被 PlanExecutor 消费）。"""
        router = _FakeRouter(output="invalid")
        planner = LLMPlanner(router=router)

        task = Task.from_text("hello then world")
        plan = planner.decompose(task)

        # RuleBasedPlanner 的产出：2 步，线性依赖
        assert len(plan.steps) == 2
        assert plan.steps[0].step_id == "step-0"
        assert plan.steps[1].step_id == "step-1"
        assert plan.steps[1].depends_on == ["step-0"]


class TestLLMPlannerValidation:
    """LLMPlanner 与 PlanValidator 集成测试。"""

    def test_unknown_capability_downgraded(self):
        """LLM 返回未知 capability → 降级 general.chat。"""
        json_bad_cap = json.dumps([
            {"content": "step a", "capabilities": ["fake.cap.v99"]},
        ])
        router = _FakeRouter(output=json_bad_cap)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("test"))
        assert "general.chat" in plan.steps[0].capabilities
        assert "fake.cap.v99" not in plan.steps[0].capabilities

    def test_self_dependency_dropped(self):
        """LLM 返回自依赖 → 被丢弃。"""
        json_self_dep = json.dumps([
            {"content": "step a", "depends_on": ["step-0"]},
        ])
        router = _FakeRouter(output=json_self_dep)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("test"))
        assert plan.steps[0].depends_on == []

    def test_unknown_dependency_dropped(self):
        """LLM 返回未知依赖 → 被丢弃。"""
        json_unknown_dep = json.dumps([
            {"content": "step a", "depends_on": ["nonexistent"]},
        ])
        router = _FakeRouter(output=json_unknown_dep)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("test"))
        assert plan.steps[0].depends_on == []

    def test_over_limit_truncated(self):
        """LLM 返回超量 step → 截断到 MAX_STEPS。"""
        from planner.plan_validator import MAX_STEPS

        too_many = json.dumps([
            {"content": f"step-{i}"} for i in range(MAX_STEPS + 5)
        ])
        router = _FakeRouter(output=too_many)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("test"))
        assert len(plan.steps) == MAX_STEPS


class TestLLMPlannerRouterSharing:
    """LLMPlanner 与 PlanExecutor 共享 Router 实例（ADR-0015）。"""

    def test_router_instance_reused(self):
        """LLMPlanner 持有的 Router 与传入的是同一实例。"""
        router = _FakeRouter(output=_VALID_JSON)
        planner = LLMPlanner(router=router)

        assert planner.router is router

    def test_multiple_decompose_calls_share_router(self):
        """多次 decompose 复用同一 Router（不重复创建）。"""
        router = _FakeRouter(output=_VALID_JSON)
        planner = LLMPlanner(router=router)

        planner.decompose(Task.from_text("test1"))
        planner.decompose(Task.from_text("test2"))

        # 两次调用都走同一 Router
        assert router.execute_count == 2


class TestLLMPlannerEdgeCases:
    """LLMPlanner 边界场景。"""

    def test_single_step_task(self):
        """单步任务（LLM 返回单元素数组）→ 仍生成单步 Plan。"""
        single = json.dumps([{"content": "just one step"}])
        router = _FakeRouter(output=single)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("single"))
        assert len(plan.steps) == 1
        assert plan.steps[0].content == "just one step"

    def test_missing_capabilities_field(self):
        """LLM 缺 capabilities 字段 → 默认补 general.chat。"""
        no_caps = json.dumps([{"content": "step a"}])
        router = _FakeRouter(output=no_caps)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("test"))
        assert plan.steps[0].capabilities == ["general.chat"]

    def test_whitespace_only_output(self):
        """LLM 返回纯空白 → 降级。"""
        router = _FakeRouter(output="   \n  \t  ")
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("hello then world"))
        assert plan.metadata.get("planner") == "rule_based"

    def test_partial_json_extraction(self):
        """LLM 返回的 JSON 数组前后有噪声 → 提取数组部分。"""
        noisy = 'Sure! Here is the plan:\n[{"content": "step a"}]\nHope it helps!'
        router = _FakeRouter(output=noisy)
        planner = LLMPlanner(router=router)

        plan = planner.decompose(Task.from_text("test"))
        assert len(plan.steps) == 1
        assert plan.steps[0].content == "step a"
