# ADR-0009: Health-aware Router

**Date**: 2026-07-15
**Status**: Accepted

## Context

V0.6 引入了 Health Framework（HealthReport + HealthRegistry），Provider 可以报告自身健康状态（healthy/degraded/unknown/unavailable）。

Router（`router/router.py`）在 V0.4.2 被 ADR-0008 冻结。Router 的 `route()` 只做 capability match + quota 过滤，不感知 Provider 健康状态。

V0.7 需要让 Router 在选 Provider 时跳过 unavailable 的 Provider，degraded 的降优先级。

## Decision

**新建 `router/health_router.py`，不修改 `router/router.py`。**

`HealthAwareRouter` 继承 `Router`，覆盖 `route()` 方法，在候选 Provider 列表上插入 Health Filter：

1. unavailable → 跳过
2. degraded → 分到兜底组
3. healthy + unknown → 优先组
4. priority 保持静态，不与健康状态混合

`execute()` 完全继承父类。

## Rationale

- ADR-0008 冻结 router/router.py，不能修改
- Health 是动态状态，priority 是静态能力描述，二者分离
- unknown 算可用（不阻断未实现 health() 的 Provider）
- Lazy Refresh + TTL 缓存，不引入后台线程

## Consequences

- `route()` 逻辑与父类有重复（capability match + fallback 链），这是 Core Freeze 的必要代价
- 未来如果引入 RouterPolicy pipeline，可以消除重复
- `last_route_reason` 属性记录路由决策原因，方便调试
- Fallback providers are intentionally not health-filtered in V0.7.0 because fallback represents the final recovery path. Recursive health-aware fallback is deferred.

## Future

- V0.7.1: Cost/Latency Policy
- V0.8: Smart Router（LLM 分类 / 动态模型选择）
