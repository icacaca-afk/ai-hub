# AI Hub — Roadmap

> 版本：v0.4.1
> 术语定义见 [GLOSSARY.md](GLOSSARY.md)

## 路线图

| 版本 | 目标 | 成功标准 | 状态 |
|------|------|---------|------|
| **V0.0.6** ✅ | 接口冻结 + 文档统一 | 12 测试通过 + 4 Provider Validation 通过 | Done |
| V0.1 | 3 个真实 Provider | API + CLI + GUI 各一个，不改 Router | Done |
| V0.2 | 额度管理 | Quota Manager + 自动切换 | Done |
| V0.3 | AI 智能路由 + GUIBridge | LLM 分类替代关键词 | Done |
| **V0.4** | Marvis 集成 | GUI Bridge 探索（11 轮迭代） | ~~GUI Bridge~~ → **方向调整** |
| **V0.4.1** | **Marvis 反向 MCP Server** | ai-hub 暴露为 Marvis 工具集 | 🚧 In Progress |
| V0.5 | 任务分解 / BrowserBridge | 多步任务自动拆分 + Playwright | Planned |
| V1.0 | Agent 编排 | 多 Provider 协同 + 飞书交付 | Planned |
| V2.0 | 插件生态 | 社区贡献 Provider | Planned |

## 当前状态：V0.4.1 Marvis 反向 MCP Server 集成

### V0.4 收尾（2026-07-12）
- ❌ GUI Bridge 方向失败（8 个方向穷举验证，详见 ADR-0007）
- ✅ 调查报告完成：[marvis_investigation_20260712.md](../marvis_investigation_20260712.md)

### V0.4.1 进展（2026-07-12 启动）

**决策依据**：[ADR-0007: Marvis 集成 — 反向 MCP Server 模式](adr/0007-marvis-integration-via-mcp.md)

**已完成的交付物**：
- [x] ADR-0007 决策记录
- [x] `adapters/marvis_mcp_server.py` — MCP Server 实现（3 个 tools：run_provider / list_providers / list_capabilities）
- [x] `scripts/configure_marvis_mcp.py` — Marvis 配置写入脚本
- [ ] Marvis 配置写入 + 重启验证
- [ ] 端到端测试（Marvis 对话调用 ai-hub tool）
- [x] 本文档更新

**架构**：
```
Marvis (MCP Client) --stdio--> ai-hub MCP Server (adapters/)
                                ↓
                        CapabilityRegistry
                                ↓
                    Provider → Bridge → Result
```

**核心约束**：
- ai-hub core/ 零修改（V0.1~V0.3 冻结承诺）
- 新代码仅在 adapters/ 和 scripts/
- stdio transport（MCP 标准集成方式）

### 相关文档
- [MARVIS_HANDOVER_20260712.md](../MARVIS_HANDOVER_20260712.md) — 完整交接清单
- [ADR-0007](adr/0007-marvis-integration-via-mcp.md) — 反向 MCP Server 决策记录
- [ADR-0006](adr/0006-marvis-gui-bridge.md) — 被取代的 GUI Bridge 方案（历史参考）

## 历史里程碑

V0.0.6 接口冻结完成：

- ✅ Task dataclass（输入端）
- ✅ Result dataclass（输出端，含 artifacts）
- ✅ Provider 无 execute()，只有声明 + select_bridge()
- ✅ Bridge 5 种类型（Fake/CLI/API/GUI/Browser）
- ✅ CapabilityRegistry 按 Capability 查找
- ✅ Router 负责执行（调 select_bridge + bridge.run）
- ✅ Glossary 概念字典冻结
- ✅ 所有文档统一引用 Glossary
- ✅ 测试全通过
- ✅ 4 个 Provider Validation 全部通过
