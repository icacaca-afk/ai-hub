# CONTRIBUTING.md
## 如何为 AI Hub 贡献代码

> 感谢你有兴趣参与！这个项目的核心非常简单——只要你能实现一个接口，就能接入一个 AI 平台。

---

## 快速上手

```bash
# 1. 克隆仓库
git clone https://github.com/<your-org>/ai-hub.git
cd ai-hub

# 2. 运行骨架验证
python tests/test_skeleton.py

# 3. 用 Demo Provider 跑通端到端
python -m cli.main ask "你好"
```

---

## 如何新增一个 Provider

### 第一步：创建配置文件

在 `providers/` 目录下创建你的 Provider 目录和 YAML 配置：

```
providers/
└── your_platform/
    ├── __init__.py
    ├── provider.py      # 适配器代码
    └── your_platform.yaml  # 配置文件
```

配置文件模板（参考 `providers/qoder/qoder.yaml`）：

```yaml
provider: your_platform
display_name: YourPlatform
description: 一句话描述
version: "0.1.0"

capabilities:
  - coding          # 能力标签

task_types:
  - coding          # 支持的任务类型

priority: 50        # 优先级（0-100，越大越优先）
fallback:
  - gemini_cli      # 不可用时降级到谁

quota:
  type: daily
  total: 100
  remaining: 100
  auto_detect: false

health_check:
  method: cli
  command: "your_platform --version"
  expect_contains: "your_platform"
  timeout: 10

auth_check:
  method: cli
  command: "your_platform auth status"
  expect_contains: "logged in"
  timeout: 10

executor:
  type: cli
  command_template: "your_platform run \"{task}\""
  timeout: 300

status: enabled
```

### 第二步：实现适配器

继承 `Provider` 基类，实现 4 个方法：

```python
# providers/your_platform/provider.py

from core.provider import Provider
from core.result import Result


class YourPlatformProvider(Provider):
    name = "your_platform"
    display_name = "YourPlatform"
    description = "一句话描述"
    version = "0.1.0"

    capabilities = ["coding"]
    task_types = ["coding"]
    priority = 50
    fallback = ["gemini_cli"]

    def health(self) -> bool:
        # 检查服务是否在线（通常是检查 CLI 是否安装）
        ...

    def authenticated(self) -> bool:
        # 检查用户是否已登录
        ...

    def quota_left(self) -> int:
        # 返回剩余免费额度；无限制返回 -1
        ...

    def execute(self, task: str, context=None) -> Result:
        # 调用平台执行任务，返回统一格式的 Result
        ...
```

### 第三步：注册到 Registry

在 `cli/main.py` 的 `_build_registry()` 中添加：

```python
from providers.your_platform.provider import YourPlatformProvider
registry.register(YourPlatformProvider())
```

### 第四步：添加路由规则

在 `config/router_rules.yaml` 中，把你的 Provider 加到对应任务类型下。

### 第五步：测试

```bash
# 单独测试你的 Provider
python -m cli.main ask "测试任务"

# 跑全部测试
python tests/test_skeleton.py
```

### 第六步：提交 PR

```
1. Fork 仓库
2. 创建分支：git checkout -b add-your-platform
3. 提交：git commit -m "Add YourPlatform provider"
4. 推送：git push origin add-your-platform
5. 在 GitHub 上创建 Pull Request
```

---

## 代码规范

- Python 3.11+
- 类型标注必填（用 `typing` 模块）
- 每个方法必须有 docstring
- Result 格式不可修改（这是全项目的契约）
- Provider 接口不可修改（新增参数必须带默认值）

---

## 目录结构

```
ai-hub/
├── docs/               # 规划文档
├── providers/          # Provider 适配器
│   ├── base/           # (预留)
│   ├── demo/           # Demo Provider（骨架验证用）
│   ├── qoder/          # QODER 适配器
│   ├── gemini/         # Gemini CLI 适配器
│   └── qclaw/          # QClaw 适配器
├── router/             # 路由层
├── core/               # 核心数据结构（Provider 基类、Result、Registry）
├── cli/                # CLI 入口
├── config/             # 路由规则、关键词映射
├── history/            # 运行时任务记录
├── tests/              # 测试
├── pyproject.toml
├── .gitignore
└── README.md
```

---

## 版本规范

遵循 [Semantic Versioning](https://semver.org/)：

- **MAJOR**：Provider 接口不兼容的修改（尽量不做）
- **MINOR**：新增 Provider、新增功能（向后兼容）
- **PATCH**：Bug 修复

---

## 有问题？

- 提 [Issue](https://github.com/<your-org>/ai-hub/issues)
- 讨论区提问
- 查看 [DESIGN.md](docs/DESIGN.md) 了解设计决策
