# AI Hub — LLM Planner
# V0.9.2: 用 chat-capable Provider 做语义任务分解
#
# ADR-0015: LLMPlanner 通过构造函数注入 Router（与 PlanExecutor 共享同一实例）。
# 降级链：LLMPlanner → RuleBasedPlanner → 单步 Plan。
#
# LLM 输出属于不可信输入（untrusted input），必须经过 PlanValidator 校验后才能构建 Plan。
#
# API Stability: Experimental

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from core.task import Task
from planner.base import Planner
from planner.plan import Plan, Step
from planner.plan_validator import PlanValidator
from planner.prompts import build_decompose_prompt
from planner.rule_based_planner import RuleBasedPlanner


logger = logging.getLogger(__name__)


# LLM 返回的 JSON 可能被 ```json ... ``` 包裹，用正则提取
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMPlanner(Planner):
    """基于 LLM 的语义任务分解器。

    通过 chat-capable Provider 调用 LLM，让模型分解复合任务。
    降级策略：任何失败都降级到 RuleBasedPlanner。

    架构约束（ADR-0015）：
        - 与 PlanExecutor 共享同一个 Router 实例（Router 无状态，多消费者安全）
        - 只在 decompose() 阶段调 Router，不参与 Step 执行
        - LLM 输出必须过 PlanValidator 校验

    API Stability: Experimental
    """

    def __init__(self, router: Any):
        """
        Args:
            router: Router 实例（与 PlanExecutor 共享同一个）
        """
        self.router = router
        # 降级用 RuleBasedPlanner（不依赖 Router，纯规则）
        self._fallback = RuleBasedPlanner()
        self._validator = PlanValidator()

    def decompose(self, task: Task) -> Plan:
        """将 Task 用 LLM 语义分解为 Plan。

        失败时降级到 RuleBasedPlanner。
        """
        try:
            raw_json = self._call_llm(task)
            if raw_json is None:
                logger.warning("LLMPlanner: LLM returned empty, fallback to RuleBasedPlanner")
                return self._fallback.decompose(task)

            steps_data = self._parse_json(raw_json)
            if steps_data is None:
                logger.warning("LLMPlanner: JSON parse failed, fallback to RuleBasedPlanner")
                return self._fallback.decompose(task)

            # 结构清洗（dict 列表）
            cleaned, raw_warnings = self._validator.validate_steps_raw(steps_data)
            for w in raw_warnings:
                logger.warning("LLMPlanner: %s", w)

            if not cleaned:
                logger.warning("LLMPlanner: no valid steps after cleaning, fallback to RuleBasedPlanner")
                return self._fallback.decompose(task)

            # 构建 Step 列表
            steps: list[Step] = []
            for i, item in enumerate(cleaned):
                step = Step(
                    step_id=f"step-{i}",
                    content=item["content"],
                    capabilities=item["capabilities"],
                    depends_on=item["depends_on"],
                )
                steps.append(step)

            # 构建 Plan 并做语义校验
            plan = Plan(
                plan_id=uuid.uuid4().hex[:12],
                task_id=task.task_id,
                steps=steps,
                created_at=datetime.now(timezone.utc).isoformat(),
                metadata={"planner": "llm", "version": "0.9.2"},
            )
            plan, plan_warnings = self._validator.validate(plan)
            for w in plan_warnings:
                logger.warning("LLMPlanner: %s", w)

            if not plan.steps:
                logger.warning("LLMPlanner: plan has no steps after validation, fallback to RuleBasedPlanner")
                return self._fallback.decompose(task)

            return plan

        except Exception as e:
            logger.warning("LLMPlanner: decompose failed (%s), fallback to RuleBasedPlanner", e)
            return self._fallback.decompose(task)

    def _call_llm(self, task: Task) -> str | None:
        """调用 Router 路由到 chat-capable Provider，返回 LLM 文本输出。

        Returns:
            LLM 返回的文本，失败返回 None
        """
        prompt = build_decompose_prompt(task.content)

        # 构造分解子任务（强制 chat 能力）
        decompose_task = Task.from_text(prompt, capabilities=["general.chat"])

        result = self.router.execute(decompose_task)

        if not result.is_success:
            logger.warning("LLMPlanner: router execute failed: %s", result.error)
            return None

        return result.output

    def _parse_json(self, raw: str) -> list[dict[str, Any]] | None:
        """从 LLM 文本中提取 JSON 数组。

        支持：
        - 纯 JSON 数组
        - ```json ... ``` 包裹的 JSON

        Returns:
            解析后的 dict 列表，失败返回 None
        """
        if not raw or not raw.strip():
            return None

        text = raw.strip()

        # 尝试提取 ```json ... ``` 包裹的内容
        fence_match = _JSON_FENCE_PATTERN.search(text)
        if fence_match:
            text = fence_match.group(1).strip()

        # 尝试直接解析
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到第一个 [ 和最后一个 ]，提取数组部分
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None

        if not isinstance(parsed, list):
            return None

        return parsed
