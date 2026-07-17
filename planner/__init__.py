# AI Hub — Planner 包
# V0.9: 多步任务分解 + 子任务路由
#
# ADR-0013: V0.9.0 骨架，保持 Core Freeze（ADR-0008）。
#
# 用法：
#     from planner import PlanExecutor, RuleBasedPlanner
#     executor = PlanExecutor(router=score_router)
#     result = executor.execute(task)
#
# API Stability: Experimental

from planner.plan import Plan, Step
from planner.base import Planner
from planner.rule_based_planner import RuleBasedPlanner
from planner.executor import PlanExecutor

__all__ = [
    "Plan",
    "Step",
    "Planner",
    "RuleBasedPlanner",
    "PlanExecutor",
]
