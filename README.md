# AI Hub

> **One command. Multiple providers. Free-first routing.**

AI Hub 是一个能够自动调用多个 AI 工具、优先使用免费额度完成任务的统一入口。

说一句话，系统自动选最合适的免费平台，返回结果。你不需要知道背后是谁干的。

## Why?

2026 年，你手上有 QODER、Gemini CLI、QClaw、ChatGPT、Coze……每次完成任务都要手动判断用哪个、查额度、切换平台。

**问题不是没有工具，而是工具太多。**

AI Hub 解决这个问题：

```
ai-hub ask "写一个 Python HTTP 服务"
  → [Router] 识别为 coding 任务
  → [Provider] 选择 QODER（额度充足，优先级最高）
  → 返回代码
```

额度用完？自动切换：

```
ai-hub ask "搜索 Rust 1.80 新特性"
  → [Router] 识别为 search 任务
  → [Provider] Gemini CLI 不可用 → 自动切到 QClaw
  → 返回结果
```

## Quick Start

```bash
# 克隆
git clone https://github.com/<your-org>/ai-hub.git
cd ai-hub

# 跑通骨架验证（使用 Demo Provider，不需要任何外部服务）
python tests/test_skeleton.py

# 试用
python -m cli.main ask "你好"
python -m cli.main status
python -m cli.main history
```

## Features

| 功能 | 状态 |
|------|------|
| Provider 管理（多平台接入） | ✅ V0.0 骨架 |
| 规则路由（关键词 + 优先级） | ✅ V0.0 骨架 |
| 统一 CLI | ✅ V0.0 骨架 |
| 统一结果格式 | ✅ V0.0 骨架 |
| 历史记录 | ✅ V0.0 骨架 |
| 免费额度管理 | 🔜 V0.2 |
| AI 智能路由 | 🔜 V0.3 |
| 任务分解 | 🔜 V0.5 |
| Agent 编排 | 🔜 V1.0 |
| 插件生态 | 🔜 V2.0 |

## Architecture

```
┌────────────────┐
│   CLI Entry    │
└───────┬────────┘
        ▼
┌────────────────┐
│    Router      │  ← 规则路由（V0.1）→ AI 路由（V0.3）
└───────┬────────┘
        ▼
┌────────────────┐
│    Registry    │  ← Provider 注册中心 + 额度管理
└───────┬────────┘
    ┌───┼───┬───────┐
    ▼   ▼   ▼       ▼
 QODER Gemini QClaw ChatGPT  ← 各平台适配器（统一接口）
    │   │   │       │
    └───┴───┴───────┘
            ▼
    ┌────────────────┐
    │  Result Store   │  ← 统一结果格式 + 历史记录
    └────────────────┘
```

## Add a New Provider

只需要 3 步：

1. 创建 `providers/your_platform/` 目录
2. 继承 `Provider` 基类，实现 4 个方法：`health()` / `authenticated()` / `quota_left()` / `execute()`
3. 注册到 Registry

**不需要修改 Router、CLI 或其他 Provider 的代码。**

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## Design Philosophy

- **Provider 接口是项目最核心的资产**——一旦定义，长期不变
- **渐进式架构**——每一层可以独立升级，不需要推翻重来
- **配置驱动**——能力描述、路由规则全部外置为 YAML
- **免费优先**——Router 优先选择有免费额度的 Provider

详见 [DESIGN.md](DESIGN.md)。

## Roadmap

| 版本 | 目标 | 状态 |
|------|------|------|
| V0.0 | Skeleton（骨架验证） | ✅ |
| V0.1 | AI 聚合器（3 个真实 Provider） | 🔜 |
| V0.2 | 额度管理 + Web UI | 📋 |
| V0.3 | AI 智能路由 | 📋 |
| V0.5 | 任务分解 | 📋 |
| V1.0 | Agent 编排 | 📋 |
| V2.0 | 插件生态 | 📋 |

详见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## License

MIT

---

**Use all your free AI quotas through one unified interface.**
