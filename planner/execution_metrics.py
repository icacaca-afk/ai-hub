# AI Hub — ExecutionMetrics
# V0.9.4: 可测量的执行指标（与 ExecutionResult 解耦）
#
# ADR-0017 D3（ChatGPT 关键建议）：
#   不要把 latency / token / cost / retry 塞进 ExecutionResult。
#   ExecutionResult 以后容易越来越胖（最后会像 Prometheus）。
#   建议单独 ExecutionMetrics。
#
# 字段（只含可测量字段，ChatGPT 强建议）：
#   - latency_ms / token_in / token_out / cost_usd / retry_count
# 不含：status / provider / error（这些是 Result，不是 Metrics）。
#
# V0.9.4 只填 latency_ms（最简单）。
# token_* / cost 留 V0.9.5+ 与 Provider 配合。
#
# 不修改 core/ + router/ + providers/（Core Freeze）。
#
# API Stability: Experimental

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionMetrics:
    """可测量的执行指标（V0.9.4）。

    单 Plan / 单 Step 都持有该结构。
    字段全部是「可测量」（latency / token / cost / retry）。

    V0.9.4 实施：
        - latency_ms: 由 Event 派生（provider_finished.latency_ms 或 step 间隔）

    未来扩展（保留注释，不启用）：
        # cache_hit: bool = False
        # queue_wait_ms: int = 0
        # network_latency_ms: int = 0
        # provider_latency_ms: int = 0
    """

    latency_ms: int = 0
    token_in: int = 0
    token_out: int = 0
    cost_usd: float = 0.0
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "latency_ms": self.latency_ms,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "cost_usd": self.cost_usd,
            "retry_count": self.retry_count,
        }

    def add(self, other: "ExecutionMetrics") -> None:
        """聚合另一个 metrics（用于 Plan 聚合层）。"""
        self.latency_ms += other.latency_ms
        self.token_in += other.token_in
        self.token_out += other.token_out
        self.cost_usd += other.cost_usd
        self.retry_count += other.retry_count
