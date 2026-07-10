# AI Hub

> One Task. Any AI. Any Runtime.

## Architecture Validation

| Bridge Type | Status | Real Provider Verified |
-------------|--------|----------------------|
| ✅ CLIBridge | Stable | Gemini CLI, QODER CLI, Stub |
| ✅ APIBridge | Stable | DeepSeek (OpenAI-compatible) |
| ⏳ GUIBridge | Planned | — |
| ⏳ BrowserBridge | Planned | — |

| KPI | Result |
|-----|--------|
| Zero Core Modification | ✅ `git diff core/ router/` = empty |
| Bridge API Frozen | ✅ V0.1.1 (Stable) |
| Contract Test | ✅ 6/6 passed |
| Skeleton Tests | ✅ 12/12 passed |
| ADRs | ✅ 4 published |

## Release Gate

Every release must pass:

- ✅ Contract Test (`tests/test_provider_contract.py`)
- ✅ Skeleton Tests (`tests/test_skeleton.py`)
- ✅ Zero Core Modification (`git diff core/ router/`)
- ✅ Documentation Updated
- ✅ ADR (if architecture changes)

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

> 完整指南见 [docs/provider_sdk.md](docs/provider_sdk.md)。
> 示例代码见 [examples/](examples/)。

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
┌────────────┐     ┌──────────────────┐
│   Bridge   │ ←──│ RuntimeRegistry   │  Runtime → Bridge 类型映射
└──────┬─────┘     └──────────────────┘
       ▼
┌────────────┐
│  Runtime   │  CLI / HTTP API / GUI (pyautogui) / Browser (Playwright)
└────────────┘
```

## Runtime Types

AI Hub 支持 4 种 Runtime，通过 Bridge 层统一接口：

| Runtime | Bridge | 依赖 | 适用场景 |
|---------|--------|------|---------|
| CLI | `CLIBridge` | subprocess | Gemini CLI, QODER, QClaw |
| HTTP API | `APIBridge` | urllib | OpenAI, Claude, DeepSeek |
| GUI | `GUIBridge` | pyautogui | Marvis, 桌面 AI 应用 |
| Browser | `BrowserBridge` | Playwright | Claude Web, ChatGPT Web |

### BrowserBridge (Playwright)

```python
from core.bridge import BrowserBridge
from core.task import Task

bridge = BrowserBridge(headless=True, browser_type="chromium")

# 方式 1: URL 自动导航 + 截图
task = Task.from_text("https://example.com")
result = bridge.run(task)

# 方式 2: 结构化 actions
task = Task.from_text("搜索 AI Hub", context={
    "actions": [
        {"action": "goto", "url": "https://google.com"},
        {"action": "input", "selector": "#search", "text": "AI Hub"},
        {"action": "click", "selector": "#search-btn"},
        {"action": "wait", "selector": "#results"},
        {"action": "screenshot", "name": "search_result"},
        {"action": "extract", "selector": "#result-count"},
    ]
})
result = bridge.run(task)
print(result.output)          # 执行日志
print(result.artifacts)       # ['/tmp/ai_hub_browser/search_result.png']
```

支持的 action：`goto` `wait` `input` `click` `screenshot` `extract` `scroll` `evaluate` `close`

### GUIBridge (pyautogui)

```python
from core.bridge import GUIBridge
from core.task import Task

bridge = GUIBridge(app_name="Marvis")

task = Task.from_text("GUI automation", context={
    "actions": [
        {"action": "move", "x": 500, "y": 300},
        {"action": "click", "x": 500, "y": 300},
        {"action": "type", "text": "Hello AI Hub"},
        {"action": "press", "key": "Enter"},
        {"action": "wait", "seconds": 2},
        {"action": "screenshot", "name": "result"},
    ]
})
result = bridge.run(task)
```

支持的 action：`move` `click` `type` `press` `screenshot` `wait` `scroll`

### RuntimeRegistry

```python
from core.runtime_registry import RuntimeRegistry

reg = RuntimeRegistry.default()

# 创建 Bridge 实例
bridge = reg.create_bridge("browser", headless=False)

# 注册自定义 Runtime
reg.register("my_runtime", MyBridge, description="custom")

# 查看可用 Runtime
print(reg.available_types())       # ['fake', 'cli', 'api', 'gui', 'browser']
print(reg.available_runtimes())   # 当前实际可用的
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
| Bridge | ✅ Stable (V0.1.1) | 从第二个 Provider 起接口不再修改。新需求走 ADR。 |
| RuntimeRegistry | ⚠ Experimental | V0.2 新增，接口可能调整 |
| GUIBridge | ⚠ Experimental | 已实现 MVP（pyautogui） |
| BrowserBridge | ⚠ Experimental | 已实现 MVP（Playwright） |

## Bridge Types

| Bridge | 通信方式 | 适用平台 | 状态 |
|--------|---------|---------|------|
| `FakeBridge` | 不通信 | 测试 / 骨架验证 | ✅ Stable |
| `CLIBridge` | CLI subprocess | Gemini CLI, QODER, QClaw | ✅ Stable |
| `APIBridge` | HTTP 请求 | OpenAI API, Claude API | ✅ Stable |
| `GUIBridge` | GUI 自动化 | Marvis, 桌面 AI 应用 | ✅ MVP (pyautogui) |
| `BrowserBridge` | 浏览器控制 | Claude Web, ChatGPT Web | ✅ MVP (Playwright) |

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
| V0.1 | 4 个真实 Provider + Contract | CLI + API + BrowserBridge + GUIBridge ✅ |
| V0.2 | Runtime 验证 | 4 种 Runtime 全部可跑通 |
| V0.3 | AI 智能路由 | LLM 分类替代关键词 |
| V0.5 | 任务分解 | 多步任务自动拆分 |
| V1.0 | Agent 编排 | 多 Provider 协同 + 飞书交付 |
| V2.0 | 插件生态 | 社区贡献 Provider |

详见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## License

MIT
