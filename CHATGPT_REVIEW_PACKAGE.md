# ChatGPT 审查包 · V0.4.1 (Marvis 反向 MCP Server)

**项目**：ai-hub（统一 AI 执行 runtime，非 LLM 框架）
**里程碑**：V0.4.1（替代 V0.4 GUI Bridge 失败路线）
**时间**：2026-07-12 22:25 GMT+8
**状态**：6/6 关键验证全过，待 ChatGPT 审查

---

## 0. 30 秒电梯版

ai-hub 之前试图用 Win32/UIA **驱动** Marvis 桌面（V0.4 GUI Bridge），11 轮失败。
**V0.4.1 转向反向 MCP**：让 Marvis **主动调用** ai-hub 暴露的 stdio MCP server。
Marvis 官方是 MCP 客户端（内置 FastMCP），ai-hub 通过 mcp Python SDK 暴露 3 个 tool。
**零修改** core/ + router/，新代码全在 `adapters/` + `scripts/`。

---

## 1. 核心交付物（按重要性排序）

| # | 文件 | 角色 | 必读？ |
|---|------|------|--------|
| 1 | `docs/adr/0007-marvis-integration-via-mcp.md` | **决策记录**——为什么放弃 V0.4，为什么选反向 MCP | ⭐⭐⭐ |
| 2 | `adapters/marvis_mcp_server.py` | **MCP server 实现**——FastMCP 暴露 3 个 tools | ⭐⭐⭐ |
| 3 | `scripts/configure_marvis_mcp.py` | Marvis 客户端配置脚本（幂等） | ⭐⭐ |
| 4 | `V041_VERIFICATION_REPORT.md` | 验收报告（实测结果 + 修复 + 已知问题） | ⭐⭐⭐ |
| 5 | `AUDIT_OUTPUT.txt` | audit 脚本原始输出（可重跑 verify_audit.py） | ⭐ |
| 6 | `verify_audit.py` | 自动审计脚本 | ⭐ |
| 7 | `providers/marvis/{bridge,provider}.py` | V0.4 路线残留（**已知问题，未清理**） | ⚠️ |
| 8 | `cli/main.py` | CLI 入口（**仍注册 MarvisProvider，未清理**） | ⚠️ |

---

## 2. 架构

```
┌────────────────────────────────────────────────────────┐
│                    Marvis Desktop                       │
│                  (MCP Client, 内置)                      │
└──────────┬─────────────────────────────────────────────┘
           │ stdio JSON-RPC
           │ command: python -m ai_hub.adapters.marvis_mcp_server
           ▼
┌────────────────────────────────────────────────────────┐
│           ai-hub MCP Server (adapters/)                 │
│                                                          │
│   暴露 tools:                                            │
│   - run_provider(capability, content, context)          │
│   - list_providers()                                     │
│   - list_capabilities()                                  │
│                                                          │
│   内部链路：                                              │
│   Task → Router → Provider → Bridge → Result            │
└──────────┬─────────────────────────────────────────────┘
           │ 复用
           ▼
┌────────────────────────────────────────────────────────┐
│   core/ (V0.0.6 冻结接口，零修改)                       │
│   - Task / Result / CapabilityRegistry / Provider        │
│   - QuotaManager / HistoryStore / SessionManager        │
│                                                          │
│   providers/ (V0.1~V0.4 累积)                            │
│   - demo / gemini / stub / openai_api / qoder           │
│   - fake_browser / marvis (V0.4 残留)                    │
└────────────────────────────────────────────────────────┘
```

---

## 3. 关键事实（实测验证）

### 3.1 core/ 零修改证据
```bash
$ git diff --stat core/ router/
# (no output - means ZERO changes)
```

### 3.2 mcp SDK 工作正常
```
mcp 1.28.1
```

### 3.3 stdio 握手实测
```json
// Request: {"jsonrpc":"2.0","id":1,"method":"initialize",...}
// Response:
{
  "serverInfo": {"name": "ai-hub", "version": "1.28.1"},
  "capabilities": {"tools": {"listChanged": false}, ...}
}

// tools/list 返回 3 个 tool:
- run_provider
- list_providers  
- list_capabilities
```

### 3.4 Marvis 客户端已配置
```json
// C:\Users\Administrator\AppData\Roaming\Marvis\marvis-client.config.json
{
  "mcpServers": {
    "ai-hub": {
      "command": "python",
      "args": ["-m", "ai_hub.adapters.marvis_mcp_server"]
    }
  }
}
```

### 3.5 三种入口方式全过
- `python adapters/marvis_mcp_server.py` ✅
- `python -m adapters.marvis_mcp_server` ✅
- `python -m ai_hub.adapters.marvis_mcp_server` ✅（editable install 后）

---

## 4. 我做的关键修复

| # | 问题 | 修复 |
|---|------|------|
| 1 | `pyproject.toml` build-backend 写错 | 改 `setuptools.build_meta` |
| 2 | `pyproject.toml` packages 缺 `adapters` 和 `scripts` | 补全 |
| 3 | `mcp.__version__` 在 1.28.1 不可用 | 改 `importlib.metadata.version("mcp")` |
| 4 | `python -m ai_hub.adapters.marvis_mcp_server` 找不到模块 | 加 `_ensure_project_root_on_path()` |
| 5 | Python 3.13 没装 mcp SDK | 在 3.13 单独 `pip install mcp` |

---

## 5. 已知问题（诚实清单，不藏）

### 5.1 🚨 未端到端验证
- Marvis 客户端**未实际重启并对话测试** ai-hub tool
- 配置文件已写入，但 MCP 客户端行为需在 Marvis UI 中手动触发
- 建议审查后做这件事

### 5.2 ⚠️ V0.4 残留未清理
- `providers/marvis/bridge.py` + `provider.py` 仍是 V0.4 路线代码
- `cli/main.py` 第 60 行仍 `registry.register(MarvisProvider())`
- **影响**：`ai-hub ask "解释CAP theorem"` 走 Marvis GUI Bridge（V0.4 失败方案，返回空）
- **建议清理**：删 `providers/marvis/`，从 `cli/main.py` 移除注册
- **为什么没清**：V0.4.1 目标只是"反向 MCP 落地"，清理是另一个 PR

### 5.3 ⚠️ git push 失败
- 历史 403 token 权限问题未修
- 本次未尝试 push

### 5.4 ⚠️ 真实 LLM provider 不可用
- `gemini_cli` provider available=False（缺 GEMINI_API_KEY）
- `openai_api` available=False（缺 API key）
- 这导致 `ai-hub ask` 走 Marvis 残留或 demo
- Marvis 客户端跑起来后，实际能跑通真 LLM 取决于 gemini CLI 是否配好

---

## 6. 建议审查重点

请 ChatGPT 重点评估：

1. **架构合理性**：反向 MCP 模式是否符合 ai-hub 长期定位？
2. **接口设计**：`run_provider(capability, content, context)` 三参数是否够用？是否需要 `session_id`、`timeout`、`priority` 等？
3. **错误处理**：MCP 工具调用失败时返回 dict 的 `success`/`error` 字段是否清晰？
4. **配置脚本**：`scripts/configure_marvis_mcp.py` 是否有边界 case 未处理？（Marvis 配置文件格式变更、权限问题等）
5. **ADR-0007**：决策记录是否充分说明了"为什么放弃 V0.4"？
6. **残留代码**：`providers/marvis/` + `cli/main.py` 中的 V0.4 残留应该立刻清理还是先观察？
7. **测试覆盖**：audit 脚本覆盖了协议层、配置层、入口兼容性，但**没有覆盖** Provider/Bridge 行为（这些由原 V0.0~V0.3 测试覆盖）。需要补吗？

---

## 7. 可重跑验证

```bash
cd "C:\Users\Administrator\.qclaw\workspace-bg0wgtn9jlge3doh\ai-hub"
python verify_audit.py
```

输出会写到 stdout，可重定向到文件：
```bash
python verify_audit.py > AUDIT_OUTPUT.txt
```

---

## 8. 提交清单（待 git commit）

```
M  docs/ROADMAP.md                          (V0.4 状态更新)
M  pyproject.toml                            (build-backend + packages 修复)
?? V041_VERIFICATION_REPORT.md               (验收报告)
?? AUDIT_OUTPUT.txt                          (audit 原始输出)
?? adapters/__init__.py                      (空包标记)
?? adapters/marvis_mcp_server.py             (MCP server 主实现)
?? scripts/configure_marvis_mcp.py           (Marvis 配置脚本)
?? docs/adr/0007-marvis-integration-via-mcp.md (ADR)
?? verify_audit.py                           (审计脚本)
```

**未变更**（保持冻结承诺）：
- `core/` — V0.0.6 冻结接口
- `router/` — V0.0.6 冻结接口
- `providers/*` — 除 `marvis/` 残留外，其他不动

---

**最后更新**：2026-07-12 22:25 GMT+8
**状态**：等待 ChatGPT 审查
