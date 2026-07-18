# AI Hub — Stage RuntimeMetadata Integration Tests (V1.0.7, ADR-0027)
#
# 验证 built-in Stage 强类型 + 双写 (helper 封装).
# - ConditionStage: 写 ctx.runtime.condition_eval + ctx.runtime.stopped_by (顶级)
# - MetricsStage: 写 ctx.runtime.server_metrics
# - CheckpointStage: 读 ctx.runtime.stopped_by 优先, dict 兜底
#
# 这些测试 **增量** 于现有 V1.0.6 测试, 验证 V1.0.7 强类型 API 工作.

from __future__ import annotations

import pytest

from planner.pipeline import ExecutionContext
from planner.runtime_metadata import RuntimeMetadata
from planner.stages.condition_stage import ConditionStage, ConditionEval
from planner.stages.checkpoint_stage import CheckpointStage, CheckpointSnapshot
from core.bridge import BridgeResult
from core.provider import Provider
from core.task import Task
from core.result import Result


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

def _make_task(task_id="t1"):
    return Task(task_id=task_id, content="hello", capabilities=["chat"])


def _make_bridge_result(success=True, output="ok", error=None):
    return BridgeResult(
        success=success,
        output=output,
        error=error,
        artifacts=[],
        duration_ms=10,
    )


class _StubStore:
    """Minimal in-memory ExecutionStore for CheckpointStage tests"""

    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


# ─────────────────────────────────────────────────────────────
# TestConditionStageRuntime — ConditionStage 写 runtime
# ─────────────────────────────────────────────────────────────

class TestConditionStageRuntime:
    """ConditionStage V1.0.7: 强类型 + 顶级 stopped_by"""

    def test_condition_stage_writes_runtime_condition_eval(self):
        """ConditionStage 写 ctx.runtime.condition_eval (强类型 ConditionEval)"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        stage = ConditionStage(condition=lambda c: True, on_true="skip", name="c1")
        new_ctx = stage(ctx)
        # 验证强类型写入
        assert new_ctx.runtime.condition_eval is not None
        assert isinstance(new_ctx.runtime.condition_eval, ConditionEval)
        assert new_ctx.runtime.condition_eval.action == "skip"
        assert new_ctx.runtime.condition_eval.stopped_by == "condition:c1:skip"

    def test_condition_stage_writes_runtime_stopped_by_top_level(self):
        """ConditionStage 写 ctx.runtime.stopped_by 顶级 (ChatGPT 9.2/10 关键采纳)"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        stage = ConditionStage(condition=lambda c: True, on_true="skip", name="c1")
        new_ctx = stage(ctx)
        # 顶级 stopped_by
        assert new_ctx.runtime.stopped_by == "condition:c1:skip"

    def test_condition_stage_no_stopped_by_for_continue(self):
        """continue 动作不写 stopped_by"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        stage = ConditionStage(condition=lambda c: True, on_true="continue", name="c1")
        new_ctx = stage(ctx)
        # condition_eval 写入但 stopped_by 为 None
        assert new_ctx.runtime.condition_eval is not None
        assert new_ctx.runtime.condition_eval.action == "continue"
        assert new_ctx.runtime.stopped_by is None
        # 注意: metadata 也不应包含 stopped_by
        assert "stopped_by" not in new_ctx.metadata

    def test_condition_stage_writes_both_runtime_and_metadata(self):
        """ConditionStage 双写 (helper 内部完成)"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        stage = ConditionStage(condition=lambda c: True, on_true="abort", name="c1")
        new_ctx = stage(ctx)
        # 强类型
        assert new_ctx.runtime.stopped_by == "condition:c1:abort"
        # 旧 API (write-through)
        assert "condition_eval" in new_ctx.metadata
        assert new_ctx.metadata["condition_eval"]["stopped_by"] == "condition:c1:abort"
        assert new_ctx.metadata["stopped_by"] == "condition:c1:abort"


# ─────────────────────────────────────────────────────────────
# TestCheckpointStageRuntimeRead — CheckpointStage 强类型优先
# ─────────────────────────────────────────────────────────────

class TestCheckpointStageRuntimeRead:
    """CheckpointStage V1.0.7: 强类型优先读, dict 兜底"""

    def _setup_ctx_with_runtime_stopped_by(self, stopped_by):
        """设置 ctx 有 runtime.stopped_by 顶级字段"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(
            provider="p1",
            status="success",
            output="ok",
            error=None,
            metadata={"task_id": "t1"},
        )
        # Mock provider
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        ctx.runtime.set_stopped_by(stopped_by)
        return ctx

    def test_checkpoint_prefers_runtime_top_level(self):
        """CheckpointStage 优先读 ctx.runtime.stopped_by 顶级"""
        ctx = self._setup_ctx_with_runtime_stopped_by("retry:exhausted")
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by == "retry:exhausted"
        assert snapshot.aborted is True

    def test_checkpoint_falls_back_to_runtime_condition_eval(self):
        """CheckpointStage 兜底 ctx.runtime.condition_eval.stopped_by"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(provider="p1", status="success", output="ok", metadata={})
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        # 只设 condition_eval.stopped_by, 不设顶级
        ctx.runtime.condition_eval = ConditionEval(
            stage="condition",
            condition_name="c1",
            result=True,
            action="abort",
            timestamp=0.0,
            stopped_by="condition:c1:abort",
        )
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by == "condition:c1:abort"

    def test_checkpoint_falls_back_to_legacy_dict(self):
        """CheckpointStage 兜底 ctx.metadata["condition_eval"].stopped_by (V1.0.6 兼容)"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(provider="p1", status="success", output="ok", metadata={})
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        # 不设 runtime, 只设 metadata (V1.0.6 风格)
        ctx.metadata = {
            "condition_eval": {"stopped_by": "legacy:stopped_by"},
        }
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by == "legacy:stopped_by"

    def test_checkpoint_falls_back_to_stop_flag(self):
        """CheckpointStage 兜底 ctx.stop → 'stop_flag'"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(provider="p1", status="success", output="ok", metadata={})
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        ctx.stop = True
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.stopped_by == "stop_flag"
        assert snapshot.aborted is True

    def test_checkpoint_reads_runtime_server_metrics(self):
        """CheckpointStage 优先读 ctx.runtime.server_metrics (新 API)"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(provider="p1", status="success", output="ok", metadata={})
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        # 设 ctx.runtime.server_metrics
        ctx.runtime.set_server_metrics({"token_in": 100}, ctx=ctx, merge=False)
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.server_metrics == {"token_in": 100}

    def test_checkpoint_falls_back_to_result_metadata_server_metrics(self):
        """CheckpointStage 兜底 ctx.result.metadata["server_metrics"] (V1.0.6 行为)"""
        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        ctx.result = Result(
            provider="p1",
            status="success",
            output="ok",
            metadata={"server_metrics": {"token_in": 50}},
        )
        from types import SimpleNamespace
        ctx.provider = SimpleNamespace(name="p1")
        ctx.bridge = SimpleNamespace(__class__=type("MockBridge", (), {}))
        # ctx.runtime.server_metrics 为空
        snapshot = CheckpointSnapshot.from_context(ctx)
        assert snapshot.server_metrics == {"token_in": 50}


# ─────────────────────────────────────────────────────────────
# TestMetricsStageRuntime — MetricsStage 写 runtime.server_metrics
# ─────────────────────────────────────────────────────────────

class TestMetricsStageRuntime:
    """MetricsStage V1.0.7: 写 ctx.runtime.server_metrics (强类型)"""

    def test_metrics_stage_writes_runtime_server_metrics(self):
        """MetricsStage 写 ctx.runtime.server_metrics"""
        from planner.pipeline import MetricsStage
        from planner.metrics.extractors import MetricsExtractor
        from types import SimpleNamespace

        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        ctx.provider = SimpleNamespace(name="p1")
        # Mock bridge with class name
        class MockBridge:
            pass
        ctx.bridge = MockBridge()

        # 用 fake extractor 避免依赖
        class FakeExtractor:
            def extract(self, *args, **kwargs):
                return {"token_in": 200, "token_out": 100}

        stage = MetricsStage(extractor=FakeExtractor())
        new_ctx = stage(ctx)
        # 验证强类型写入
        assert new_ctx.runtime.server_metrics == {"token_in": 200, "token_out": 100}
        # 验证 write-through (helper 也写 metadata)
        assert new_ctx.metadata["server_metrics"] == {"token_in": 200, "token_out": 100}
        # 验证 Result.metadata 仍写入 (V1.0.6 行为保留)
        assert new_ctx.result is not None
        assert new_ctx.result.metadata["server_metrics"] == {"token_in": 200, "token_out": 100}

    def test_metrics_stage_skip_when_stop(self):
        """MetricsStage 短路 ctx.stop=True"""
        from planner.pipeline import MetricsStage

        ctx = ExecutionContext(task=_make_task())
        ctx.bridge_result = _make_bridge_result()
        ctx.stop = True
        stage = MetricsStage()
        new_ctx = stage(ctx)
        # runtime 不写入
        assert new_ctx.runtime.server_metrics == {}
