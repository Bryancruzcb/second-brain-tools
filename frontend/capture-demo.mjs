import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';

(async () => {
  const outDir = path.resolve('..', 'docs', '_demo_frames');
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(20000);
  console.log('goto');
  await page.goto('http://127.0.0.1:3000/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);
  console.log('title', await page.title());
  // dump some button/nav text for debugging
  const texts = await page.locator('button, a, [role="tab"], nav *').allTextContents();
  console.log('nav-ish texts', texts.slice(0, 40));
  await page.screenshot({ path: path.join(outDir, '01-hero.png'), fullPage: false });
  console.log('hero ok');

  const tabs = ['Overview', 'Map', 'Repair', 'Ask'];
  for (let i = 0; i < tabs.length; i++) {
    const label = tabs[i];
    let clicked = false;
    for (const sel of [
      `button:has-text("${label}")`,
      `[role="tab"]:has-text("${label}")`,
      `text=${label}`,
    ]) {
      try {
        const loc = page.locator(sel).first();
        if (await loc.count()) {
          await loc.click({ timeout: 3000 });
          clicked = true;
          break;
        }
      } catch (_) {}
    }
    console.log(label, clicked ? 'clicked' : 'not found');
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(outDir, `0${i+2}-${label.toLowerCase()}.png`), fullPage: false });
  }

  await page.evaluate(() => window.scrollBy(0, 320));
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(outDir, '06-scroll.png'), fullPage: false });
  await browser.close();
  console.log('done', outDir);
})().catch((e) => { console.error(e); process.exit(1); });
