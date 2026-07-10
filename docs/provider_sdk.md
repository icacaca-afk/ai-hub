# Provider Development Guide

> 30 分钟写一个 Provider，不改 `core/`、`router/`、`bridge.py`。

## Quick Start

### 1. 复制模板

```bash
cp -r examples/stub/ providers/your_platform/
```

### 2. 改 4 个地方

| 位置 | 改什么 |
|------|--------|
| `metadata.name` | 你的 Provider 名字（小写，下划线） |
| `metadata.capabilities` | 你的 Provider 支持的能力标签 |
| `bridge` | CLIBridge 或 APIBridge 的参数 |
| `health/authenticated/quota_left` | 状态检查逻辑 |

### 3. 注册到 CLI

在 `cli/main.py` 的 `_build_registry()` 中加两行：

```python
from providers.your_platform.provider import YourProvider
registry.register(YourProvider())
```

### 4. 跑测试

```bash
python tests/test_provider_contract.py   # Contract Test
python tests/test_skeleton.py             # 全量测试
```

## Bridge 选择指南

| 你的 Runtime 类型 | 用哪个 Bridge | 示例 |
|-------------------|--------------|------|
| CLI 工具 | `CLIBridge` | Gemini CLI, QODER CLI, Claude CLI |
| HTTP API | `APIBridge` | OpenAI API, DeepSeek API |
| GUI 应用 | `GUIBridge` | Marvis (预留) |
| 浏览器 | `BrowserBridge` | Claude Web (预留) |
| 测试用 | `FakeBridge` | Demo Provider |

## CLIBridge 参数

```python
CLIBridge(
    command="qoderclicn",                          # CLI 命令名
    command_template='qoderclicn -p "{task}"',     # 自定义命令格式（{task} 占位）
    version_command="qoderclicn --version",        # 版本检查命令
    auth_command=None,                              # 认证检查命令（可选）
    timeout=300,                                    # 超时秒数
    env={"GEMINI_API_KEY": "xxx"},                  # 环境变量注入（可选）
)
```

## APIBridge 参数

```python
APIBridge(
    endpoint="https://api.deepseek.com/v1/chat/completions",
    api_key_env="DEEPSEEK_API_KEY",    # 环境变量名
    method="POST",
    timeout=60,
    headers={},                         # 额外 headers
)
```

> **注意**：APIBridge 的默认 `run()` 发送的 body 格式不是 OpenAI 格式。
> 如果需要 OpenAI 兼容格式，继承 APIBridge 并重写 `run()`。
> 参考 `providers/openai_api/provider.py` 中的 `OpenAICompatBridge`。

## Provider Checklist

- [ ] `metadata.name` 唯一，小写+下划线
- [ ] `metadata.capabilities` 中的标签都存在于 `core/capabilities.py` 的 `CAPABILITIES`
- [ ] `metadata.fallback` 中的 Provider 名字存在
- [ ] `bridge` 已设置（CLIBridge / APIBridge / FakeBridge）
- [ ] `health()` 返回 bool
- [ ] `authenticated()` 返回 bool
- [ ] `quota_left()` 返回 int（-1 表示无限）
- [ ] 没有 `execute()` 方法（V0.0.6 已移除）
- [ ] Contract Test 通过
- [ ] 端到端调用验证通过

## Bridge Checklist

- [ ] **不修改 `core/bridge.py`**（Bridge API 已冻结）
- [ ] 如果默认 Bridge 不满足需求，在 Provider 目录内创建子类
- [ ] 子类继承 `CLIBridge` / `APIBridge`，不继承 `Bridge` 基类

## Contract Test Checklist

```bash
python tests/test_provider_contract.py
```

检查项：
1. metadata 存在且完整（name, capabilities, priority, fallback）
2. bridge 存在且有 run() / check_available()
3. health / authenticated / quota_left 方法存在
4. 没有 execute()（V0.0.6 已移除）
5. 实例化成功
6. supports() 返回 bool
7. select_bridge() 返回 bridge 实例
8. 声明的 capability 都在 CAPABILITIES 注册表中

## ADR

每个真实 Provider 接入都需要写 ADR：

```bash
cp docs/adr/TEMPLATE.md docs/adr/00NN-your-provider.md
```

记录：
- 暴露了什么新需求
- core/ 是否修改（应为 ❌）
- Bridge 是否修改（应为 ❌）
- 端到端验证结果

## FAQ

**Q: 我的 CLI 工具需要特殊的命令格式怎么办？**

A: 用 `command_template` 参数。例如 `gemini -p "{task}" -o text`。

**Q: APIBridge 的 body 格式不兼容我的 API 怎么办？**

A: 继承 APIBridge，重写 `run()`。参考 `providers/openai_api/provider.py`。

**Q: 我需要新增一个 Capability 标签怎么办？**

A: 在 `core/capabilities.py` 的 `CAPABILITIES` 字典中添加。这是允许的修改（不是接口变更）。

**Q: 我的 Provider 需要环境变量怎么传？**

A: CLIBridge 有 `env` 参数。APIBridge 通过 `api_key_env` 自动检测。

**Q: 如何选择优先级？**

A: 100 = 最高（如 QODER），80 = 高（如 Gemini），50 = 中（如 OpenAI），10 = 最低（如 Stub/Demo）。
