# AI Hub — 路线图

[English](ROADMAP.md) | [简体中文](ROADMAP.zh-CN.md)

> 当前仓库里程碑：V1.0.11 · 更新：2026-08-13

## 已完成阶段

| 阶段 | 成果 | 状态 |
|---|---|---|
| V0.0–V0.5 | Provider/Bridge Runtime、额度、Session、Adapter、Core Freeze | 完成 |
| V0.6–V0.8 | Health Framework、Health-aware Router、Score Router | 完成 |
| V0.9 | Planner、ExecutionEvent、Trace、SQLite History、Analytics | 完成 |
| V1.0.1–V1.0.5 | Pipeline、Retry、Checkpoint、Condition、Hooks | 完成 |
| V1.0.6–V1.0.10 | Stage Metadata、Registry、Access API、Serialization | 完成 |
| V1.0.11 | Pipeline Introspection | 完成 |

## 当前开发顺序

| 版本 | 决策 | 交付 | 状态 |
|---|---|---|---|
| V1.0.11 | [ADR-0032](adr/0032-pipeline-introspection.md) | `PipelineDescriptor`、`describe()`、确定性 JSON | 已发布 |
| V1.0.12 | [ADR-0033](adr/0033-predicate-api.md) | 显式 Predicate 语义元数据 | 已实现，待审核 |
| V1.0.13 | ADR-0034 | Pipeline 与 Predicate Introspection 的 CLI 展示 | Planned，必须先写 ADR |

V1.0.12 明确不做 callable 源码检查、AST 解析、lambda introspection、Predicate
DSL 或 Expression Engine。V1.0.13 必须决定结构与 Predicate 语义是否只在展示层
Join，或继续分离。

## 维护支线

- 冻结 Core、基础 Router、现有 Health/Score Router 和当前 Provider 实现，除有
  依据的 Bug Fix 外不修改。
- 面向读者的说明文档持续维护英文和简体中文版本。
- 统一包元数据与仓库发布标签。
- 按实际 Contract Test 更新安装和 Provider 扩展文档。
- 外部 Claude CLI Provider PR 完成所要求的修改与 Rebase 后再审核。

## 后续候选

以下方向都需要独立 ADR，目前不是承诺：

- Pipeline 结构与 Predicate 语义的 CLI 可视化
- Metadata Schema Versioning
- 仅在 callable 元数据不足时评估受限的结构化 Predicate
- 通过既有 Provider/Bridge 边界增加 Provider
- 生态打包与插件发现

## 发布流程

架构功能遵循固定顺序：

```text
Proposed ADR → 外部审核 → 修订 → 实现 → 定向测试
→ 全量回归 → commit/tag → 代码审核 → 批准
```

历史意图和评分保留在对应 ADR 与 Review 文件中；本文只记录持续维护的方向。
