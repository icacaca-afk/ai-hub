# tests/test_plan_validator.py
# V0.9.2 — PlanValidator 单元测试
#
# 覆盖（ADR-0015）：
# - validate_steps_raw: 结构清洗（dict 列表）
# - validate: Plan 语义校验（step_id 重编号 / depends_on 修正 / capability 降级）
# - 边界场景：空输入 / 超限截断 / 自依赖 / 未知引用

import pytest

from planner.plan import Plan, Step
from planner.plan_validator import PlanValidator, MAX_STEPS


class TestValidateStepsRaw:
    """validate_steps_raw: LLM JSON 解析后的结构清洗。"""

    def test_valid_steps_pass_through(self):
        """合法的 step 列表原样通过。"""
        v = PlanValidator()
        raw = [
            {"content": "step a", "capabilities": ["general.chat"], "depends_on": []},
            {"content": "step b", "capabilities": ["text.translate"], "depends_on": ["step-0"]},
        ]
        cleaned, warnings = v.validate_steps_raw(raw)
        assert len(cleaned) == 2
        assert cleaned[0]["content"] == "step a"
        assert cleaned[1]["depends_on"] == ["step-0"]
        assert warnings == []

    def test_non_list_input(self):
        """非 list 输入返回空列表 + warning。"""
        v = PlanValidator()
        cleaned, warnings = v.validate_steps_raw({"not": "a list"})
        assert cleaned == []
        assert len(warnings) == 1
        assert "not a list" in warnings[0]

    def test_skip_non_dict_item(self):
        """非 dict 元素跳过。"""
        v = PlanValidator()
        cleaned, warnings = v.validate_steps_raw(["str", 123, {"content": "ok"}])
        assert len(cleaned) == 1
        assert cleaned[0]["content"] == "ok"
        assert len(warnings) == 2  # 两个被跳过

    def test_skip_empty_content(self):
        """空 content 跳过。"""
        v = PlanValidator()
        cleaned, warnings = v.validate_steps_raw([
            {"content": "", "capabilities": []},
            {"content": "   ", "capabilities": []},
            {"content": "valid", "capabilities": []},
        ])
        assert len(cleaned) == 1
        assert cleaned[0]["content"] == "valid"
        assert len(warnings) == 2

    def test_capabilities_not_list_defaults_to_chat(self):
        """capabilities 不是 list → 默认 general.chat。"""
        v = PlanValidator()
        cleaned, warnings = v.validate_steps_raw([
            {"content": "ok", "capabilities": "not a list"},
        ])
        assert cleaned[0]["capabilities"] == ["general.chat"]
        assert any("capabilities" in w for w in warnings)

    def test_depends_on_not_list_defaults_to_empty(self):
        """depends_on 不是 list → 默认空。"""
        v = PlanValidator()
        cleaned, warnings = v.validate_steps_raw([
            {"content": "ok", "depends_on": "step-0"},
        ])
        assert cleaned[0]["depends_on"] == []
        assert any("depends_on" in w for w in warnings)

    def test_truncate_over_limit(self):
        """step 数量超限截断到 MAX_STEPS。"""
        v = PlanValidator()
        raw = [{"content": f"step-{i}"} for i in range(MAX_STEPS + 5)]
        cleaned, warnings = v.validate_steps_raw(raw)
        assert len(cleaned) == MAX_STEPS
        assert any("exceeds limit" in w for w in warnings)

    def test_missing_capabilities_defaults_to_empty_list(self):
        """缺 capabilities 字段 → 空列表（validate 阶段再补 general.chat）。"""
        v = PlanValidator()
        cleaned, _ = v.validate_steps_raw([{"content": "ok"}])
        assert cleaned[0]["capabilities"] == []


class TestValidatePlan:
    """validate: Plan 语义校验。"""

    def test_valid_plan_no_warnings(self):
        """合法 Plan 无 warning。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="step-0", content="a", capabilities=["general.chat"]),
                Step(step_id="step-1", content="b", capabilities=["text.translate"], depends_on=["step-0"]),
            ],
        )
        validated, warnings = v.validate(plan)
        assert len(validated.steps) == 2
        assert warnings == []

    def test_drop_empty_content_step(self):
        """空 content 的 step 被丢弃。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="step-0", content="valid", capabilities=["general.chat"]),
                Step(step_id="step-1", content="", capabilities=["general.chat"]),
            ],
        )
        validated, warnings = v.validate(plan)
        assert len(validated.steps) == 1
        assert validated.steps[0].content == "valid"
        assert any("empty content" in w for w in warnings)

    def test_renumber_step_ids(self):
        """step_id 自动重编号为 step-0/step-1/..."""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="weird-id-1", content="a", capabilities=["general.chat"]),
                Step(step_id="another-id", content="b", capabilities=["general.chat"]),
            ],
        )
        validated, _ = v.validate(plan)
        assert validated.steps[0].step_id == "step-0"
        assert validated.steps[1].step_id == "step-1"

    def test_drop_self_dependency(self):
        """自依赖被丢弃。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="step-0", content="a", capabilities=["general.chat"], depends_on=["step-0"]),
            ],
        )
        validated, warnings = v.validate(plan)
        assert validated.steps[0].depends_on == []
        assert any("self-dependency" in w for w in warnings)

    def test_drop_unknown_dependency(self):
        """引用不存在的 step_id 被丢弃。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="step-0", content="a", capabilities=["general.chat"], depends_on=["nonexistent"]),
            ],
        )
        validated, warnings = v.validate(plan)
        assert validated.steps[0].depends_on == []
        assert any("unknown" in w for w in warnings)

    def test_unknown_capability_downgraded(self):
        """未知 capability 记 warning 并降级 general.chat。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="step-0", content="a", capabilities=["fake.capability.v3"]),
            ],
        )
        validated, warnings = v.validate(plan)
        assert "general.chat" in validated.steps[0].capabilities
        assert "fake.capability.v3" not in validated.steps[0].capabilities
        assert any("unknown capability" in w for w in warnings)

    def test_empty_caps_filled_with_chat(self):
        """空 capabilities 列表补 general.chat。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="step-0", content="a", capabilities=[]),
            ],
        )
        validated, _ = v.validate(plan)
        assert validated.steps[0].capabilities == ["general.chat"]

    def test_empty_plan_after_validation(self):
        """所有 step 都无效 → Plan 保持空 steps + warning。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="step-0", content="", capabilities=["general.chat"]),
            ],
        )
        validated, warnings = v.validate(plan)
        assert len(validated.steps) == 0
        assert any("no valid steps" in w for w in warnings)

    def test_truncate_over_limit(self):
        """step 超限截断。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[Step(step_id=f"step-{i}", content=f"s{i}", capabilities=["general.chat"]) for i in range(MAX_STEPS + 3)],
        )
        validated, warnings = v.validate(plan)
        assert len(validated.steps) == MAX_STEPS
        assert any("exceeds limit" in w for w in warnings)

    def test_depends_on_remapped_after_renumber(self):
        """重编号后 depends_on 引用同步更新。"""
        v = PlanValidator()
        plan = Plan(
            plan_id="p1",
            task_id="t1",
            steps=[
                Step(step_id="weird-1", content="a", capabilities=["general.chat"]),
                Step(step_id="weird-2", content="b", capabilities=["general.chat"], depends_on=["weird-1"]),
            ],
        )
        validated, _ = v.validate(plan)
        # 重编号后 step-1 依赖 step-0
        assert validated.steps[1].step_id == "step-1"
        assert validated.steps[1].depends_on == ["step-0"]
