# ADR-0003: QODER CLI Provider 集成

- **状态**: Accepted
- **日期**: 2026-07-11
- **里程碑**: V0.1.1
- **关联 Provider**: qoder (Qoder CN CLI)

## 背景

V0.1 Gemini CLI 接入后，V0.1.1 的目标是验证"第二个真实 CLI Provider 接入，core/ 和 bridge.py 零修改"。

## 命令格式

Qoder CN CLI 的 Print 模式（非交互）：
```bash
qoderclicn -p "{task}"
```

- 命令名：`qoderclicn`（非 `qoder`）
- 认证方式：Browser Login（首次浏览器登录，之后 token 缓存）
- 版本：v1.0.14
- 文档：https://help.aliyun.com/zh/lingma/qodercli-cn/product-overview/what-is-qoder-cli-cn

## 暴露的新需求

**无。** CLIBridge 的 `command_template` 和 `version_command` 参数完全覆盖 QODER 的需求。

## 接口变更

| 变更 | 类型 | 向后兼容 | 影响范围 |
|------|------|---------|---------|
| 无 | — | — | — |

## 架构验证结果

| 核心模块 | 是否修改 | 原因 |
|---------|---------|------|
| `core/provider.py` | ❌ 未修改 | — |
| `core/registry.py` | ❌ 未修改 | — |
| `core/result.py` | ❌ 未修改 | — |
| `core/task.py` | ❌ 未修改 | — |
| `core/capabilities.py` | ❌ 未修改 | — |
| `router/router.py` | ❌ 未修改 | — |
| `core/bridge.py` | ❌ **未修改** | CLIBridge 的 command_template 已有参数足够 |

> **✅ 零修改 core/ + bridge.py。CLIBridge 接口冻结后第一个验证通过的 Provider。**

## 决策

1. `authenticated()` 方法不使用 `auth_command`（qoderclicn 没有 `auth status` 非交互命令），改为用 `qoderclicn -p "ping"` 是否返回结果来判断。
2. `command_template` 使用 `qoderclicn -p "{task}"` 格式。
3. Provider 优先级 100（最高），降级链 `gemini_cli → demo`。

## 端到端验证

```
Task: Write a Python function that reverses a string.
Capabilities: ['code.generate']
Bridge: CLIBridge
Template: qoderclicn -p "{task}"

Result:
  Success: True
  Duration: 6944ms
  Output: def reverse_string(s: str) -> str: return s[::-1]
```

## 经验教训

- **CLIBridge 的 command_template 设计是对的**：Gemini 暴露的需求（自定义命令格式）在 QODER 这里直接复用，零修改。
- **认证检查没有统一方案**：Gemini 用环境变量，QODER 用 Browser Login token。`authenticated()` 应该由 Provider 自己实现，不是 Bridge 的职责。
- **官方文档很重要**：一开始用 `qoder` 作为命令名（来自旧代码猜测），实际是 `qoderclicn`。看了阿里云官方文档才纠正。
