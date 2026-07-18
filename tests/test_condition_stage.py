# Tests for ConditionStage (V1.0.4)
#
# ADR-0024 V1.0.4: ConditionStage (Pipeline Workflow Control)
# ChatGPT 外部审核: 9.9/10 APPROVED
# 关键采纳 1 项: Checkpoint 总是写 (移除 ctx.stop 短路, 增加 aborted/stopped_by)
# 非阻塞采纳 4 项: skip/abort 语义 / condition_name / deterministic / 核心原则
#
# 覆盖:
# - ConditionEval: 构造 / 序列化 / 关键字段
# - ConditionStage: 成功/失败/无 condition/短路/参数校验
# - 三个动作: continue / skip / abort (语义差异)
# - 失败处理: condition 异常 fail-closed / Stage 异常 Best Effort
# - 集成: Stage 顺序 / metadata 跨 stage 传递 / 终止后 Checkpoint 仍写
# - ChatGPT 边界: condition_name / metadata 覆盖 / aborted 传递

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.bridge import BridgeResult, FakeBridge
from core.provider import Provider, ProviderMetadata
from core.task import Task
from core.health import HealthReport
from router.router import Router
from planner.execution_event import ExecutionEvent
from planner.execution_store import ExecutionStore
from planner.sqlite_execution_store import SQLiteExecutionStore
from planner.pipeline import (
    ExecutionContext,
    ExecutionPipeline,
    RouteStage,
    MetricsStage,
    default_pipeline,
)
from planner.stages import (
    CheckpointStage,
    CheckpointSnapshot,
    ConditionStage,
    ConditionEval,
    VALID_ACTIONS,
)


# ── Test Fixtures ──

class FakeProvider(Provider):
    """Test Provider."""

    def __init__(self, name, bridge=None):
        self.metadata = ProviderMetadata(
            name=name,
            display_name=name.title(),
            description=f"Test provider {name}",
            capabilities=["code.generate"],
            priority=50,
            fallback=[],
            quota_total=None,
        )
        self._bridge = bridge or FakeBridge()

    def health(self):
        return HealthReport.healthy(self.metadata.name)

    def authenticated(self):
        return True

    def quota_left(self):
        return -1

    def select_bridge(self, task: Task):
        return self._bridge

    def execute(self, task):
        return self._bridge.run(task)


class FakeRouter(Router):
    """Test Router."""

    def __init__(self, provider):
        self._provider = provider

    def route(self, task: Task):
        return self._provider

    def execute(self, task: Task):
        return self._provider.execute(task)


def make_task(content="test", task_id="t1", capabilities=None):
    return Task(
        task_id=task_id,
        content=content,
        capabilities=capabilities or ["code.generate"],
    )


def make_success_br(output="ok", duration_ms=10):
    return BridgeResult(success=True, output=output, duration_ms=duration_ms)


def make_failure_br(error="network timeout", duration_ms=10):
    return BridgeResult(success=False, output="", error=error, duration_ms=duration_ms)


def make_ctx(task=None, br=None, stop=False):
    """构造标准 ctx 用于 ConditionStage 测试."""
    return ExecutionContext(
        task=task or make_task(),
        provider=FakeProvider("p1"),
        bridge=FakeBridge(),
        bridge_result=br or make_success_br(),
        stop=stop,
    )


# ── TestConditionEval (3) ──

class TestConditionEval:
    """ConditionEval 审计元数据 (V1.0.4)."""

    def test_construction(self):
        """构造 ConditionEval 实例."""
        eval_obj = ConditionEval(
            stage="condition",
            condition_name="on_failure",
            result=True,
            action="abort",
            timestamp=1234567890.0,
            stopped_by="condition:on_failure:abort",
        )
        assert eval_obj.condition_name == "on_failure"
        assert eval_obj.result is True
        assert eval_obj.action == "abort"
        assert eval_obj.stopped_by == "condition:on_failure:abort"

    def test_to_dict_round_trip(self):
        """to_dict 序列化 -> 字段完整."""
        eval_obj = ConditionEval(
            stage="condition",
            condition_name="test",
            result=False,
            action="continue",
            timestamp=1234567890.0,
            stopped_by=None,
        )
        d = eval_obj.to_dict()
        assert d["stage"] == "condition"
        assert d["condition_name"] == "test"
        assert d["result"] is False
        assert d["action"] == "continue"
        assert d["stopped_by"] is None

    def test_stopped_by_optional(self):
        """stopped_by 可空 (continue 时)."""
        eval_obj = ConditionEval(
            stage="condition",
            condition_name="c",
            result=True,
            action="continue",  # continue -> stopped_by=None
            timestamp=0.0,
            stopped_by=None,
        )
        assert eval_obj.stopped_by is None


# ── TestConditionStageBasics (5) ──

class TestConditionStageBasics:
    """ConditionStage 基本行为."""

    def test_init_requires_condition(self):
        """缺 condition -> ValueError."""
        with pytest.raises(ValueError, match="non-None condition"):
            ConditionStage(condition=None)

    def test_init_invalid_on_true(self):
        """on_true 非法 -> ValueError."""
        with pytest.raises(ValueError, match="on_true must be one of"):
            ConditionStage(condition=lambda c: True, on_true="invalid")

    def test_init_invalid_on_false(self):
        """on_false 非法 -> ValueError."""
        with pytest.raises(ValueError, match="on_false must be one of"):
            ConditionStage(condition=lambda c: True, on_false="invalid")

    def test_name_property_default(self):
        """name 默认 'condition'."""
        stage = ConditionStage(condition=lambda c: True)
        assert stage.name == "condition"

    def test_name_property_custom(self):
        """name 可自定义."""
        stage = ConditionStage(condition=lambda c: True, name="on_failure")
        assert stage.name == "on_failure"


# ── TestConditionStageShortCircuit (3) ──

class TestConditionStageShortCircuit:
    """短路条件: task=None / bridge_result=None."""

    def test_short_circuit_on_no_task(self):
        """ctx.task=None -> pass (不调 condition)."""
        called = []

        def cond(ctx):
            called.append(ctx)
            return True

        stage = ConditionStage(condition=cond, on_true="abort")
        ctx = ExecutionContext(
            task=None,
            provider=FakeProvider("p1"),
            bridge=FakeBridge(),
            bridge_result=make_success_br(),
        )
        new_ctx = stage(ctx)
        assert new_ctx is ctx
        assert new_ctx.stop is False
        assert called == []  # condition 未调用

    def test_short_circuit_on_no_bridge_result(self):
        """ctx.bridge_result=None -> pass."""
        called = []

        def cond(ctx):
            called.append(ctx)
            return True

        stage = ConditionStage(condition=cond, on_true="abort")
        ctx = ExecutionContext(
            task=make_task(),
            provider=FakeProvider("p1"),
            bridge=FakeBridge(),
            bridge_result=None,
        )
        new_ctx = stage(ctx)
        assert new_ctx is ctx
        assert new_ctx.stop is False
        assert called == []

    def test_does_not_short_circuit_on_stop(self):
        """V1.0.4: 不短路 ctx.stop (ChatGPT 9.9/10 Q4 关键采纳).

        即使 ctx.stop=True 也要重新求值 condition.
        这与 V1.0.3 CheckpointStage 行为一致 (Checkpoint 总是写).
        """
        called = []

        def cond(ctx):
            called.append(ctx)
            return True

        stage = ConditionStage(condition=cond, on_true="abort")
        ctx = make_ctx(stop=True)
        new_ctx = stage(ctx)
        # condition 被调用
        assert len(called) == 1
        # 因为 condition=True, on_true="abort" -> ctx.stop=True (保持)
        assert new_ctx.stop is True


# ── TestConditionStageActions (6) ──

class TestConditionStageActions:
    """三个动作: continue / skip / abort."""

    def test_condition_true_continue(self):
        """condition=True, on_true='continue' -> ctx 保持."""
        stage = ConditionStage(
            condition=lambda c: True,
            on_true="continue",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        assert new_ctx.stop is False
        assert new_ctx.metadata["condition_eval"]["result"] is True
        assert new_ctx.metadata["condition_eval"]["action"] == "continue"

    def test_condition_false_continue(self):
        """condition=False, on_false='continue' -> ctx 保持."""
        stage = ConditionStage(
            condition=lambda c: False,
            on_false="continue",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        assert new_ctx.stop is False
        assert new_ctx.metadata["condition_eval"]["result"] is False
        assert new_ctx.metadata["condition_eval"]["action"] == "continue"

    def test_condition_true_skip(self):
        """condition=True, on_true='skip' -> ctx.stop=True + stopped_by='condition:NAME:skip'."""
        stage = ConditionStage(
            condition=lambda c: True,
            on_true="skip",
            name="on_success",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        assert new_ctx.stop is True
        assert new_ctx.metadata["condition_eval"]["action"] == "skip"
        assert new_ctx.metadata["condition_eval"]["stopped_by"] == "condition:on_success:skip"

    def test_condition_false_skip(self):
        """condition=False, on_false='skip' -> ctx.stop=True."""
        stage = ConditionStage(
            condition=lambda c: False,
            on_false="skip",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        assert new_ctx.stop is True
        assert new_ctx.metadata["condition_eval"]["stopped_by"] == "condition:condition:skip"

    def test_condition_true_abort(self):
        """condition=True, on_true='abort' -> ctx.stop=True + stopped_by='condition:NAME:abort'."""
        stage = ConditionStage(
            condition=lambda c: True,
            on_true="abort",
            name="on_failure",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        assert new_ctx.stop is True
        assert new_ctx.metadata["condition_eval"]["action"] == "abort"
        assert new_ctx.metadata["condition_eval"]["stopped_by"] == "condition:on_failure:abort"

    def test_skip_vs_abort_stopped_by_differs(self):
        """ChatGPT 9.9/10 Q3 关键: skip 和 abort 的 stopped_by 不同."""
        stage_skip = ConditionStage(
            condition=lambda c: True, on_true="skip", name="c"
        )
        stage_abort = ConditionStage(
            condition=lambda c: True, on_true="abort", name="c"
        )
        # 用两个 fresh ctx, 避免 metadata 共享
        ctx1 = make_ctx(task=make_task(task_id="t1"))
        ctx2 = make_ctx(task=make_task(task_id="t2"))

        ctx_skip = stage_skip(ctx1)
        ctx_abort = stage_abort(ctx2)

        assert ctx_skip.metadata["condition_eval"]["stopped_by"] == "condition:c:skip"
        assert ctx_abort.metadata["condition_eval"]["stopped_by"] == "condition:c:abort"
        assert ctx_skip.metadata["condition_eval"]["stopped_by"] != \
               ctx_abort.metadata["condition_eval"]["stopped_by"]


# ── TestConditionStageFailureHandling (3) ──

class TestConditionStageFailureHandling:
    """失败处理: condition 异常 fail-closed, Stage 异常 Best Effort."""

    def test_condition_exception_fail_closed(self):
        """condition 抛异常 -> 视为 False -> 继续执行."""
        def bad_condition(ctx):
            raise RuntimeError("condition broken")

        stage = ConditionStage(
            condition=bad_condition,
            on_true="abort",
            on_false="skip",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        # 视为 False -> on_false=skip -> ctx.stop=True
        assert new_ctx.stop is True
        assert new_ctx.metadata["condition_eval"]["result"] is False
        assert new_ctx.metadata["condition_eval"]["action"] == "skip"

    def test_condition_exception_continues_when_on_false_continue(self):
        """condition 异常 + on_false='continue' -> ctx.stop=False."""
        def bad_condition(ctx):
            raise RuntimeError("oops")

        stage = ConditionStage(
            condition=bad_condition,
            on_false="continue",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        assert new_ctx.stop is False
        assert new_ctx.metadata["condition_eval"]["result"] is False

    def test_condition_result_coerced_to_bool(self):
        """condition 返回非 bool -> 强制转换为 bool."""
        stage = ConditionStage(
            condition=lambda c: 1,  # truthy
            on_true="abort",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        # truthy -> True
        assert new_ctx.stop is True
        assert new_ctx.metadata["condition_eval"]["result"] is True


# ── TestConditionStageChatGPTEdgeCases (5) ──

class TestConditionStageChatGPTEdgeCases:
    """ChatGPT 9.9/10 采纳的 5 个边界测试."""

    def test_condition_name_in_metadata(self):
        """ChatGPT 9.9/10 Q6 采纳: condition_name 注入 metadata."""
        stage = ConditionStage(
            condition=lambda c: True,
            on_true="abort",
            name="my_special_condition",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        assert new_ctx.metadata["condition_eval"]["condition_name"] == "my_special_condition"

    def test_metadata_overwrite_on_repeat(self):
        """ChatGPT 9.9/10 Q8 采纳: 连续 Condition 求值 -> metadata 覆盖 (不追加)."""
        stage = ConditionStage(
            condition=lambda c: True,
            on_true="abort",
            name="c1",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        # 再跑一次 (不同 name)
        stage2 = ConditionStage(
            condition=lambda c: True,
            on_true="skip",
            name="c2",
        )
        new_ctx2 = stage2(new_ctx)
        # metadata.condition_eval 被覆盖 (不是追加)
        assert new_ctx2.metadata["condition_eval"]["condition_name"] == "c2"
        assert new_ctx2.metadata["condition_eval"]["action"] == "skip"

    def test_condition_does_not_modify_task(self):
        """Condition MUST NOT 修改 ctx.task."""
        original_task = make_task(task_id="ck-original")
        stage = ConditionStage(
            condition=lambda c: True,
            on_true="abort",
        )
        ctx = ExecutionContext(
            task=original_task,
            provider=FakeProvider("p1"),
            bridge=FakeBridge(),
            bridge_result=make_success_br(),
        )
        new_ctx = stage(ctx)
        # task 不变
        assert new_ctx.task is original_task
        assert new_ctx.task.task_id == "ck-original"

    def test_condition_does_not_modify_bridge_result(self):
        """Condition MUST NOT 修改 ctx.bridge_result."""
        original_br = make_success_br(output="original output")
        stage = ConditionStage(
            condition=lambda c: True,
            on_true="abort",
        )
        ctx = ExecutionContext(
            task=make_task(),
            provider=FakeProvider("p1"),
            bridge=FakeBridge(),
            bridge_result=original_br,
        )
        new_ctx = stage(ctx)
        # bridge_result 不变
        assert new_ctx.bridge_result is original_br
        assert new_ctx.bridge_result.output == "original output"

    def test_metadata_written_only_once_per_call(self):
        """每次 __call__ 只写一次 metadata.condition_eval."""
        stage = ConditionStage(
            condition=lambda c: True,
            on_true="abort",
        )
        ctx = make_ctx()
        new_ctx = stage(ctx)
        # metadata.condition_eval 是一个 dict
        assert isinstance(new_ctx.metadata["condition_eval"], dict)
        # 不应该有 list 形式的多次记录
        assert "history" not in new_ctx.metadata["condition_eval"]


# ── TestConditionStagePipelineIntegration (5) ──

class TestConditionStagePipelineIntegration:
    """Pipeline 集成测试."""

    def test_default_pipeline_requires_condition(self):
        """default_pipeline(include_condition=True) 缺 condition -> ValueError."""
        bridge = FakeBridge()
        provider = FakeProvider("p1", bridge=bridge)
        router = FakeRouter(provider)
        with pytest.raises(ValueError, match="requires condition"):
            default_pipeline(router, include_condition=True, condition=None)

    def test_pipeline_with_condition_continue(self):
        """condition=True (continue) -> Pipeline 完整执行."""
        bridge = FakeBridge()
        provider = FakeProvider("p1", bridge=bridge)
        router = FakeRouter(provider)
        pipeline = default_pipeline(
            router,
            include_condition=True,
            condition=lambda c: True,  # 总是 True -> continue
        )
        task = make_task(task_id="ck-cont")
        result = pipeline.run(task)
        assert result.status == "success"

    def test_pipeline_with_condition_abort(self):
        """condition=True (abort) -> Pipeline 终止, 但 Checkpoint 仍写 (V1.0.4 关键)."""
        from planner.stages.checkpoint_stage import CheckpointStage

        class InMemoryStore(ExecutionStore):
            def __init__(self):
                self.events = []
            def append(self, event):
                self.events.append(event)
            def query_events(self, plan_id):
                return [e for e in self.events if e.plan_id == plan_id]

        store = InMemoryStore()
        bridge = FakeBridge()
        provider = FakeProvider("p1", bridge=bridge)
        router = FakeRouter(provider)
        pipeline = default_pipeline(
            router,
            include_condition=True,
            condition=lambda c: True,  # 总是 True
            condition_on_true="abort",
            include_checkpoint=True,
            execution_store=store,
        )
        task = make_task(task_id="ck-abort")
        result = pipeline.run(task)
        # Pipeline 终止后 result 仍可被 assemble
        # 关键: Checkpoint 仍写
        events = store.query_events(plan_id="ck-abort")
        assert len(events) == 1
        # Checkpoint 记录 aborted=True
        assert events[0].data["aborted"] is True
        assert events[0].data["stopped_by"] == "condition:condition:abort"

    def test_pipeline_with_condition_skip(self):
        """condition=True (skip) -> Pipeline 终止, stopped_by='condition:NAME:skip'."""
        class InMemoryStore(ExecutionStore):
            def __init__(self):
                self.events = []
            def append(self, event):
                self.events.append(event)
            def query_events(self, plan_id):
                return [e for e in self.events if e.plan_id == plan_id]

        store = InMemoryStore()
        bridge = FakeBridge()
        provider = FakeProvider("p1", bridge=bridge)
        router = FakeRouter(provider)
        pipeline = default_pipeline(
            router,
            include_condition=True,
            condition=lambda c: True,
            condition_on_true="skip",
            condition_name="my_skip",
            include_checkpoint=True,
            execution_store=store,
        )
        task = make_task(task_id="ck-skip")
        pipeline.run(task)
        events = store.query_events(plan_id="ck-skip")
        assert len(events) == 1
        assert events[0].data["stopped_by"] == "condition:my_skip:skip"

    def test_pipeline_with_condition_and_retry(self):
        """Retry + Condition 组合: 失败重试 N 次后 condition 终止."""
        from planner.stages.retry_stage import RetryStage

        # 简单测试: condition 检查 bridge_result.success
        bridge = FakeBridge()
        provider = FakeProvider("p1", bridge=bridge)
        router = FakeRouter(provider)
        pipeline = default_pipeline(
            router,
            include_retry=True,
            include_condition=True,
            condition=lambda c: c.bridge_result.success,  # 成功 -> continue
            condition_on_false="abort",  # 失败 -> abort
            condition_name="on_success",
        )
        task = make_task(task_id="ck-retry-cond")
        result = pipeline.run(task)
        # FakeBridge 默认成功 -> condition=True -> continue -> 成功
        assert result.status == "success"


# ── Test Fixtures: In-Memory ExecutionStore ──

# 移到 test 文件末尾, 避免 pytest 收集
class _InMemoryStoreHelper(ExecutionStore):
    """In-Memory ExecutionStore (辅助 fixture)."""
    def __init__(self):
        self.events = []
    def append(self, event):
        self.events.append(event)
    def query_events(self, plan_id):
        return [e for e in self.events if e.plan_id == plan_id]
