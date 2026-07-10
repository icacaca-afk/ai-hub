# ADR-0001: Gemini CLI Provider 集成

- **状态**: Accepted
- **日期**: 2026-07-11
- **里程碑**: V0.1

## 背景

V0.0.6 冻结后，第一个接入的真实 Provider。
目的是验证："新增一个 Provider 不需要修改 core/"。

## 暴露的新需求

Gemini CLI 真实运行后，Bridge 层需要处理以下 V0.0 FakeBridge 没有遇到的问题：

### 1. 自定义命令格式

Gemini CLI 的非交互调用语法：
```bash
gemini -p "{task}" -o text --yolo --skip-trust
```

与简单 `command "{task}"` 不同。**结论**: CLIBridge 引入 `command_template` 参数。

### 2. 环境变量注入

Gemini CLI 通过 `GEMINI_API_KEY` 环境变量认证。**结论**: CLIBridge 引入 `env` 参数。

### 3. 代理配置

用户环境使用系统代理 `127.0.0.1:10809`。在 Windows 上 `HTTPS_PROXY` 环境变量需要手动注入。**结论**: 这属于部署文档，不属于 Bridge 接口。

## 接口变更

| 变更 | 类型 | 影响 |
|------|------|------|
| `CLIBridge.__init__` 新增 `command_template: str \| None` | 新增可选参数 | 向后兼容 |
| `CLIBridge.__init__` 新增 `env: dict[str, str] \| None` | 新增可选参数 | 向后兼容 |
| `CLIBridge.run()` 内部将 `self.env` 合并进 `os.environ` | 行为变化 | 不影响 API |

## 架构验证结果

| 核心模块 | 是否修改 |
|---------|---------|
| `core/provider.py` | ❌ 未修改 |
| `core/registry.py` | ❌ 未修改 |
| `core/result.py` | ❌ 未修改 |
| `core/task.py` | ❌ 未修改 |
| `core/capabilities.py` | ❌ 未修改 |
| `router/router.py` | ❌ 未修改 |
| `core/bridge.py` | ✅ **修改（增强 CLIBridge）** |

> **第一次接入真实 Provider，Bridge 层被允许修改以暴露真实需求。**
> **从第二个 Provider 起，Bridge 接口冻结。**

## 决策

1. **冻结 CLIBridge 接口**：从第二个 Provider 起，`core/bridge.py` 不再修改。
   后续 Provider 如需新能力，必须：
   - (a) 走已有 `command_template` / `env` 参数组合，或
   - (b) 提出 ADR 申请 Bridge 升级（视为架构问题）。

2. **新增 KPI**：见 `README.md` "Zero-Modification Contract" 表格。

3. **新增 Contract Test**：见 `tests/test_provider_contract.py`。
   任何 Provider 必须通过，否则 CI 红。

## 经验教训

- **真实环境先于完美抽象**：先跑通一个真 Provider，再决定哪些抽象值得保留。
- **Bridge 是适配器，不是胶水**：它应该封装 Runtime 的怪癖，但不主动猜测。
- **文档驱动**：每个真实 Provider 都要写 ADR，记录"我们改了什么、为什么"。
