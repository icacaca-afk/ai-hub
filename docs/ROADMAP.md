# AI Hub — Roadmap

> 渐进式架构：每一层可以独立升级，不需要推翻重来。

## V0.0.5 — Bridge + Capability + Validation ✅

**目标**：验证"同一套接口统一三种通信方式"

**功能**：
- Bridge 层（CLIBridge / APIBridge / FakeBridge）
- Capability 系统（Task → Capability → Provider）
- ProviderMetadata 声明式定义
- Provider Validation 脚本 + GitHub Action
- 三种 Bridge 的 Provider 示例（Demo/QODER/Gemini/OpenAI）

**成功标准**：
- ✅ 10 个测试通过
- ✅ 4 个 Provider 通过 Validation
- ✅ 新增 Provider 只需 ~30 行代码
- ✅ 三种 Bridge 共用同一套 Provider 接口

---

## V0.1 — 3 个真实 Provider

**目标**：接入 3 种不同通信方式的真实 AI 平台

**开发顺序**：
1. QODER（CLIBridge）— 编程任务
2. Gemini CLI（CLIBridge）— 搜索 + 通用
3. OpenAI API 或 QClaw（APIBridge）— 通用兜底

**成功标准**：
- 3 个真实 Provider 全部通过 Validation
- 端到端测试 20 个场景
- **完全不修改 Router、History、CLI、Registry**
- 证明同一套架构可以统一 API 和 CLI

**不做**：
- 飞书集成
- Web UI
- AI 路由
- 任务分解

---

## V0.2 — 额度管理 + Web UI

**目标**：可视化管理和监控

**功能**：
- Quota Manager（定时检测额度、自动刷新）
- Web Dashboard（Provider 状态、额度、历史）
- 配置热加载

---

## V0.3 — AI 智能路由

**目标**：用 LLM 替代关键词匹配

**功能**：
- AI Classifier（用小模型分类任务）
- GUIBridge（GUI 自动化，接入 Marvis 等）
- 路由准确率 > 90%

**升级触发条件**：用户反馈"路由选错了"超过每周 3 次

---

## V0.5 — 任务分解

**目标**：多步任务自动拆分

**功能**：
- Task Splitter（复杂任务 → 子任务列表）
- 多 Provider 串行执行
- 中间结果传递

---

## V1.0 — Agent 编排

**目标**：多 Provider 协同完成复杂任务

**功能**：
- Agent 层（= Provider + 规划 + 上下文）
- 多 Agent 串行/并行编排
- 飞书交付层（Lark CLI）
- 冲突处理

**成功标准**：
- 一个复杂任务自动分解并分发给 3+ 个 Agent 执行
- 结果自动整合并交付到飞书

---

## V2.0 — 插件生态

**目标**：社区贡献 Provider

**功能**：
- Provider 插件化（pip install ai-hub-qoder）
- Provider Marketplace
- 版本管理 + 兼容性检查
