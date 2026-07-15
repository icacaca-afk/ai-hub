const { chromium } = require('playwright');
(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = b.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('chatgpt.com'));
  if (!page) { console.error('NO PAGE'); process.exit(1); }

  // 检查是否还在生成
  const stopBtn = page.locator('[data-testid="stop-button"]');
  const stillGen = await stopBtn.isVisible({ timeout: 2000 }).catch(() => false);
  if (stillGen) {
    console.log('STILL_GENERATING');
    await b.close();
    process.exit(0);
  }

  // 获取所有 assistant 消息
  const elements = await page.$$('[data-message-author-role="assistant"]');
  if (elements.length === 0) {
    console.log('NO_REPLIES');
    await b.close();
    process.exit(0);
  }

  // 获取最后一条
  const lastEl = elements[elements.length - 1];
  const text = await lastEl.innerText();
  console.log(text);

  await b.close();
})().catch(e => { console.error('ERR:', e.message); process.exit(1); });
