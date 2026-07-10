# AI Hub

> **One Task. Any AI. Any Runtime.**

Route one task to the best AI provider automatically.

```
Task → Router → Capability → Registry → Provider → Bridge → Runtime → Result
```

**新增 Provider 不允许修改 Router。**

## Quick Start

```bash
git clone https://github.com/<your-org>/ai-hub.git
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
from core.result import Result

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

    def execute(self, task, context=None):
        br = self._run_bridge(task)
        return self._bridge_to_result(br, self.name)
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
│  Provider  │  metadata（声明能力）+ execute（语法糖）
└──────┬─────┘
       ▼
┌────────────┐
│   Bridge   │  通信层（对 Provider 屏蔽 Runtime 细节）
└──────┬─────┘
       ▼
┌────────────┐
│  Runtime   │  CLI 进程 / HTTP API / GUI
└────────────┘
```

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
| Task | 用户提交的请求 |
| Capability | 系统识别出的能力标签，如 `code.generate` |
| Provider | 能力声明 + Bridge 选择策略，不负责通信细节 |
| Bridge | 与 Runtime 通信的实现层 |
| Runtime | 真正执行任务的 AI 平台实例 |
| Result | 统一结果格式 |
| CapabilityRegistry | Capability → Provider 的注册与查询中心 |
| Router | 根据 Capability 选择 Provider |

## Roadmap

| 版本 | 目标 | 成功标准 |
|------|------|---------|
| V0.0.5 | Bridge + Capability + Validation | 三种 Bridge 跑通同一接口 ✅ |
| V0.1 | 3 个真实 Provider | API + CLI + GUI 各一个，不改 Router |
| V0.3 | AI 智能路由 + GUIBridge | LLM 分类替代关键词 |
| V0.5 | 任务分解 | 多步任务自动拆分 |
| V1.0 | Agent 编排 | 多 Provider 协同 + 飞书交付 |
| V2.0 | 插件生态 | 社区贡献 Provider |

详见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## License

MIT
