# AI Hub — 产品说明

[English](PRODUCT.md) | [简体中文](PRODUCT.zh-CN.md)

> 对应仓库 V1.0.11 里程碑的产品方向

## 一句话定义

AI Hub 是本地优先的执行 Runtime：接收一个任务，选择合适且可用的 AI Provider，
并返回统一结果。

## 解决的问题

开发者通常同时使用本地 CLI、在线 API、浏览器产品和 Workflow 系统。它们的命令、
登录方式、额度、健康状态和输出结构各不相同。用户把时间花在选择和切换工具上，
而不是完成任务。

## 产品承诺

```text
一个任务输入 → 感知 Capability 的执行 → 一个统一结果
```

AI Hub 应当：

- 优先选择满足任务 Capability 的 Provider；
- 说明为何选择某个 Provider；
- 综合可用性、额度、延迟和优先级；
- 同时支持单步任务与多步 Plan；
- 保存执行事实，用于诊断和统计；
- 把外部 Runtime 的通信细节隔离在 Bridge 后面。

## 核心用户

- 个人开发者和技术型独立工作者
- 已经同时使用多个 AI CLI 或 API 的人
- 关注成本和额度，同时要求执行行为可预测的用户
- 希望新增 Runtime Adapter、但不想重写 Router 的贡献者

企业身份体系、组织级策略、计费和 SLA 管理不是当前产品目标。

## 当前产品能力

| 需求 | 产品能力 |
|---|---|
| 执行一个请求 | `ai-hub ask` |
| 拆解较大的请求 | `ai-hub plan` |
| 理解路由决策 | `ai-hub explain-route` |
| 诊断 Provider 就绪状态 | `ai-hub status`、`doctor`、`benchmark` |
| 查看执行过程 | `inspect`、`trace`、`exec-history`、`stats` |
| 组合 Workflow 行为 | ExecutionPipeline Stage 与 Hook |
| 查看 Pipeline 结构 | `describe()`、`to_dict()`、`to_json()` API |

## 产品原则

1. 统一执行，不统一模型。
2. 把 Task 和执行事实作为第一公民。
3. 先按 Capability 路由，再考虑 Provider 身份。
4. 优先使用显式元数据，不从源码猜语义。
5. Provider 通信必须在 Bridge 边界之后。
6. 保护冻结契约，在扩展点增加行为。

## 成功指标

- 新用户能在十分钟内安装项目并查看可用 Provider。
- 路由决策能由明确的 Health、Capability、Priority、Latency 和 Quota 信号解释。
- Workflow 功能不需要修改冻结 Core 或基础 Router API。
- 面向读者的英文与简体中文文档保持同步。
- Release Test 和 Contract Test 不强制依赖在线 Provider，能够复现。

计划里程碑见[路线图](ROADMAP.zh-CN.md)，技术边界见
[架构总览](ARCHITECTURE.zh-CN.md)。
