# AI Hub — 项目说明 & 现状 & 差距

> 更新时间：2026-08-23（由 2026-08-13 版本更新）
> 当前状态：**V1.0.13 发布候选**（分支 `release/v1.0.13-integration`，代码基线 `33dc88a`，外部审核进行中；正式发布以不可变 tag 标识）
> 测试基线：完整 non-live 回归 **1106 passed / 1 skipped**（354s），详见 [docs/releases/2026-08-23-v1.0.13-release-record.md](docs/releases/2026-08-23-v1.0.13-release-record.md)
> 仓库：https://github.com/icacaca-afk/ai-hub

---

## 一、这个项目是做什么的

**一句话**：ai-hub 是一个「多 AI Provider 聚合 + 智能路由 + 工作流编排」的 **命令行 AI Runtime**。

**它解决的问题**（来自 docs/PRODUCT.md）：

2026 年个人开发者手上有一堆 AI 工具（QODER / Gemini CLI / ChatGPT / QClaw / Coze / Marvis / Trae / Claude CLI），但问题不是"没有工具"，而是"工具太多"。每次完成任务要手动判断：用哪个？额度还剩多少？额度用完换哪个？结果格式不统一怎么对比？

**ai-hub 的价值**：打开一个入口，说一句话，自动选最合适的免费平台执行，统一返回结果，用户不用知道背后是谁干的。

> 核心哲学（README.md）：
> **AI Hub 不统一 AI 模型，AI Hub 统一「执行」。**
> `Task → Capability → Provider → Bridge → Runtime → Result`

**关键定位**（docs/ARCHITECTURE.md）：
- **Task 第一公民**（不是 Provider 第一公民）
- **Event Sourcing 风格执行模型**（ExecutionEvent 是 Source of Truth）
- **Capability Routing**（不是 Provider Routing）
- **Workflow Runtime on ExecutionEvent**（V1.0 主题）

---

## 二、核心架构（冻结的数据流）

```
Task → Capability → CapabilityRegistry → Provider → Bridge → Runtime → Result
```

| 术语 | 含义 | 位置 |
|------|------|------|
| Task | 用户提交的请求 | core/task.py |
| Capability | 能力标签（domain.action，如 code.generate） | core/capabilities.py |
| Provider | 能力声明 + 选择策略，**不执行 execute()** | core/provider.py |
| Bridge | 与 Runtime 通信的适配层（CLI/HTTP/GUI/Browser） | core/bridge.py |
| Runtime | 真正执行任务的 AI 平台（外部实体） | — |
| Result | 统一返回格式 | core/result.py |
| CapabilityRegistry | Provider 注册与查询中心 | core/registry.py |
| Router | 按 Capability 选 Provider 并执行 | router/ |

**V1.0 后的执行层**：`ExecutionPipeline`（Decorator/Middleware 模式）接管了 Router 的 execute() 装饰职责。

---

## 三、项目演进时间线

### 阶段 1：Runtime 核心（V0.0 – V0.4）✅ 完成

| 版本 | 目标 |
|------|------|
| V0.0.6 | 接口冻结（Task/Result/Provider/Bridge/Registry/Router）+ 文档统一 |
| V0.1 | 3 个真实 Provider（Gemini CLI + QODER + Stub），CLIBridge Stable |
| V0.1.2 | SDK 零修改扩展验证（OpenAICompatBridge） |
| V0.2 | 额度管理 QuotaManager（SQLite + 事务安全） |
| V0.3 | Session + Runtime 生命周期（55 测试） |
| V0.4 | Marvis 集成探索（GUI Bridge 失败 → 反向 MCP 路线） |
| **V0.4.2** | **Core Freeze（ADR-0008），63 测试** |

### 阶段 2：能力扩展 + 智能路由（V0.5 – V0.8）✅ 完成

| 版本 | 目标 |
|------|------|
| V0.5 | BrowserBridge（Playwright Chromium） |
| V0.6 | Health Framework（Health 是 Capability，非 Provider Interface） |
| V0.7 | Health-aware Router（跳过 unavailable Provider） |
| V0.7.2 | explain-route --json |
| V0.8 | ScoreRouter（静态权重评分：capability×40 + health×25 + priority×20 + latency×10 + quota×5） |
| V0.8.2 | Routing Decision Trace v2 + Benchmark 隔离 + CLI 集成测试（146 passed） |

### 阶段 3：Planner + Runtime Observability（V0.9.x）✅ 完成

| 版本 | 目标 |
|------|------|
| V0.9.0 | Planner 骨架（多步任务分解 + 子任务路由） |
| V0.9.1 | Planner CLI Integration + Execution Metadata |
| V0.9.2 | LLM Planner + PlanValidator |
| V0.9.3 | CLI --json + inspect + schema_version |
| V0.9.4 | ExecutionEvent + Metrics + Trace（10.0/10） |
| V0.9.5 | SQLiteExecutionStore（10.0/10） |
| V0.9.6 | Provider Metrics（10.0/10） |
| V0.9.7 | Execution Analytics（10.0/10） |

### 阶段 4：Workflow Runtime + 元数据链（V1.0.x）✅ 核心完成

| 版本 | 主题 | ADR | 状态 |
|------|------|-----|------|
| V1.0.0 – V1.0.11 | ARCHITECTURE / Pipeline / Retry / Checkpoint / Condition / Hooks / StageDescriptor / RuntimeMetadata / StageRegistry / Introspection / Serialization / pipeline.describe() | ADR-0021–0032 | ✅ 已发布（v1.0.11 为远程最新 tag） |
| **V1.0.12** | **Predicate API**（显式谓词语义元数据，明确排除 parser/AST/lambda 内省/DSL） | ADR-0033 | 实现完成；随 V1.0.13 候选一并送审 |
| **V1.0.13** | **CLI Pipeline Introspection**（`ai-hub pipeline inspect [--json]`）+ clean install 可复现 + 版本单一来源 + MCP 加固 + MetricsRouter 弃用兼容契约 | ADR-0034/0037 | **发布候选**（外部审核中） |

**开发支线**（不在 V1.0.13 范围）：`codex/multi-agent-loop` 分支含 TraeCLIProvider（27ef548）与 multi-agent-loop 上层编排评审结论——定位为 AI Hub 之上的可选治理层（RunController），不替换 Router→Provider→Bridge。

---

## 四、冻结边界（最高优先级约束，ADR-0008）

以下文件**除 Bug Fix 外禁止修改**：

| 路径 | 说明 |
|------|------|
| `core/` 全部 | Task/Result/Provider/Bridge/Registry/Health |
| `router/router.py` | 基础 Router |
| `router/health_router.py` | V0.7 Health-aware Router |
| `router/score_router.py` | V0.8 Score Router |
| `providers/` 全部 | 各 Provider 实现 |

**当前唯一例外声明**：`33dc88a` 中 `router/metrics_router.py` 的弃用兼容修复（deprecation warning → 断言兼容契约），作为 Bug Fix 单列送审；若审核否决，发布基线退至 `f00985a` 并按路径收编非 Router 变更。

**新功能去哪里写**：`planner/`、`router/` 下新建文件继承现有 Router、`providers/<name>/` 新建。

---

## 五、距离原定目标还有多少差距

### 5.1 产品最初目标（PRODUCT.md 第一版）—— 已 100% 超额完成 ✅

### 5.2 三阶段演进路线 —— 全部完成 ✅

聚合器（V0.0–0.5）→ 智能路由（V0.6–0.8）→ 多 Agent 编排（Planner + Workflow Runtime）核心全部落地。

### 5.3 V1.0 元数据链 —— 已闭环 ✅

Predicate API（V1.0.12）与 CLI Introspection（V1.0.13）均已实现并通过完整 non-live 回归；剩余动作只有「外部审核 + PR 合并 + 打 tag + Release」这一条发布流程（见发布记录第六节清单）。

### 5.4 当前已知技术债（登记待办，非本次范围）

| 项 | 说明 |
|----|------|
| 双 `default_pipeline` 工厂并存 | planner/pipeline.py（flag 驱动，V1.0.4）与 stage_registry.py（registry 驱动，V1.0.8）为文档化的有意设计；需定义公共契约 + 能力矩阵测试，经弃用周期收敛，不直接合并 |
| Router fallback 链三份拷贝 | router.py / health_router.py / score_router.py 各一份（ADR-0009 认可的冻结后果）；提取前须先过冻结边界审查 |
| MetricsRouter 正式弃用窗口 | 弃用自 V1.0.1，删除承诺逾期；需正式弃用 ADR 与窗口期 |
| 死配置 | config/router_rules.yaml、config/task_keywords.yaml 无代码引用且提及未注册 provider；删除或恢复使用 |
| 大文件 | cli/main.py、planner/pipeline.py、stage_registry.py（非冻结区，可拆）；core/bridge.py 在冻结区内，暂不动 |
| 入口命名 | wheel 安装态 MCP 入口为 `python -m adapters.marvis_mcp_server`，与模块文档字符串的 `ai_hub.*` 写法不一致（见发布记录观察项） |

### 5.5 差距总结（一屏看清）

| 维度 | 完成度 |
|------|--------|
| 产品最初目标（聚合+路由+统一输出） | **100% 完成** |
| 三阶段路线（聚合器→智能路由→编排） | **核心全部完成** |
| V1.0 Workflow Runtime + 元数据链 | **100% 实现**，差发布流程收尾 |
| 发布整合（tag 补齐/master 收编/审核记录） | **候选就绪，等待外部审核** |
| 远期（multi-agent-loop 上层编排、V2.0 插件生态） | 未启动（非阻塞） |

---

## 六、质量护栏（一贯的流程）

每个版本固定节奏（ARCHITECTURE.md §8）：

```
ADR (Proposed) → ChatGPT 审核 → 编码 → 测试 → ChatGPT 代码审核 → 冻结 → 下一 ADR
```

V1.0.12/V1.0.13 的实现先行于审核（历史欠账），正在通过本次发布整合补齐：审核材料包已按「最终候选相对 origin/master 完整 diff」准备，MetricsRouter 例外单列。累计历史审核记录见 docs/reviews/。

---

## 七、文档索引

| 文件 | 内容 |
|------|------|
| `README.md` / `README.zh-CN.md` | 项目介绍（双语，已更新至 V1.0.13 候选口径） |
| `docs/ARCHITECTURE.md` | 架构总入口（双语） |
| `docs/ROADMAP.md` | 路线图（双语，已更新） |
| `docs/PRODUCT.md` | 产品定义 |
| `docs/GLOSSARY.md` | 术语表 |
| `docs/runtime-contract.md` | 运行时契约 |
| `docs/adr/` | 决策记录（0001–0037；0033/0034/0037 随候选送审） |
| `docs/reviews/` | 外部审核记录 |
| `docs/releases/` | **发布记录（新增，V1.0.13 起）** |
| `docs/history/` | 历史实施文档归档（v1.0.10 metadata serialization 等） |
| `HANDOFF_TO_TRAE.md` | 交接文档（⚠️ 停留在 V0.8.2，仅作历史保留） |
