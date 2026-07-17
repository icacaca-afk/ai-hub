# Tests for Planner (V0.9.0)
#
# 覆盖：
# - RuleBasedPlanner 分解（中英文关键词 / 分号 / 换行 / 单步退化）
# - Plan / Step 数据结构与 to_dict
# - PlanExecutor 顺序执行 + 聚合（success / failed / partial）
# - artifacts 合并去重
# - 组合 Router 架构约束（Core Freeze 回归）
#
# ADR-0013: V0.9.0 骨架测试，不依赖真实 Provider。

import pytest
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.result import Result
from core.task import Task
from planner.plan import Plan, Step
from planner.base import Planner
from planner.rule_based_planner import RuleBasedPlanner
from planner.executor import PlanExecutor


# ── Test Fixtures ──

class FakeRouter:
    """测试用 Fake Router，不依赖真实 Provider。

    按 content 关键词匹配返回预设 Result，用于隔离测试 PlanExecutor 聚合逻辑。
    """

    def __init__(self, results=None, default=None):
        # content 关键词 → Result 映射
        self.results = results or {}
        self.default = default
        self.calls: list[Task] = []

    def execute(self, task: Task) -> Result:
        self.calls.append(task)
        for key, result in self.results.items():
            if key in task.content:
                return result
        if self.default is not None:
            return self.default
        return Result(
            provider="fake",
            status="success",
            output=f"ok: {task.content}",
        )


# ── RuleBasedPlanner 分解测试 ──

class TestRuleBasedPlanner:
    """RuleBasedPlanner 启发式分解测试。"""

    def setup_method(self):
        self.planner = RuleBasedPlanner()

    def test_single_step_no_split(self):
        """不可切分的内容 → 单步 Plan（退化）。"""
        task = Task.from_text("你好")
        plan = self.planner.decompose(task)

        assert plan.step_count == 1
        assert plan.steps[0].step_id == "step-0"
        assert plan.steps[0].content == "你好"
        assert plan.steps[0].depends_on == []

    def test_split_chinese_keywords(self):
        """中文连接关键词切分：然后 / 接着 / 最后。"""
        task = Task.from_text("总结文档然后翻译成英文最后发邮件")
        plan = self.planner.decompose(task)

        assert plan.step_count == 3
        assert plan.steps[0].content == "总结文档"
        assert plan.steps[1].content == "翻译成英文"
        assert plan.steps[2].content == "发邮件"

    def test_split_chinese_semicolon(self):
        """中文分号切分。"""
        task = Task.from_text("写代码；测试代码")
        plan = self.planner.decompose(task)

        assert plan.step_count == 2
        assert plan.steps[0].content == "写代码"
        assert plan.steps[1].content == "测试代码"

    def test_split_english_semicolon(self):
        """英文分号切分。"""
        task = Task.from_text("write code; test code")
        plan = self.planner.decompose(task)

        assert plan.step_count == 2
        assert plan.steps[0].content == "write code"
        assert plan.steps[1].content == "test code"

    def test_split_newline(self):
        """换行切分。"""
        task = Task.from_text("第一步\n第二步\n第三步")
        plan = self.planner.decompose(task)

        assert plan.step_count == 3
        assert plan.steps[0].content == "第一步"
        assert plan.steps[1].content == "第二步"
        assert plan.steps[2].content == "第三步"

    def test_split_english_keywords(self):
        """英文连接关键词切分：then / finally。"""
        task = Task.from_text("search the web then summarize finally send email")
        plan = self.planner.decompose(task)

        assert plan.step_count == 3
        assert plan.steps[0].content == "search the web"
        assert plan.steps[1].content == "summarize"
        assert plan.steps[2].content == "send email"

    def test_capabilities_per_step(self):
        """每个 Step 独立识别 capabilities。"""
        task = Task.from_text("写代码然后搜索网络")
        plan = self.planner.decompose(task)

        assert "code.generate" in plan.steps[0].capabilities
        assert "search.web" in plan.steps[1].capabilities

    def test_depends_on_linear_chain(self):
        """depends_on 默认线性链式：step[i] 依赖 step[i-1]。"""
        task = Task.from_text("第一步然后第二步然后第三步")
        plan = self.planner.decompose(task)

        assert plan.steps[0].depends_on == []
        assert plan.steps[1].depends_on == ["step-0"]
        assert plan.steps[2].depends_on == ["step-1"]

    def test_step_ids_sequential(self):
        """step_id 形如 step-0, step-1, ..."""
        task = Task.from_text("a然后b然后c然后d")
        plan = self.planner.decompose(task)

        for i, step in enumerate(plan.steps):
            assert step.step_id == f"step-{i}"

    def test_plan_metadata(self):
        """Plan.metadata 记录 planner 类型和版本。"""
        task = Task.from_text("hello")
        plan = self.planner.decompose(task)

        assert plan.metadata["planner"] == "rule_based"
        assert plan.metadata["version"] == "0.9.0"

    def test_plan_preserves_task_id(self):
        """Plan.task_id 关联原 Task.task_id。"""
        task = Task.from_text("hello")
        plan = self.planner.decompose(task)

        assert plan.task_id == task.task_id

    def test_plan_has_id_and_timestamp(self):
        """Plan 有 plan_id 和 created_at。"""
        task = Task.from_text("hello")
        plan = self.planner.decompose(task)

        assert len(plan.plan_id) > 0
        assert len(plan.created_at) > 0

    def test_empty_content_defensive(self):
        """空 content 防御：返回单步 Plan。"""
        task = Task(content="", capabilities=["general.chat"])
        plan = self.planner.decompose(task)

        assert plan.step_count == 1
        assert plan.steps[0].status == "pending"

    def test_whitespace_only_segments_dropped(self):
        """纯空白段被丢弃。"""
        task = Task.from_text("第一步\n\n\n第二步")
        plan = self.planner.decompose(task)

        assert plan.step_count == 2
        assert plan.steps[0].content == "第一步"
        assert plan.steps[1].content == "第二步"


# ── Plan / Step 数据结构测试 ──

class TestPlanStepDataclass:
    """Plan / Step dataclass 测试。"""

    def test_step_defaults(self):
        """Step 默认值。"""
        step = Step(step_id="step-0", content="hello")
        assert step.capabilities == []
        assert step.depends_on == []
        assert step.context == {}
        assert step.status == "pending"
        assert step.execution_result is None

    def test_step_to_dict(self):
        """Step.to_dict()。"""
        step = Step(step_id="step-0", content="hello", capabilities=["general.chat"])
        d = step.to_dict()

        assert d["step_id"] == "step-0"
        assert d["content"] == "hello"
        assert d["capabilities"] == ["general.chat"]
        assert d["status"] == "pending"
        assert d["execution_result"] is None

    def test_step_to_dict_with_result(self):
        """Step.to_dict() 带 Result。"""
        result = Result(provider="fake", status="success", output="ok")
        step = Step(step_id="step-0", content="hello", execution_result=result)
        d = step.to_dict()

        assert d["execution_result"] is not None
        assert d["execution_result"]["provider"] == "fake"

    def test_plan_to_dict(self):
        """Plan.to_dict()。"""
        steps = [Step(step_id="step-0", content="a"), Step(step_id="step-1", content="b")]
        plan = Plan(plan_id="p1", task_id="t1", steps=steps)
        d = plan.to_dict()

        assert d["plan_id"] == "p1"
        assert d["task_id"] == "t1"
        assert len(d["steps"]) == 2
        assert d["status"] == "pending"

    def test_plan_step_count(self):
        """Plan.step_count 属性。"""
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[Step(step_id="step-0", content="a")],
        )
        assert plan.step_count == 1


# ── PlanExecutor 聚合测试 ──

class TestPlanExecutor:
    """PlanExecutor 顺序执行 + 聚合测试。"""

    def test_all_success(self):
        """全 success → Plan status=success，Result status=success。"""
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="done"
        ))
        executor = PlanExecutor(router=router)
        task = Task.from_text("第一步然后第二步")

        result = executor.execute(task)

        assert result.status == "success"
        assert result.is_success
        assert result.provider == "planner"
        assert "done" in result.output
        assert result.metadata["plan"]["steps"] == 2
        assert result.metadata["plan"]["success"] == 2
        assert result.metadata["plan"]["failed"] == 0
        assert result.metadata["plan"]["status"] == "success"
        assert result.metadata["runtime"]["planner"] == "RuleBasedPlanner"
        # V0.9.3 (ADR-0016): metadata 顶层 schema_version
        assert result.metadata["schema_version"] == "1"

    def test_all_failed(self):
        """全 failed → Plan status=failed，Result status=failed。"""
        router = FakeRouter(default=Result(
            provider="fake", status="failed", output="", error="boom"
        ))
        executor = PlanExecutor(router=router)
        task = Task.from_text("第一步然后第二步")

        result = executor.execute(task)

        assert result.status == "failed"
        assert not result.is_success
        assert result.metadata["plan"]["failed"] == 2
        assert result.metadata["plan"]["success"] == 0
        assert result.metadata["plan"]["status"] == "failed"
        assert result.error is not None

    def test_mixed_partial(self):
        """混合（部分成功部分失败）→ partial。"""
        router = FakeRouter(results={
            "第一步": Result(provider="fake", status="success", output="ok1"),
            "第二步": Result(provider="fake", status="failed", output="", error="fail"),
        })
        executor = PlanExecutor(router=router)
        task = Task.from_text("第一步然后第二步")

        result = executor.execute(task)

        assert result.status == "partial"
        assert result.metadata["plan"]["success"] == 1
        assert result.metadata["plan"]["failed"] == 1
        assert result.metadata["plan"]["status"] == "partial"

    def test_single_step_equivalent_to_router(self):
        """单步 Plan 等价于直接走 Router（退化场景）。"""
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="hello back"
        ))
        executor = PlanExecutor(router=router)
        task = Task.from_text("你好")  # 不可切分

        result = executor.execute(task)

        assert result.status == "success"
        assert result.metadata["plan"]["steps"] == 1
        assert "hello back" in result.output
        assert len(router.calls) == 1

    def test_artifacts_merge_dedup(self):
        """artifacts 合并去重保序。"""
        router = FakeRouter(results={
            "第一步": Result(
                provider="fake", status="success",
                output="ok1", artifacts=["a.txt", "b.txt"]
            ),
            "第二步": Result(
                provider="fake", status="success",
                output="ok2", artifacts=["b.txt", "c.txt"]
            ),
        })
        executor = PlanExecutor(router=router)
        task = Task.from_text("第一步然后第二步")

        result = executor.execute(task)

        # 去重后：a.txt, b.txt, c.txt（b.txt 不重复）
        assert result.artifacts == ["a.txt", "b.txt", "c.txt"]

    def test_last_plan_set(self):
        """执行后 last_plan 被设置。"""
        router = FakeRouter()
        executor = PlanExecutor(router=router)

        assert executor.last_plan is None

        task = Task.from_text("第一步然后第二步")
        executor.execute(task)

        assert executor.last_plan is not None
        assert executor.last_plan.step_count == 2
        assert executor.last_plan.status == "success"

    def test_output_has_step_headers(self):
        """聚合 output 包含 [Step i: content] header。"""
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="done"
        ))
        executor = PlanExecutor(router=router)
        task = Task.from_text("写代码然后测试")

        result = executor.execute(task)

        assert "[Step 0:" in result.output
        assert "[Step 1:" in result.output

    def test_custom_planner_injected(self):
        """可注入自定义 Planner。"""
        class SingleStepPlanner(Planner):
            def decompose(self, task):
                return Plan(
                    plan_id="custom",
                    task_id=task.task_id,
                    steps=[Step(step_id="step-0", content=task.content,
                                capabilities=task.capabilities)],
                )

        router = FakeRouter()
        executor = PlanExecutor(router=router, planner=SingleStepPlanner())
        task = Task.from_text("任意内容然后更多内容")

        result = executor.execute(task)

        # 自定义 planner 不切分，只有 1 步
        assert result.metadata["plan"]["steps"] == 1
        # 自定义 planner 类名应反映在 runtime.planner
        assert result.metadata["runtime"]["planner"] == "SingleStepPlanner"
        assert executor.last_plan.plan_id == "custom"

    def test_step_status_updated(self):
        """执行后每个 step.status 被更新。"""
        router = FakeRouter(results={
            "成功步": Result(provider="fake", status="success", output="ok"),
            "失败步": Result(provider="fake", status="failed", output="", error="err"),
        })
        executor = PlanExecutor(router=router)
        task = Task.from_text("成功步然后失败步")

        executor.execute(task)

        steps = executor.last_plan.steps
        assert steps[0].status == "success"
        assert steps[1].status == "failed"
        assert steps[0].execution_result is not None
        assert steps[1].execution_result is not None

    def test_context_merged(self):
        """子 Task 的 context 合并了原 Task context 和 step context。"""
        router = FakeRouter()
        executor = PlanExecutor(router=router)
        task = Task.from_text("第一步然后第二步")
        task.context["user_id"] = "u123"

        executor.execute(task)

        # 检查 router 收到的 sub_task 带有原 context
        assert all(t.context.get("user_id") == "u123" for t in router.calls)


# ── Core Freeze 架构约束回归 ──

class TestCoreFreezeConstraint:
    """ADR-0008 Core Freeze + ADR-0013 架构约束回归。

    验证 PlanExecutor 通过组合（has-a）而非继承（is-a）持有 Router，
    确保不破坏冻结的 Router 接口。
    """

    def test_plan_executor_composes_router_not_inherits(self):
        """PlanExecutor 必须组合 Router，不能继承（保持 Core Freeze）。"""
        from router.router import Router

        router = FakeRouter()
        executor = PlanExecutor(router=router)

        # 组合而非继承
        assert not isinstance(executor, Router)
        # 通过组合持有 router 引用
        assert executor.router is router

    def test_planner_does_not_inherit_task(self):
        """Step 不继承 Task（避免污染冻结的 Task 抽象）。"""
        from core.task import Task

        step = Step(step_id="step-0", content="hello")
        assert not isinstance(step, Task)

    def test_planner_module_imports_cleanly(self):
        """planner 包可独立导入，不触发 core 修改。"""
        import planner
        assert hasattr(planner, "PlanExecutor")
        assert hasattr(planner, "RuleBasedPlanner")
        assert hasattr(planner, "Plan")
        assert hasattr(planner, "Step")
        assert hasattr(planner, "Planner")

    def test_planner_abc_cannot_instantiate(self):
        """Planner ABC 不能直接实例化。"""
        with pytest.raises(TypeError):
            Planner()


# ── V0.9.3: schema_version + PlanStore 集成 ──

class TestSchemaVersionContract:
    """V0.9.3 (ADR-0016): metadata.schema_version 契约。"""

    def test_schema_version_present_all_status(self):
        """success / failed / partial 三种状态都带 schema_version='1'。"""
        cases = [
            (Result(provider="fake", status="success", output="ok"), "success"),
            (Result(provider="fake", status="failed", output="", error="x"), "failed"),
        ]
        for step_result, expected in cases:
            router = FakeRouter(default=step_result)
            executor = PlanExecutor(router=router)
            result = executor.execute(Task.from_text("第一步然后第二步"))

            assert result.metadata["schema_version"] == "1", f"case={expected}"
            assert result.metadata["plan"]["status"] == expected

    def test_schema_version_is_top_level(self):
        """schema_version 位于 metadata 顶层（不嵌套在 plan/runtime 下）。"""
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="ok"
        ))
        executor = PlanExecutor(router=router)
        result = executor.execute(Task.from_text("hello"))

        meta = result.metadata
        assert "schema_version" in meta
        # 不在 plan 子键
        assert "schema_version" not in meta["plan"]
        # 不在 runtime 子键
        assert "schema_version" not in meta["runtime"]

    def test_schema_version_does_not_break_existing_keys(self):
        """schema_version 引入不应破坏现有 metadata 字段（ADR-0014 兼容）。"""
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="ok"
        ))
        executor = PlanExecutor(router=router)
        result = executor.execute(Task.from_text("hello"))

        # 现有字段（ADR-0014）必须保留
        assert "plan_id" in result.metadata
        assert "task_id" in result.metadata
        assert "plan" in result.metadata
        assert "runtime" in result.metadata
        # 新字段（V0.9.3）
        assert "schema_version" in result.metadata


class TestPlanStoreIntegration:
    """V0.9.3 (ADR-0016): PlanExecutor 与 PlanStore 集成。"""

    def test_executor_saves_plan_when_store_provided(self):
        """传入 plan_store 后，execute 完成自动 save。"""
        from planner.plan_store import PlanStore

        store = PlanStore(max_size=5)
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="ok"
        ))
        executor = PlanExecutor(router=router, plan_store=store)
        task = Task.from_text("第一步然后第二步")

        # 初始：store 空
        assert store.size == 0

        executor.execute(task)

        # 执行后：store 收到一个 plan
        assert store.size == 1
        saved = store.list_recent(limit=1)[0]
        assert saved.step_count == 2
        assert saved.status == "success"
        assert saved.task_id == task.task_id

    def test_executor_without_store_works_normally(self):
        """不传 plan_store 时向后兼容（不 save）。"""
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="ok"
        ))
        executor = PlanExecutor(router=router)  # 不传 plan_store
        task = Task.from_text("hello")

        # 不应抛异常
        result = executor.execute(task)
        assert result.status == "success"
        # plan_store 默认为 None
        assert executor.plan_store is None

    def test_each_execute_call_saves_one_plan(self):
        """多次 execute → store 中累积多个 plan。"""
        from planner.plan_store import PlanStore

        store = PlanStore(max_size=10)
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="ok"
        ))
        executor = PlanExecutor(router=router, plan_store=store)

        executor.execute(Task.from_text("task-1"))
        executor.execute(Task.from_text("task-2"))
        executor.execute(Task.from_text("task-3"))

        assert store.size == 3
        recent = store.list_recent(limit=3)
        # 最近在前
        assert recent[0].task_id != recent[-1].task_id

    def test_plan_store_respects_max_size(self):
        """PlanStore 在 PlanExecutor 中尊重 max_size 限制。"""
        from planner.plan_store import PlanStore

        store = PlanStore(max_size=2)
        router = FakeRouter(default=Result(
            provider="fake", status="success", output="ok"
        ))
        executor = PlanExecutor(router=router, plan_store=store)

        executor.execute(Task.from_text("t-1"))
        executor.execute(Task.from_text("t-2"))
        executor.execute(Task.from_text("t-3"))  # 触发弹出

        assert store.size == 2  # 不是 3

    def test_failed_plan_also_saved(self):
        """失败的 plan 也被保存（V0.9.3 不区分 status，失败案例也要可查）。"""
        from planner.plan_store import PlanStore

        store = PlanStore(max_size=5)
        router = FakeRouter(default=Result(
            provider="fake", status="failed", output="", error="boom"
        ))
        executor = PlanExecutor(router=router, plan_store=store)
        executor.execute(Task.from_text("hello"))

        assert store.size == 1
        saved = store.list_recent(limit=1)[0]
        assert saved.status == "failed"
