#!/usr/bin/env node
"use strict";

const puppeteer = require("/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer");
const path = require("path");
const fs = require("fs");

const BASE = process.env.CAPTURE_BASE || "http://localhost:8000";
const OUT = path.resolve(__dirname, "../video/memoria-demo/public/screenshots");
const USER = process.env.CAPTURE_USER || "tester";
const PASS = process.env.CAPTURE_PASS || "tester123";

const VIEWPORT = { width: 1920, height: 1080, deviceScaleFactor: 1 };
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

const FREEZE_STYLE = `
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
  }
`;

async function login(page) {
  let attempts = 0;
  while (attempts < 3) {
    try {
      await page.goto(`${BASE}/accounts/login/`, { waitUntil: "domcontentloaded", timeout: 60000 });
      break;
    } catch (err) {
      attempts++;
      console.warn(`  login page nav timed out, retrying (${attempts}/3)`);
      if (attempts >= 3) throw err;
      await delay(3000);
    }
  }
  await page.waitForSelector("input[name='login']", { timeout: 20000 });
  await page.type("input[name='login']", USER);
  await page.type("input[name='password']", PASS);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 45000 }),
    page.click("button[type='submit']")
  ]);
  await delay(1500);
}

async function freezeAnimations(page) {
  await page.addStyleTag({ content: FREEZE_STYLE });
}

async function shot(page, filename, url, opts = {}) {
  await page.setViewport(VIEWPORT);
  try {
    await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 45000 });
  } catch (err) {
    console.warn(`  ⚠ ${filename} navigation slow, retrying with networkidle2 strategy…`);
    await page.goto(`${BASE}${url}`, { waitUntil: "load", timeout: 45000 });
  }
  await freezeAnimations(page);
  await delay(opts.settleMs ?? 1800);
  if (opts.scrollY) await page.evaluate((y) => window.scrollTo(0, y), opts.scrollY);
  await delay(600);
  const out = path.join(OUT, filename);
  await page.screenshot({ path: out, fullPage: false });
  console.log(`  ✓ ${filename}`);
}

async function findConversationUrl(page) {
  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await delay(700);
  const href = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll("a[href*='/chat/c/']"));
    return links.length ? links[0].getAttribute("href") : null;
  });
  return href;
}

async function captureTypingWebm(page) {
  const out = path.join(OUT, "chat_typing.webm");
  const convoHref = await findConversationUrl(page);
  const chatUrl = convoHref ? `${BASE}${convoHref}` : `${BASE}/`;
  await page.setViewport(VIEWPORT);
  await page.goto(chatUrl, { waitUntil: "domcontentloaded", timeout: 25000 });
  await delay(1500);

  const recorder = await page.screencast({ path: out });
  await delay(500);
  const composer = await page.$("textarea, [contenteditable='true'], input[type='text']");
  if (composer) {
    const text = "@Kevin's Agent — can you pick this up for me while I'm out?";
    for (const ch of text) {
      await composer.type(ch, { delay: 50 });
    }
    await delay(800);
  } else {
    await delay(5500);
  }
  await recorder.stop();
  console.log("  ✓ chat_typing.webm");
}

async function captureScrollWebm(page, url, filename) {
  const out = path.join(OUT, filename);
  await page.setViewport(VIEWPORT);
  await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 25000 });
  await freezeAnimations(page);
  await delay(1500);

  const recorder = await page.screencast({ path: out });
  for (let y = 0; y <= 1200; y += 8) {
    await page.evaluate((py) => window.scrollTo(0, py), y);
    await delay(16);
  }
  await delay(600);
  await recorder.stop();
  console.log(`  ✓ ${filename}`);
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await puppeteer.launch({
    headless: "new",
    args: ["--no-sandbox", "--window-size=1920,1080"],
    defaultViewport: VIEWPORT
  });

  try {
    const page = await browser.newPage();
    await page.setViewport(VIEWPORT);

    console.log("→ Logging in as", USER);
    await login(page);

    console.log("→ Capturing authenticated stills");
    await shot(page, "dashboard.png", "/chat/dashboard/");
    await shot(page, "agent_hub.png", "/chat/agents/my/");
    await shot(page, "memory.png", "/chat/memory/");
    await shot(page, "documents.png", "/chat/documents/");
    await shot(page, "analytics.png", "/chat/analytics/");

    const convoHref = await findConversationUrl(page);
    if (convoHref) {
      const chatUrl = convoHref.startsWith("http") ? convoHref.replace(BASE, "") : convoHref;
      await shot(page, "chat.png", chatUrl);
    } else {
      await shot(page, "chat.png", "/chat/");
    }

    console.log("→ Capturing screencasts");
    try {
      await captureTypingWebm(page);
    } catch (e) {
      console.warn("  ✗ chat_typing.webm skipped:", e.message);
    }
    try {
      await captureScrollWebm(page, "/memory/", "memory_scroll.webm");
    } catch (e) {
      console.warn("  ✗ memory_scroll.webm skipped:", e.message);
    }

    console.log("✓ Done. Output:", OUT);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error("capture_video_assets failed:", err);
  process.exit(1);
});
