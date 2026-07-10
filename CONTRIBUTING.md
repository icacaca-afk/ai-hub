# Contributing to AI Hub

## Quick Start

```bash
git clone https://github.com/<your-org>/ai-hub.git
cd ai-hub
python tests/test_skeleton.py
```

## Add a New Provider (3 步)

### Step 1: 创建目录

```
providers/your_platform/
├── __init__.py
├── provider.py
└── manifest.yaml    # 可选
```

### Step 2: 实现 Provider（~30 行）

```python
from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge    # 或 APIBridge
from core.result import Result

class YourProvider(Provider):
    metadata = ProviderMetadata(
        name="your_platform",
        display_name="Your Platform",
        description="一句话描述",
        capabilities=["code.generate"],  # 见 core/capabilities.py 中的完整列表
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

### Step 3: 注册

```python
# cli/main.py → _build_registry()
from providers.your_platform.provider import YourProvider
registry.register(YourProvider())
```

### 验证

```bash
python tests/validate_provider.py
```

## Bridge 选择

| 场景 | Bridge | 示例 |
|------|--------|------|
| 平台提供 CLI 工具 | `CLIBridge` | Gemini CLI, QODER |
| 平台提供 HTTP API | `APIBridge` | OpenAI API, Claude API |
| 测试 / 骨架验证 | `FakeBridge` | DemoProvider |
| GUI 自动化 | `GUIBridge` (V0.3) | Marvis |

## Capability 标签

在 `core/capabilities.py` 中定义。如果现有标签不覆盖你的场景，可以新增：

```python
# core/capabilities.py
CAPABILITIES = {
    ...
    "image.generate": "生成图片",  # 新增
}
```

## Code Style

- Python 3.11+
- 类型标注必填
- dataclass 优先（不引入 Pydantic）
- 零额外依赖（标准库优先）
- Windows 兼容（不用 emoji 以外的非 ASCII 字符在代码中）

## Directory Structure

```
ai-hub/
├── core/               # 核心代码（稳定接口）
│   ├── provider.py     # Provider 基类 + ProviderMetadata
│   ├── bridge.py       # Bridge 层（CLI / API / Fake）
│   ├── capabilities.py # 能力标签定义 + 关键词映射
│   ├── registry.py     # Provider 注册中心
│   ├── result.py       # 统一结果格式
│   └── history.py      # 历史记录
├── router/             # 路由器
│   └── router.py       # Task → Capability → Provider
├── providers/          # Provider 适配器（每个平台一个目录）
│   ├── demo/           # DemoProvider (FakeBridge)
│   ├── qoder/          # QODER (CLIBridge)
│   ├── gemini/         # Gemini CLI (CLIBridge)
│   └── openai_api/     # OpenAI API (APIBridge)
├── cli/                # CLI 入口
├── config/             # 配置文件
├── tests/              # 测试 + 验证脚本
└── docs/               # 文档
```
