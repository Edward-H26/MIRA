#!/usr/bin/env node
/**
 * Browser test for a Google-auth user (Qiran). Since we cannot drive Google
 * OAuth through Puppeteer, we inject a Django session cookie created via
 * force_login, then test the agent identity and prompt behavior.
 */
import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import { execSync } from "child_process";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const HEADFUL = process.env.HEADFUL !== "0";

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const record = (area, assertion, ok, detail) => {
  results.push({ area, assertion, ok, detail });
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${area}: ${assertion}${detail ? " — " + detail : ""}`);
};

console.log("=== Google-Auth User (Qiran) Agent Test ===\n");

const sessionId = execSync(
  `DJANGO_SETTINGS_MODULE=memoria.settings.dev python -c "
import django; django.setup()
from django.test import Client
from django.contrib.auth.models import User
c = Client()
u = User.objects.get(username='Qiran')
c.force_login(u)
print(c.cookies['sessionid'].value, end='')
"`,
  { encoding: "utf-8", cwd: process.cwd() }
).trim();

console.log(`Session cookie obtained for Qiran: ${sessionId.slice(0, 8)}...`);

const browser = await puppeteer.launch({
  headless: HEADFUL ? false : "new",
  slowMo: HEADFUL ? 80 : 0,
  defaultViewport: HEADFUL ? null : { width: 1280, height: 900 },
  args: ["--no-sandbox", "--disable-setuid-sandbox", HEADFUL ? "--window-size=1400,1000" : ""].filter(Boolean),
});
const page = await browser.newPage();
if (!HEADFUL) await page.setViewport({ width: 1280, height: 900 });

const errs = { page: [], http500: [] };
page.on("pageerror", e => errs.page.push(String(e)));
page.on("response", r => { if (r.status() >= 500) errs.http500.push({ url: r.url(), status: r.status() }); });

try {
  await page.setCookie({
    name: "sessionid",
    value: sessionId,
    domain: "127.0.0.1",
    path: "/",
  });

  // ── Step 1: Home page with injected session ──────────────────────
  console.log("\n1. Loading home page as Qiran (Google-auth user)...");
  await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2", timeout: 15000 });
  const onHome = page.url().includes("/home");
  record("auth", "Qiran is logged in at /home/", onHome, `url=${page.url()}`);

  if (!onHome) throw new Error("Login failed — session cookie rejected");

  const displayedUser = await page.evaluate(() => {
    const el = document.querySelector("[data-user-display-name], .user-display-name, [data-current-user]");
    return el ? el.textContent.trim() : document.title;
  });
  console.log(`   Displayed user context: ${displayedUser}`);

  // ── Step 2: Create new chat ──────────────────────────────────────
  console.log("\n2. Creating a fresh chat...");
  const csrf = await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "");
  const chatResp = await page.evaluate(async (base, token) => {
    const r = await fetch(base + "/chat/new/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": token },
      redirect: "follow",
    });
    return { status: r.status, url: r.url };
  }, BASE, csrf);
  record("new-chat", "new chat created", chatResp.status === 200, `url=${chatResp.url}`);

  await page.goto(chatResp.url, { waitUntil: "networkidle2" });
  record("chat-page", "chat page loads", page.url().includes("/chat/c/"), `url=${page.url()}`);

  // ── Step 3: Test edge-case prompts ───────────────────────────────
  const prompts = [
    { text: "who are you", desc: "identity probe" },
    { text: "are you an AI? what's your name?", desc: "name + AI probe" },
    { text: "what can you help me with?", desc: "capability probe" },
  ];

  console.log("\n3. Testing edge-case prompts...\n");

  for (let i = 0; i < prompts.length; i++) {
    const { text, desc } = prompts[i];
    console.log(`  ── Prompt ${i + 1}: "${text}" (${desc}) ──`);

    await page.evaluate((msg) => {
      const ta = document.getElementById("conversation-message-input");
      ta.value = msg;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }, text);
    await sleep(300);

    await page.evaluate(() => {
      const form = document.getElementById("conversation-message-input").closest("form");
      if (form) {
        const btn = form.querySelector('button[type="submit"]');
        if (btn) btn.click();
        else form.requestSubmit();
      }
    });

    console.log("    waiting for response...");
    let responseText = "";
    let senderLabel = "";
    const maxWait = 60000;
    const startTime = Date.now();
    while (Date.now() - startTime < maxWait) {
      await sleep(2000);
      const state = await page.evaluate(() => {
        const msgs = document.querySelectorAll(".chat-msg-row");
        if (msgs.length === 0) return { done: false };
        const lastMsg = msgs[msgs.length - 1];
        if (lastMsg.classList.contains("flex-row-reverse")) return { done: false };
        const contentEl = lastMsg.querySelector(".message-content");
        const labelEl = lastMsg.querySelector("[data-sender-label]");
        const content = contentEl ? contentEl.textContent.trim() : "";
        const label = labelEl ? labelEl.textContent.trim() : "";
        return { done: content.length > 10, content, label };
      });
      if (state.done) {
        responseText = state.content;
        senderLabel = state.label;
        break;
      }
    }

    if (!responseText) {
      record(`prompt-${i + 1}`, "got response", false, "timed out");
      continue;
    }

    console.log(`    response (${responseText.length} chars): ${responseText.slice(0, 140)}...`);
    console.log(`    sender label: "${senderLabel}"`);

    record(`prompt-${i + 1}-label`, `sender = user's agent, not "Assistant"`,
      senderLabel !== "Assistant" && senderLabel !== "", `label="${senderLabel}"`);

    const hasGemini = /^I am Gemini|^I'm Gemini|trained by Google/i.test(responseText);
    record(`prompt-${i + 1}-no-gemini`, "no Gemini identity leak", !hasGemini,
      hasGemini ? `LEAKED: ${responseText.slice(0, 80)}` : "clean");

    const hasMemoria = /^I am Memoria|^I'm Memoria/i.test(responseText);
    record(`prompt-${i + 1}-no-generic`, `no generic "Memoria" identity`,
      !hasMemoria, hasMemoria ? `GENERIC: ${responseText.slice(0, 80)}` : "clean");

    await sleep(1000);
  }

  // ── Step 4: Screenshot ──────────────────────────────────────────
  console.log("\n4. Taking screenshot...");
  await page.screenshot({ path: "/tmp/google_auth_agent_test.png", fullPage: false });
  console.log("   saved to /tmp/google_auth_agent_test.png");

} catch (err) {
  console.error("FATAL:", err.message || err);
  results.push({ area: "fatal", assertion: String(err), ok: false });
} finally {
  const pass = results.filter(r => r.ok).length;
  const fail = results.filter(r => !r.ok).length;
  console.log(`\n${"=".repeat(50)}`);
  console.log(`SUMMARY: ${pass} pass / ${fail} fail`);
  if (errs.http500.length) for (const h of errs.http500) console.log(`  500: ${h.url}`);
  if (errs.page.length) for (const e of errs.page.slice(0, 3)) console.log(`  page error: ${e.slice(0, 120)}`);
  await browser.close();
  process.exit(fail === 0 && errs.http500.length === 0 ? 0 : 1);
}
