# AI Hub — Plugin Compatibility Tests (V1.0.7, ADR-0027 Accepted 9.85/10)
#
# T2 (采纳 ChatGPT 9.85/10): 模拟 V1.0.6 第三方 Plugin 用 ctx.metadata dict API
# 验证 V1.0.7 additive migration 不破坏 V1.0.6 风格.
#
# 覆盖 ADR §6.6 Plugin Compatibility:
#   - 第三方 Plugin ctx.metadata["abc"] = 1 仍工作
#   - 旧 Hook 读 ctx.metadata["trace_id"] 仍工作
#   - 第三方 Plugin dict 写入不污染 ctx.runtime
#   - 混合 V1.0.6 风格 + V1.0.7 强类型 Stage 协同

from __future__ import annotations

import pytest

from planner.pipeline import ExecutionContext
from planner.runtime_metadata import RuntimeMetadata
from planner.stages.condition_stage import ConditionEval
from core.task import Task


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

def _make_task():
    return Task(task_id="t1", content="hello", capabilities=["chat"])


def _make_ctx():
    return ExecutionContext(task=_make_task())


# ─────────────────────────────────────────────────────────────
# TestV1_0_6_PluginStillWorks — T2 核心
# ─────────────────────────────────────────────────────────────

class TestV1_0_6_PluginStillWorks:
    """模拟 V1.0.6 第三方 Plugin 用 ctx.metadata dict API"""

    def test_v106_third_party_plugin_writes_dict(self):
        """V1.0.6 第三方 Plugin: ctx.metadata["abc"] = 1 仍工作"""
        ctx = _make_ctx()
        # 第三方 Plugin 旧风格 (V1.0.6)
        ctx.metadata = {}  # V1.0.6 行为: 首次写入时创建
        ctx.metadata["my_plugin_key"] = {"value": 42}
        # 验证
        assert ctx.metadata["my_plugin_key"] == {"value": 42}

    def test_v106_plugin_in_pipeline_path(self):
        """第三方 Plugin dict 写入 Pipeline 正常 (不抛异常)"""
        ctx = _make_ctx()
        # 模拟第三方 Plugin 在 Pipeline 中插入逻辑
        ctx.metadata = {"trace_id": "abc123", "user_id": "u1"}
        # 模拟 ConditionStage 写 condition_eval
        ctx.runtime.set_condition_eval(
            ConditionEval(
                stage="condition",
                condition_name="cond1",
                result=True,
                action="continue",
                timestamp=0.0,
                stopped_by=None,
            ),
            ctx=ctx,
        )
        # 验证两个 API 独立
        assert ctx.metadata["trace_id"] == "abc123"
        assert ctx.metadata["user_id"] == "u1"
        assert ctx.runtime.condition_eval is not None
        assert "trace_id" not in ctx.runtime.custom

    def test_v106_plugin_does_not_affect_runtime(self):
        """第三方 Plugin dict 写入 runtime 不受影响 (write-through only)"""
        ctx = _make_ctx()
        # 第三方 Plugin 写 metadata
        ctx.metadata = {"server_metrics": {"fake": 1}}
        ctx.metadata["stopped_by"] = "fake_value"
        # 验证 runtime 不受污染
        assert ctx.runtime.server_metrics == {}
        assert ctx.runtime.stopped_by is None
        assert ctx.runtime.condition_eval is None


# ─────────────────────────────────────────────────────────────
# TestV1_0_6_HookStillWorks — Hook 旧风格读取
# ─────────────────────────────────────────────────────────────

class TestV1_0_6_HookStillWorks:
    """模拟 V1.0.6 Hook 读 ctx.metadata dict API"""

    def test_hook_reads_ctx_metadata(self):
        """Hook 读 ctx.metadata["trace_id"] 仍工作"""
        ctx = _make_ctx()
        ctx.metadata = {"trace_id": "trace-abc"}
        # 模拟 Hook 读
        trace_id = ctx.metadata.get("trace_id")
        assert trace_id == "trace-abc"

    def test_hook_reads_after_condition_stage(self):
        """Hook 在 ConditionStage 写后读 dict 仍能读"""
        ctx = _make_ctx()
        # ConditionStage 通过 helper 写 (强类型 + write-through)
        ctx.runtime.set_condition_eval(
            ConditionEval(
                stage="condition",
                condition_name="cond1",
                result=True,
                action="skip",
                timestamp=0.0,
                stopped_by="condition:cond1:skip",
            ),
            ctx=ctx,
        )
        # Hook 读旧 dict API
        condition_eval = ctx.metadata.get("condition_eval")
        assert condition_eval is not None
        assert condition_eval["stopped_by"] == "condition:cond1:skip"
        stopped_by = ctx.metadata.get("stopped_by")
        assert stopped_by == "condition:cond1:skip"

    def test_hook_reads_after_metrics_stage(self):
        """Hook 在 MetricsStage 写后读 dict 仍能读"""
        ctx = _make_ctx()
        # MetricsStage 通过 helper 写
        ctx.runtime.set_server_metrics(
            {"token_in": 100, "token_out": 50},
            ctx=ctx,
            merge=False,
        )
        # Hook 读旧 dict API
        server_metrics = ctx.metadata.get("server_metrics")
        assert server_metrics == {"token_in": 100, "token_out": 50}


# ─────────────────────────────────────────────────────────────
# TestMixedV1_0_6_V1_0_7 — 混合 V1.0.6 风格 + V1.0.7 强类型
# ─────────────────────────────────────────────────────────────

class TestMixedV1_0_6_V1_0_7:
    """混合 V1.0.6 风格 + V1.0.7 强类型 Stage 协同工作"""

    def test_v106_writes_metadata_v107_reads_runtime(self):
        """V1.0.6 Plugin 写 metadata, V1.0.7 Stage 读 runtime (互不影响)"""
        ctx = _make_ctx()
        # V1.0.6 Plugin
        ctx.metadata = {"legacy_key": "v106_data"}
        # V1.0.7 Stage (helper)
        ctx.runtime.set_stopped_by("v107:reason", ctx=ctx)
        # 两个世界独立
        assert ctx.runtime.stopped_by == "v107:reason"
        assert ctx.metadata["legacy_key"] == "v106_data"
        assert "stopped_by" in ctx.metadata  # helper 也写 metadata

    def test_v107_writes_runtime_v106_reads_metadata(self):
        """V1.0.7 Stage 写 runtime (helper 也写 metadata), V1.0.6 Plugin 读 metadata"""
        ctx = _make_ctx()
        # V1.0.7 Stage
        ctx.runtime.set_plan({"success": 5, "failed": 1}, ctx=ctx)
        # V1.0.6 Plugin 读
        plan = ctx.metadata.get("plan")
        assert plan == {"success": 5, "failed": 1}

    def test_independent_default_values(self):
        """runtime 和 metadata 默认独立"""
        ctx = _make_ctx()
        # runtime 是新字段, 默认 RuntimeMetadata()
        assert isinstance(ctx.runtime, RuntimeMetadata)
        assert ctx.runtime.server_metrics == {}
        # metadata 默认不存在 (V1.0.6 行为, 首次写入时创建)
        assert not hasattr(ctx, "metadata") or ctx.metadata is None


# ─────────────────────────────────────────────────────────────
# TestWithXxxPropagatesRuntime — with_xxx 透传 runtime
# ─────────────────────────────────────────────────────────────

class TestWithXxxPropagatesRuntime:
    """ExecutionContext.with_xxx 透传 runtime 字段 (V1.0.7)"""

    def test_with_provider_propagates_runtime(self):
        """with_provider 透传 runtime"""
        ctx = _make_ctx()
        ctx.runtime.set_stopped_by("original", ctx=ctx)
        # 模拟 with_provider (创建新 ctx, 透传 runtime)
        new_ctx = ctx.with_provider(None)
        # 验证透传
        assert new_ctx.runtime.stopped_by == "original"

    def test_with_result_propagates_runtime(self):
        """with_result 透传 runtime"""
        from core.result import Result
        ctx = _make_ctx()
        ctx.runtime.set_stopped_by("test", ctx=ctx)
        new_ctx = ctx.with_result(
            Result(provider="p1", status="success", output="ok", metadata={}),
            stop=True,
        )
        assert new_ctx.runtime.stopped_by == "test"

    def test_with_bridge_result_propagates_runtime(self):
        """with_bridge_result 透传 runtime"""
        from core.bridge import BridgeResult
        ctx = _make_ctx()
        ctx.runtime.set_server_metrics({"x": 1}, ctx=ctx)
        new_ctx = ctx.with_bridge_result(
            BridgeResult(success=True, output="ok", error=None, artifacts=[], duration_ms=10),
        )
        assert new_ctx.runtime.server_metrics == {"x": 1}

    def test_with_stop_propagates_runtime(self):
        """with_stop 透传 runtime"""
        ctx = _make_ctx()
        ctx.runtime.set_plan({"success": 1}, ctx=ctx)
        new_ctx = ctx.with_stop()
        assert new_ctx.runtime.plan == {"success": 1}
        assert new_ctx.stop is True


# ─────────────────────────────────────────────────────────────
# TestRuntimeContractMUST — Runtime Contract MUSTs (ChatGPT 9.85/10)
# ─────────────────────────────────────────────────────────────

class TestRuntimeContractMUSTs:
    """Runtime Contract MUSTs (ADR §2.7 采纳 ChatGPT 9.85/10)"""

    def test_must_1_runtime_is_canonical_for_builtin(self):
        """MUST-1: RuntimeMetadata 是 built-in canonical source"""
        ctx = _make_ctx()
        # built-in Stage 通过 helper 写
        ctx.runtime.set_stopped_by("condition:abort", ctx=ctx)
        # built-in Stage 读 (CheckpointStage 实际行为) 应优先读 runtime
        assert ctx.runtime.stopped_by == "condition:abort"

    def test_must_2_write_through_only(self):
        """MUST-2: metadata 兼容性为 write-through only"""
        ctx = _make_ctx()
        # 第三方 Stage 写 metadata (旧 API)
        ctx.metadata = {"legacy": "data"}
        ctx.metadata["custom_field"] = "value"
        # runtime 不应被反向同步
        assert ctx.runtime.custom == {}
        assert ctx.runtime.server_metrics == {}

    def test_must_3_additive_no_invalidate(self):
        """MUST-3: RuntimeMetadata additive, 不 invalidate 旧 metadata"""
        ctx = _make_ctx()
        # 旧代码 (V1.0.6 风格)
        ctx.metadata = {"a": 1, "b": 2}
        # 新代码 (V1.0.7 风格)
        ctx.runtime.set_stopped_by("new", ctx=ctx)
        # 旧代码仍可读
        assert ctx.metadata["a"] == 1
        assert ctx.metadata["b"] == 2
        # 新代码可读
        assert ctx.runtime.stopped_by == "new"

    def test_must_4_metadata_permanent_in_v1x(self):
        """MUST-4: V1.x 永远支持 ctx.metadata (无 warning)"""
        import logging
        ctx = _make_ctx()
        # 模拟 V1.0.6 风格写入
        with_log = []
        handler = logging.Handler()
        handler.emit = lambda record: with_log.append(record)
        logger = logging.getLogger("planner.runtime_metadata")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        try:
            ctx.metadata = {"k": "v"}
            ctx.metadata["another"] = "data"
        finally:
            logger.removeHandler(handler)
        # V1.0.7 不发 warning
        assert len(with_log) == 0
