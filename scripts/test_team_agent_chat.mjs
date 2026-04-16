#!/usr/bin/env node
/**
 * Verifies the Team tab flow: starting a chat with a teammate's agent
 * (e.g., Sarah Chen's Agent) should make THAT agent respond to all subsequent
 * messages, not the user's own agent.
 */
import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import { execSync } from "child_process";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const USERNAME = process.env.E2E_USERNAME || "Qiran";
const TEMPLATE_ID = process.env.TEMPLATE_ID || "executive-assistant";
const EXPECTED_AGENT = process.env.EXPECTED_AGENT || "Sarah Chen's Agent";
const HEADFUL = process.env.HEADFUL !== "0";

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const record = (area, ok, detail) => {
  results.push({ area, ok, detail });
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${area}${detail ? " — " + detail : ""}`);
};

console.log(`=== Team Agent Chat Test: ${EXPECTED_AGENT} ===\n`);

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

console.log(`Session cookie for ${USERNAME}: ${sessionCookie.slice(0, 8)}...`);

const browser = await puppeteer.launch({
  headless: HEADFUL ? false : "new",
  slowMo: HEADFUL ? 50 : 0,
  defaultViewport: HEADFUL ? null : { width: 1280, height: 900 },
  args: ["--no-sandbox", "--disable-setuid-sandbox", HEADFUL ? "--window-size=1400,1000" : ""].filter(Boolean),
});
const page = await browser.newPage();
if (!HEADFUL) await page.setViewport({ width: 1280, height: 900 });

const errs = { http500: [] };
page.on("response", r => { if (r.status() >= 500) errs.http500.push({ url: r.url(), status: r.status() }); });

try {
  await page.setCookie({ name: "sessionid", value: sessionCookie, domain: "127.0.0.1", path: "/" });

  // Step 1: POST to agent_start_chat to create the team session
  console.log("\n1. Starting team chat with " + EXPECTED_AGENT + "...");
  await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
  const csrf = await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "");

  const startResp = await page.evaluate(async (base, token, tplId) => {
    const fd = new FormData();
    fd.append("csrfmiddlewaretoken", token);
    const r = await fetch(base + "/chat/agents/marketplace/" + tplId + "/start-chat/", {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": token },
      body: fd, redirect: "follow",
    });
    return { status: r.status, url: r.url };
  }, BASE, csrf, TEMPLATE_ID);
  record("team-chat-start", startResp.status === 200, `url=${startResp.url}`);

  await page.goto(startResp.url, { waitUntil: "networkidle2" });
  record("chat-page-load", page.url().includes("/chat/c/"), `url=${page.url()}`);

  // Step 2: Verify greeting sender is the team agent
  await sleep(1000);
  const greeting = await page.evaluate(() => {
    const msgs = document.querySelectorAll(".chat-msg-row");
    if (msgs.length === 0) return null;
    const first = msgs[0];
    const label = first.querySelector("[data-sender-label]");
    const content = first.querySelector(".message-content");
    return {
      sender: label ? label.textContent.trim() : "",
      content: content ? content.textContent.trim() : "",
    };
  });
  console.log(`   greeting sender: "${greeting?.sender}"`);
  console.log(`   greeting content: ${greeting?.content.slice(0, 100)}...`);
  record("greeting-sender-is-team-agent",
    greeting?.sender === EXPECTED_AGENT,
    `expected="${EXPECTED_AGENT}" got="${greeting?.sender}"`);

  // Step 3: Send a message without @-mention and verify the response is from the team agent
  console.log("\n2. Sending reply (no @-mention) and checking responder...");

  await page.evaluate((msg) => {
    const ta = document.getElementById("conversation-message-input");
    ta.value = msg;
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }, "how are you doing");
  await sleep(300);

  await page.evaluate(() => {
    const form = document.getElementById("conversation-message-input").closest("form");
    if (form) {
      const btn = form.querySelector('button[type="submit"]');
      if (btn) btn.click();
      else form.requestSubmit();
    }
  });

  console.log("   waiting for response...");
  let responseInfo = null;
  const maxWait = 60000;
  const startTime = Date.now();
  while (Date.now() - startTime < maxWait) {
    await sleep(2000);
    const state = await page.evaluate(() => {
      const msgs = document.querySelectorAll(".chat-msg-row");
      if (msgs.length < 3) return { done: false };
      const last = msgs[msgs.length - 1];
      if (last.classList.contains("flex-row-reverse")) return { done: false };
      const label = last.querySelector("[data-sender-label]");
      const content = last.querySelector(".message-content");
      const text = content ? content.textContent.trim() : "";
      return {
        done: text.length > 15,
        sender: label ? label.textContent.trim() : "",
        content: text,
      };
    });
    if (state.done) {
      responseInfo = state;
      break;
    }
  }

  if (!responseInfo) {
    record("got-response", false, "timed out");
  } else {
    console.log(`   response sender: "${responseInfo.sender}"`);
    console.log(`   response content: ${responseInfo.content.slice(0, 140)}...`);
    record("responder-is-team-agent",
      responseInfo.sender === EXPECTED_AGENT,
      `expected="${EXPECTED_AGENT}" got="${responseInfo.sender}"`);

    const userOwnAgent = /Qiran's Agent|Qiran Hu's Agent|Team's Agent|browsertest's Agent/;
    const leakedToOwn = userOwnAgent.test(responseInfo.sender);
    record("did-not-fall-back-to-user-agent",
      !leakedToOwn,
      leakedToOwn ? `FELL BACK to user's own agent: ${responseInfo.sender}` : "clean");

    const staysInCharacter = responseInfo.content.includes("Sarah Chen") ||
      responseInfo.content.includes("executive assistant") ||
      responseInfo.content.toLowerCase().includes("scheduling") ||
      responseInfo.content.toLowerCase().includes("briefing");
    record("response-stays-in-character",
      staysInCharacter,
      `content snippet=${responseInfo.content.slice(0, 80)}`);
  }

  await page.screenshot({ path: "/tmp/team_agent_chat_test.png", fullPage: false });
  console.log("\n   screenshot saved to /tmp/team_agent_chat_test.png");

} catch (err) {
  console.error("FATAL:", err.message || err);
  results.push({ area: "fatal", ok: false, detail: String(err) });
} finally {
  const pass = results.filter(r => r.ok).length;
  const fail = results.filter(r => !r.ok).length;
  console.log(`\n${"=".repeat(50)}`);
  console.log(`SUMMARY: ${pass} pass / ${fail} fail`);
  if (errs.http500.length) for (const h of errs.http500) console.log(`  500: ${h.url}`);
  await browser.close();
  process.exit(fail === 0 && errs.http500.length === 0 ? 0 : 1);
}
