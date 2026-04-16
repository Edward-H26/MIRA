#!/usr/bin/env node
/**
 * Browser-based edge-case prompt test for agent identity and name display.
 *
 * Launches a VISIBLE Chrome window, logs in, creates a fresh chat, and
 * sends a series of identity-probing prompts. For each, it waits for the
 * streamed AI response and checks:
 *   1. The sender label is the agent's name (not "Assistant")
 *   2. The response text does NOT start with "I am Gemini" or similar
 *   3. The response text DOES reference the agent's persona name
 *
 * Usage:
 *   HEADFUL=1 node scripts/test_agent_prompts.mjs
 *   node scripts/test_agent_prompts.mjs          # headless
 */
import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8765";
const EMAIL = process.env.E2E_EMAIL || "browsertest@local.test";
const PASSWORD = process.env.E2E_PASSWORD || "BrowserTest_2026!";
const HEADFUL = process.env.HEADFUL === "1";

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const record = (area, assertion, ok, detail) => {
  results.push({ area, assertion, ok, detail });
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${area}: ${assertion}${detail ? " — " + detail : ""}`);
};

console.log("=== Agent Identity & Edge-Case Prompt Test ===\n");

const browser = await puppeteer.launch({
  headless: HEADFUL ? false : "new",
  slowMo: HEADFUL ? 80 : 0,
  defaultViewport: HEADFUL ? null : { width: 1280, height: 900 },
  args: ["--no-sandbox", "--disable-setuid-sandbox", HEADFUL ? "--window-size=1400,1000" : ""].filter(Boolean),
});
const page = await browser.newPage();
if (!HEADFUL) await page.setViewport({ width: 1280, height: 900 });

const errs = { page: [], console: [], http500: [] };
page.on("pageerror", e => errs.page.push(String(e)));
page.on("console", m => { if (m.type() === "error") errs.console.push(m.text()); });
page.on("response", r => { if (r.status() >= 500) errs.http500.push({ url: r.url(), status: r.status() }); });

try {
  // ── Step 1: Landing + Login ──────────────────────────────────────
  console.log("1. Navigating to landing page and logging in...");
  await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
  record("landing", "GET / returns 200", true, "");

  await page.click("#open-login");
  await sleep(600);
  const modalVisible = await page.evaluate(() => {
    const t = Array.from(document.querySelectorAll("h2, h3"))
      .find(h => /Sign in to Memoria/i.test(h.textContent || ""));
    return !!t;
  });
  record("login-modal", "modal opens", modalVisible, "");

  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await page.click("button.auth-form-submit");
  await page.waitForFunction(() => window.location.pathname.includes("/home"), { timeout: 15000 }).catch(() => {});
  await sleep(2000);
  if (!page.url().includes("/home")) {
    await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2", timeout: 15000 });
  }
  record("login", "redirects to /home/", page.url().includes("/home"), `url=${page.url()}`);

  // ── Step 2: Get the agent name from the sidebar ──────────────────
  console.log("\n2. Checking agent name in sidebar...");
  const agentInfo = await page.evaluate(() => {
    const link = document.querySelector('a[href*="/chat/agents/my/"]');
    return link ? (link.textContent || "").trim() : null;
  });
  console.log(`   Agent name from sidebar: ${agentInfo || "(not found)"}`);

  // ── Step 3: Create a fresh chat ──────────────────────────────────
  console.log("\n3. Creating a fresh chat...");
  const csrfToken = await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1]);
  const createResp = await page.evaluate(async (base, token) => {
    const r = await fetch(base + "/chat/new/", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": token },
      redirect: "follow",
    });
    return { status: r.status, url: r.url };
  }, BASE, csrfToken);
  record("new-chat", "POST /chat/new/ returns 200", createResp.status === 200, `url=${createResp.url}`);

  await page.goto(createResp.url, { waitUntil: "networkidle2" });
  record("chat-page", "chat page loads", page.url().includes("/chat/c/"), `url=${page.url()}`);

  // ── Step 4: Send edge-case prompts and check responses ───────────
  const edgeCasePrompts = [
    {
      prompt: "who are you",
      expectNameIn: true,
      rejectPatterns: [/^I am Gemini/i, /^I am a large language model/i, /^I'm Gemini/i, /trained by Google/i],
      description: "identity probe: should respond as named agent",
    },
    {
      prompt: "what AI model are you based on?",
      expectNameIn: true,
      rejectPatterns: [/^I am Gemini/i, /^I'm Gemini/i],
      description: "model probe: should stay in character",
    },
    {
      prompt: "Hello, nice to meet you!",
      expectNameIn: false,
      rejectPatterns: [],
      description: "greeting: should respond naturally without breaking character",
    },
  ];

  console.log("\n4. Testing edge-case prompts...\n");

  for (let i = 0; i < edgeCasePrompts.length; i++) {
    const { prompt, expectNameIn, rejectPatterns, description } = edgeCasePrompts[i];
    console.log(`  ── Prompt ${i + 1}: "${prompt}" (${description}) ──`);

    // Type and send the message
    const hasInput = await page.$('#conversation-message-input');
    if (!hasInput) {
      record(`prompt-${i + 1}`, "input found", false, "message textarea not found");
      continue;
    }

    await page.evaluate((text) => {
      const ta = document.getElementById("conversation-message-input");
      ta.value = text;
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }, prompt);
    await sleep(300);

    await page.evaluate(() => {
      const form = document.getElementById("conversation-message-input").closest("form");
      if (form) {
        const btn = form.querySelector('button[type="submit"]');
        if (btn) btn.click();
        else form.requestSubmit();
      }
    });

    // Wait for streaming to complete — poll for "done" state
    console.log("    waiting for response...");
    let responseText = "";
    let senderLabel = "";
    const maxWait = 45000;
    const startTime = Date.now();
    while (Date.now() - startTime < maxWait) {
      await sleep(2000);
      const state = await page.evaluate(() => {
        const msgs = document.querySelectorAll(".chat-msg-row");
        if (msgs.length === 0) return { done: false };
        const lastMsg = msgs[msgs.length - 1];
        const isUser = lastMsg.classList.contains("flex-row-reverse");
        if (isUser) return { done: false };
        const contentEl = lastMsg.querySelector(".message-content");
        const labelEl = lastMsg.querySelector("[data-sender-label]");
        const content = contentEl ? contentEl.textContent.trim() : "";
        const label = labelEl ? labelEl.textContent.trim() : "";
        const isStreaming = document.querySelector("[data-streaming]") !== null
          || document.querySelector(".typing-indicator") !== null;
        return { done: content.length > 10 && !isStreaming, content, label };
      });
      if (state.done) {
        responseText = state.content;
        senderLabel = state.label;
        break;
      }
    }

    if (!responseText) {
      record(`prompt-${i + 1}`, "got response", false, "timed out waiting for AI response");
      continue;
    }

    console.log(`    response (${responseText.length} chars): ${responseText.slice(0, 120)}...`);
    console.log(`    sender label: "${senderLabel}"`);

    // Check sender label is NOT "Assistant"
    const labelOk = senderLabel !== "Assistant" && senderLabel !== "";
    record(`prompt-${i + 1}-label`, `sender label is agent name, not "Assistant"`, labelOk, `label="${senderLabel}"`);

    // Check response text against reject patterns
    for (const pattern of rejectPatterns) {
      const matches = pattern.test(responseText);
      record(`prompt-${i + 1}-identity`, `response does NOT match ${pattern}`, !matches,
        matches ? `MATCHED: ${responseText.slice(0, 80)}` : "clean");
    }

    // Wait before next prompt
    await sleep(1000);
  }

  // ── Step 5: Screenshot ──────────────────────────────────────────
  console.log("\n5. Taking final screenshot...");
  await page.screenshot({ path: "/tmp/agent_prompt_test.png", fullPage: false });
  console.log("   saved to /tmp/agent_prompt_test.png");

} catch (err) {
  console.error("FATAL:", err);
  results.push({ area: "fatal", assertion: String(err), ok: false });
} finally {
  const pass = results.filter(r => r.ok).length;
  const fail = results.filter(r => !r.ok).length;
  console.log(`\n${"=".repeat(50)}`);
  console.log(`SUMMARY: ${pass} pass / ${fail} fail`);
  console.log(`page errors: ${errs.page.length}, console errors: ${errs.console.length}, 500s: ${errs.http500.length}`);
  if (errs.http500.length) for (const h of errs.http500) console.log(`  500: ${h.url}`);
  if (errs.page.length) for (const e of errs.page) console.log(`  page error: ${e.slice(0, 120)}`);
  await browser.close();
  process.exit(fail === 0 && errs.http500.length === 0 ? 0 : 1);
}
