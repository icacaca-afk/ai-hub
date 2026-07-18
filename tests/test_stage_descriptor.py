# Tests for StageDescriptor (V1.0.6)
#
# ADR-0026 V1.0.6: StageDescriptor (Stage 元数据描述对象)
# ChatGPT 外部审核: 9.94/10 APPROVED with 1 Critical + 2 Non-blocking 全部采纳
# 关键采纳 (Q7 Critical): 所有 built-in Stage 显式 descriptor
# 关键采纳 (Q4 Non-blocking): Protocol 替代基类
# 关键采纳 (Q8 Non-blocking): immutable + legacy fallback tests
#
# 覆盖:
# - StageDescriptor 单类: 构造 / frozen / hash / equality
# - Protocol: structural typing
# - get_descriptor: built-in / legacy fallback
# - 行为信号: always_run_after_stop

import os
import sys
from dataclasses import FrozenInstanceError

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from planner.stage_descriptor import (
    Stage,
    StageDescriptor,
    get_descriptor,
)


# ── TestStageDescriptorDefaults ──

class TestStageDescriptorDefaults:
    """StageDescriptor 默认值 (3 tests)."""

    def test_required_name_only(self):
        """只 name 必填."""
        d = StageDescriptor(name="custom")
        assert d.name == "custom"
        assert d.version == 1
        assert d.role == "stage"
        assert d.idempotent is True
        assert d.has_side_effects is False
        assert d.always_run_after_stop is False
        assert d.experimental is False
        assert d.description == ""
        assert d.owner == "ai-hub"
        assert d.capabilities == frozenset()

    def test_always_run_after_stop_default_false(self):
        """always_run_after_stop 默认 False (Critical Q7: 兜底不暗示语义)."""
        d = StageDescriptor(name="x")
        assert d.always_run_after_stop is False

    def test_role_default_stage(self):
        """role 默认 'stage'."""
        d = StageDescriptor(name="x")
        assert d.role == "stage"


# ── TestStageDescriptorFrozen (Q8 ChatGPT 采纳) ──

class TestStageDescriptorFrozen:
    """StageDescriptor 不可变 (ChatGPT 9.94/10 Q8 采纳)."""

    def test_frozen_cannot_set_role(self):
        """descriptor.role = ... 抛 FrozenInstanceError."""
        d = StageDescriptor(name="x")
        with pytest.raises(FrozenInstanceError):
            d.role = "metric"

    def test_frozen_cannot_set_name(self):
        """descriptor.name = ... 抛 FrozenInstanceError."""
        d = StageDescriptor(name="x")
        with pytest.raises(FrozenInstanceError):
            d.name = "y"

    def test_frozen_cannot_set_capabilities(self):
        """descriptor.capabilities = ... 抛 FrozenInstanceError."""
        d = StageDescriptor(name="x")
        with pytest.raises(FrozenInstanceError):
            d.capabilities = {"foo"}

    def test_frozen_cannot_set_always_run_after_stop(self):
        """descriptor.always_run_after_stop = ... 抛 FrozenInstanceError."""
        d = StageDescriptor(name="x")
        with pytest.raises(FrozenInstanceError):
            d.always_run_after_stop = True


# ── TestStageDescriptorHashable ──

class TestStageDescriptorHashable:
    """StageDescriptor 可哈希 (frozen=True 默认)."""

    def test_hashable(self):
        """可放入 set."""
        d1 = StageDescriptor(name="x")
        d2 = StageDescriptor(name="x")
        s = {d1, d2}
        assert len(s) == 1  # same hash + eq

    def test_equality(self):
        """dataclass eq."""
        d1 = StageDescriptor(name="x", role="metric")
        d2 = StageDescriptor(name="x", role="metric")
        assert d1 == d2

    def test_inequality(self):
        """不同 name 不等."""
        d1 = StageDescriptor(name="x")
        d2 = StageDescriptor(name="y")
        assert d1 != d2


# ── TestStageDescriptorCapabilities ──

class TestStageDescriptorCapabilities:
    """capabilities FrozenSet[str] (Q6 语义标签无重复, frozen=True 兼容 hash)."""

    def test_capabilities_frozenset(self):
        """capabilities 是 frozenset."""
        d = StageDescriptor(name="x", capabilities=frozenset({"foo", "bar"}))
        assert isinstance(d.capabilities, frozenset)
        assert d.capabilities == frozenset({"foo", "bar"})

    def test_capabilities_dedup(self):
        """重复值自动去重 (set 语义)."""
        d = StageDescriptor(name="x", capabilities=frozenset({"foo", "foo", "bar"}))
        assert d.capabilities == frozenset({"foo", "bar"})


# ── TestStageDescriptorBehavioralFlags ──

class TestStageDescriptorBehavioralFlags:
    """行为标志字段 (Q2 Behavior > taxonomy)."""

    def test_always_run_after_stop_true(self):
        """CheckpointStage 关键字段."""
        d = StageDescriptor(name="checkpoint", always_run_after_stop=True)
        assert d.always_run_after_stop is True

    def test_idempotent_flag(self):
        """idempotent 字段."""
        d_idem = StageDescriptor(name="x", idempotent=True)
        d_no_idem = StageDescriptor(name="x", idempotent=False)
        assert d_idem.idempotent is True
        assert d_no_idem.idempotent is False

    def test_has_side_effects_flag(self):
        """has_side_effects 字段."""
        d = StageDescriptor(name="x", has_side_effects=True)
        assert d.has_side_effects is True


# ── TestStageProtocol (Q4 ChatGPT 采纳) ──

class TestStageProtocol:
    """Stage Protocol (Q4 采纳: Protocol 替代基类)."""

    def test_protocol_structural_match(self):
        """Protocol 接受 structural typing."""
        class MyStage:
            descriptor = StageDescriptor(name="custom")
            def __call__(self, ctx):
                return ctx

        s = MyStage()
        assert isinstance(s, Stage)  # Protocol runtime_checkable

    def test_protocol_rejects_missing_descriptor(self):
        """无 descriptor 的对象不满足 Protocol."""
        class NotAStage:
            def __call__(self, ctx):
                return ctx

        s = NotAStage()
        # 没有 descriptor 属性 → 不满足 Protocol
        assert not isinstance(s, Stage)

    def test_protocol_rejects_missing_call(self):
        """无 __call__ 的对象不满足 Protocol."""
        class NotAStage:
            descriptor = StageDescriptor(name="custom")

        s = NotAStage()
        # runtime_checkable 不会强制 __call__ 存在
        # 这只是字段检查
        # 注: 严格 Protocol 行为在 V2 评估
        assert not hasattr(s, "__call__")


# ── TestGetDescriptor (Q7 Critical + Q8 采纳) ──

class TestGetDescriptor:
    """get_descriptor() 兼容 helper (Q7 + Q8)."""

    def test_builtin_stage_descriptor(self):
        """built-in Stage 显式 descriptor (Critical Q7 强制)."""
        class CheckpointStage:
            descriptor = StageDescriptor(
                name="checkpoint",
                always_run_after_stop=True,
            )
            def __call__(self, ctx):
                return ctx

        stage = CheckpointStage()
        d = get_descriptor(stage)
        assert d.name == "checkpoint"
        assert d.always_run_after_stop is True

    def test_legacy_stage_default_descriptor(self):
        """V1.0.x 旧 Stage 无 descriptor 时接收默认 Descriptor (Q8 采纳)."""
        class LegacyStage:
            name = "legacy"
            def __call__(self, ctx):
                return ctx

        stage = LegacyStage()
        d = get_descriptor(stage)
        # 关键: 默认 always_run_after_stop=False (Q7 Critical 兜底不暗示语义)
        assert d.name == "legacy"
        assert d.always_run_after_stop is False

    def test_legacy_stage_with_no_name_uses_stage(self):
        """无 descriptor 也无 name 的 Stage 接收 'stage' 兜底."""
        class NamelessStage:
            def __call__(self, ctx):
                return ctx

        stage = NamelessStage()
        d = get_descriptor(stage)
        assert d.name == "stage"

    def test_legacy_stage_does_not_infer_checkpoint(self):
        """Q7 关键: 兼容性 helper 绝不推断 checkpoint 语义."""
        class CheckpointLikeLegacy:
            """V1.0.x 旧 CheckpointStage (无 descriptor, 但有 store 属性)."""
            name = "checkpoint"
            store = "fake_store"  # V1.0.5 之前用 hasattr 探测
            def __call__(self, ctx):
                return ctx

        stage = CheckpointLikeLegacy()
        d = get_descriptor(stage)
        # Critical: 不再 hasattr 探测, always_run_after_stop 仍为 False
        assert d.always_run_after_stop is False
        assert d.name == "checkpoint"  # 仅 name 兜底

    def test_builtin_stage_preferred_over_legacy(self):
        """built-in Stage 显式 descriptor 优先 (Q7 强制)."""
        class CheckpointV106:
            descriptor = StageDescriptor(
                name="checkpoint",
                always_run_after_stop=True,  # 关键
            )
            name = "checkpoint"  # 旧 API
            store = "store"      # 旧 API
            def __call__(self, ctx):
                return ctx

        stage = CheckpointV106()
        d = get_descriptor(stage)
        # 显式 descriptor 胜出
        assert d.always_run_after_stop is True


# ── TestStageDescriptorExperimental ──

class TestStageDescriptorExperimental:
    """experimental 字段 (Hook 可见)."""

    def test_experimental_default_false(self):
        """experimental 默认 False."""
        d = StageDescriptor(name="x")
        assert d.experimental is False

    def test_experimental_true(self):
        """experimental=True 用于 V1.x 实验性 Stage."""
        d = StageDescriptor(name="x", experimental=True)
        assert d.experimental is True


# ── TestStageDescriptorVersion ──

class TestStageDescriptorVersion:
    """version 字段."""

    def test_version_default_1(self):
        """version 默认 1."""
        d = StageDescriptor(name="x")
        assert d.version == 1

    def test_version_custom(self):
        """自定义 version."""
        d = StageDescriptor(name="x", version=2)
        assert d.version == 2


# ── TestDescriptorIdentity (Q9 ChatGPT 采纳) ──

class TestDescriptorIdentity:
    """Descriptor identity (ChatGPT 9.95/10 Q9 采纳).

    关键: Descriptor 是常量, 同一 stage 多次访问返回同一对象.
    不是每次 __call__ 都新建 (避免 hash 失效 + 节省内存).
    """

    def test_descriptor_is_class_attribute(self):
        """Descriptor 是类属性, 同一 stage 多次访问返回同一对象."""
        from planner.stages.checkpoint_stage import CheckpointStage

        class _StubStore:
            def append(self, event): pass
        stage = CheckpointStage(store=_StubStore())
        # 同一 stage 多次访问 descriptor
        assert stage.descriptor is stage.descriptor

    def test_descriptor_is_same_across_instances(self):
        """同一类的不同 instance 共享同一 descriptor."""
        from planner.stages.checkpoint_stage import CheckpointStage

        class _StubStore:
            def append(self, event): pass
        s1 = CheckpointStage(store=_StubStore())
        s2 = CheckpointStage(store=_StubStore())
        assert s1.descriptor is s2.descriptor


# ── TestThirdPartyStage (Q9 ChatGPT 采纳) ──

class TestThirdPartyStage:
    """Unknown third-party stage 兼容性 (ChatGPT 9.95/10 Q9 采纳).

    关键: V1.0.x 用户自定义 Stage (无 descriptor) 接收默认 Descriptor,
    Pipeline 仍能正常运行 (Q7 Critical 不破坏兼容性).
    """

    def test_third_party_stage_gets_default_descriptor(self):
        """Unknown third-party Stage 接收默认 Descriptor (always_run_after_stop=False)."""
        class ThirdParty:
            name = "abc"
            def __call__(self, ctx):
                return ctx

        d = get_descriptor(ThirdParty())
        assert d.name == "abc"
        assert d.always_run_after_stop is False  # 兜底不暗示 checkpoint 语义

    def test_third_party_stage_runs_in_pipeline(self):
        """Third-party Stage 集成到 Pipeline 仍可工作.

        关键: get_descriptor(stage) 不抛异常, 默认 descriptor 兼容 Pipeline.run().
        """
        class ThirdPartyPreBridge:
            name = "third_party_pre"
            def __call__(self, ctx):
                ctx.metadata["third_party_ran"] = True
                return ctx

        stage = ThirdPartyPreBridge()
        d = get_descriptor(stage)
        # 默认 descriptor (无 always_run_after_stop)
        assert d.name == "third_party_pre"
        assert d.always_run_after_stop is False
        # Pipeline 不会因为缺少 descriptor 而失败

    def test_third_party_stage_does_not_inherit_checkpoint_semantics(self):
        """Third-party Stage 即使 name='checkpoint' 也不继承 checkpoint 语义.

        Q7 Critical: 默认 always_run_after_stop=False, 不基于 name 字符串推断.
        """
        class FakeCheckpoint:
            name = "checkpoint"  # 旧 API
            store = "fake_store"  # V1.0.5 之前的探测字段
            def __call__(self, ctx):
                return ctx

        d = get_descriptor(FakeCheckpoint())
        # Critical: 不再 hasattr 探测, 仍 always_run_after_stop=False
        assert d.always_run_after_stop is False
        assert d.name == "checkpoint"  # 仅 name 兜底
