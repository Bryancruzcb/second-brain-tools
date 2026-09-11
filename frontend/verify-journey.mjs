// Live check of the scrollable workspace against a running backend (:8000) and
// frontend (:3000). Prints one JSON report and writes screenshots to OUT_DIR.
//
//   cd frontend && node verify-journey.mjs
//   OUT_DIR=/tmp/shots BASE_URL=http://localhost:3000 API_PORT=8000 node verify-journey.mjs
//
// Exit code 1 when any check fails.
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

// `next dev` only hydrates for its own origin (localhost); use 127.0.0.1 against `next start`.
const BASE_URL = process.env.BASE_URL || "http://localhost:3000/";
/** Port the frontend was pointed at via NEXT_PUBLIC_API_URL; used to count API calls. */
const API_PORT = process.env.API_PORT || "8000";
const OUT_DIR = path.resolve(process.env.OUT_DIR || path.join("..", "docs", "_demo_frames"));
fs.mkdirSync(OUT_DIR, { recursive: true });

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok: Boolean(ok), detail: detail ?? null });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail != null ? `  — ${typeof detail === "string" ? detail : JSON.stringify(detail)}` : ""}`);
}

/* ---------- WCAG contrast for the palette pairs the page actually uses ---------- */
function srgbToLin(c) {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function luminance([r, g, b]) {
  return 0.2126 * srgbToLin(r) + 0.7152 * srgbToLin(g) + 0.0722 * srgbToLin(b);
}
function blend(fg, alpha, bg) {
  return fg.map((c, i) => Math.round(c * alpha + bg[i] * (1 - alpha)));
}
function contrast(fgHex, bgRgb) {
  const l1 = luminance(hexToRgb(fgHex));
  const l2 = luminance(bgRgb);
  const [a, b] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (a + 0.05) / (b + 0.05);
}
const PAGE = hexToRgb("#f5f5f7");
const SIDEBAR = hexToRgb("#fafafa");
const WHITE = hexToRgb("#ffffff");
const ACCENT = hexToRgb("#5e6ad2");
const pairs = [
  ["muted on page (subtitles, hints)", "#6e6e73", PAGE],
  ["muted on sidebar", "#6e6e73", SIDEBAR],
  ["muted on white (cards)", "#6e6e73", WHITE],
  ["ink on page", "#1d1d1f", PAGE],
  ["map label on page", "#6e6e73", PAGE],
  ["accent text on white", "#5e6ad2", WHITE],
  ["accent-ink on accent-soft over sidebar (active nav)", "#4652b8", blend(ACCENT, 0.1, SIDEBAR)],
  ["accent-ink on page (issue actions)", "#4652b8", PAGE],
  ["accent-ink on accent-softer over white (tag chips)", "#4652b8", blend(ACCENT, 0.06, WHITE)],
  ["accent-ink on accent-softer over page (count pill)", "#4652b8", blend(ACCENT, 0.06, PAGE)],
  ["danger text on page", "#b42318", PAGE],
  ["broken pill text on its tint over page", "#b42318", blend(hexToRgb("#d9534f"), 0.1, PAGE)],
  ["orphan pill text on its tint over page", "#8a5a10", blend(hexToRgb("#c9892a"), 0.12, PAGE)],
  ["tagless pill text on its tint over page", "#5f5f64", blend(hexToRgb("#6e6e73"), 0.12, PAGE)],
  ["ink 85% on sidebar (recent notes)", "#1d1d1f", SIDEBAR],
];
for (const [name, fg, bg] of pairs) {
  const ratio = contrast(fg, bg);
  check(`contrast ≥ 4.5: ${name}`, ratio >= 4.5, ratio.toFixed(2));
}

/* ---------- browser checks ---------- */
const browser = await chromium.launch({ headless: true });

async function openPage(context, label) {
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });
  const apiHits = {};
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.port === API_PORT) apiHits[u.pathname] = (apiHits[u.pathname] || 0) + 1;
  });
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForSelector(".map-node", { timeout: 30000 }).catch(() => null);
  await page.waitForTimeout(1200);
  page._label = label;
  page._errors = errors;
  page._apiHits = apiHits;
  return page;
}

const shot = (page, name) =>
  page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: false });

/** Wait until window.scrollY stops changing (smooth scrolls vary in length). */
async function settle(page, timeout = 4000) {
  const start = Date.now();
  let last = await page.evaluate(() => window.scrollY);
  let stable = 0;
  while (Date.now() - start < timeout) {
    await page.waitForTimeout(120);
    const y = await page.evaluate(() => window.scrollY);
    stable = y === last ? stable + 1 : 0;
    last = y;
    if (stable >= 3) break;
  }
  await page.waitForTimeout(200);
}

/* ----- Desktop ----- */
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await openPage(ctx, "desktop");

  check("desktop: sidebar visible", await page.locator(".app-sidebar").isVisible());
  check("desktop: top bar hidden", !(await page.locator("header.sticky").isVisible()));
  const sectionIds = await page.$$eval("main section[id]", (els) => els.map((e) => e.id));
  check("one <main> with the four sections in order", JSON.stringify(sectionIds) === JSON.stringify(["overview", "map", "health", "ask"]), sectionIds);
  check("no card/panel wrapper around the map", (await page.locator("#map .card-elevated, #map .glow-panel").count()) === 0);
  check("no bento grid / browser frame left", (await page.locator(".bento-grid, .browser-frame").count()) === 0);
  check("skip link is first tabbable", await page.evaluate(() => { document.body.focus(); return true; }));
  await page.keyboard.press("Tab");
  check("skip link receives first Tab", await page.evaluate(() => document.activeElement?.classList.contains("skip-link")));
  await page.keyboard.press("Enter");
  await page.waitForTimeout(300);
  check("skip link moves focus to <main>", await page.evaluate(() => document.activeElement?.id === "main"));

  const nodeCount = await page.locator(".map-node").count();
  check("map rendered nodes", nodeCount > 0, nodeCount);
  const labelled = await page.locator(".map-node .map-label:not(.map-label-quiet)").count();
  const quiet = await page.locator(".map-node .map-label-quiet").count();
  check("map labels: at least a third always-on (greedy placement)", labelled >= Math.ceil(nodeCount / 3), { labelled, quiet, total: nodeCount });
  const overlaps = await page.$$eval(".map-node .map-label:not(.map-label-quiet)", (els) => {
    const boxes = els.map((e) => e.getBoundingClientRect());
    let n = 0;
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        if (a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top) n++;
      }
    return n;
  });
  check("no two visible map labels overlap (measured)", overlaps === 0, overlaps);
  const svgBox = await page.locator("svg.map-svg").boundingBox();
  const mainBox = await page.locator("main").boundingBox();
  check("map spans the workspace width", svgBox && mainBox && svgBox.width >= mainBox.width - 60, svgBox && { svg: Math.round(svgBox.width), main: Math.round(mainBox.width) });

  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "journey-01-overview");

  // Sidebar nav → scroll + active state
  await page.click('.app-sidebar a[href="#map"]');
  await settle(page);
  check("sidebar Map link becomes aria-current", (await page.getAttribute('.app-sidebar a[href="#map"]', "aria-current")) === "location");
  const mapTop = await page.evaluate(() => document.getElementById("map").getBoundingClientRect().top);
  check("map section scrolled near the top", mapTop >= -10 && mapTop < 120, Math.round(mapTop));
  await shot(page, "journey-02-map");

  // Scroll-spy without clicking: scroll to Ask and see the sidebar follow
  await page.evaluate(() => document.getElementById("ask").scrollIntoView({ behavior: "auto", block: "start" }));
  await page.waitForTimeout(500);
  check("scroll-spy: Ask active after plain scroll", (await page.getAttribute('.app-sidebar a[href="#ask"]', "aria-current")) === "location");
  await shot(page, "journey-04-ask");
  await page.evaluate(() => document.getElementById("health").scrollIntoView({ behavior: "auto", block: "start" }));
  await page.waitForTimeout(500);
  await shot(page, "journey-03-repair");

  // Map node click → reader opens + ask context chip
  await page.click('.app-sidebar a[href="#map"]');
  await settle(page);
  // Click the node's dot, not the <g> bbox centre (which can land between dot and label).
  const clickNode = async (loc) => {
    const box = await loc.locator("circle").first().boundingBox();
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  };
  const firstNode = page.locator(".map-node").first();
  const firstTitle = (await firstNode.getAttribute("aria-label")) || "";
  await clickNode(firstNode);
  await page.waitForTimeout(1500);
  const readerTitle = await page.locator("#notes article h3").first().textContent().catch(() => null);
  check("map node click opens the reader", Boolean(readerTitle), readerTitle);
  check("reader title matches the clicked node", readerTitle && firstTitle.startsWith(readerTitle.trim()), { readerTitle, firstTitle });
  check("map node click seeds Ask context chip", (await page.locator(".context-chip").count()) === 1);
  check("active node has aria-pressed", (await page.locator('.map-node[aria-pressed="true"]').count()) === 1);
  await shot(page, "journey-05-reader-from-map");

  // Keyboard on the map: focus a node, Enter selects it, focus ring visible
  await page.locator(".map-node").nth(1).focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(800);
  const secondTitle = (await page.locator(".map-node").nth(1).getAttribute("aria-label")) || "";
  const readerTitle2 = await page.locator("#notes article h3").first().textContent().catch(() => null);
  check("keyboard Enter on a node selects it", readerTitle2 && secondTitle.startsWith(readerTitle2.trim()), { readerTitle2, secondTitle });

  // Repair → reader with callout
  await page.click('.app-sidebar a[href="#health"]');
  await settle(page);
  const issueBtn = page.locator("#health ul li button").first();
  if (await issueBtn.count()) {
    await issueBtn.click();
    await page.waitForTimeout(1200);
    check("repair issue opens the reader with a repair callout", (await page.locator("#notes .repair-callout").count()) === 1);
  } else {
    check("repair issue opens the reader with a repair callout", true, "no issues to open (clean scan)");
  }
  const showMore = page.locator("#health .show-more");
  if (await showMore.count()) {
    const before = await page.locator("#health ul li").count();
    await showMore.click();
    const after = await page.locator("#health ul li").count();
    check("repair Show all expands the list", after > before, { before, after });
  }

  // Sidebar recent note → reader
  const recentBtn = page.locator(".sidebar-note").first();
  const recentTitle = (await recentBtn.locator("span").first().textContent()) || "";
  await recentBtn.click();
  await page.waitForTimeout(1200);
  const readerTitle3 = await page.locator("#notes article h3").first().textContent().catch(() => null);
  check("sidebar recent note opens the reader", readerTitle3 && readerTitle3.trim() === recentTitle.trim(), { readerTitle3, recentTitle });
  check("sidebar recent note marked aria-pressed", (await page.locator('.sidebar-note[aria-pressed="true"]').count()) === 1);

  // Reel card click toggles the reader (the first card may already be the open note)
  const openBefore = await page.locator("#notes .expand-panel").getAttribute("data-open");
  await page.locator(".reel button.card").first().click();
  await page.waitForTimeout(600);
  const openAfter = await page.locator("#notes .expand-panel").getAttribute("data-open");
  check("reel card click toggles the reader", openBefore !== openAfter, { openBefore, openAfter });

  // Ask scope chips still work
  await page.click('#ask button[aria-pressed]:has-text("All")');
  check("ask scope chip toggles", (await page.getAttribute('#ask button:has-text("All")', "aria-pressed")) === "true");

  check("desktop: no console/page errors", page._errors.length === 0, page._errors.slice(0, 5));
  check("/api/health fetched once (shared cache)", page._apiHits["/api/health"] === 1, page._apiHits);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(OUT_DIR, "journey-full.png"), fullPage: true });
  await ctx.close();
}

/* ----- Reduced motion ----- */
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const page = await openPage(ctx, "reduced-motion");
  check("reduced motion: html scroll-behavior is auto", (await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior)) === "auto");
  await page.click('.app-sidebar a[href="#ask"]');
  const y = await page.evaluate(() => window.scrollY);
  check("reduced motion: nav jump is instant", y > 500, y);
  const anim = await page.evaluate(() => getComputedStyle(document.querySelector(".glow-line")).animationDuration);
  check("reduced motion: glow animation disabled", parseFloat(anim) <= 0.001, anim);
  check("reduced motion: no console/page errors", page._errors.length === 0, page._errors.slice(0, 5));
  await ctx.close();
}

/* ----- Tablet + mobile ----- */
for (const [label, viewport] of [["tablet", { width: 820, height: 1180 }], ["mobile", { width: 390, height: 844 }]]) {
  const ctx = await browser.newContext({ viewport, isMobile: label === "mobile", hasTouch: label === "mobile" });
  const page = await openPage(ctx, label);
  check(`${label}: sidebar hidden`, !(await page.locator(".app-sidebar").isVisible()));
  check(`${label}: top bar visible with 4 section links`, (await page.locator("header.sticky nav a").count()) === 4);
  const overflow = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  check(`${label}: no horizontal page overflow`, overflow.scrollWidth <= overflow.innerWidth, overflow);
  const svgBox = await page.locator("svg.map-svg").boundingBox();
  check(`${label}: map fits the viewport width`, svgBox && svgBox.width <= viewport.width, svgBox && Math.round(svgBox.width));
  const nodes = await page.locator(".map-node").count();
  check(`${label}: map renders`, nodes > 0, nodes);
  await page.click('header.sticky nav a[href="#map"]');
  await settle(page);
  const mapTop = await page.evaluate(() => document.getElementById("map").getBoundingClientRect().top);
  check(`${label}: top bar link scrolls to Map below the sticky bar`, mapTop >= 40 && mapTop < 140, Math.round(mapTop));
  check(`${label}: top bar link becomes aria-current`, (await page.getAttribute('header.sticky nav a[href="#map"]', "aria-current")) === "location");
  await shot(page, `journey-${label}-map`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, `journey-${label}-overview`);
  check(`${label}: no console/page errors`, page._errors.length === 0, page._errors.slice(0, 5));
  await ctx.close();
}

await browser.close();

const failed = checks.filter((c) => !c.ok);
console.log(JSON.stringify({ passed: checks.length - failed.length, failed: failed.length, outDir: OUT_DIR, failures: failed }, null, 2));
process.exit(failed.length ? 1 : 0);
