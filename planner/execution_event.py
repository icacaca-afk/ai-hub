# AI Hub — ExecutionEvent
# V0.9.4: 执行事件数据类（Single Source of Execution Truth）
#
# ADR-0017: 8 种 event_type
#   - plan_started / planner_started / planner_finished
#   - step_started / provider_selected / provider_finished / step_finished
#   - plan_finished
#
# 字段语义（ChatGPT 审核建议）：
#   - event_id: 唯一键（UUID，区别于 timestamp）
#   - type / timestamp: 事件类型 + 触发时间
#   - plan_id: 关联 Plan
#   - step_id: 关联 Step（plan-level event 为 None）
#   - provider: provider-level event 携带
#   - latency_ms: 仅显式记录 Provider latency（Step/Plan 由 Consumer 派生）
#   - data: 自由扩展字段（避免主结构膨胀）
#
# 不修改 core/ + router/ + providers/（Core Freeze）。
#
# API Stability: Experimental

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    """当前 UTC 时间（ISO 8601，毫秒精度）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class ExecutionEvent:
    """执行事件（V0.9.4）。

    Event 类型列表（ADR-0017 D1）：

    - ``plan_started``         PlanExecutor.execute 入口
    - ``planner_started``      Planner.decompose 入口
    - ``planner_finished``     Planner.decompose 返回
    - ``step_started``         每个 Step 开始执行
    - ``provider_selected``    Router 选定 Provider
    - ``provider_finished``    Provider.execute 返回（含 latency_ms）
    - ``step_finished``        每个 Step 结束
    - ``plan_finished``        PlanExecutor.execute 出口

    单进程内顺序调用，不需要锁。
    """

    type: str
    plan_id: str
    timestamp: str = field(default_factory=_now_iso)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    step_id: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: Optional[int] = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（Postel's Law：尽量保守输出）。"""
        return {
            "event_id": self.event_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "data": dict(self.data),
        }
