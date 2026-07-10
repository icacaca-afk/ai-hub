# AI Hub — Roadmap

> 版本：v0.0.6
> 术语定义见 [GLOSSARY.md](GLOSSARY.md)

## 路线图

| 版本 | 目标 | 成功标准 |
|------|------|---------|
| **V0.0.6** ✅ | 接口冻结 + 文档统一 | 12 测试通过 + 4 Provider Validation 通过 |
| V0.1 | 3 个真实 Provider | API + CLI + GUI 各一个，不改 Router |
| V0.2 | 额度管理 | Quota Manager + 自动切换 |
| V0.3 | AI 智能路由 + GUIBridge | LLM 分类替代关键词 |
| V0.5 | 任务分解 | 多步任务自动拆分 |
| V1.0 | Agent 编排 | 多 Provider 协同 + 飞书交付 |
| V2.0 | 插件生态 | 社区贡献 Provider |

## 当前状态

V0.0.6 接口冻结完成：

- ✅ Task dataclass（输入端）
- ✅ Result dataclass（输出端，含 artifacts）
- ✅ Provider 无 execute()，只有声明 + select_bridge()
- ✅ Bridge 5 种类型（Fake/CLI/API/GUI/Browser）
- ✅ CapabilityRegistry 按 Capability 查找
- ✅ Router 负责执行（调 select_bridge + bridge.run）
- ✅ Glossary 概念字典冻结
- ✅ 所有文档统一引用 Glossary
- ✅ 12 个测试全部通过
- ✅ 4 个 Provider Validation 全部通过
