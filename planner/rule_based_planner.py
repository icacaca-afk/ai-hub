# AI Hub — Rule-based Planner
# V0.9.0: 启发式任务分解（关键词 + 分隔符切分）
#
# ADR-0013: 极简分解，不做语义理解。单段不可切分则返回单步 Plan（退化）。
#
# 切分依据：
#   - 换行 / 中英文分号
#   - 连接关键词：然后 / 接着 / 之后 / 最后 / 再 / then / finally 等
#
# 已知限制（V0.9.0 接受，V0.9.1 LLM Planner 替代后消除）：
#   - 「再」会匹配到「再说」「再见」等非连接词场景
#   - 不做语义理解，无法处理隐式多步（如「总结并发送」）
#
# API Stability: Experimental

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from core.capabilities import classify
from core.task import Task
from planner.base import Planner
from planner.plan import Plan, Step


# 切分模式：换行 / 中英文分号 / 连接关键词
# 注意：「再」作为单字匹配有误切风险，V0.9.0 接受此限制
_SPLIT_PATTERN = re.compile(
    r"\n+"
    r"|；"
    r"|;"
    r"|然后"
    r"|接着"
    r"|之后"
    r"|最后"
    r"|再"
    r"|and\s+then"
    r"|then"
    r"|finally",
    re.IGNORECASE,
)


class RuleBasedPlanner(Planner):
    """基于规则的任务分解器。

    启发式切分：按分隔符和连接关键词把复合 Task 拆成多段。
    每段独立识别 capabilities，depends_on 默认线性链式。

    V0.9.0 范围：
        - 只做文本切分，不做语义理解
        - depends_on 默认线性链式（执行器不消费）
        - 单段不可切分 → 单步 Plan（退化，等价于直接走 Router）

    API Stability: Experimental
    """

    def decompose(self, task: Task) -> Plan:
        segments = _SPLIT_PATTERN.split(task.content)
        contents = [s.strip() for s in segments if s and s.strip()]

        steps: list[Step] = []
        for i, content in enumerate(contents):
            step = Step(
                step_id=f"step-{i}",
                content=content,
                capabilities=classify(content),
            )
            if i > 0:
                step.depends_on = [f"step-{i - 1}"]
            steps.append(step)

        # 退化：空 content 也返回单步（防御）
        if not steps:
            steps.append(Step(
                step_id="step-0",
                content=task.content,
                capabilities=task.capabilities,
            ))

        return Plan(
            plan_id=uuid.uuid4().hex[:12],
            task_id=task.task_id,
            steps=steps,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata={"planner": "rule_based", "version": "0.9.0"},
        )
