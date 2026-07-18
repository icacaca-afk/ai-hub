/**
 * chatgpt_send_v2.js — 修复版：先 fetch ws URL 再 connectOverCDP（绕开 Playwright 1.60-alpha 兼容问题）
 *
 * 用法：node chatgpt_send_v2.js "<message text>"
 *       或通过 stdin
 *
 * 与 chatgpt_send.js 区别：用 ws URL 替代 http URL（避免 "Unexpected status 400" 错误）
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
  let message = process.argv[2];
  if (!message) {
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    message = Buffer.concat(chunks).toString('utf-8').trim();
  }

  if (!message) {
    console.error('ERROR: No message provided. Usage: node chatgpt_send_v2.js "<message>"');
    process.exit(1);
  }

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
    await page.waitForTimeout(500);

    const editor = page.locator('#prompt-textarea').first();
    await editor.waitFor({ timeout: 10000 });
    await editor.click();
    await page.waitForTimeout(300);

    // 分块插入（每 500 字符）
    for (let i = 0; i < message.length; i += 500) {
      await page.keyboard.insertText(message.substring(i, i + 500));
      await page.waitForTimeout(120);
    }

    await page.waitForTimeout(600);
    await page.keyboard.press('Enter');

    console.log('Sent! Length:', message.length, 'chars');
    await browser.close();
  } catch (e) {
    console.error('ERROR:', e.message);
    process.exit(1);
  }
})();
