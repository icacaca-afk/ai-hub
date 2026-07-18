/**
 * chatgpt_cdp_ws.js — 修复版 CDP 连接（用 ws URL 绕过 Playwright 1.60-alpha 兼容问题）
 *
 * 用法：node chatgpt_cdp_ws.js
 * 输出：诊断信息（连接 / ChatGPT 页面 / 编辑器）
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
  try {
    const wsUrl = await fetchWsUrl();
    console.log('WS URL:', wsUrl);

    const browser = await chromium.connectOverCDP(wsUrl);
    const ctx = browser.contexts()[0];
    const pages = ctx.pages();
    const page = pages.find(p => p.url().includes('chatgpt.com'));

    if (!page) {
      console.error('ERROR: No ChatGPT tab found. Open https://chatgpt.com in Chrome first.');
      process.exit(1);
    }

    console.log('Connected to:', await page.title());
    console.log('URL:', page.url());

    const editor = page.locator('#prompt-textarea').first();
    const hasEditor = await editor.count();
    console.log('Editor found:', hasEditor > 0 ? 'YES' : 'NO');

    await browser.close();
  } catch (e) {
    console.error('ERROR:', e.message);
    process.exit(1);
  }
})();
