# ai-hub ChatGPT 自动审核流程（完整操作指南）

> 用途：每个版本（V0.x）开发完成后，把改动发给 ChatGPT 做外部 AI 专家审核，取回评分 + 结论 + 改进建议。
> 本流程已在 V0.6–V0.8.2 多次验证可用（`chatgpt-review` skill 已实现）。
> 适用接手人：Trae（或其他 Agent）。

---

## 前置条件（⚠️ 每次审核前必须确认）

### 1. Chrome 启动（关键坑）

普通 `chrome.exe --remote-debugging-port=9222` **不会开放调试端口**，必须带 `--user-data-dir`：

```powershell
# 用这个命令启动（目录可自定义，首次需手动登录 ChatGPT）
Start-Process "chrome.exe" -ArgumentList "--user-data-dir=C:\Temp\chrome-debug","--remote-debugging-port=9222"
```

启动后在弹出的 Chrome 窗口打开 `https://chatgpt.com` 并登录（首次会要求扫码/输密码）。

### 2. NODE_PATH 配置

Playwright 的 node_modules 路径必须设置（PowerShell 会话内）：

```powershell
$env:NODE_PATH = "C:\Users\Administrator\AppData\Roaming\QClaw\npm-global\node_modules\@playwright\cli\node_modules"
```

### 3. OpenClaw 内置 browser 工具不可用

对 chatgpt.com 被 SSRF 策略拦截，**只能用 Playwright CDP 直连**（below）。不要用 OpenClaw 的 `browser` 工具 / `xbrowser`。

---

## 完整操作流程（5 步）

### Step 1 — 检查连接

```powershell
$env:NODE_PATH = "C:\Users\Administrator\AppData\Roaming\QClaw\npm-global\node_modules\@playwright\cli\node_modules"
node C:\Users\Administrator\.qclaw\skills\chatgpt-review\scripts\chatgpt_cdp.js
```

输出 `Connected to: ...` + `Editor found: YES` 即就绪。否则回到「前置条件 1」重开 Chrome。

### Step 2 — 构造审核请求

按 `C:\Users\Administrator\.qclaw\skills\chatgpt-review\references\review_template.md` 的模板写。模板核心结构：

```
{V版本号} 审核请求

你上一轮{批准/建议}了 {上一版本}。{当前版本}已实现：

━━━ 新增文件 ━━━
1. file — 描述

━━━ 设计 ━━━
{核心设计决策 / 接口 / 数据流}

━━━ 范围约束 ━━━
只做：...
不做：❌ ...

━━━ 冻结/兼容检查 ━━━
core/ — 0修改 ✅
router/router.py — 0修改 ✅
providers/ — 0修改 ✅

━━━ 测试 ━━━
新增{N}测试，全量：{passed} passed, {skipped} skipped, 0 failed
Git: {commit hash}

━━━ 确认问题 ━━━
1. {具体技术问题}
2. {下一步建议}
```

**要点**：一次一个版本 / 提供完整上下文（ChatGPT 无项目记忆）/ 明确"不做"比"做"更重要 / 提具体问题不要问"怎么样" / 引用前序审核形成审核链。

### Step 3 — 发送

**长文本（推荐，避免截断）：** 把审核内容写入一个临时 `.js` 文件（参考 SKILL.md「方式 A」模板），用 `chatgpt_send.js` 的循环分块插入逻辑。或简单用：

```powershell
$env:NODE_PATH = "C:\Users\Administrator\AppData\Roaming\QClaw\npm-global\node_modules\@playwright\cli\node_modules"
node C:\Users\Administrator\.qclaw\skills\chatgpt-review\scripts\chatgpt_send.js "$(Get-Content review_prompt.txt -Raw)"
```

（`review_prompt.txt` 是 Step 2 写好的审核文本；`chatgpt_send.js` 会自动分块每 500 字符插入，ProseMirror 编辑器 `fill()` 无效必须用 `insertText`）

### Step 4 — 等待并取回回复

```powershell
$env:NODE_PATH = "C:\Users\Administrator\AppData\Roaming\QClaw\npm-global\node_modules\@playwright\cli\node_modules"
node C:\Users\Administrator\.qclaw\skills\chatgpt-review\scripts\chatgpt_reply.js --wait 180
```

`--wait` = 最大等待秒数（默认 120，复杂审核用 180+）。脚本会检测「停止生成」按钮消失 + 消息数稳定 2 秒后才提取，用 `innerText` 全量返回不截断。

### Step 5 — 解析结论并更新文档

从回复提取：评分（X.X/10）、结论（APPROVED/MERGE/NEEDS REVISION）、逐项评价、非阻塞建议、后续路线。

- 若 **APPROVED**：在 commit message / ADR 标注 `ChatGPT 审核 9.X/10 APPROVED`，可合入 + tag + push。
- 若有**阻塞问题**：修复后重发审核（引用上一轮结论）。
- 若**非阻塞建议**：评估是否纳入下一版本（如 V0.8.2 的四项建议即来自 V0.8 审核）。

更新项目文档（`MEMORY.md` / 对应 ADR / `HANDOFF_TO_TRAE.md` 如有需要）。

---

## 脚本位置

| 脚本 | 用途 |
|------|------|
| `C:\Users\Administrator\.qclaw\skills\chatgpt-review\scripts\chatgpt_cdp.js` | 连接诊断 |
| `C:\Users\Administrator\.qclaw\skills\chatgpt-review\scripts\chatgpt_send.js` | 发送消息 |
| `C:\Users\Administrator\.qclaw\skills\chatgpt-review\scripts\chatgpt_reply.js` | 取回回复 |
| `C:\Users\Administrator\.qclaw\skills\chatgpt-review\references\review_template.md` | 审核模板 |

完整细节见 `C:\Users\Administrator\.qclaw\skills\chatgpt-review\SKILL.md`。

---

## 历史审核记录（参考评分标准）

| 版本 | 评分 | 结论 | 关键建议 |
|------|------|------|----------|
| V0.6.3 | 9.6/10 | ✅ APPROVED | Health 是 Capability 不改 core |
| V0.7.0 | 9.5/10 | ✅ | Health Filter 跳过 unavailable |
| V0.7.2 | 9.7/10 | ✅ | version → schema_version（后纳入 V0.8.2） |
| V0.8.0 | 9.5/10 | ✅ MERGE | 完整名称输出 |
| V0.8.1 | 9.6/10 | ✅ APPROVED | 四项建议 → V0.8.2 |

---

## 给 Trae 的启动 Prompt

```
ai-hub 每个版本做完后需要发给 ChatGPT 外部审核。
请读 ai-hub/CHATGPT_REVIEW_WORKFLOW.md 和
~/.qclaw/skills/chatgpt-review/SKILL.md 了解完整流程。
流程：1) 带 --user-data-dir 启动 Chrome + 登录 ChatGPT；
2) 用 chatgpt_cdp.js 验证连接；
3) 按 review_template.md 构造审核请求；
4) chatgpt_send.js 发送；
5) chatgpt_reply.js 取回，解析评分/结论，APPROVED 才合入。
注意：OpenClaw 内置 browser 对 chatgpt.com 被 SSRF 拦截，必须用 Playwright CDP。
```
