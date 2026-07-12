# AI Hub — Glossary（概念字典）

> **这是整个项目的唯一术语来源。所有文档只能引用此文件，不能重新定义。**
>
> 版本：v1.1（V0.3 新增 Session / SessionManager / RuntimeRegistry）
> 日期：2026-07-12

| 名词 | 唯一定义 | 代码位置 |
|------|---------|---------|
| **Task** | 用户提交的请求（自然语言字符串） | `cli/main.py` → `ask` 命令的参数 |
| **Capability** | 系统识别出的能力标签，格式 `domain.action`，如 `code.generate` | `core/capabilities.py` → `CAPABILITIES` |
| **Provider** | 能力描述与选择策略的声明。定义 metadata（能力、优先级、降级链），选择 Bridge，保留 `execute()` 作为语法糖（内部调 Bridge + 转 Result）。**不直接处理通信细节。** | `core/provider.py` → `Provider` 基类 |
| **Bridge** | 与 Runtime 通信的实现层。封装 CLI subprocess / HTTP API / GUI 自动化等通信方式。Provider 通过 Bridge 执行任务，不关心底层协议。 | `core/bridge.py` → `Bridge` 基类 |
| **Runtime** | 真正执行任务的 AI 平台或工具实例。如 QODER 进程、Gemini CLI 进程、OpenAI API 服务、Marvis GUI。Bridge 是 Runtime 的适配器。 | 无代码（外部实体） |
| **Result** | 所有 Bridge 和 Provider 返回的统一结果格式。包含 provider、status、output、error、metadata。 | `core/result.py` → `Result` dataclass |
| **CapabilityRegistry** | Provider 注册与查询中心。维护 Capability → Provider 的映射。Router 通过 CapabilityRegistry 查找 Provider，不直接持有 Provider 列表。 | `core/registry.py` → `CapabilityRegistry` |
| **Router** | 根据 Task 关键词匹配出 Capability 列表，通过 CapabilityRegistry 查找可用 Provider，选择最优并执行。**Router 不知道具体 Provider 的存在，只知道 Capability。** | `router/router.py` → `Router` |
| **Session** | 一个跨多次 Task 的上下文容器。由 SessionManager 创建、Checkpoint 持久化、Resume 恢复、Destroy 释放。**所有 Bridge 都有 Session 概念，不只是 GUIBridge。** Session 不代替 Task.context；Task.context 是单次输入，Session 是跨 Task 状态。 | `core/session.py` → `Session` dataclass |
| **SessionManager** | Session 的创建/查询/Checkpoint/Resume/Destroy 中心。**不修改 Router**。Bridge 可以请求 Session（用于跨调用状态），但 Router 不感知。 | `core/session.py` → `SessionManager` |
| **RuntimeRegistry** | Session 创建时绑定一个 Bridge 会话（API/CLI/GUI 三类不同）。RuntimeRegistry 维护 Session → Bridge 的映射，Session.destroy() 时通知 Bridge 释放。**不修改 Router，不修改 Provider。** | `core/runtime_registry.py` → `RuntimeRegistry` |

## 关系链

```
Task → Router → Capability → CapabilityRegistry → Provider → Bridge → Runtime
                                                                    ↓
                                                                  Result
```

## 工程约束

> **新增 Provider 不允许修改 Router。**

如果新增一个 Provider 需要改 Router，说明架构出了问题，应该在 PR review 中打回。

## API Stability

| API | 状态 | 含义 |
|-----|------|------|
| Provider API | **Stable** | 接口签名不再变化，新参数只能带默认值 |
| Result API | **Stable** | 数据结构不再变化 |
| CapabilityRegistry API | **Stable** | 方法签名不再变化 |
| Capability API | **Stable** | 已定义的标签不会移除 |
| Router API | **Stable** | 外部接口不变，内部实现可升级 |
| Bridge API | **Stable** (V0.1.1 冻结) | 从第二个 Provider 起，Bridge 接口不再修改。新需求走 ADR 申请。 |
| QuotaManager API | **Experimental** (V0.2 新增) | 额度管理接口，V0.3 稳定化 |
| SessionManager API | **Experimental** (V0.3 新增) | 会话管理接口，V0.4 稳定化 |
| RuntimeRegistry API | **Experimental** (V0.3 新增) | Runtime 绑定接口，V0.4 稳定化 |
