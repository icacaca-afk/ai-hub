# AI Hub — Roadmap

> 版本：v0.5.0-alpha（冻结）
> 术语定义见 [GLOSSARY.md](GLOSSARY.md)

## 路线图

### V0.0–V0.4：建立 Runtime 核心

| 版本 | 目标 | 成功标准 | 状态 |
|------|------|---------|------|
| V0.0.6 ✅ | 接口冻结 + 文档统一 | 12 测试通过 + 4 Provider Validation | Done |
| V0.1 ✅ | 3 个真实 Provider | API + CLI + Stub，零修改 core/ | Done |
| V0.1.2 ✅ | SDK 零修改扩展验证 | OpenAICompatBridge + Good First Issues | Done |
| V0.2 ✅ | 额度管理 | QuotaManager（SQLite + 事务安全） | Done |
| V0.3 ✅ | Session + Runtime 生命周期 | 55 测试通过，模型路由约定 | Done |
| V0.4 ✅ | Marvis 集成路线探索 | GUI Bridge 失败 → MCP 反向集成 | Done |
| **V0.4.2 ✅** | **Core Freeze** | **63 测试通过，ADR-0008 冻结** | **Done** |

### V0.5–V0.8：扩展 Runtime 能力

| 版本 | 目标 | 成功标准 | 状态 |
|------|------|---------|------|
| **V0.5 Alpha** | BrowserBridge（能力扩展） | Playwright 集成，不改 core/ | Planned |
| **V0.6 Alpha** | Planner（能力编排） | 多步任务自动拆分 | Planned |
| **V0.7 Alpha** | AI Router（智能路由） | LLM 分类替代关键词路由 | Planned |
| **V0.8 Beta** | Workflow | 多 Provider 协同 + 飞书交付 | Planned |

### V1.0+：稳定版与生态

| 版本 | 目标 |
|------|------|
| V1.0 | 稳定版（API 冻结） |
| V2.0 | 插件生态（社区贡献 Provider） |

## 当前状态：V0.4.2 Core Freeze → V0.5 Alpha 启动

### V0.4.2 收口（2026-07-13）

**ADR-0008: Core Freeze** — core/ 和 router/ 除 Bug Fix 外不再修改。

冻结文件清单：
- `core/`：bridge.py, capabilities.py, history.py, provider.py, quota.py, registry.py, result.py, runtime_registry.py, session.py, task.py
- `router/`：router.py

后续功能归属：
- 新 Bridge → `bridges/` 或 `providers/<name>/`
- 新 Provider → `providers/<name>/`
- 新 Adapter → `adapters/`
- Planner → `planner/`
- AI Router → `router/` 下新文件（不改现有 `router.py`）
- Workflow → `workflow/`

### V0.4 系列总结

| 决策 | 结果 | ADR |
|------|------|-----|
| GUI Bridge（驱动 Marvis） | ❌ 失败（Qt 自渲染，11 轮迭代） | ADR-0006（历史） |
| 反向 MCP Server（Marvis 调用 ai-hub） | ✅ 代码完成，待 Marvis 端验证 | ADR-0007 |
| MarvisProvider 移除 | ✅ 清理完成 | ADR-0007 更新 |
| Core Freeze | ✅ 冻结 | ADR-0008 |

### V0.5 Alpha 目标

**不是架构调整，而是能力扩展。**

BrowserBridge 已在 `core/bridge.py` 中定义骨架（V0.0.6），但未实现。
V0.5 将在 `bridges/` 目录下实现具体 Browser Bridge，接入 Playwright，不改 core/。

**成功标准**：
- [ ] BrowserBridge 实现（Playwright 集成）
- [ ] 至少 1 个 Web AI Provider 接入（如 ChatGPT Web / Claude Web）
- [ ] core/ + router.py 零修改（Bug Fix 除外）
- [ ] MCP Contract Test 全通过
- [ ] 新增 Browser Bridge Contract Test

## 历史里程碑

- **V0.0.6**（接口冻结）：Task/Result/Provider/Bridge/CapabilityRegistry/Router 全部冻结
- **V0.1**（真实 Provider）：Gemini CLI + QODER + Stub，CLIBridge Stable（ADR-0002/0003）
- **V0.2**（额度管理）：QuotaManager SQLite + `BEGIN IMMEDIATE` + WAL
- **V0.3**（Session + Runtime）：SessionManager 全生命周期 + RuntimeRegistry + 模型路由约定
- **V0.4**（Marvis 集成）：GUI Bridge 失败 → MCP 反向集成 → V0.4.2 Core Freeze
