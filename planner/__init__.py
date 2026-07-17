# AI Hub — Planner 包
# V0.9: 多步任务分解 + 子任务路由
#
# ADR-0013: V0.9.0 骨架，保持 Core Freeze（ADR-0008）。
# ADR-0017: V0.9.4 Execution Event + Metrics + Trace
#
# 用法：
#     from planner import PlanExecutor, RuleBasedPlanner, EventBus
#     from planner import ExecutionEvent, ExecutionMetrics
#     from planner import InMemoryTraceCollector
#
#     bus = EventBus()
#     trace = InMemoryTraceCollector()
#     trace.attach(bus)
#     executor = PlanExecutor(router=score_router, event_bus=bus)
#     result = executor.execute(task)
#
# API Stability: Experimental

from planner.plan import Plan, Step
from planner.base import Planner
from planner.rule_based_planner import RuleBasedPlanner
from planner.llm_planner import LLMPlanner
from planner.plan_validator import PlanValidator
from planner.plan_store import PlanStore
from planner.execution_event import ExecutionEvent
from planner.execution_metrics import ExecutionMetrics
from planner.event_bus import EventBus
from planner.trace_collector import InMemoryTraceCollector
from planner.executor import PlanExecutor

__all__ = [
    "Plan",
    "Step",
    "Planner",
    "RuleBasedPlanner",
    "LLMPlanner",
    "PlanValidator",
    "PlanStore",
    "ExecutionEvent",
    "ExecutionMetrics",
    "EventBus",
    "InMemoryTraceCollector",
    "PlanExecutor",
]
