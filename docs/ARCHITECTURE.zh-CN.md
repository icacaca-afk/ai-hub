# AI Hub — 架构总览

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

> 仓库里程碑：V1.0.11 · 状态：持续维护 · 更新：2026-08-13

## 目的

本文是 AI Hub 架构的统一入口。规范性细节以 Runtime Contract、Provider
Specification 和已接受的 ADR 为准。

## 系统定位

AI Hub 是 AI Runtime，不只是模型网关。Task 是第一公民；Capability 决定可选
Provider；Provider 选择 Bridge；Bridge 与外部 Runtime 通信。

```text
Task → Capability → Provider → Bridge → Runtime → Result
```

系统统一的是执行方式，而不是模型语义。

## 静态架构

```text
┌──────────────────────────────────────────────────────────┐
│ CLI / MCP Adapter                                       │
│ ask · plan · inspect · trace · history · stats          │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Planner 与路由                                          │
│ RuleBasedPlanner / LLMPlanner · ScoreRouter             │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ ExecutionPipeline                                       │
│ pre-stages → Bridge boundary → post-stages              │
│ retry · checkpoint · condition · hooks                  │
└──────────────┬──────────────────────────┬────────────────┘
               ▼                          ▼
┌──────────────────────────┐  ┌────────────────────────────┐
│ Provider + Bridge        │  │ ExecutionEvent Consumer    │
│ CLI / API / Browser / MCP│  │ trace · SQLite · statistics│
└──────────────┬───────────┘  └────────────────────────────┘
               ▼
          外部 Runtime
```

## 组件边界

| 区域 | 职责 | 稳定性 |
|---|---|---|
| `core/` | Task、Result、Provider、Bridge、Health、Registry 契约 | 冻结 |
| `router/` | 基于 Capability 和评分选择 Provider | 基类与现有 Router 冻结 |
| `providers/` | 特定 Runtime 的适配实现 | 现有实现冻结；新 Provider 使用新目录 |
| `planner/` | Plan、Pipeline、Stage、Event、持久化与元数据 | Experimental，持续开发 |
| `cli/` | 用户命令与展示层 | Experimental |
| `adapters/` | MCP 等协议集成 | 扩展边界 |

发布包同样是架构边界。Setuptools 只在维护中的项目命名空间下递归发现 Package，
发布验证必须在源码目录外安装非 editable Wheel。CLI 固定 Provider 的实现是在
Router 构造前收窄 Registry，不会绕过或修改 Router 行为。`cli/version.py` 是
Wheel 元数据与 Runtime 检查的单一版本源；`cli/` 是正规 Package，避免被环境中
无关的 `cli.py` 模块遮蔽入口。

MCP 发现默认只观察元数据：`list_providers` 把可用性标记为 `unchecked`，不执行
外部探测。由于探测可能启动 CLI、认证、浏览器或网络检查，只有调用方显式要求时
才执行。

冻结规则由 [ADR-0008](adr/0008-core-freeze.md) 管理。当前仓库中，冻结范围包括
`core/`、`router/router.py`、`router/health_router.py`、
`router/score_router.py` 和现有 Provider 实现。Bug Fix 必须有明确理由；新的
Workflow 行为进入 `planner/`。

## 运行时流程

1. CLI 或 Adapter 创建 `Task`。
2. Planner 可把它拆成由多个 `Step` 组成的 `Plan`。
3. Router 把所需 Capability 映射到合适的 Provider。
4. `ExecutionPipeline` 运行 pre-stage，跨越 Provider/Bridge 边界，再运行
   post-stage。
5. 执行事实以 `ExecutionEvent` 发出。
6. Trace、SQLite Store 和 Statistics 消费这些事件，但不会成为执行事实来源。
7. 调用方获得统一 `Result`。

## Execution Pipeline

V1.0 把 Workflow 关注点从 Router 子类迁入可组合的 Pipeline Stage：

- V1.0.1：ExecutionPipeline
- V1.0.2：RetryStage
- V1.0.3：CheckpointStage
- V1.0.4：ConditionStage
- V1.0.5：Pipeline Hooks
- V1.0.6–V1.0.10：Descriptor、Registry、Metadata Access 与 Serialization
- V1.0.11：PipelineDescriptor 与无副作用的 Pipeline Introspection

V1.0.11 的 Introspection 保持单向链路：

```text
ExecutionPipeline
  → describe()
  → PipelineDescriptor
  → serialize_pipeline()
  → dict
  → JSON
```

`serialize_pipeline()` 只消费 Descriptor，不直接检查可执行 Pipeline。

## 可观察性模型

`ExecutionEvent` 是不可变执行事实。内存 Trace、持久化历史与统计是基于这些事实的
Projection。静态元数据走另一条链路：StageDescriptor、RuntimeMetadata、
StageRegistry、PipelineDescriptor 和 canonical serialization functions。

这种分离避免执行逻辑、静态结构和展示层互相产生隐式影响。

## 文档地图

| 文档 | 作用 |
|---|---|
| [Runtime Contract](runtime-contract.md) | 规范运行时行为 |
| [Provider 规范](PROVIDER_SPEC.zh-CN.md) | Provider 与 Bridge 扩展契约 |
| [术语表](GLOSSARY.zh-CN.md) | 项目唯一术语定义 |
| [路线图](ROADMAP.zh-CN.md) | 里程碑和当前方向 |
| [ADR 目录](adr/) | 不可变架构决策 |
| [审核目录](reviews/) | 外部审核记录 |

## Governance Layer

[AI Agent 数字资产 SOP](AI-Agent-Digital-Asset-SOP-v1.0.md) 属于治理参考，不是
Runtime 组件。其定位由 [ADR-0035](adr/0035-digital-asset-sop-position.md) 记录；
它不扩展冻结 Core，也不引入执行依赖。

## 下一里程碑

[ADR-0033](adr/0033-predicate-api.md) 定义了 V1.0.12 的显式 Predicate 语义元数据，
实现目前等待发布审核。它明确不做源码 introspection、AST 解析、lambda introspection 或 Predicate
Expression Engine。CLI 展示留给后续 ADR。
