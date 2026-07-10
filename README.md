# AI Hub

> One Task. One Capability. Any AI. Any Runtime.

## Why AI Hub?

Today's AI tools all have different interfaces:

```
QODER      → CLI
Claude     → API
Gemini     → CLI
Marvis     → GUI
OpenAI     → API
```

You learn each one. You switch between them. You lose context.

**AI Hub unifies execution — not models.**

One task in. The best available AI runs it. You get one result back.

```
Task → Capability → Provider → Bridge → Runtime → Result
```

## Philosophy

```
AI Hub does not unify AI models.
AI Hub unifies execution.

A task becomes a capability.
A capability selects a provider.
A provider selects a bridge.
A bridge communicates with a runtime.
```

All design decisions follow from this. Interfaces may add fields, Bridges may
add streaming, Providers may add health checks — but this chain never changes.

---

## Quick Start

```bash
git clone https://github.com/icacaca-afk/ai-hub.git
cd ai-hub

# 骨架验证（不需要任何外部服务）
python tests/test_skeleton.py

# 试用
python -m cli.main ask "写一个 Python HTTP 服务"
python -m cli.main caps      # 查看能力映射
python -m cli.main status    # 查看 Provider 状态
python -m cli.main history   # 查看历史
```

## Add a New Provider in 30 Minutes

只需要 3 步，**不改 Router、CLI、Registry 或任何其他代码**：

### Step 1: 创建目录

```
providers/your_platform/
├── __init__.py
└── provider.py
```

### Step 2: 写 provider.py（~20 行）

```python
from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge

class YourProvider(Provider):
    metadata = ProviderMetadata(
        name="your_platform",
        display_name="Your Platform",
        description="一句话描述",
        capabilities=["code.generate", "text.summarize"],
        priority=90,
        fallback=["demo"],
    )

    bridge = CLIBridge(command="your-cli")

    def health(self): return self.bridge.check_available()
    def authenticated(self): return self.bridge.check_auth()
    def quota_left(self): return -1
```

### Step 3: 注册 + 验证

```python
# cli/main.py → _build_registry() 中加一行
registry.register(YourProvider())
```

```bash
python tests/validate_provider.py
```

**搞定。** Router 自动按 Capability 路由。

## Architecture

```
┌────────────┐
│    User     │
└──────┬─────┘
       ▼
┌────────────┐
│    CLI     │  ask / history / status / caps / quota
└──────┬─────┘
       ▼
┌────────────┐
│   Router   │  Task → 关键词 → Capability
└──────┬─────┘
       ▼
┌────────────────────┐
│ CapabilityRegistry │  Capability → Provider（按优先级排序）
└──────┬─────────────┘
       ▼
┌────────────┐
│  Provider  │  metadata（声明能力）+ select_bridge(task) → Bridge
└──────┬─────┘  【不实现 execute()】
       ▼
┌────────────┐
│   Bridge   │  通信层（CLI / API / GUI / Browser）
└──────┬─────┘
       ▼
┌────────────┐
│  Runtime   │  CLI 进程 / HTTP API / GUI / 浏览器
└────────────┘
```

## Compatibility Promise

| API | Status | 含义 |
|-----|--------|------|
| Task | ✅ Stable | 数据结构不再变化 |
| Result | ✅ Stable | 数据结构不再变化 |
| Provider | ✅ Stable | 接口签名不再变化，新参数只能带默认值 |
| CapabilityRegistry | ✅ Stable | 方法签名不再变化 |
| Capability | ✅ Stable | 已定义的标签不会移除 |
| Router | ✅ Stable | 外部接口不变，内部实现可升级 |
| Bridge | ⚠ Experimental | V0.1 阶段接口可能调整 |
| GUIBridge | ⚠ Experimental | V0.3 实现 |
| BrowserBridge | ⚠ Experimental | V0.5 实现 |

## Bridge Types

| Bridge | 通信方式 | 适用平台 | 状态 |
|--------|---------|---------|------|
| `FakeBridge` | 不通信 | 测试 / 骨架验证 | ✅ Stable |
| `CLIBridge` | CLI subprocess | Gemini CLI, QODER, QClaw | ✅ Stable |
| `APIBridge` | HTTP 请求 | OpenAI API, Claude API | ✅ Stable |
| `GUIBridge` | GUI 自动化 | Marvis | 🔜 V0.3 |
| `BrowserBridge` | 浏览器控制 | Claude Web, ChatGPT Web | 🔜 V0.5 |

## Terminology

所有术语定义见 [docs/GLOSSARY.md](docs/GLOSSARY.md)。以下是要点：

| 名词 | 定义 |
|------|------|
| Task | 用户提交的请求（自然语言字符串） |
| Capability | 系统识别出的能力标签，如 `code.generate` |
| Provider | 能力声明 + Bridge 选择策略，不负责执行 |
| Bridge | 与 Runtime 通信的实现层 |
| Runtime | 真正执行任务的 AI 平台实例 |
| Result | 统一结果格式（output + artifacts） |
| CapabilityRegistry | Capability → Provider 的注册与查询中心 |
| Router | 根据 Capability 选择 Provider 并执行 |

## Roadmap

| 版本 | 目标 | 成功标准 |
|------|------|---------|
| V0.0.6 | 接口冻结 + 文档统一 | 12 测试通过 + 4 Provider Validation ✅ |
| V0.1 | 3 个真实 Provider | CLI + API + GUI 各一个，零修改核心接口 |
| V0.2 | 额度管理 | Quota Manager + 自动切换 |
| V0.3 | AI 智能路由 + GUIBridge | LLM 分类替代关键词 |
| V0.5 | 任务分解 | 多步任务自动拆分 |
| V1.0 | Agent 编排 | 多 Provider 协同 + 飞书交付 |
| V2.0 | 插件生态 | 社区贡献 Provider |

详见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## License

MIT
