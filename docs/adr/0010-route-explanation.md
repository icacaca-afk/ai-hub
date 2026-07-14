# ADR-0010: Route Explanation

**Date**: 2026-07-15
**Status**: Accepted
**Version**: V0.7.1

## Context

V0.7.0 引入了 `HealthAwareRouter.last_route_reason`，但这是一个内部调试变量，用户不可见。

用户需要理解：
- 为什么选了 Provider A 而不是 Provider B？
- 哪些 Provider 被跳过了？为什么？
- Health 状态如何影响路由决策？

## Decision

新增 `ai-hub explain-route` CLI 命令，将 `last_route_reason` 产品化。

### 范围

- **只做**：展示路由决策过程（Task → Capabilities → Candidates → Decision）
- **不做**：Router 重构、Score 模型、Latency 排序、Cost 排序、AI 判断

### 实现

新增 `cli/explain_route.py`，在 `cli/main.py` 注册命令入口。

`explain-route` 使用 `HealthAwareRouter` 执行路由（不执行 Task），输出：
1. Task 内容和识别到的 capabilities
2. 所有候选 Provider 的 health/quota/priority/bridge 信息
3. 最终选择结果、所属组（healthy/degraded/fallback）、被跳过的 Provider

### V0.7.1 不修改

- `core/` — 不修改
- `router/` — 不修改
- `providers/` — 不修改
- `cli/main.py` — 仅新增命令注册（允许）

## Consequences

- `explain-route` 复用 `_build_registry()`，与 `cmd_ask`/`cmd_status` 保持一致
- `last_route_reason` 格式未来可能变化（V0.8 Score 模型），`explain-route` 输出格式跟随变化
- skipped 格式当前为 `list[str]`，V0.7.1 保持不变，未来可升级为 `list[dict]`
