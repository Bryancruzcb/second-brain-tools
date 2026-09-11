// Record docs/demo.gif from the live app: a short walk through the scrollable
// workspace (Overview -> note reader -> Map -> node click -> Repair -> Ask).
// Needs the backend and the frontend on localhost:3000, plus Ollama for the
// Ask frame (skipped with a note if the answer does not arrive). Record from
// `npm run build && npm start`, not `next dev`, so the dev badge stays out.
//
//   cd frontend && node record-demo.mjs
//   BASE_URL=http://localhost:3000 OUT=../docs/demo.gif node record-demo.mjs
//
// Frames are stills held ~1.6 s each, assembled with ffmpeg from PATH
// (winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg).
import { chromium } from "playwright";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

const BASE_URL = process.env.BASE_URL || "http://localhost:3000/";
const OUT = path.resolve(process.env.OUT || path.join("..", "docs", "demo.gif"));
const WIDTH = 1280;
const HEIGHT = 800;
const HOLD_S = 1.6;
const GIF_WIDTH = 1000;

function findFfmpeg() {
  // Playwright's bundled ffmpeg is a minimal build (no gif encoder, no
  // palettegen), so this needs a full ffmpeg on PATH.
  try {
    execFileSync("ffmpeg", ["-version"], { stdio: "ignore" });
    return "ffmpeg";
  } catch {
    return null;
  }
}

const frameDir = fs.mkdtempSync(path.join(os.tmpdir(), "sbt-demo-"));
const frames = [];
async function frame(page, name) {
  const file = path.join(frameDir, `${String(frames.length).padStart(2, "0")}-${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  frames.push(file);
  console.log("frame", name);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT } });
const page = await context.newPage();
await page.goto(BASE_URL, { waitUntil: "domcontentloaded", timeout: 30000 });
await page.waitForSelector(".map-node", { timeout: 30000 });
await page.waitForSelector(".reel button.card", { timeout: 30000 });
await page.waitForTimeout(1000);

// 1. Overview: sidebar, live counts, recent reel.
await frame(page, "overview");

// 2. Open the first recent note inline.
await page.locator(".reel button.card").first().click();
await page.waitForTimeout(1200);
await page.evaluate(() => document.getElementById("notes")?.scrollIntoView({ behavior: "auto", block: "start" }));
await page.waitForTimeout(400);
await frame(page, "reader");
await page.locator("#notes article button:has-text('Close')").click();
await page.waitForTimeout(500);

// 3. Map, drawn on the page with labelled hubs.
await page.click('.app-sidebar a[href="#map"]');
await page.waitForTimeout(1500);
await frame(page, "map");

// 4. Hover a quiet node so its label shows, then click a hub.
const quiet = page.locator(".map-node:has(.map-label-quiet)").first();
if (await quiet.count()) {
  const box = await quiet.locator("circle").first().boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(400);
  await frame(page, "map-hover");
}
const hub = page.locator(".map-node").first();
const hubBox = await hub.locator("circle").first().boundingBox();
await page.mouse.click(hubBox.x + hubBox.width / 2, hubBox.y + hubBox.height / 2);
await page.waitForTimeout(1600);
await frame(page, "reader-from-map");

// 5. Back to the map to show the selected hub with lit edges and neighbours.
await page.click('.app-sidebar a[href="#map"]');
await page.waitForTimeout(1500);
await frame(page, "map-selected");

// 6. Repair queue.
await page.click('.app-sidebar a[href="#health"]');
await page.waitForTimeout(1500);
await frame(page, "repair");

// 7. Ask, with the context chip seeded by the map click.
await page.click('.app-sidebar a[href="#ask"]');
await page.waitForTimeout(1500);
await page.click('#ask button[aria-pressed]:has-text("Notes")');
await page.fill('#ask input[aria-label="Ask"]', "Which notes are most connected?");
await frame(page, "ask-typed");
await page.keyboard.press("Enter");
const answered = await page
  .waitForSelector("#ask .ask-answer", { timeout: 120000 })
  .then(() => true)
  .catch(() => false);
if (answered) {
  await page.waitForTimeout(600);
  await frame(page, "ask-answer");
} else {
  console.log("no Ask answer within 120 s (Ollama down?) - skipping that frame");
}

await browser.close();

// Assemble: hold each still, 2-pass palette for clean text.
const ffmpeg = findFfmpeg();
if (!ffmpeg) {
  console.error(`ffmpeg not found on PATH; frames kept in ${frameDir}`);
  process.exit(1);
}
const list = path.join(frameDir, "frames.txt");
fs.writeFileSync(
  list,
  frames.map((f) => `file '${f.replace(/\\/g, "/")}'\nduration ${HOLD_S}`).join("\n") +
    `\nfile '${frames[frames.length - 1].replace(/\\/g, "/")}'\n`,
);
const filters = `fps=4,scale=${GIF_WIDTH}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3`;
fs.mkdirSync(path.dirname(OUT), { recursive: true });
execFileSync(ffmpeg, ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list, "-vf", filters, "-loop", "0", OUT], {
  stdio: "inherit",
});
const kb = Math.round(fs.statSync(OUT).size / 1024);
console.log(`wrote ${OUT} (${frames.length} frames, ${kb} KB)`);
fs.rmSync(frameDir, { recursive: true, force: true });
