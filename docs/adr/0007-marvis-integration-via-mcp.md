# ADR-0007: Marvis 集成 — 反向 MCP Server 模式

## 日期
2026-07-12

## 状态
Accepted（替代 ADR-0006 GUI Bridge 方向）

## 背景

V0.4 原计划通过 GUI Bridge 驱动 Marvis 主对话（ADR-0006），经 11 轮迭代 + 8 个方向穷举验证，全部失败：

| 方向 | 结果 |
|------|------|
| MarvisAgent 6161 HTTP API | 仅 `/health` + `/version`，无业务 API |
| MarvisHost 39099 CEF 端口 | 内部端口，需 token |
| Chrome native messaging | `allowed_origins` 白名单仅 3 个自家扩展 |
| GUI 自动化 (UIA/Win32) | Qt 6 WebEngine 自渲染，不暴露控件树 |
| Chrome DevTools Protocol | 未开启远程调试 |
| 内部 WebSocket (5287/5283) | CEF binary protocol，需破解 |
| 截屏+OCR | 脆，不能读流式输出 |
| 剪贴板注入 | 最后 fallback，不可靠 |

**结论**：正向驱动 Marvis 主对话不可行。

## 决策

### V0.4.1 改为反向 MCP Server 模式

**核心思路**：Marvis 是 MCP 客户端（内置 FastMCP，`mcp_server/` 目录存放第三方 MCP servers）。让 ai-hub 暴露为 MCP Server，由 Marvis 主动调用 ai-hub 的工具能力。

```
┌─────────────┐    stdio/json-rpc    ┌──────────────────┐
│   Marvis     │ ◄─────────────────► │  ai-hub MCP Server │
│ (MCP Client) │   tool_call / result │  (adapters/)      │
└─────────────┘                      └────────┬─────────┘
                                              │
                                    ┌─────────▼─────────┐
                                    │  CapabilityRegistry │
                                    │  Provider → Bridge  │
                                    └───────────────────┘
```

### 技术方案

1. **新建 `adapters/marvis_mcp_server.py`**
   - 使用 `mcp` Python SDK（FastMCP）
   - 暴露 tool：`run_provider(capability, content, context)` + `list_providers()` + `list_capabilities()`
   - stdio transport（MCP 标准集成方式）
   - 内部复用 cli/main.py 的 `_build_registry()` 模式注册 Provider

2. **新建 `scripts/configure_marvis_mcp.py`**
   - 自动检测 Marvis 配置文件位置
   - 写入 ai-hub MCP server 入口配置
   - 幂等操作（不覆盖已有配置）

3. **零修改 core/**
   - 新代码全部在 `adapters/` 和 `scripts/`
   - 复用现有 Registry/Task/Bridge/Result API（V0.0.6 冻结接口）

## 影响评估

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| core/* | **不改** | V0.1~V0.3 冻结承诺 |
| router/* | **不改** | Router 不变 |
| providers/* | **不改** | Provider 不变 |
| adapters/__init__.py | NEW | 空文件，包标记 |
| adapters/marvis_mcp_server.py | NEW | MCP Server 实现 |
| scripts/configure_marvis_mcp.py | NEW | Marvis 配置写入脚本 |
| docs/adr/0007-*.md | NEW | 本文档 |
| docs/ROADMAP.md | EDIT | V0.4 状态更新 |

## 替代方案考虑

| 方案 | 结论 |
|------|------|
| 正向驱动 Marvia GUI（ADR-0006） | ❌ 已穷举失败 |
| 直接 HTTP 调 6161 | ❌ 无业务 API |
| Native messaging 扩展 | ❌ 白名单限制 |
| 剪贴板 fallback | ⚠️ 仅作最后手段 |
| **反向 MCP Server** | ✅ **采用** — Marvis 官方支持、一次配置永久生效 |

## 验证标准

- [ ] `python -m ai_hub.adapters.marvis_mcp_server` 启动无报错
- [ ] Marvis 重启后能看到 ai-hub 工具
- [ ] Marvis 对话中调用 ai-hub tool 返回正常结果
- [ ] ai-hub history 记录调用记录
- [ ] core/ 目录零变更（`git diff core/` 为空）

## 与 ADR-0006 关系

ADR-0006（GUI Bridge）被本 ADR 取代。V0.4 方向从"驱动 Marvis"调整为"被 Marvis 调用"。
providers/marvis/ 目录已在 V0.4.2 中删除（GUI 路线遗留清理）。ADR-0006 保留为历史记录。

## 定位声明

**本决策不改变 ai-hub 的产品定位，仅新增一种 Integration。** ai-hub 仍然是"统一 AI 执行 runtime"，不是 Marvis 插件。MCP Adapter 是通用的集成层，未来 Claude Desktop、Cursor、Cherry Studio 等 MCP 客户端均可通过同一 adapter 接入。

## 参考

- [MARVIS_HANDOVER_20260712.md](../../MARVIS_HANDOVER_20260712.md)
- [marvis_investigation_20260712.md](../../../marvis_investigation_20260712.md)
- [ADR-0006: Marvis GUI Bridge](0006-marvis-gui-bridge.md)
