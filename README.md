# AI Hub

> **One command. Multiple providers. Free-first routing.**

AI Hub 让你在 30 分钟内接入任意 AI 平台——API、CLI、GUI，同一套接口，同一套路由。

```
You
 ↓
CLI
 ↓
Router ──→ Capability ──→ Registry
                            ↓
                        Provider
                            ↓
                         Bridge ──→ CLI subprocess
                                  ──→ HTTP API
                                  ──→ GUI automation
```

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
├── provider.py      # 你的 Provider 实现
└── manifest.yaml    # 元信息（可选，也可在代码中声明）
```

### Step 2: 写 provider.py（~30 行）

```python
from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge    # 或 APIBridge / FakeBridge
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
# cli/main.py 的 _build_registry() 中加一行
registry.register(YourProvider())
```

```bash
# 验证
python tests/validate_provider.py
```

**搞定。** Router 会自动按 capability 路由到你的 Provider。

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
│   Router   │  Task → 关键词 → Capability → Provider
└──────┬─────┘
       ▼
┌────────────┐
│  Registry  │  按 capability 查找 + 优先级排序
└──────┬─────┘
       ▼
┌────────────┐
│  Provider  │  metadata + 4 个方法
└──────┬─────┘
       ▼
┌────────────┐
│   Bridge   │  CLIBridge / APIBridge / FakeBridge (未来: GUIBridge)
└──────┬─────┘
       ▼
┌────────────┐
│  Runtime   │  subprocess / HTTP / GUI
└────────────┘
```

## Bridge Types

| Bridge | 通信方式 | 适用平台 | 状态 |
|--------|---------|---------|------|
| `FakeBridge` | 不通信 | 测试 / 骨架验证 | ✅ Stable |
| `CLIBridge` | CLI subprocess | Gemini CLI, QODER, QClaw | ✅ Stable |
| `APIBridge` | HTTP 请求 | OpenAI API, Claude API | ✅ Stable |
| `GUIBridge` | GUI 自动化 | Marvis, 桌面应用 | 🔜 V0.3 |

## API Stability

| API | 状态 | 含义 |
|-----|------|------|
| Provider API | **Stable** | 接口签名不再变化，新参数只能带默认值 |
| Result API | **Stable** | 数据结构不再变化 |
| Registry API | **Stable** | 方法签名不再变化 |
| Capability API | **Stable** | 能力标签定义不再移除 |
| Bridge API | **Experimental** | V0.1 阶段接口可能调整 |
| Router API | **Stable** | 路由逻辑内部可变，外部接口不变 |

## Capabilities

能力标签采用命名空间格式 `domain.action`：

| 标签 | 说明 |
|------|------|
| `code.generate` | 生成代码 |
| `code.debug` | 调试代码 |
| `code.refactor` | 重构代码 |
| `code.review` | 代码审查 |
| `text.summarize` | 总结文本 |
| `text.analyze` | 分析文本 |
| `text.translate` | 翻译文本 |
| `text.generate` | 生成文本 |
| `search.web` | 搜索网络 |
| `search.local` | 本地搜索 |
| `file.organize` | 整理文件 |
| `file.transform` | 文件转换 |
| `general.chat` | 通用对话 |

## Provider Validation

每个 Provider 自动验证 7 项检查：

```bash
python tests/validate_provider.py
```

检查项：metadata → capabilities → bridge → available() → quota_left() → execute() → supports()

GitHub Action 自动在每次 PR 时运行验证。

## Roadmap

| 版本 | 目标 | 成功标准 |
|------|------|---------|
| V0.0.5 | Bridge + Capability + Validation | 三种 Bridge 跑通同一接口 ✅ |
| V0.1 | 3 个真实 Provider | API + CLI + GUI 各一个，不改 Router |
| V0.2 | 额度管理 + Web UI | 可视化额度状态 |
| V0.3 | AI 智能路由 | LLM 分类替代关键词 |
| V0.5 | 任务分解 | 多步任务自动拆分 |
| V1.0 | Agent 编排 | 多 Provider 协同 |
| V2.0 | 插件生态 | 社区贡献 Provider |

## License

MIT
