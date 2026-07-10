# AI Hub — Provider Specification

> 版本：v0.0.6（冻结）
> 术语定义见 [GLOSSARY.md](GLOSSARY.md)

## Provider 接口

Provider 是能力描述与选择策略的声明。**Provider 不实现 execute()。**

### 必须定义

```python
class YourProvider(Provider):
    # 1. Metadata — 声明能力
    metadata = ProviderMetadata(
        name="your_platform",
        display_name="Your Platform",
        description="一句话描述",
        capabilities=["code.generate", "text.summarize"],
        priority=90,
        fallback=["demo"],
    )

    # 2. Bridge — 选择通信方式
    bridge = CLIBridge(command="your-cli")
```

### 必须实现（3 个方法）

```python
    def health(self) -> bool:
        """检查服务是否在线。"""

    def authenticated(self) -> bool:
        """检查用户是否已登录。"""

    def quota_left(self) -> int:
        """返回剩余免费额度。-1 = 无限制，0 = 不可用。"""
```

### 可选覆盖

```python
    def select_bridge(self, task: Task) -> Bridge:
        """选择 Bridge。默认返回 self.bridge。
        如果一个 Provider 支持多种通信方式，可根据 task 选择不同 Bridge。"""
        return self.bridge
```

### 不允许实现

```python
    # ❌ 不要实现 execute()
    # 执行由 Router 调 bridge.run(task) 完成
```

## Bridge 接口

Bridge 封装与 Runtime 的通信方式。

```python
class Bridge(ABC):
    def run(self, task: Task, **kwargs) -> BridgeResult:
        """执行任务，返回 BridgeResult。"""

    def check_available(self) -> bool:
        """检查 Bridge 是否可用。"""
```

### Bridge 类型

| Bridge | 通信方式 | 适用平台 | 状态 |
|--------|---------|---------|------|
| `FakeBridge` | 不通信 | 测试 | ✅ Stable |
| `CLIBridge` | CLI subprocess | QODER, Gemini CLI | ✅ Stable |
| `APIBridge` | HTTP 请求 | OpenAI API | ✅ Stable |
| `GUIBridge` | GUI 自动化 | Marvis | 🔜 V0.3 |
| `BrowserBridge` | 浏览器控制 | Claude Web | 🔜 V0.5 |

## Task 接口

```python
@dataclass
class Task:
    content: str                                    # 任务描述
    task_id: str                                    # 唯一标识符（自动生成）
    capabilities: list[str]                         # 识别出的能力标签
    context: dict[str, Any]                         # 上下文
    artifacts: list[str]                            # 输入产物文件路径
```

创建方式：

```python
task = Task.from_text("写一个 Python 服务")
# capabilities 自动识别
# task_id 自动生成
```

## Result 接口

```python
@dataclass
class Result:
    provider: str                                   # Provider 名称
    status: str                                     # success / failed / timeout / partial
    output: str                                     # 纯文本输出
    error: str | None = None                        # 错误详情
    artifacts: list[str] = []                       # 产物文件路径
    metadata: dict[str, Any] = {}                   # 执行元数据
```

`output` 永远是纯文本。截图、PDF、代码文件等产物走 `artifacts`。

## ProviderMetadata 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | str | ✅ | 唯一标识符 |
| display_name | str | ✅ | 用户可见名称 |
| description | str | ✅ | 一句话描述 |
| version | str | ❌ | 适配器版本，默认 "0.0.1" |
| capabilities | list[str] | ✅ | 能力标签列表 |
| priority | int | ❌ | 优先级，越大越优先，默认 0 |
| fallback | list[str] | ❌ | 降级链 |
| quota_type | str | ❌ | daily / monthly / unlimited / unknown |
| quota_total | int | ❌ | 总额度，-1 = 无限制 |
| quota_auto_detect | bool | ❌ | 是否自动检测 |
| cost_currency | str \| None | ❌ | 成本货币 |
| cost_amount | float | ❌ | 成本金额 |
| cost_unit | str | ❌ | 成本单位 |

## 30 分钟接入指南

### Step 1: 创建目录

```
providers/your_platform/
├── __init__.py
└── provider.py
```

### Step 2: 写 provider.py

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

**搞定。不改 Router、CLI、Registry 或任何其他代码。**
