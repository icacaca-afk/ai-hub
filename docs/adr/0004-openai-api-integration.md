# ADR-0004: OpenAI API Provider 集成

- **状态**: Accepted
- **日期**: 2026-07-11
- **里程碑**: V0.1.2
- **关联 Provider**: openai_api (OpenAI 兼容 API)

## 背景

V0.1.1 验证了 CLIBridge 的零修改可扩展性。V0.1.2 目标：验证 APIBridge 同样支持零修改扩展。

## 暴露的新需求

APIBridge 的 `run()` 方法硬编码了请求体格式 `{"task": ..., "capabilities": ...}`，不兼容 OpenAI Chat Completions API 的 `{"model": ..., "messages": [...]}` 格式。

### 解决方案：Provider 内部继承 APIBridge

不修改 `core/bridge.py`。在 `providers/openai_api/provider.py` 中创建 `OpenAICompatBridge(APIBridge)` 子类，重写 `run()` 方法。

这证明了：**即使 Bridge 的默认实现不满足需求，也可以通过继承扩展，而无需修改 core/。**

## 接口变更

| 变更 | 类型 | 向后兼容 | 影响范围 |
|------|------|---------|---------|
| 无 core/ 修改 | — | — | — |

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

> **✅ 零修改 core/ + bridge.py。APIBridge 通过继承扩展验证通过。**

## 决策

1. **自动检测后端**：DeepSeek 优先（如果 `DEEPSEEK_API_KEY` 存在），否则 OpenAI。
2. **OpenAI 兼容格式**：所有兼容 OpenAI 的 API（DeepSeek、Moonshot、Qwen）复用同一个 Provider。
3. **继承而非修改**：`OpenAICompatBridge` 继承 `APIBridge`，重写 `run()`。这是"Bridge 冻结后如何扩展"的范例。

## 端到端验证

```
Backend: https://api.deepseek.com/v1/chat/completions
Model: deepseek-chat
Task: Write a Python function that reverses a string.
Result:
  Success: True
  Duration: 968ms
  Output: def reverse_string(s): return s[::-1]
```

## 经验教训

- **Bridge 冻结不等于无法扩展**：继承是正解。Provider 可以在自己的目录内创建 Bridge 子类。
- **OpenAI 兼容格式是事实标准**：DeepSeek、Moonshot、Qwen 都兼容。一个 Provider 覆盖多个后端。
- **APIBridge 的默认 `run()` 设计有缺陷**：硬编码 body 格式。但通过继承可以绕过。未来如果 core/ 允许修改，可以考虑让 APIBridge 支持 `body_builder` 回调参数。
