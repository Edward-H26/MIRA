import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import { mkdirSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";

const BASE = "http://127.0.0.1:8765";
const SESSION_COOKIE = process.env.SESSION_COOKIE || "";
const OUT_DIR = resolve("/Users/edwardhu/Desktop/INFO490/miramemoria/docs/screenshots");
const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 2 };

if (!existsSync(OUT_DIR)) {
  mkdirSync(OUT_DIR, { recursive: true });
}

const targets = [
  { file: "01-landing.png", path: "/", needsAuth: false },
  { file: "02-home.png", path: "/home/", needsAuth: true },
  { file: "03-dashboard.png", path: "/chat/dashboard/", needsAuth: true },
  { file: "04-memory.png", path: "/chat/memory/", needsAuth: true },
  { file: "05-analytics.png", path: "/chat/analytics/", needsAuth: true },
  { file: "07-groups.png", path: "/chat/groups/", needsAuth: true },
  { file: "08-activity-log.png", path: "/chat/activity/", needsAuth: true },
  { file: "09-skill-marketplace.png", path: "/chat/skills/marketplace/", needsAuth: true },
  { file: "11-documents.png", path: "/chat/documents/", needsAuth: true },
];

async function capture(page, target) {
  const url = BASE + target.path;
  try {
    await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 });
  } catch (err) {
    console.log(JSON.stringify({ target: target.file, ok: false, error: String(err).slice(0, 200) }));
    return { ok: false };
  }
  await new Promise((r) => setTimeout(r, 800));
  const out = resolve(OUT_DIR, target.file);
  await page.screenshot({ path: out, fullPage: true, type: "png" });
  const size = (await import("node:fs")).statSync(out).size;
  console.log(JSON.stringify({ target: target.file, ok: true, path: out, size, url }));
  return { ok: true };
}

async function captureAgentDetailAndSkills(page) {
  await page.goto(BASE + "/chat/dashboard/", { waitUntil: "networkidle2", timeout: 30000 });
  const agentHref = await page.evaluate(() => {
    const a = Array.from(document.querySelectorAll('a[href*="/chat/agents/"]')).find(el => /\/chat\/agents\/[A-Za-z0-9\-]+\/?$/.test(el.getAttribute("href") || ""));
    return a ? a.getAttribute("href") : null;
  });
  if (agentHref) {
    await capture(page, { file: "06-agent-detail.png", path: agentHref });
    const skillsUrl = agentHref.replace(/\/?$/, "/") + "skills/";
    await capture(page, { file: "12-agent-skills.png", path: skillsUrl });
  } else {
    console.log(JSON.stringify({ target: "06-agent-detail.png", ok: false, error: "no agent link found" }));
  }
}

async function captureConversation(page) {
  await page.goto(BASE + "/home/", { waitUntil: "networkidle2", timeout: 30000 });
  const convHref = await page.evaluate(() => {
    const a = Array.from(document.querySelectorAll('a[href*="/chat/c/"]'))[0];
    return a ? a.getAttribute("href") : null;
  });
  if (convHref) {
    await capture(page, { file: "10-conversation.png", path: convHref });
  } else {
    console.log(JSON.stringify({ target: "10-conversation.png", ok: false, error: "no conversation link found" }));
  }
}

const browser = await puppeteer.launch({
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});

try {
  const page = await browser.newPage();
  await page.setViewport(VIEWPORT);

  if (SESSION_COOKIE) {
    await page.setCookie({
      name: "sessionid",
      value: SESSION_COOKIE,
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    });
  }

  for (const target of targets) {
    await capture(page, target);
  }
  await captureAgentDetailAndSkills(page);
  await captureConversation(page);
} finally {
  await browser.close();
}
