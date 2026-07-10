# ADR-0002: Stub Provider 架构验证

- **状态**: Accepted
- **日期**: 2026-07-11
- **里程碑**: V0.1.1
- **关联 Provider**: stub (Architecture Probe)

## 背景

V0.1 Gemini CLI 接入时修改了 `core/bridge.py`（增强 CLIBridge）。用户要求：从第二个 Provider 起，`core/` 和 `bridge.py` 都必须零修改。

Stub Provider 的唯一目的：验证这条 KPI 成立。

## 实现

Stub 使用本仓库自带的 `tools/fake_runtime.py` 作为假 Runtime：
```bash
python tools/fake_runtime.py "{task}"
# 输出: Stub processed: {task}
```

通过 CLIBridge 的 `command_template` 参数配置：
```python
bridge = CLIBridge(
    command="python",
    command_template=f'python "{_FAKE_RUNTIME}" {{task}}',
    version_command="python --version",
    timeout=10,
)
```

## 暴露的新需求

**无。** 完全复用 CLIBridge 已有接口。

## 架构验证结果

| 核心模块 | 是否修改 |
|---------|---------|
| `core/provider.py` | ❌ |
| `core/registry.py` | ❌ |
| `core/result.py` | ❌ |
| `core/task.py` | ❌ |
| `core/capabilities.py` | ❌ |
| `router/router.py` | ❌ |
| `core/bridge.py` | ❌ |

## 决策

1. Stub Provider 保留在代码库中，作为"Bridge 冻结后第一个验证点"。
2. 优先级 10（最低），不影响真实 Provider 路由。
3. `tools/fake_runtime.py` 作为 Stub 的 Runtime，不删除。

## 经验教训

- **桩 Provider 有真实价值**：它证明 Bridge 接口不是为某个 Provider 量身定制的。
- **Windows 的 `cmd /C echo` 在 subprocess 中行为不可预测**：改用 Python 脚本作为 Runtime 更可靠。
