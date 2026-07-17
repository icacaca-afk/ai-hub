# AI Hub — Planner 抽象基类
# V0.9: Task → Plan 分解策略的可插拔接口
#
# ADR-0013: V0.9.0 提供 RuleBasedPlanner，V0.9.1+ 可加 LLMPlanner。
#
# API Stability: Experimental

from __future__ import annotations

from abc import ABC, abstractmethod

from core.task import Task
from planner.plan import Plan


class Planner(ABC):
    """任务分解器抽象基类。

    将复合 Task 分解为多步 Plan。具体分解策略由子类实现：
    - RuleBasedPlanner（V0.9.0）：启发式关键词切分
    - LLMPlanner（V0.9.1+，规划）：用 chat-capable Provider 做语义分解

    API Stability: Experimental
    """

    @abstractmethod
    def decompose(self, task: Task) -> Plan:
        """将 Task 分解为 Plan。

        Args:
            task: 原始任务

        Returns:
            Plan 对象（含有序 Step 列表）
        """
        ...
