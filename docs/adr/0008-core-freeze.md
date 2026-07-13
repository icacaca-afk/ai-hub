# ADR-0008: Core Freeze

**Date**: 2026-07-13
**Status**: Accepted
**Supersedes**: None

## Context

V0.0–V0.4 阶段建立了 ai-hub 的 Runtime 核心。经过 V0.4.2 cleanup（移除 MarvisProvider、统一 Result Error Schema、MCP Contract Test），core/ 和 router/ 已经稳定。

继续在 core/ 中添加功能会导致：
1. 接口不稳定，下游 Provider/Bridge/Adapter 跟着改
2. 代码审查焦点分散，无法区分"架构变更"和"能力扩展"
3. 新贡献者难以判断哪些文件可以改、哪些不能碰

## Decision

**冻结以下文件，除 Bug Fix 外不再修改：**

### core/
| 文件 | 职责 | 行数 |
|------|------|------|
| `core/__init__.py` | 包导出 | ~30 |
| `core/task.py` | Task dataclass（content/capabilities/context/artifacts） | ~50 |
| `core/result.py` | Result dataclass（status/output/error/artifacts/code/retryable） | ~70 |
| `core/provider.py` | Provider 抽象类 + ProviderMetadata | ~180 |
| `core/bridge.py` | Bridge 基类 + CLIBridge/APIBridge/FakeBridge/GUIBridge/BrowserBridge | ~900 |
| `core/registry.py` | CapabilityRegistry（register/find_available） | ~70 |
| `core/capabilities.py` | CAPABILITIES 常量注册表 | ~130 |
| `core/session.py` | SessionManager（create/checkpoint/resume/destroy） | ~180 |
| `core/quota.py` | QuotaManager（SQLite 持久化 + 事务安全） | ~250 |
| `core/runtime_registry.py` | RuntimeRegistry（bind/unbind/active_sessions） | ~60 |
| `core/history.py` | HistoryStore（SQLite 执行记录） | ~55 |

### router/
| 文件 | 职责 | 行数 |
|------|------|------|
| `router/router.py` | Router（route + execute，含 QuotaManager 集成） | ~120 |

## Freeze 规则

| 变更类型 | 允许？ | 流程 |
|----------|--------|------|
| Bug Fix | ✅ | 直接修，加回归测试 |
| 新增 Bridge 子类 | ✅ | 在 `providers/` 或 `bridges/` 中实现，不改 `core/bridge.py` |
| 新增 Provider | ✅ | 在 `providers/` 中实现，不改 `core/provider.py` |
| 新增 Adapter | ✅ | 在 `adapters/` 中实现 |
| 修改 core/ 接口签名 | ❌ | 需新 ADR 论证 |
| 修改 router/ 路由逻辑 | ❌ | 需新 ADR 论证 |
| 新增 core/ 文件 | ⚠️ | 需 discussion + ADR |

## 后续功能归属

| 功能 | 归属目录 | 不改 core/ |
|------|----------|------------|
| BrowserBridge 实现 | `bridges/` 或 `providers/fake_browser/` | ✅ |
| Planner（能力编排） | `planner/` | ✅ |
| AI Router（智能路由） | `router/` 下新文件或 `adapters/` | 不改 `router.py` 现有逻辑 |
| Workflow | `workflow/` | ✅ |
| 新 MCP Adapter | `adapters/` | ✅ |
| 新 Provider 接入 | `providers/<name>/` | ✅ |

## 与 ADR-0002/0003 关系

ADR-0002（Stub Provider）和 ADR-0003（CLIBridge Stability）记录了 V0.1 的接口冻结决策。本 ADR 将冻结范围从单个 Bridge/Provider 扩展到整个 core/ 和 router/。

## 里程碑

此 ADR 标志着 **V0.4.x 系列收口**，项目进入 **V0.5 Alpha（能力扩展）** 阶段。
