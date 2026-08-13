# AI Hub 文档

[English](README.md) | [简体中文](README.zh-CN.md)

## 持续维护的读者文档

| 主题 | English | 简体中文 |
|---|---|---|
| 项目介绍 | [README](../README.md) | [README](../README.zh-CN.md) |
| 架构 | [Architecture Overview](ARCHITECTURE.md) | [架构总览](ARCHITECTURE.zh-CN.md) |
| 产品 | [Product Overview](PRODUCT.md) | [产品说明](PRODUCT.zh-CN.md) |
| 路线图 | [Roadmap](ROADMAP.md) | [路线图](ROADMAP.zh-CN.md) |
| 术语 | [Glossary](GLOSSARY.md) | [术语表](GLOSSARY.zh-CN.md) |
| Provider 扩展 | [Provider Specification](PROVIDER_SPEC.md) | [Provider 规范](PROVIDER_SPEC.zh-CN.md) |
| 参与贡献 | [Contributing](../CONTRIBUTING.md) | [贡献指南](../CONTRIBUTING.zh-CN.md) |

## 规范与历史档案

以下文档保留原始语言。不可变决策或审核如果产生翻译副本，容易形成与 Accepted
Source 不一致的第二份记录。

- [Runtime Contract](runtime-contract.md) — 规范运行时行为
- [Architecture Decision Records](adr/) — Accepted 与 Proposed 决策
- [外部审核](reviews/) — 审核 Prompt 与结果
- [Provider SDK（遗留指南）](provider_sdk.md) — 新贡献优先使用持续维护的 Provider
  规范
- [GUI Bridge 设计历史](GUI_BRIDGE_DESIGN.md)
- 特定版本的 SOP、Scope、Verification Report 与 Handoff

## 语言规则

- 持续维护文档的无后缀文件使用英文。
- 简体中文配对文件使用 `.zh-CN.md`。
- 两个版本顶部互相链接。
- 行为、命令、版本状态或公共契约发生变化时，同一个 Pull Request 必须同时更新
  两种语言。
- Code Identifier、Schema 和命令示例在两个版本之间保持不变。
- ADR、Review、Handoff 和 Release Artifact 保留原始语言。

## 事实来源

Git tag 和 Accepted ADR 是发布版本的事实来源。目前包元数据仍报告 `0.0.1`，而仓库
发布里程碑是 V1.0.11；该差异属于文档与打包维护事项。
