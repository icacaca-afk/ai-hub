# ADR-0007: Claude CLI Provider 集成

- **状态**: Accepted
- **日期**: 2026-07-13
- **里程碑**: V0.1.1
- **关联 Provider**: claude_cli (Claude Code CLI)

## 背景

CLIBridge 已经通过 Gemini CLI 和 QODER CLI 两个真实 Provider 验证过。这个 ADR
接入第三个真实 CLI Provider（Claude Code CLI），进一步验证 CLIBridge 在不同认证方式
（环境变量 vs OAuth 登录）下的稳定性。

## 命令格式

Claude Code CLI 的 Print 模式（非交互）：
```bash
claude -p "{task}"
```

- 命令名：`claude`
- 认证方式：`ANTHROPIC_API_KEY` 环境变量，或提前完成的 `claude login` OAuth 登录
- 文档：https://docs.claude.com/claude-code

## 暴露的新需求

**无。** CLIBridge 已有的 `command_template` 和 `env` 参数完全覆盖 Claude CLI 的需求，
和 Gemini CLI 的接入方式一致。

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
| `core/capabilities.py` | ❌ 未修改 | 使用的能力标签均已存在 |
| `router/router.py` | ❌ 未修改 | — |
| `core/bridge.py` | ❌ **未修改** | CLIBridge 的 command_template + env 参数已足够 |

> **✅ 零修改 core/ + bridge.py。**

## 决策

1. `authenticated()` 优先检查 `ANTHROPIC_API_KEY` 环境变量；如果未设置，退化为
   检查 CLI 是否可用（假设用户已通过 `claude login` 完成 OAuth 登录）。这是因为
   Claude CLI 没有独立的非交互 `auth status` 命令，和 QODER 遇到的问题一致，但
   处理方式更轻量（不发起真实调用去探测登录状态）。
2. `command_template` 使用 `claude -p "{task}"` 格式，和 Gemini 的 `-p` 参数风格一致。
3. Provider 优先级 85（介于 QODER 的 100 和 Gemini 的 80 之间），降级链
   `gemini_cli → demo`。

## 经验教训

- **CLIBridge 的 env 参数设计足够通用**：只在 `ANTHROPIC_API_KEY` 存在时才注入，
  不存在时留空字典，兼容"环境变量认证"和"OAuth 登录认证"两种模式，不需要改 Bridge。
- **不同 CLI 的认证方式差异很大**（Gemini 用环境变量，QODER 用浏览器登录，
  Claude CLI 两种都支持），`authenticated()` 应该继续由每个 Provider 自己实现，
  这个设计在第三个真实 Provider 上依然成立。
