const { chromium } = require('playwright');
(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = b.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('chatgpt.com'));
  if (!page) { console.error('NO ChatGPT page'); process.exit(1); }

  await page.bringToFront();
  await page.waitForTimeout(500);

  const question = `你好，这是 ai-hub 项目的又一轮审核。

## 背景

ai-hub 是一个多 AI Provider 路由运行时。已完成 V0.8.0 ScoreRouter（评分路由器），评分公式：
total = (capability×40 + health×25 + priority×20 + latency×10 + quota×5) / 100

但 CLI 的 ask 和 explain-route 命令仍在用基础 Router（按注册顺序选第一个 healthy provider），导致实际运行时选了 Stub（priority=10）而不是 Gemini CLI（priority=80）。

## 本次变更：V0.8.1 CLI 接入 ScoreRouter

### 改动文件（2 个 CLI 文件 + 1 个测试清理）

**1. cli/main.py — cmd_ask()**
- Router → ScoreRouter（加 HealthRegistry）
- 输出新增评分明细行

**2. cli/explain_route.py — cmd_explain_route()**
- HealthAwareRouter → ScoreRouter
- _output_human() 新增 score 行展示
- _output_json() 新增 score 字段（用 ProviderScore.to_dict()）
- version 从 v0.7.1 改为 v0.8

**3. tests/test_marvis_e2e.py — 删除**
- providers.marvis 在 V0.4.2 已删除，测试文件遗留至今

### 关键设计决策

1. **为什么 cmd_ask 用 ScoreRouter 而非 HealthAwareRouter？**
   ScoreRouter 继承 HealthAwareRouter，route() 中先做 Health Filter 再做 Score 排序。用 ScoreRouter 可以确保 CLI 选择的 Provider 是评分最高的，而非注册顺序第一个。

2. **为什么 explain_route 也切换？**
   explain-route 的目的是展示路由决策过程。用 ScoreRouter 可以额外展示评分明细，让用户理解为什么选了某个 Provider。

3. **score 输出格式**
   Human: \`score: 94.7 (cap=100 health=100 pri=80 lat=87 quota=100)\`
   JSON: \`"score": {"provider": "gemini_cli", "capability": 100.0, "health": 100.0, "priority": 80.0, "latency": 87.0, "quota": 100.0, "total": 94.7}\`

### 冻结检查
- core/ ✅ 零修改
- router/router.py ✅ 零修改
- router/health_router.py ✅ 零修改
- router/score_router.py ✅ 零修改
- providers/ ✅ 零修改

### 测试结果
- test_score_router.py: 17 passed
- test_explain_route.py: 19 passed
- 其余测试（不含 explain_route + mcp_contract）: 118 passed, 16 skipped, 0 failed
- test_benchmark.py 2 个 timeout（subprocess 60s 限制，非回归）
- test_marvis_e2e.py 已删除

### 实际运行验证
\`\`\`
ai-hub explain-route "write a hello world program"

Gemini CLI → SELECTED
  score: 94.7 (cap=100 health=100 pri=80 lat=87 quota=100)
Stub
  score: 82.0 (cap=100 health=100 pri=10 lat=100 quota=100)
Demo
  score: 80.0 (cap=100 health=100 pri=0 lat=100 quota=100)
\`\`\`

## 审核问题

1. cmd_ask 现在每次都会创建 HealthRegistry 并在 route() 时做 health check（lazy=True 用缓存）。这在 CLI 一次性运行场景下是否合理？是否需要加 --no-health 选项跳过 health check？

2. explain_route 的 version 字段从 "v0.7.1" 改为 "v0.8"。之前 ChatGPT 建议过改为 schema_version + runtime_version。这次先简单改版本号，V0.8.2 再做 schema cleanup。这个节奏可以吗？

3. score 输出格式 (cap=100 health=100 pri=80 lat=87 quota=100) 对 CLI 用户是否清晰？还是应该用更完整的 capability=100 health=100 priority=80 latency=87 quota=100？

4. 删除 test_marvis_e2e.py 是否有隐患？providers.marvis 在 V0.4.2 ADR-0007 中已记录删除。`;

  const editor = page.locator('#prompt-textarea').first();
  await editor.waitFor({ timeout: 10000 });
  await editor.click();
  await page.waitForTimeout(300);

  // 分块插入
  for (let i = 0; i < question.length; i += 500) {
    await page.keyboard.insertText(question.substring(i, i + 500));
    await page.waitForTimeout(120);
  }

  await page.waitForTimeout(600);
  await page.keyboard.press('Enter');
  console.log('Review request sent!');
  await b.close();
})().catch(e => { console.error('ERR:', e.message); process.exit(1); });
