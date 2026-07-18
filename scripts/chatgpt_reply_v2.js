/**
 * chatgpt_reply_v2.js — 修复版：用 ws URL 连接，绕过 Playwright 1.60-alpha 兼容问题
 *
 * 用法：node chatgpt_reply_v2.js [--wait <seconds>]
 * 默认 wait 180 秒
 */

const { chromium } = require('playwright');
const http = require('http');

function fetchWsUrl() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222/json/version', (res) => {
      let data = '';
      res.on('data', (c) => data += c);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data).webSocketDebuggerUrl);
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

(async () => {
  const waitIdx = process.argv.indexOf('--wait');
  const waitSeconds = waitIdx > -1 ? parseInt(process.argv[waitIdx + 1]) || 180 : 180;

  try {
    const wsUrl = await fetchWsUrl();
    const browser = await chromium.connectOverCDP(wsUrl);
    const ctx = browser.contexts()[0];
    const page = ctx.pages().find(p => p.url().includes('chatgpt.com'));

    if (!page) {
      console.error('ERROR: No ChatGPT tab found.');
      process.exit(1);
    }

    await page.bringToFront();

    // 等待回复完成
    let lastCount = 0;
    let stableCount = 0;
    const maxIterations = waitSeconds * 2;

    for (let i = 0; i < maxIterations; i++) {
      await page.waitForTimeout(500);

      const info = await page.evaluate(() => {
        const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
        const stopBtn = document.querySelector('[data-testid="stop-button"]');
        return {
          count: msgs.length,
          isGenerating: !!stopBtn
        };
      });

      if (i % 4 === 0) {
        console.log(`[${new Date().toISOString()}] count=${info.count} generating=${info.isGenerating}`);
      }

      if (info.count === lastCount && !info.isGenerating) {
        stableCount++;
        if (stableCount >= 4) break;
      } else {
        stableCount = 0;
      }
      lastCount = info.count;
    }

    // 滚动到底部
    await page.evaluate(() => {
      const scrollContainer = document.querySelector('main') || document.body;
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    });
    await page.waitForTimeout(1000);

    const lastReply = await page.evaluate(() => {
      const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
      if (msgs.length === 0) return null;
      return msgs[msgs.length - 1].innerText;
    });

    if (lastReply) {
      console.log('=== CHATGPT REPLY (full) ===');
      console.log(lastReply);
    } else {
      console.log('No assistant reply found. ChatGPT may still be generating.');
      process.exit(2);
    }

    await browser.close();
  } catch (e) {
    console.error('ERROR:', e.message);
    process.exit(1);
  }
})();
