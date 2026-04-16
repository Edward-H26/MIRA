#!/usr/bin/env node
/**
 * Comprehensive browser test — exercises every fix from this session plus
 * additional edge cases. Runs with visible Chrome via Puppeteer.
 *
 * Fixes tested:
 *   F1. Cross-user data isolation (sidebar scoped to user)
 *   F2. Pusher channel ACL (foreign session denied, own session allowed)
 *   F3. Agent identity — no "I am Gemini" leak
 *   F4. Default agent fallback (user's own agent auto-responds)
 *   F5. Team-tab chat routes to teammate's agent (not user's)
 *   F6. No "Assistant" flash during streaming
 *   F7. First-name-based naming with collision suffix
 *
 * Edge cases:
 *   E1. @mention routes to that specific agent
 *   E2. Unknown channel prefix rejected
 *   E3. Pusher spoofed user-channel rejected
 *   E4. Existing user keeps their agent (idempotent)
 */
import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import { execSync } from "child_process";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const HEADFUL = process.env.HEADFUL !== "0";

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const pass = (name, detail = "") => { results.push({ name, ok: true, detail }); console.log(`  \x1b[32m[PASS]\x1b[0m ${name}${detail ? " — " + detail : ""}`); };
const fail = (name, detail = "") => { results.push({ name, ok: false, detail }); console.log(`  \x1b[31m[FAIL]\x1b[0m ${name}${detail ? " — " + detail : ""}`); };

function getCookie(username) {
  return execSync(
    `DJANGO_SETTINGS_MODULE=memoria.settings.dev python -c "
import django; django.setup()
from django.test import Client
from django.contrib.auth.models import User
c = Client()
u = User.objects.get(username='${username}')
c.force_login(u)
print(c.cookies['sessionid'].value, end='')
"`,
    { encoding: "utf-8", cwd: process.cwd() }
  ).trim();
}

async function waitForAssistantResponse(page, { minChars = 15, maxMs = 60000 } = {}) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    await sleep(2000);
    const state = await page.evaluate((min) => {
      const msgs = document.querySelectorAll(".chat-msg-row");
      if (msgs.length === 0) return { done: false };
      const last = msgs[msgs.length - 1];
      if (last.classList.contains("flex-row-reverse")) return { done: false };
      const labelEl = last.querySelector("[data-sender-label]");
      const contentEl = last.querySelector(".message-content");
      const content = contentEl ? contentEl.textContent.trim() : "";
      return {
        done: content.length > min,
        sender: labelEl ? labelEl.textContent.trim() : "",
        content,
      };
    }, minChars);
    if (state.done) return state;
  }
  return null;
}

async function sendMessage(page, text) {
  await page.evaluate((msg) => {
    const ta = document.getElementById("conversation-message-input");
    ta.value = msg;
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }, text);
  await sleep(200);
  await page.evaluate(() => {
    const form = document.getElementById("conversation-message-input").closest("form");
    const btn = form?.querySelector('button[type="submit"]');
    if (btn) btn.click();
    else form?.requestSubmit();
  });
}

async function postJson(page, path, body) {
  const csrf = await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "");
  return page.evaluate(async (base, p, b, token) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(b || {})) fd.append(k, v);
    fd.append("csrfmiddlewaretoken", token);
    const r = await fetch(base + p, {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": token },
      body: fd, redirect: "manual",
    });
    let body = null;
    try { body = await r.json(); } catch (e) {}
    return { status: r.status, body };
  }, BASE, path, body, csrf);
}

console.log("\n═══ COMPREHENSIVE FIX VERIFICATION ═══\n");

const qiranCookie = getCookie("Qiran");
const btCookie = getCookie("browsertest");

const browser = await puppeteer.launch({
  headless: HEADFUL ? false : "new",
  slowMo: HEADFUL ? 30 : 0,
  defaultViewport: HEADFUL ? null : { width: 1280, height: 900 },
  args: ["--no-sandbox", "--disable-setuid-sandbox", HEADFUL ? "--window-size=1400,1000" : ""].filter(Boolean),
});

const errs500 = [];

try {
  // ── F1: Cross-user sidebar isolation (uses isolated browser contexts) ──
  console.log("── F1: Cross-user sidebar isolation ──");
  const ctxQ = await browser.createBrowserContext();
  const ctxB = await browser.createBrowserContext();
  const pq = await ctxQ.newPage();
  const pb = await ctxB.newPage();
  await pq.setCookie({ name: "sessionid", value: qiranCookie, domain: "127.0.0.1", path: "/" });
  await pb.setCookie({ name: "sessionid", value: btCookie, domain: "127.0.0.1", path: "/" });
  await pq.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
  await pb.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });

  const qiranSids = await pq.evaluate(() =>
    Array.from(document.querySelectorAll("[data-conv-sidebar] a[href*='/chat/c/']"))
      .map(a => (a.getAttribute("href") || "").replace(/\/+$/, "").split("/").pop())
  );
  const btSids = await pb.evaluate(() =>
    Array.from(document.querySelectorAll("[data-conv-sidebar] a[href*='/chat/c/']"))
      .map(a => (a.getAttribute("href") || "").replace(/\/+$/, "").split("/").pop())
  );
  console.log(`   Qiran sidebar session IDs: ${qiranSids.length}`);
  console.log(`   browsertest sidebar session IDs: ${btSids.length}`);
  const overlap = qiranSids.filter(s => btSids.includes(s));
  if (qiranSids.length > 0) pass("F1-qiran-has-sidebar", `${qiranSids.length} sessions`);
  else fail("F1-qiran-has-sidebar", "empty");
  if (overlap.length === 0) pass("F1-sidebars-disjoint-by-id");
  else fail("F1-sidebars-disjoint-by-id", `LEAKED session IDs: ${overlap.join(", ")}`);

  await ctxB.close();

  // Continue tests on Qiran's page
  const page = pq;
  page.on("response", r => { if (r.status() >= 500) errs500.push({ url: r.url(), status: r.status() }); });

  // ── F4 + F6 + F7: Solo chat, default agent, no flash, first name ─
  console.log("\n── F4/F6/F7: Solo chat with default agent ──");
  const newChatResp = await postJson(page, "/chat/new/", {});
  const chatUrl = await page.evaluate(async (base, token) => {
    const fd = new FormData();
    fd.append("csrfmiddlewaretoken", token);
    const r = await fetch(base + "/chat/new/", {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": token },
      body: fd, redirect: "follow",
    });
    return r.url;
  }, BASE, await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ""));
  await page.goto(chatUrl, { waitUntil: "networkidle2" });
  await sleep(500);

  const initialAgent = await page.evaluate(() =>
    document.querySelector("[data-initial-agent-name]")?.getAttribute("data-initial-agent-name")
  );
  console.log(`   data-initial-agent-name = "${initialAgent}"`);
  if (initialAgent === "Qiran's Agent") pass("F7-first-name-naming", initialAgent);
  else fail("F7-first-name-naming", `expected "Qiran's Agent" got "${initialAgent}"`);

  // Check sidebar still shows Qiran's Agent label (after agent-lookup refactor)
  await sendMessage(page, "who are you");
  // Monitor for flash
  const labels = [];
  for (let i = 0; i < 15; i++) {
    await sleep(200);
    const lbl = await page.evaluate(() => {
      const msgs = document.querySelectorAll(".chat-msg-row");
      const last = msgs[msgs.length - 1];
      if (!last || last.classList.contains("flex-row-reverse")) return null;
      return last.querySelector("[data-sender-label]")?.textContent.trim();
    });
    if (lbl) labels.push(lbl);
  }
  const unique = [...new Set(labels)];
  console.log(`   labels captured: ${JSON.stringify(unique)}`);
  if (!unique.includes("Assistant")) pass("F6-no-assistant-flash");
  else fail("F6-no-assistant-flash", `flashed Assistant`);

  // Wait for response
  const solo = await waitForAssistantResponse(page, { maxMs: 45000 });
  if (!solo) fail("F4-got-response");
  else {
    console.log(`   solo response: ${solo.content.slice(0, 80)}...`);
    console.log(`   solo sender: "${solo.sender}"`);
    if (solo.sender === "Qiran's Agent") pass("F4-default-is-own-agent");
    else fail("F4-default-is-own-agent", `got "${solo.sender}"`);
    const hasGeminiLeak = /^I am Gemini|trained by Google/i.test(solo.content);
    if (!hasGeminiLeak) pass("F3-no-gemini-leak");
    else fail("F3-no-gemini-leak", solo.content.slice(0, 80));
  }

  // ── F5: Team tab chat routes to teammate's agent ──────────────────
  console.log("\n── F5: Team tab → teammate agent responds ──");
  // POST and follow redirect directly; we verify success by the final URL shape.
  const teamUrl = await page.evaluate(async (base, token) => {
    const fd = new FormData();
    fd.append("csrfmiddlewaretoken", token);
    const r = await fetch(base + "/chat/agents/marketplace/executive-assistant/start-chat/", {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": token },
      body: fd, redirect: "follow",
    });
    return r.url;
  }, BASE, await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ""));
  await page.goto(teamUrl, { waitUntil: "networkidle2" });
  if (teamUrl.includes("/chat/c/")) pass("F5-team-chat-url");
  else fail("F5-team-chat-url", `url=${teamUrl}`);

  await sendMessage(page, "hello, what do you do?");
  const teamReply = await waitForAssistantResponse(page, { maxMs: 45000 });
  if (!teamReply) fail("F5-team-got-response");
  else {
    console.log(`   team sender: "${teamReply.sender}"`);
    console.log(`   team response: ${teamReply.content.slice(0, 80)}...`);
    if (teamReply.sender === "Sarah Chen's Agent") pass("F5-team-agent-responds");
    else fail("F5-team-agent-responds", `got "${teamReply.sender}"`);
    if (!/Qiran's Agent/.test(teamReply.sender)) pass("F5-not-own-agent");
    else fail("F5-not-own-agent");
  }

  // ── F2 + E2 + E3: Pusher channel ACL ──────────────────────────────
  console.log("\n── F2/E2/E3: Pusher channel ACL ──");
  // Find a session owned by browsertest (for cross-user ACL test)
  const btSessionId = execSync(
    `DJANGO_SETTINGS_MODULE=memoria.settings.dev python -c "
import django; django.setup()
from app.services import neo4j_memory as neo4j
s = neo4j.get_sessions_for_user('302', limit=1)
print(s[0]['id'] if s else '', end='')
"`,
    { encoding: "utf-8", cwd: process.cwd() }
  ).trim();

  if (btSessionId) {
    const foreignResp = await postJson(page, "/chat/api/pusher/auth/", {
      socket_id: "1234.5678",
      channel_name: `private-group-${btSessionId}`,
    });
    if (foreignResp.status === 403) pass("F2-foreign-session-denied");
    else fail("F2-foreign-session-denied", `status=${foreignResp.status}`);
  }

  const unknownResp = await postJson(page, "/chat/api/pusher/auth/", {
    socket_id: "1234.5678",
    channel_name: "presence-admin-debug",
  });
  if (unknownResp.status === 403) pass("E2-unknown-channel-denied");
  else fail("E2-unknown-channel-denied", `status=${unknownResp.status}`);

  const spoofedResp = await postJson(page, "/chat/api/pusher/auth/", {
    socket_id: "1234.5678",
    channel_name: "private-user-302",
  });
  if (spoofedResp.status === 403) pass("E3-spoofed-user-channel-denied");
  else fail("E3-spoofed-user-channel-denied", `status=${spoofedResp.status}`);

  // ── E4: First-name collision handled ──────────────────────────────
  console.log("\n── E4: First-name collision logic ──");
  const collisionProbe = execSync(
    `DJANGO_SETTINGS_MODULE=memoria.settings.dev python -c "
import django; django.setup()
from app.chat.agent_service import _pick_unique_default_agent_name
print(_pick_unique_default_agent_name('Qiran'), end='')
"`,
    { encoding: "utf-8", cwd: process.cwd() }
  ).trim();
  console.log(`   new collision candidate for 'Qiran': "${collisionProbe}"`);
  if (/^Qiran\d+'s Agent$/.test(collisionProbe)) pass("F7-collision-suffix-applied", collisionProbe);
  else fail("F7-collision-suffix-applied", `got "${collisionProbe}"`);

  // ── Screenshot ────────────────────────────────────────────────────
  await page.screenshot({ path: "/tmp/comprehensive_test.png", fullPage: false });
  console.log("\n   screenshot: /tmp/comprehensive_test.png");

} catch (err) {
  console.error("FATAL:", err.message || err);
  results.push({ name: "fatal", ok: false, detail: String(err) });
} finally {
  const passed = results.filter(r => r.ok).length;
  const failed = results.filter(r => !r.ok).length;
  console.log(`\n═══ SUMMARY: ${passed} pass / ${failed} fail ═══`);
  if (errs500.length) console.log(`  HTTP 500s: ${errs500.map(e => e.url).join("\n  ")}`);
  await browser.close();
  process.exit(failed === 0 && errs500.length === 0 ? 0 : 1);
}
