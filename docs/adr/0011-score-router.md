# ADR-0011: Score-based Router

**Date**: 2026-07-15
**Status**: Accepted
**Version**: V0.8.0

## Context

V0.7 HealthAwareRouter 使用 health 分组 + 静态 priority 选择 Provider。当多个 Provider 都 healthy 时，选择完全由 priority 决定，不考虑延迟、配额余量等因素。

V0.8 引入 Score Engine，用加权评分替代纯 priority 排序。

## Decision

新增 `router/score_router.py`（ScoreRouter 继承 HealthAwareRouter）。

### 评分公式

```
total = (capability×40 + health×25 + priority×20 + latency×10 + quota×5) / 100
```

### V0.8.0 范围

- **只做**：静态权重评分，latency 从 HealthReport 读取
- **不做**：LLM 判断 / 自动学习权重 / Prompt 分类 / 动态权重

### Score 各维度

| 维度 | 权重 | 评分规则 |
|------|------|----------|
| Capability | 40% | 匹配 capability 数量 / 请求总数 × 100 |
| Health | 25% | healthy=100, unknown=60, degraded=30, unavailable=0 |
| Priority | 20% | provider.metadata.priority / 100 × 100 |
| Latency | 10% | ≤1s=100, ≥10s=0, 线性插值, 无数据=50 |
| Quota | 5% | 有额度=100, 无额度=0 |

### 不修改

- `core/` — 不修改
- `router/router.py` — 不修改
- `router/health_router.py` — 不修改
- `providers/` — 不修改

## Consequences

- ScoreRouter 继承 HealthAwareRouter.route()，覆盖 route() 实现
- `last_scores` 属性记录所有候选 Provider 的评分明细
- `last_route_reason` 新增 `score` 字段
- Health Filter 逻辑与 HealthAwareRouter 一致（unavailable 跳过）
- Fallback 链不做评分（与 V0.7 一致）
- V0.9+ 可引入动态权重 / LLM 判断
