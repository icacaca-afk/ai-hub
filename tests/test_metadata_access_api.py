# AI Hub — Metadata Access API Tests (V1.0.8, ADR-0028 Accepted 9.91/10)
#
# 测试 5 getter + 5 has_xxx + 1 resolver (新增 RuntimeMetadata 接口层).
# 覆盖 ADR §6.1-6.4:
#   - 5 getter (return type / defensive copy / default values)
#   - 5 has_xxx (T2 Non-blocking 采纳)
#   - resolve_stop_reason (T1 命名一致 Non-blocking 采纳)
#   - resolve_stopped_by alias (backward compat)
#   - CheckpointStage 改用 resolver (净减 ~14 行)
#   - V1.0.7 API 100% 兼容

from __future__ import annotations

import pytest

from planner.pipeline import ExecutionContext
from planner.runtime_metadata import RuntimeMetadata
from planner.stages.condition_stage import ConditionEval
from planner.stages.checkpoint_stage import CheckpointSnapshot
from core.bridge import BridgeResult
from core.result import Result
from core.task import Task


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

def _make_task():
    return Task(task_id="t1", content="hello", capabilities=["chat"])


def _make_ctx():
    return ExecutionContext(task=_make_task())


def _make_bridge_result(success=True, output="ok", error=None):
    return BridgeResult(
        success=success,
        output=output,
        error=error,
        artifacts=[],
        duration_ms=10,
    )


# ─────────────────────────────────────────────────────────────
# TestGetters — 5 getter 单元测试 (15+)
# ─────────────────────────────────────────────────────────────

class TestGetStopReason:
    """get_stop_reason()"""

    def test_returns_top_level(self):
        rm = RuntimeMetadata()
        rm.stopped_by = "condition:c1:skip"
        assert rm.get_stop_reason() == "condition:c1:skip"

    def test_returns_none_when_not_set(self):
        rm = RuntimeMetadata()
        assert rm.get_stop_reason() is None


class TestGetMetrics:
    """get_metrics() — 返回 copy"""

    def test_returns_dict_copy(self):
        rm = RuntimeMetadata()
        rm.server_metrics["token_in"] = 100
        result = rm.get_metrics()
        assert result == {"token_in": 100}
        # 修改 result 不影响 runtime
        result["hacked"] = True
        assert "hacked" not in rm.server_metrics

    def test_returns_default_empty_dict(self):
        rm = RuntimeMetadata()
        result = rm.get_metrics()
        assert result == {}
        # 永远是 dict, never None
        assert isinstance(result, dict)


class TestGetCondition:
    """get_condition()"""

    def test_returns_condition_eval(self):
        rm = RuntimeMetadata()
        eval = ConditionEval(
            stage="condition", condition_name="c1", result=True,
            action="skip", timestamp=0.0, stopped_by="condition:c1:skip",
        )
        rm.condition_eval = eval
        assert rm.get_condition() is eval

    def test_returns_none_when_not_set(self):
        rm = RuntimeMetadata()
        assert rm.get_condition() is None


class TestGetPlanProgress:
    """get_plan_progress() — 返回 copy"""

    def test_returns_dict_copy(self):
        rm = RuntimeMetadata()
        rm.plan = {"success": 3, "failed": 1}
        result = rm.get_plan_progress()
        assert result == {"success": 3, "failed": 1}
        result["hacked"] = True
        assert "hacked" not in rm.plan

    def test_returns_default_empty_dict(self):
        rm = RuntimeMetadata()
        result = rm.get_plan_progress()
        assert result == {}
        assert isinstance(result, dict)


class TestGetCustom:
    """get_custom() — 返回引用 (允许 plugin 修改)"""

    def test_returns_plugin_data(self):
        rm = RuntimeMetadata()
        rm.custom["my_plugin"] = {"trace_id": "abc"}
        result = rm.get_custom("my_plugin")
        assert result == {"trace_id": "abc"}

    def test_returns_default_when_missing(self):
        rm = RuntimeMetadata()
        assert rm.get_custom("missing") is None
        assert rm.get_custom("missing", default={}) == {}

    def test_returns_reference_not_copy(self):
        """custom 返回引用 (与 metrics/plan 不同, 允许 plugin 修改)"""
        rm = RuntimeMetadata()
        original = {"v": 1}
        rm.custom["my_plugin"] = original
        result = rm.get_custom("my_plugin")
        # 修改 result 应影响 runtime (reference semantics)
        result["v"] = 999
        assert rm.custom["my_plugin"]["v"] == 999

    def test_getter_does_not_modify_runtime_metrics(self):
        """所有 getter 不修改 runtime 状态"""
        rm = RuntimeMetadata()
        rm.server_metrics = {"a": 1}
        rm.plan = {"x": 1}
        rm.condition_eval = ConditionEval(
            stage="c", condition_name="c", result=True,
            action="skip", timestamp=0.0, stopped_by="c",
        )
        # 调用所有 getter
        rm.get_stop_reason()
        rm.get_metrics()
        rm.get_condition()
        rm.get_plan_progress()
        # 状态不变
        assert rm.server_metrics == {"a": 1}
        assert rm.plan == {"x": 1}
        assert rm.condition_eval is not None


# ─────────────────────────────────────────────────────────────
# TestHasXxx — 5 has_xxx (T2 Non-blocking 采纳)
# ─────────────────────────────────────────────────────────────

class TestHasXxx:
    """has_xxx() — API Human Factor (ChatGPT 9.91/10 T2)"""

    def test_has_stop_reason(self):
        rm = RuntimeMetadata()
        assert rm.has_stop_reason() is False
        rm.stopped_by = "x"
        assert rm.has_stop_reason() is True

    def test_has_metrics(self):
        rm = RuntimeMetadata()
        assert rm.has_metrics() is False
        rm.server_metrics["a"] = 1
        assert rm.has_metrics() is True

    def test_has_metrics_empty_dict(self):
        """has_metrics: 空 dict 返回 False (bool({}) == False)"""
        rm = RuntimeMetadata()
        rm.server_metrics = {}
        assert rm.has_metrics() is False

    def test_has_condition(self):
        rm = RuntimeMetadata()
        assert rm.has_condition() is False
        rm.condition_eval = ConditionEval(
            stage="c", condition_name="c", result=True,
            action="skip", timestamp=0.0, stopped_by=None,
        )
        assert rm.has_condition() is True

    def test_has_plan_progress(self):
        rm = RuntimeMetadata()
        assert rm.has_plan_progress() is False
        rm.plan["success"] = 1
        assert rm.has_plan_progress() is True

    def test_has_custom(self):
        rm = RuntimeMetadata()
        assert rm.has_custom("my_plugin") is False
        rm.custom["my_plugin"] = {"x": 1}
        assert rm.has_custom("my_plugin") is True

    def test_has_custom_other_plugin(self):
        """has_custom 隔离: my_plugin 不影响 other_plugin"""
        rm = RuntimeMetadata()
        rm.custom["my_plugin"] = {"x": 1}
        assert rm.has_custom("my_plugin") is True
        assert rm.has_custom("other_plugin") is False


# ─────────────────────────────────────────────────────────────
# TestResolveStopReason — 6+ resolver 单元测试
# ─────────────────────────────────────────────────────────────

class TestResolveStopReason:
    """resolve_stop_reason() — 4 级优先级查找 (T1 命名一致)"""

    def test_priority_1_top_level_stopped_by(self):
        """优先级 1: runtime.stopped_by"""
        rm = RuntimeMetadata()
        rm.stopped_by = "retry:exhausted"
        ctx = _make_ctx()
        assert rm.resolve_stop_reason(ctx) == "retry:exhausted"

    def test_priority_2_condition_eval_stopped_by(self):
        """优先级 2: runtime.condition_eval.stopped_by"""
        rm = RuntimeMetadata()
        rm.condition_eval = ConditionEval(
            stage="condition", condition_name="c1", result=True,
            action="abort", timestamp=0.0, stopped_by="condition:c1:abort",
        )
        ctx = _make_ctx()
        assert rm.resolve_stop_reason(ctx) == "condition:c1:abort"

    def test_priority_3_metadata_dict_fallback(self):
        """优先级 3: ctx.metadata["condition_eval"] dict 兜底 (V1.0.6 兼容)"""
        rm = RuntimeMetadata()
        ctx = _make_ctx()
        ctx.metadata = {"condition_eval": {"stopped_by": "legacy:stop"}}
        assert rm.resolve_stop_reason(ctx) == "legacy:stop"

    def test_priority_4_stop_flag_fallback(self):
        """优先级 4: ctx.stop → 'stop_flag'"""
        rm = RuntimeMetadata()
        ctx = _make_ctx()
        ctx.stop = True
        assert rm.resolve_stop_reason(ctx) == "stop_flag"

    def test_returns_none_when_no_stop(self):
        """未停止返回 None"""
        rm = RuntimeMetadata()
        ctx = _make_ctx()
        ctx.stop = False
        assert rm.resolve_stop_reason(ctx) is None

    def test_priority_order_top_wins(self):
        """优先级 1 > 2 > 3 > 4"""
        rm = RuntimeMetadata()
        rm.stopped_by = "P1:top"  # 优先级 1
        rm.condition_eval = ConditionEval(
            stage="c", condition_name="c", result=True,
            action="skip", timestamp=0.0, stopped_by="P2:condition",
        )
        ctx = _make_ctx()
        ctx.metadata = {"condition_eval": {"stopped_by": "P3:metadata"}}
        ctx.stop = True
        # P1 胜
        assert rm.resolve_stop_reason(ctx) == "P1:top"

    def test_priority_order_condition_wins_over_metadata(self):
        """优先级 2 > 3 > 4"""
        rm = RuntimeMetadata()
        rm.condition_eval = ConditionEval(
            stage="c", condition_name="c", result=True,
            action="skip", timestamp=0.0, stopped_by="P2:condition",
        )
        ctx = _make_ctx()
        ctx.metadata = {"condition_eval": {"stopped_by": "P3:metadata"}}
        ctx.stop = True
        assert rm.resolve_stop_reason(ctx) == "P2:condition"

    def test_priority_order_metadata_wins_over_stop_flag(self):
        """优先级 3 > 4"""
        rm = RuntimeMetadata()
        ctx = _make_ctx()
        ctx.metadata = {"condition_eval": {"stopped_by": "P3:metadata"}}
        ctx.stop = True
        assert rm.resolve_stop_reason(ctx) == "P3:metadata"


# ─────────────────────────────────────────────────────────────
# TestResolveStoppedByAlias — V1.0.7 → V1.0.8 命名过渡
# ─────────────────────────────────────────────────────────────

class TestResolveStoppedByAlias:
    """resolve_stopped_by = resolve_stop_reason (backward compat)"""

    def test_resolve_stopped_by_is_alias(self):
        """resolve_stopped_by 应是 resolve_stop_reason 的别名"""
        rm = RuntimeMetadata()
        ctx = _make_ctx()
        rm.stopped_by = "test"
        # 两者应返回相同结果
        assert rm.resolve_stopped_by(ctx) == rm.resolve_stop_reason(ctx)
        assert rm.resolve_stopped_by(ctx) == "test"

    def test_resolve_stopped_by_priority_works(self):
        """resolve_stopped_by 走相同优先级逻辑"""
        rm = RuntimeMetadata()
        ctx = _make_ctx()
        ctx.metadata = {"condition_eval": {"stopped_by": "legacy"}}
        # 即使新代码用 resolve_stop_reason, 别名也工作
        assert rm.resolve_stopped_by(ctx) == "legacy"


# ─────────────────────────────────────────────────────────────
# TestCheckpointStageUsesResolver — V1.0.8 集成测试
# ─────────────────────────────────────────────────────────────

class TestCheckpointStageUsesResolver:
    """CheckpointStage V1.0.8: 改用 resolve_stop_reason"""

    def _setup_ctx(self, *, runtime_stopped_by=None, metadata=None, stop=False):
        ctx = _make_ctx()
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(
            provider="p1", status="success", output="ok",
            error=None, metadata={},
        )
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        if runtime_stopped_by is not None:
            ctx.runtime.stopped_by = runtime_stopped_by
        if metadata is not None:
            ctx.metadata = metadata
        ctx.stop = stop
        return ctx

    def test_checkpoint_uses_top_level_resolver(self):
        """CheckpointStage 用 resolver, 顶级 stopped_by 命中"""
        ctx = self._setup_ctx(runtime_stopped_by="manual:abort")
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by == "manual:abort"
        assert snapshot.aborted is True

    def test_checkpoint_uses_condition_eval_resolver(self):
        """CheckpointStage 用 resolver, condition_eval.stopped_by 命中"""
        ctx = _make_ctx()
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(provider="p1", status="success", output="ok", metadata={})
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        ctx.runtime.condition_eval = ConditionEval(
            stage="condition", condition_name="c1", result=True,
            action="abort", timestamp=0.0, stopped_by="condition:c1:abort",
        )
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by == "condition:c1:abort"

    def test_checkpoint_uses_metadata_fallback(self):
        """CheckpointStage 用 resolver, metadata dict 兜底"""
        ctx = self._setup_ctx(metadata={"condition_eval": {"stopped_by": "legacy:stop"}})
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by == "legacy:stop"

    def test_checkpoint_uses_stop_flag_fallback(self):
        """CheckpointStage 用 resolver, ctx.stop → 'stop_flag'"""
        ctx = self._setup_ctx(stop=True)
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by == "stop_flag"

    def test_checkpoint_behavior_unchanged_from_v107(self):
        """V1.0.7 行为完全保留: 未停止 → aborted=False, stopped_by=None"""
        ctx = _make_ctx()
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(provider="p1", status="success", output="ok", metadata={})
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by is None
        assert snapshot.aborted is False

    def test_checkpoint_uses_get_metrics(self):
        """CheckpointStage 用 get_metrics() 统一接口"""
        ctx = _make_ctx()
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(provider="p1", status="success", output="ok", metadata={})
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        ctx.runtime.set_server_metrics({"token_in": 200}, ctx=ctx, merge=False)
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.server_metrics == {"token_in": 200}


# ─────────────────────────────────────────────────────────────
# TestBackwardCompat — V1.0.7 API 100% 兼容
# ─────────────────────────────────────────────────────────────

class TestBackwardCompat:
    """V1.0.7 API 100% 兼容 (V1.0.8 不破坏任何东西)"""

    def test_v107_property_access_still_works(self):
        """V1.0.7 直读属性仍工作"""
        rm = RuntimeMetadata()
        rm.stopped_by = "v107"
        # V1.0.7 直读
        assert rm.stopped_by == "v107"
        # V1.0.8 getter 等价
        assert rm.get_stop_reason() == "v107"

    def test_v107_helper_calls_still_work(self):
        """V1.0.7 set_*() helper 仍工作"""
        ctx = _make_ctx()
        ctx.runtime.set_condition_eval(
            ConditionEval(
                stage="condition", condition_name="c1", result=True,
                action="skip", timestamp=0.0, stopped_by="condition:c1:skip",
            ),
            ctx=ctx,
        )
        # V1.0.7 直读
        assert ctx.runtime.stopped_by == "condition:c1:skip"
        # V1.0.8 getter 等价
        assert ctx.runtime.get_stop_reason() == "condition:c1:skip"

    def test_v107_third_party_plugin_dict_still_works(self):
        """V1.0.6 第三方 Plugin dict 仍工作"""
        ctx = _make_ctx()
        ctx.metadata = {"legacy_key": "v106_data"}
        # 旧 API 仍可读
        assert ctx.metadata["legacy_key"] == "v106_data"
        # V1.0.8 resolver 仍支持 dict 兜底
        ctx.metadata = {"condition_eval": {"stopped_by": "v106:stop"}}
        assert ctx.runtime.resolve_stop_reason(ctx) == "v106:stop"

    def test_v107_v108_api_coexist(self):
        """V1.0.7 直读 + V1.0.8 getter 共存"""
        rm = RuntimeMetadata()
        rm.stopped_by = "value"
        # 两种 API 都应工作
        assert rm.stopped_by == "value"  # V1.0.7
        assert rm.get_stop_reason() == "value"  # V1.0.8
        assert rm.has_stop_reason() is True  # V1.0.8 T2
