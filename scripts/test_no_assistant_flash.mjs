#!/usr/bin/env node
/**
 * Verifies there is NO flash of "Assistant" label when the user sends a
 * message. The bubble should render with the correct agent name from the
 * first paint, matching the session's responding agent.
 */
import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import { execSync } from "child_process";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const USERNAME = process.env.E2E_USERNAME || "Qiran";
const EXPECTED_AGENT = process.env.EXPECTED_AGENT || "Qiran's Agent";
const HEADFUL = process.env.HEADFUL !== "0";

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const record = (area, ok, detail) => {
  results.push({ area, ok, detail });
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${area}${detail ? " — " + detail : ""}`);
};

console.log(`=== "Assistant" Flash Test (solo chat; expected agent: ${EXPECTED_AGENT}) ===\n`);

const sessionCookie = execSync(
  `DJANGO_SETTINGS_MODULE=memoria.settings.dev python -c "
import django; django.setup()
from django.test import Client
from django.contrib.auth.models import User
c = Client()
u = User.objects.get(username='${USERNAME}')
c.force_login(u)
print(c.cookies['sessionid'].value, end='')
"`,
  { encoding: "utf-8", cwd: process.cwd() }
).trim();

const browser = await puppeteer.launch({
  headless: HEADFUL ? false : "new",
  slowMo: HEADFUL ? 30 : 0,
  defaultViewport: HEADFUL ? null : { width: 1280, height: 900 },
  args: ["--no-sandbox", "--disable-setuid-sandbox", HEADFUL ? "--window-size=1400,1000" : ""].filter(Boolean),
});
const page = await browser.newPage();
if (!HEADFUL) await page.setViewport({ width: 1280, height: 900 });

try {
  await page.setCookie({ name: "sessionid", value: sessionCookie, domain: "127.0.0.1", path: "/" });

  // Create a new solo chat session
  console.log("1. Creating solo chat (no specific agent — defaults to user's own)...");
  await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
  const csrf = await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "");

  const chatResp = await page.evaluate(async (base, token) => {
    const r = await fetch(base + "/chat/new/", {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": token }, redirect: "follow",
    });
    return { status: r.status, url: r.url };
  }, BASE, csrf);
  record("chat-created", chatResp.status === 200, `url=${chatResp.url}`);

  await page.goto(chatResp.url, { waitUntil: "networkidle2" });
  await sleep(500);

  // Check the data-initial-agent-name attribute
  const initialAgentName = await page.evaluate(() => {
    const form = document.querySelector("[data-initial-agent-name]");
    return form ? form.getAttribute("data-initial-agent-name") : null;
  });
  console.log(`   data-initial-agent-name = "${initialAgentName}"`);
  record("template-exposes-agent-name",
    initialAgentName && initialAgentName !== "Assistant",
    `value="${initialAgentName}"`);

  // Send a message
  console.log("\n2. Sending message and monitoring the label BEFORE any server response arrives...");

  await page.evaluate((msg) => {
    const ta = document.getElementById("conversation-message-input");
    ta.value = msg;
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }, "Can you show me how to do a python forloop");

  // Start polling IMMEDIATELY after submit to catch any Assistant flash
  const labelsSeen = [];
  const pollPromise = (async () => {
    for (let i = 0; i < 30; i++) {
      await sleep(100);
      const label = await page.evaluate(() => {
        const msgs = document.querySelectorAll(".chat-msg-row");
        if (msgs.length === 0) return null;
        const last = msgs[msgs.length - 1];
        if (last.classList.contains("flex-row-reverse")) return null;
        const labelEl = last.querySelector("[data-sender-label]");
        return labelEl ? labelEl.textContent.trim() : null;
      });
      if (label !== null && label !== "") labelsSeen.push({ t: i * 100, label });
    }
  })();

  // Submit the form
  await page.evaluate(() => {
    const form = document.getElementById("conversation-message-input").closest("form");
    if (form) {
      const btn = form.querySelector('button[type="submit"]');
      if (btn) btn.click();
      else form.requestSubmit();
    }
  });

  await pollPromise;

  console.log(`\n   captured label frames (first 10):`);
  const sampled = labelsSeen.slice(0, 10);
  for (const s of sampled) console.log(`     t+${s.t}ms: "${s.label}"`);

  const uniqueLabels = Array.from(new Set(labelsSeen.map(l => l.label)));
  console.log(`   unique labels seen: ${JSON.stringify(uniqueLabels)}`);

  record("no-assistant-flash",
    !uniqueLabels.includes("Assistant"),
    uniqueLabels.includes("Assistant") ? "saw 'Assistant' at some point" : "never showed Assistant");

  record("first-label-is-agent-name",
    labelsSeen.length > 0 && labelsSeen[0].label === EXPECTED_AGENT,
    `first label = "${labelsSeen[0]?.label}"`);

  // Wait for full response
  console.log("\n3. Waiting for complete response...");
  await sleep(20000);
  const finalState = await page.evaluate(() => {
    const msgs = document.querySelectorAll(".chat-msg-row");
    const last = msgs[msgs.length - 1];
    const label = last?.querySelector("[data-sender-label]");
    const content = last?.querySelector(".message-content");
    return {
      label: label ? label.textContent.trim() : "",
      content: content ? content.textContent.trim().slice(0, 100) : "",
    };
  });
  console.log(`   final label: "${finalState.label}"`);
  console.log(`   final content: ${finalState.content}...`);
  record("final-label-is-agent",
    finalState.label && finalState.label !== "Assistant",
    `label="${finalState.label}"`);

  await page.screenshot({ path: "/tmp/no_assistant_flash_test.png", fullPage: false });

} catch (err) {
  console.error("FATAL:", err.message || err);
  results.push({ area: "fatal", ok: false, detail: String(err) });
} finally {
  const pass = results.filter(r => r.ok).length;
  const fail = results.filter(r => !r.ok).length;
  console.log(`\n${"=".repeat(50)}`);
  console.log(`SUMMARY: ${pass} pass / ${fail} fail`);
  await browser.close();
  process.exit(fail === 0 ? 0 : 1);
}
