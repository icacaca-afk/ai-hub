# AI Hub — Plan Validator
# V0.9.2: Plan 语义校验（与 Planner 解耦）
#
# ADR-0015: LLM 输出属于不可信输入（untrusted input），必须校验后才能构建 Plan。
# PlanValidator 独立于 Planner，所有 Planner 产出（RuleBased / LLM / Web）共用一套验证。
#
# 校验规则：
#   - step 数量限制（≤32）
#   - content 非空
#   - depends_on 引用合法（不存在则忽略）
#   - 无自依赖（step-i 不能依赖 step-i）
#   - 无重复 step_id（自动重编号避免冲突）
#   - capability 未知 → 记 warning，降级 general.chat
#
# API Stability: Experimental

from __future__ import annotations

import logging
from typing import Any

from core.capabilities import CAPABILITIES
from planner.plan import Plan, Step


logger = logging.getLogger(__name__)


# V0.9.2 硬约束：单 Plan 最多 32 步（防止 LLM 生成失控）
MAX_STEPS = 32

# 已知 capability 集合（用于校验 LLM 返回的标签）
_KNOWN_CAPABILITIES = set(CAPABILITIES.keys())


class PlanValidator:
    """Plan 语义校验器。

    与 Planner 解耦：所有 Planner 产出都应过一遍 validate()。
    校验失败不抛异常，而是返回修正后的 Plan（best-effort）+ warnings 列表。

    API Stability: Experimental
    """

    def validate(self, plan: Plan) -> tuple[Plan, list[str]]:
        """校验并修正 Plan。

        Args:
            plan: 待校验的 Plan

        Returns:
            (修正后的 Plan, warnings 列表)
        """
        warnings: list[str] = []

        # 1. step 数量限制
        if len(plan.steps) > MAX_STEPS:
            warnings.append(f"Step count {len(plan.steps)} exceeds limit {MAX_STEPS}, truncated")
            plan.steps = plan.steps[:MAX_STEPS]

        # 2. 过滤 content 为空的 step
        valid_steps: list[Step] = []
        for step in plan.steps:
            if not step.content or not step.content.strip():
                warnings.append(f"Step {step.step_id} has empty content, dropped")
                continue
            valid_steps.append(step)
        plan.steps = valid_steps

        if not plan.steps:
            warnings.append("Plan has no valid steps after validation")
            return plan, warnings

        # 3. 重新编号 step_id（避免 LLM 返回的 id 冲突或格式不一）
        old_to_new: dict[str, str] = {}
        for i, step in enumerate(plan.steps):
            old_id = step.step_id
            new_id = f"step-{i}"
            if old_id != new_id:
                old_to_new[old_id] = new_id
                step.step_id = new_id

        # 4. 修正 depends_on
        valid_step_ids = {s.step_id for s in plan.steps}
        for i, step in enumerate(plan.steps):
            cleaned_deps: list[str] = []
            for dep in step.depends_on:
                # 映射旧 id 到新 id
                dep_mapped = old_to_new.get(dep, dep)
                # 自依赖检查
                if dep_mapped == step.step_id:
                    warnings.append(f"Step {step.step_id} self-dependency dropped")
                    continue
                # 引用合法性检查
                if dep_mapped not in valid_step_ids:
                    warnings.append(f"Step {step.step_id} depends on unknown '{dep}', dropped")
                    continue
                cleaned_deps.append(dep_mapped)
            step.depends_on = cleaned_deps

        # 5. capability 校验
        for step in plan.steps:
            normalized_caps: list[str] = []
            for cap in step.capabilities:
                if cap in _KNOWN_CAPABILITIES:
                    normalized_caps.append(cap)
                else:
                    logger.warning(
                        "Step %s has unknown capability '%s', downgraded to general.chat",
                        step.step_id, cap,
                    )
                    warnings.append(f"Step {step.step_id} unknown capability '{cap}' -> general.chat")
                    if "general.chat" not in normalized_caps:
                        normalized_caps.append("general.chat")
            if not normalized_caps:
                normalized_caps = ["general.chat"]
            step.capabilities = normalized_caps

        return plan, warnings

    def validate_steps_raw(self, raw_steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        """校验原始 dict 列表（LLM JSON 解析后、构建 Step 前）。

        用于 LLMPlanner 在构造 Step 之前先做结构清洗。

        Args:
            raw_steps: LLM 返回的 JSON 数组（已 json.loads）

        Returns:
            (清洗后的 dict 列表, warnings 列表)
        """
        warnings: list[str] = []

        if not isinstance(raw_steps, list):
            warnings.append("LLM output is not a list")
            return [], warnings

        cleaned: list[dict[str, Any]] = []
        for i, item in enumerate(raw_steps):
            if not isinstance(item, dict):
                warnings.append(f"Step [{i}] is not a dict, skipped")
                continue

            content = item.get("content")
            if not content or not isinstance(content, str) or not content.strip():
                warnings.append(f"Step [{i}] has empty/invalid content, skipped")
                continue

            # capabilities 规整
            caps = item.get("capabilities", [])
            if not isinstance(caps, list):
                warnings.append(f"Step [{i}] capabilities is not a list, defaulted to general.chat")
                caps = ["general.chat"]

            # depends_on 规整
            deps = item.get("depends_on", [])
            if not isinstance(deps, list):
                warnings.append(f"Step [{i}] depends_on is not a list, defaulted to empty")
                deps = []

            cleaned.append({
                "content": content.strip(),
                "capabilities": [str(c) for c in caps],
                "depends_on": [str(d) for d in deps],
            })

        # 数量限制
        if len(cleaned) > MAX_STEPS:
            warnings.append(f"Step count {len(cleaned)} exceeds limit {MAX_STEPS}, truncated")
            cleaned = cleaned[:MAX_STEPS]

        return cleaned, warnings
