# AI Hub

> One Task. Any AI. Any Runtime.

## Status: V0.5.0-alpha (Core Frozen)

**Core Freeze (ADR-0008)**：`core/` 和 `router/` 除 Bug Fix 外不再修改。
后续功能全部通过 `providers/`、`bridges/`、`adapters/`、`planner/`、`workflow/` 扩展。

## Architecture Validation

| Bridge Type | Status | Real Provider Verified |
|-------------|--------|----------------------|
| ✅ FakeBridge | Stable | Demo Provider |
| ✅ CLIBridge | Stable (ADR-0002/0003) | Gemini CLI, QODER, Stub |
| ✅ APIBridge | Stable | DeepSeek (OpenAI-compatible) |
| ⚠️ GUIBridge | Experimental | — (V0.4 GUI 路线失败, ADR-0006) |
| ⏳ BrowserBridge | Planned (V0.5) | — |

| KPI | Result |
|-----|--------|
| Core Freeze | ✅ ADR-0008 |
| Zero Core Modification | ✅ `git diff core/ router/` = empty |
| Bridge API Frozen | ✅ V0.1.1 (Stable) |
| Provider Contract Test | ✅ 6/6 passed |
| MCP Contract Test | ✅ 7/7 passed |
| Skeleton Tests | ✅ 12/12 passed |
| Total Tests | ✅ 63 passed, 1 skipped, 1 deselected |
| ADRs | ✅ 8 published |

## Release Gate

Every release must pass:

- ✅ Provider Contract Test (`tests/test_provider_contract.py`)
- ✅ MCP Contract Test (`tests/test_mcp_contract.py`)
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
Marvis     → MCP Client
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

All design decisions follow from this. This chain never changes.

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
python -m cli.main history  # 查看历史
```

## Add a New Provider in 30 Minutes

> 完整指南见 [docs/provider_sdk.md](docs/provider_sdk.md)。

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

## MCP Integration

ai-hub 可作为 MCP Server 暴露给任何 MCP 客户端（Marvis、Claude Desktop、Cursor 等）：

```
MCP Client (Marvis / Cursor / Claude Desktop)
    ↓ stdio (JSON-RPC)
ai-hub MCP Server (adapters/marvis_mcp_server.py)
    ↓
CapabilityRegistry → Provider → Bridge → Result
```

3 个 MCP Tools：
- `run_provider(task)` — 执行任务，返回结构化 Result
- `list_providers()` — 列出所有 Provider 及状态
- `list_capabilities()` — 列出所有能力标签

```bash
# 配置 Marvis 调用 ai-hub
python scripts/configure_marvis_mcp.py
```

详见 [ADR-0007](docs/adr/0007-marvis-integration-via-mcp.md)。

## Architecture

```
┌────────────┐
│    User     │   CLI / MCP Client
└──────┬─────┘
       ▼
┌────────────┐
│   Router    │   Task → Capability → Provider
└──────┬─────┘
       ▼
┌────────────────────┐
│ CapabilityRegistry │   Capability → Provider（按优先级排序）
└──────┬─────────────┘
       ▼
┌────────────┐
│  Provider   │   metadata + select_bridge(task) → Bridge
└──────┬─────┘   【不实现 execute()】
       ▼
┌────────────┐     ┌──────────────────┐
│   Bridge    │ ←──│ RuntimeRegistry  │   session → bridge 绑定
└──────┬─────┘     └──────────────────┘
       ▼
┌────────────┐
│   Runtime   │   CLI / HTTP API / GUI / Browser
└────────────┘
```

## Compatibility Promise (Core Frozen — ADR-0008)

| API | Status | 含义 |
|-----|--------|------|
| Task | ✅ Frozen | 数据结构不再变化 |
| Result | ✅ Frozen | 数据结构不再变化（含 code + retryable） |
| Provider | ✅ Frozen | 接口签名不再变化 |
| CapabilityRegistry | ✅ Frozen | 方法签名不再变化 |
| Router | ✅ Frozen | 外部接口不变 |
| Bridge | ✅ Frozen (V0.1.1) | 新需求走 ADR |
| Session | ✅ Frozen | 全生命周期稳定 |
| QuotaManager | ✅ Frozen | SQLite + 事务安全 |
| RuntimeRegistry | ✅ Frozen | bind/unbind/active_sessions |
| HistoryStore | ✅ Frozen | SQLite 执行记录 |

**冻结后规则**：新功能 → `providers/` / `bridges/` / `adapters/` / `planner/` / `workflow/`。不改 `core/` 和 `router/router.py`。

## Terminology

所有术语定义见 [docs/GLOSSARY.md](docs/GLOSSARY.md)。

## Roadmap

### V0.0–V0.4：建立 Runtime 核心 ✅

| 版本 | 目标 |
|------|------|
| V0.0.6 | 接口冻结 + 文档统一 |
| V0.1 | 真实 Provider 接入 + Contract |
| V0.2 | 额度管理（QuotaManager） |
| V0.3 | Session + Runtime 生命周期 |
| V0.4 | Marvis 集成探索 → MCP 反向集成 → Core Freeze |

### V0.5–V0.8：扩展 Runtime 能力

| 版本 | 目标 |
|------|------|
| **V0.5 Alpha** | BrowserBridge（能力扩展） |
| **V0.6 Alpha** | Planner（能力编排） |
| **V0.7 Alpha** | AI Router（智能路由） |
| **V0.8 Beta** | Workflow |

### V1.0+：稳定版与生态

| 版本 | 目标 |
|------|------|
| V1.0 | 稳定版（API 冻结） |
| V2.0 | 插件生态（社区贡献 Provider） |

详见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## ADRs

| # | Title | Status |
|---|-------|--------|
| 0002 | Stub Provider (CLIBridge Stable) | Accepted |
| 0003 | CLIBridge Stability | Accepted |
| 0006 | Marvis GUI Bridge (Failed) | superseded by 0007 |
| 0007 | Marvis Integration via MCP | Accepted |
| 0008 | Core Freeze | Accepted |

## License

MIT
