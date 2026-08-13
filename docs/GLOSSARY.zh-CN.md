# AI Hub — 术语表

[English](GLOSSARY.md) | [简体中文](GLOSSARY.zh-CN.md)

> V1.0.11 持续维护文档的唯一术语来源。

| 术语 | 定义 | 主要代码位置 |
|---|---|---|
| Task | 用户请求的单个工作单元，包含内容、Capability、Context 和 Artifact。 | `core/task.py` |
| Capability | `code.generate` 形式的命名空间标签，用于把 Task 匹配到 Provider。 | `core/capabilities.py` |
| Provider | 声明 Capability 和路由元数据并选择 Bridge；不持有底层通信细节。 | `core/provider.py` |
| Bridge | CLI 进程、HTTP API、浏览器、GUI 或测试 Runtime 的通信边界，返回 `BridgeResult`。 | `core/bridge.py` |
| Runtime | 真正完成工作的外部工具或服务。 | 外部实体 |
| Result | 面向用户的统一执行结果。 | `core/result.py` |
| CapabilityRegistry | Provider 注册中心和 Capability-to-Provider 查询。 | `core/registry.py` |
| Router | 为 Task 选择 Provider；专用 Router 可以综合 Health 或 Score 信号。 | `router/` |
| HealthReport | Provider 的四态观察结果：healthy、degraded、unknown、unavailable。 | `core/health.py` |
| Plan | Planner 产生的有序 Step 集合。 | `planner/plan.py` |
| Step | Plan 中独立路由的一个工作单元。 | `planner/plan.py` |
| ExecutionPipeline | 围绕 Bridge 边界组合 pre-stage 与 post-stage。 | `planner/pipeline.py` |
| ExecutionContext | 在 Pipeline Stage 之间传递的不可变风格数据。 | `planner/pipeline.py` |
| ExecutionStage | RetryStage、CheckpointStage、ConditionStage 等可调用 Pipeline 单元。 | `planner/stages/` |
| ExecutionEvent | 供 Trace、持久化和统计 Consumer 使用的不可变执行事实。 | `planner/execution_event.py` |
| StageDescriptor | Stage 的静态身份和 Capability 元数据。 | `planner/stage_descriptor.py` |
| RuntimeMetadata | Pipeline 执行期间产生的结构化运行时元数据。 | `planner/runtime_metadata.py` |
| StageRegistry | Stage Descriptor 与 Factory 的注册和发现中心。 | `planner/stage_registry.py` |
| PipelineDescriptor | 无副作用的 Pipeline 结构描述，包含稳定 Node ID 和 Edge。 | `planner/pipeline_descriptor.py` |
| PredicateDescriptor | V1.0.12：ConditionStage Predicate 的显式语义元数据。 | `planner/predicate_descriptor.py` |
| ADR | `docs/adr/` 下的不可变 Architecture Decision Record。 | `docs/adr/` |

## 标准关系

```text
Task → Capability → Provider → Bridge → Runtime → Result

Plan → Step → ExecutionPipeline → ExecutionEvent
                     │
                     └──► RuntimeMetadata / Descriptor / Serialization
```

其他持续维护文档需要定义这些术语时，应链接到本文件，不要重新定义。
