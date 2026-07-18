# AI Hub — RuntimeMetadata Unit Tests (V1.0.7, ADR-0027 Accepted 9.85/10)
#
# 测试 RuntimeMetadata dataclass + helper 方法 (ChatGPT 9.85/10 N1 采纳).
# 覆盖 ADR §6.1 + §6.1.1 + §6.5 (双写一致性):
#   - 默认值
#   - 字段集 (无 retry / 无 experimental, ChatGPT 9.2/10 deferral)
#   - stopped_by 顶级字段
#   - custom 命名空间
#   - Helper 方法 set_condition_eval / set_server_metrics / set_plan / set_custom / set_stopped_by
#   - write-through only (MUST-2: 写 runtime → metadata, 不做反向)

from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from planner.runtime_metadata import (
    RUNTIME_RESERVED_KEYS,
    RuntimeMetadata,
    _ensure_metadata,
)
from planner.stages.condition_stage import ConditionEval


# ─────────────────────────────────────────────────────────────
# TestRuntimeMetadataDefaults — 默认值
# ─────────────────────────────────────────────────────────────

class TestRuntimeMetadataDefaults:
    def test_default_runtime_metadata(self):
        """默认值: 所有字段都是空/None"""
        rm = RuntimeMetadata()
        assert rm.server_metrics == {}
        assert rm.condition_eval is None
        assert rm.stopped_by is None
        assert rm.plan == {}
        assert rm.custom == {}

    def test_server_metrics_default_dict(self):
        """server_metrics 默认可写 (非 frozen)"""
        rm = RuntimeMetadata()
        rm.server_metrics["a"] = 1
        assert rm.server_metrics == {"a": 1}

    def test_condition_eval_optional(self):
        """condition_eval 默认 None, 可设置"""
        rm = RuntimeMetadata()
        assert rm.condition_eval is None
        rm.condition_eval = "fake"
        assert rm.condition_eval == "fake"

    def test_stopped_by_optional(self):
        """stopped_by 默认 None, 可设置"""
        rm = RuntimeMetadata()
        assert rm.stopped_by is None
        rm.stopped_by = "condition:abort"
        assert rm.stopped_by == "condition:abort"

    def test_plan_default_dict(self):
        """plan 默认可写"""
        rm = RuntimeMetadata()
        rm.plan["success"] = 3
        assert rm.plan == {"success": 3}

    def test_custom_default_dict(self):
        """custom 默认可写"""
        rm = RuntimeMetadata()
        rm.custom["my_plugin"] = {"key": "value"}
        assert rm.custom == {"my_plugin": {"key": "value"}}


# ─────────────────────────────────────────────────────────────
# TestRuntimeMetadataFieldSet — 字段集约束 (ChatGPT 9.2/10)
# ─────────────────────────────────────────────────────────────

class TestRuntimeMetadataFieldSet:
    def test_no_retry_field(self):
        """V1.0.7 无 retry 字段 (ChatGPT 9.2/10 defer to V1.1)"""
        rm = RuntimeMetadata()
        assert not hasattr(rm, "retry")
        with pytest.raises(AttributeError):
            _ = rm.retry

    def test_no_experimental_field(self):
        """V1.0.7 无 experimental 字段 (ChatGPT 9.2/10 defer to V2)"""
        rm = RuntimeMetadata()
        assert not hasattr(rm, "experimental")
        with pytest.raises(AttributeError):
            _ = rm.experimental

    def test_runtime_reserved_keys_listed(self):
        """RUNTIME_RESERVED_KEYS 包含所有 V1.0.7 字段"""
        assert "server_metrics" in RUNTIME_RESERVED_KEYS
        assert "condition_eval" in RUNTIME_RESERVED_KEYS
        assert "stopped_by" in RUNTIME_RESERVED_KEYS
        assert "plan" in RUNTIME_RESERVED_KEYS
        assert "custom" in RUNTIME_RESERVED_KEYS
        assert "retry" not in RUNTIME_RESERVED_KEYS  # V1.1
        assert "experimental" not in RUNTIME_RESERVED_KEYS  # V2

    def test_stopped_by_top_level_not_nested(self):
        """stopped_by 是顶级字段, 不在 condition_eval 子字段 (ChatGPT 9.2/10 关键采纳)"""
        rm = RuntimeMetadata()
        # 设置 stopped_by 不应自动创建 condition_eval
        rm.stopped_by = "manual:stop"
        assert rm.condition_eval is None
        assert rm.stopped_by == "manual:stop"

    def test_user_plugin_can_write_custom(self):
        """custom 命名空间可写 (受控 namespace)"""
        rm = RuntimeMetadata()
        rm.custom["my_plugin"] = {"x": 1}
        rm.custom["other_plugin"] = ["a", "b"]
        assert rm.custom == {"my_plugin": {"x": 1}, "other_plugin": ["a", "b"]}

    def test_metadata_equality(self):
        """dataclass eq"""
        rm1 = RuntimeMetadata(server_metrics={"a": 1})
        rm2 = RuntimeMetadata(server_metrics={"a": 1})
        rm3 = RuntimeMetadata(server_metrics={"a": 2})
        assert rm1 == rm2
        assert rm1 != rm3


# ─────────────────────────────────────────────────────────────
# TestHelperSetConditionEval — helper.set_condition_eval
# ─────────────────────────────────────────────────────────────

class TestHelperSetConditionEval:
    """测试 set_condition_eval helper (N1 采纳: 封装双写到 helper)"""

    def _make_ctx(self):
        """构造一个 mock ExecutionContext (无 metadata 字段)"""
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        return ExecutionContext(task=task)

    def _make_eval(self, stopped_by=None):
        return ConditionEval(
            stage="condition",
            condition_name="cond1",
            result=True,
            action="skip",
            timestamp=123.0,
            stopped_by=stopped_by,
        )

    def test_set_condition_eval_writes_runtime(self):
        """helper 写 runtime.condition_eval (强类型)"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        eval = self._make_eval(stopped_by="condition:cond1:skip")
        rm.set_condition_eval(eval, ctx=ctx)
        assert rm.condition_eval is eval
        assert rm.stopped_by == "condition:cond1:skip"

    def test_set_condition_eval_writes_metadata_via_ctx(self):
        """helper 通过 ctx 写 metadata (write-through)"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        eval = self._make_eval(stopped_by="condition:cond1:skip")
        rm.set_condition_eval(eval, ctx=ctx)
        assert "condition_eval" in ctx.metadata
        assert ctx.metadata["condition_eval"]["stopped_by"] == "condition:cond1:skip"
        assert ctx.metadata["stopped_by"] == "condition:cond1:skip"

    def test_set_condition_eval_no_stopped_by(self):
        """helper 处理 stopped_by=None (condition=True 但 continue)"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        eval = self._make_eval(stopped_by=None)
        rm.set_condition_eval(eval, ctx=ctx)
        assert rm.condition_eval is eval
        assert rm.stopped_by is None
        # metadata 仍写入 condition_eval (即使 stopped_by 为 None)
        assert "condition_eval" in ctx.metadata
        assert "stopped_by" not in ctx.metadata

    def test_set_condition_eval_creates_metadata_if_missing(self):
        """helper 在 ctx 没有 metadata 时自动创建"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        assert not hasattr(ctx, "metadata") or ctx.metadata is None
        eval = self._make_eval(stopped_by="c")
        rm.set_condition_eval(eval, ctx=ctx)
        assert hasattr(ctx, "metadata")
        assert ctx.metadata["condition_eval"]["stopped_by"] == "c"


# ─────────────────────────────────────────────────────────────
# TestHelperSetServerMetrics — helper.set_server_metrics
# ─────────────────────────────────────────────────────────────

class TestHelperSetServerMetrics:
    """测试 set_server_metrics helper"""

    def _make_ctx(self):
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        return ExecutionContext(task=task)

    def test_set_server_metrics_replace_default(self):
        """默认 merge=False, 替换现有 metrics"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        rm.set_server_metrics({"token_in": 100, "token_out": 50}, ctx=ctx)
        assert rm.server_metrics == {"token_in": 100, "token_out": 50}
        assert ctx.metadata["server_metrics"] == {"token_in": 100, "token_out": 50}

    def test_set_server_metrics_merge_true(self):
        """merge=True 合并"""
        rm = RuntimeMetadata(server_metrics={"a": 1})
        ctx = self._make_ctx()
        ctx.metadata = {"server_metrics": {"a": 1}}
        rm.set_server_metrics({"b": 2}, ctx=ctx, merge=True)
        assert rm.server_metrics == {"a": 1, "b": 2}
        assert ctx.metadata["server_metrics"] == {"a": 1, "b": 2}

    def test_set_server_metrics_creates_metadata(self):
        """helper 在 ctx 没有 metadata 时自动创建"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        rm.set_server_metrics({"a": 1}, ctx=ctx)
        assert hasattr(ctx, "metadata")
        assert ctx.metadata["server_metrics"] == {"a": 1}


# ─────────────────────────────────────────────────────────────
# TestHelperSetPlan — helper.set_plan
# ─────────────────────────────────────────────────────────────

class TestHelperSetPlan:
    """测试 set_plan helper"""

    def _make_ctx(self):
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        return ExecutionContext(task=task)

    def test_set_plan_writes_both(self):
        """helper 写 runtime.plan + ctx.metadata["plan"]"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        rm.set_plan({"success": 3, "failed": 1, "total": 4}, ctx=ctx)
        assert rm.plan == {"success": 3, "failed": 1, "total": 4}
        assert ctx.metadata["plan"] == {"success": 3, "failed": 1, "total": 4}

    def test_set_plan_copy(self):
        """helper 拷贝 plan (避免外部修改)"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        plan = {"success": 1}
        rm.set_plan(plan, ctx=ctx)
        plan["success"] = 999
        # helper 应已拷贝, 不受外部修改影响
        assert rm.plan == {"success": 1}


# ─────────────────────────────────────────────────────────────
# TestHelperSetStoppedBy — helper.set_stopped_by (顶级字段)
# ─────────────────────────────────────────────────────────────

class TestHelperSetStoppedBy:
    """测试 set_stopped_by helper (用于未来 Retry/Timeout/ManualAbort)"""

    def _make_ctx(self):
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        return ExecutionContext(task=task)

    def test_set_stopped_by_writes_both(self):
        """helper 写 runtime.stopped_by + ctx.metadata["stopped_by"]"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        rm.set_stopped_by("retry:exhausted", ctx=ctx)
        assert rm.stopped_by == "retry:exhausted"
        assert ctx.metadata["stopped_by"] == "retry:exhausted"

    def test_set_stopped_by_creates_metadata(self):
        """helper 在 ctx 没有 metadata 时自动创建"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        assert not hasattr(ctx, "metadata") or ctx.metadata is None
        rm.set_stopped_by("timeout", ctx=ctx)
        assert hasattr(ctx, "metadata")
        assert ctx.metadata["stopped_by"] == "timeout"


# ─────────────────────────────────────────────────────────────
# TestHelperSetCustom — helper.set_custom (user plugin)
# ─────────────────────────────────────────────────────────────

class TestHelperSetCustom:
    """测试 set_custom helper (user plugin 写入)"""

    def test_set_custom_writes_runtime_only(self):
        """set_custom 只写 runtime.custom, 不写 metadata (新 API)"""
        rm = RuntimeMetadata()
        ctx = None  # 故意不传 ctx, 因为 custom 不需要 write-through
        rm.set_custom("my_plugin", {"x": 1})
        assert rm.custom == {"my_plugin": {"x": 1}}


# ─────────────────────────────────────────────────────────────
# TestWriteThroughOnly — MUST-2: 写穿单向
# ─────────────────────────────────────────────────────────────

class TestWriteThroughOnly:
    """MUST-2: metadata compatibility is write-through only.
    写 runtime → metadata, 不做反向同步."""

    def test_metadata_to_runtime_not_synced(self):
        """写 ctx.metadata["abc"] = 1 不会自动同步到 ctx.runtime"""
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        ctx = ExecutionContext(task=task)
        ctx.metadata = {"custom_key": "value"}
        # 第三方 Stage 旧风格写 metadata
        ctx.metadata["another"] = "data"
        # runtime 应为空 (未受污染)
        assert ctx.runtime.server_metrics == {}
        assert ctx.runtime.condition_eval is None
        assert ctx.runtime.stopped_by is None
        assert ctx.runtime.plan == {}
        assert ctx.runtime.custom == {}

    def test_no_reverse_sync_from_legacy_dict(self):
        """第三方 Stage 写 ctx.metadata["server_metrics"] 不污染 ctx.runtime.server_metrics"""
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        ctx = ExecutionContext(task=task)
        ctx.metadata = {"server_metrics": {"token_in": 999}}
        # runtime.server_metrics 应为空
        assert ctx.runtime.server_metrics == {}


# ─────────────────────────────────────────────────────────────
# TestEnsureMetadata — _ensure_metadata helper
# ─────────────────────────────────────────────────────────────

class TestEnsureMetadata:
    """_ensure_metadata helper: V1.0.6 兼容"""

    def test_ensure_creates_when_missing(self):
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        ctx = ExecutionContext(task=task)
        assert not hasattr(ctx, "metadata")
        md = _ensure_metadata(ctx)
        assert md == {}
        assert hasattr(ctx, "metadata")
        assert ctx.metadata == {}

    def test_ensure_returns_existing(self):
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        ctx = ExecutionContext(task=task)
        ctx.metadata = {"existing": "data"}
        md = _ensure_metadata(ctx)
        assert md == {"existing": "data"}

    def test_ensure_replaces_none(self):
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        ctx = ExecutionContext(task=task)
        ctx.metadata = None
        md = _ensure_metadata(ctx)
        assert md == {}
        assert ctx.metadata == {}


# ─────────────────────────────────────────────────────────────
# TestRuntimeMetadataNotFrozen — 可写
# ─────────────────────────────────────────────────────────────

class TestRuntimeMetadataNotFrozen:
    def test_not_frozen_can_modify(self):
        """RuntimeMetadata 默认可写 (非 frozen)"""
        rm = RuntimeMetadata()
        rm.server_metrics["a"] = 1
        rm.stopped_by = "test"
        assert rm.server_metrics == {"a": 1}
        assert rm.stopped_by == "test"


# ─────────────────────────────────────────────────────────────
# TestHelperIdempotency (T3) — 采纳 ChatGPT 9.88/10 Non-blocking
# ─────────────────────────────────────────────────────────────

class TestHelperIdempotency:
    """T3: helper 幂等性 — 多次调用 set_*() 结果一致.

    避免重复同步 bug. e.g. Pipeline 中重试执行导致 helper 调用多次.
    """

    def _make_ctx(self):
        from planner.pipeline import ExecutionContext
        from core.task import Task
        task = Task(task_id="t1", content="c", capabilities=["x"])
        return ExecutionContext(task=task)

    def test_set_condition_eval_idempotent(self):
        """多次 set_condition_eval 相同输入, 结果一致"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        eval1 = ConditionEval(
            stage="condition", condition_name="c1", result=True,
            action="skip", timestamp=100.0, stopped_by="condition:c1:skip",
        )
        rm.set_condition_eval(eval1, ctx=ctx)
        eval2 = ConditionEval(
            stage="condition", condition_name="c1", result=True,
            action="skip", timestamp=100.0, stopped_by="condition:c1:skip",
        )
        rm.set_condition_eval(eval2, ctx=ctx)
        # 最终状态应一致
        assert rm.condition_eval is eval2
        assert rm.stopped_by == "condition:c1:skip"
        assert ctx.metadata["condition_eval"]["stopped_by"] == "condition:c1:skip"

    def test_set_server_metrics_idempotent_replace(self):
        """多次 set_server_metrics (merge=False) 结果一致"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        rm.set_server_metrics({"a": 1}, ctx=ctx, merge=False)
        rm.set_server_metrics({"a": 1}, ctx=ctx, merge=False)
        assert rm.server_metrics == {"a": 1}
        assert ctx.metadata["server_metrics"] == {"a": 1}

    def test_set_server_metrics_idempotent_merge(self):
        """多次 set_server_metrics (merge=True) 第二次应保留第一次结果 (key 相同 value 相同)"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        rm.set_server_metrics({"a": 1, "b": 2}, ctx=ctx, merge=True)
        rm.set_server_metrics({"a": 1, "b": 2}, ctx=ctx, merge=True)
        # 合并结果应稳定
        assert rm.server_metrics == {"a": 1, "b": 2}
        assert ctx.metadata["server_metrics"] == {"a": 1, "b": 2}

    def test_set_plan_idempotent(self):
        """多次 set_plan 相同输入, 结果一致"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        rm.set_plan({"success": 1, "failed": 0}, ctx=ctx)
        rm.set_plan({"success": 1, "failed": 0}, ctx=ctx)
        assert rm.plan == {"success": 1, "failed": 0}
        assert ctx.metadata["plan"] == {"success": 1, "failed": 0}

    def test_set_stopped_by_idempotent(self):
        """多次 set_stopped_by 相同输入, 结果一致"""
        rm = RuntimeMetadata()
        ctx = self._make_ctx()
        rm.set_stopped_by("timeout", ctx=ctx)
        rm.set_stopped_by("timeout", ctx=ctx)
        assert rm.stopped_by == "timeout"
        assert ctx.metadata["stopped_by"] == "timeout"


# ─────────────────────────────────────────────────────────────
# TestReservedKeyConflict (T4) — 采纳 ChatGPT 9.88/10 Non-blocking
# ─────────────────────────────────────────────────────────────

class TestReservedKeyConflict:
    """T4: reserved key 冲突规则.

    明确: user plugin 写 ctx.runtime.custom["condition_eval"] 等 reserved key 时,
    RuntimeMetadata 应当 _不_阻止, 但 _文档化_ 这种行为是有意为之 (override 用).
    """

    def test_custom_does_not_reserve_keys(self):
        """set_custom() 不阻止 reserved key (允许 override)"""
        rm = RuntimeMetadata()
        # user plugin 故意写 reserved key
        rm.set_custom("condition_eval", "override_value")
        rm.set_custom("stopped_by", "custom_stop")
        # 写入了 custom 命名空间 (不污染顶级字段)
        assert rm.custom["condition_eval"] == "override_value"
        assert rm.custom["stopped_by"] == "custom_stop"
        # 顶级字段不变
        assert rm.condition_eval is None
        assert rm.stopped_by is None

    def test_reserved_keys_documented(self):
        """RUNTIME_RESERVED_KEYS 文档化所有 reserved namespace"""
        # reserved keys 用于 built-in Stage 强类型字段
        assert "server_metrics" in RUNTIME_RESERVED_KEYS
        assert "condition_eval" in RUNTIME_RESERVED_KEYS
        assert "stopped_by" in RUNTIME_RESERVED_KEYS
        assert "plan" in RUNTIME_RESERVED_KEYS
        # custom 是 user plugin namespace, 但它本身是 reserved 字段
        assert "custom" in RUNTIME_RESERVED_KEYS

    def test_user_plugin_can_use_custom_as_namespace_dict(self):
        """user plugin 用 custom 作为 namespace dict (推荐)"""
        rm = RuntimeMetadata()
        # 第三方 Plugin 标准用法
        rm.custom["my_plugin"] = {"trace_id": "abc", "version": "1.0"}
        rm.custom["other_plugin"] = {"enabled": True}
        # 验证 namespace 隔离
        assert rm.custom["my_plugin"]["trace_id"] == "abc"
        assert rm.custom["other_plugin"]["enabled"] is True
        # 不同 plugin 互不干扰
        assert len(rm.custom) == 2
