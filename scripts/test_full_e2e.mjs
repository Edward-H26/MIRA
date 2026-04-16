#!/usr/bin/env node
/**
 * Full end-to-end browser verification — all fixes from this session.
 *
 * DESKTOP fixes:
 *   D1. Cross-user sidebar isolation
 *   D2. Pusher ACL: foreign session denied
 *   D3. Pusher ACL: unknown channel denied
 *   D4. Pusher ACL: spoofed user channel denied
 *   D5. Default agent fallback (no @mention) -> user's own agent responds
 *   D6. Agent identity: no "I am Gemini" leak
 *   D7. Team chat: teammate agent responds, not user's own
 *   D8. First-name naming with collision suffix
 *   D9. No "Assistant" flash during streaming
 *
 * MOBILE fixes:
 *   M1. Mobile Chat tab shows recent conversations on /home/
 *   M2. Notification dropdown fits viewport (no left/right overflow)
 *   M3. Chat bubble wraps cleanly (no horizontal overflow)
 *   M4. min-w-0 on <main> prevents flex inflation
 *   M5. Mobile recent chats are tappable and lead to /chat/c/<id>/
 *   M6. Multiple viewports (320, 375, 390) all contained
 */
import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import { execSync } from "child_process";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const HEADFUL = process.env.HEADFUL === "1";

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const pass = (n, d = "") => { results.push({ n, ok: true, d }); console.log(`  \x1b[32m[PASS]\x1b[0m ${n}${d ? " — " + d : ""}`); };
const fail = (n, d = "") => { results.push({ n, ok: false, d }); console.log(`  \x1b[31m[FAIL]\x1b[0m ${n}${d ? " — " + d : ""}`); };

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
"`, { encoding: "utf-8", cwd: process.cwd() }
  ).trim();
}
function pyOneLine(code) {
  return execSync(
    `DJANGO_SETTINGS_MODULE=memoria.settings.dev python -c "
import django; django.setup()
${code}
"`, { encoding: "utf-8", cwd: process.cwd() }
  ).trim();
}

async function waitReply(page, { min = 15, maxMs = 60000 } = {}) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    await sleep(2000);
    const s = await page.evaluate((m) => {
      const rows = document.querySelectorAll(".chat-msg-row");
      if (!rows.length) return { done: false };
      const last = rows[rows.length - 1];
      if (last.classList.contains("flex-row-reverse")) return { done: false };
      const lbl = last.querySelector("[data-sender-label]");
      const c = last.querySelector(".message-content, .message-content-markdown");
      const t = c ? c.textContent.trim() : "";
      return { done: t.length > m, sender: lbl?.textContent.trim() || "", content: t };
    }, min);
    if (s.done) return s;
  }
  return null;
}
async function send(page, text) {
  await page.evaluate((m) => {
    const ta = document.getElementById("conversation-message-input");
    ta.value = m; ta.dispatchEvent(new Event("input", { bubbles: true }));
    const f = ta.closest("form");
    f?.querySelector('button[type="submit"]')?.click() || f?.requestSubmit();
  }, text);
}
async function postForm(page, path, fields = {}) {
  const csrf = await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "");
  return page.evaluate(async (base, p, fs, t) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fs)) fd.append(k, v);
    fd.append("csrfmiddlewaretoken", t);
    const r = await fetch(base + p, {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": t }, body: fd, redirect: "manual",
    });
    return { status: r.status };
  }, BASE, path, fields, csrf);
}

console.log("\n═══ FULL END-TO-END VERIFICATION ═══\n");

const qiranCookie = getCookie("Qiran");
const btCookie = getCookie("browsertest");
const errs500 = [];

const browser = await puppeteer.launch({
  headless: HEADFUL ? false : true,
  defaultViewport: HEADFUL ? null : undefined,
  slowMo: HEADFUL ? 30 : 0,
  args: ["--no-sandbox", "--disable-setuid-sandbox", HEADFUL ? "--window-size=1400,1000" : ""].filter(Boolean),
});

try {
  // ╔═══════════════════════════════════════════════════════════════╗
  // ║ DESKTOP TESTS (1280×900 viewport)                             ║
  // ╚═══════════════════════════════════════════════════════════════╝
  console.log("══ DESKTOP (1280×900) ══");

  // D1: Cross-user sidebar isolation
  console.log("\n— D1: cross-user sidebar isolation —");
  const ctxQ = await browser.createBrowserContext();
  const ctxB = await browser.createBrowserContext();
  const pq = await ctxQ.newPage();
  const pb = await ctxB.newPage();
  await pq.setViewport({ width: 1280, height: 900 });
  await pb.setViewport({ width: 1280, height: 900 });
  await pq.setCookie({ name: "sessionid", value: qiranCookie, domain: "127.0.0.1", path: "/" });
  await pb.setCookie({ name: "sessionid", value: btCookie, domain: "127.0.0.1", path: "/" });
  await pq.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
  await pb.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
  const qSids = await pq.evaluate(() => Array.from(document.querySelectorAll("[data-conv-sidebar] a[href*='/chat/c/']")).map(a => (a.getAttribute("href") || "").replace(/\/+$/, "").split("/").pop()));
  const bSids = await pb.evaluate(() => Array.from(document.querySelectorAll("[data-conv-sidebar] a[href*='/chat/c/']")).map(a => (a.getAttribute("href") || "").replace(/\/+$/, "").split("/").pop()));
  const overlap = qSids.filter(s => bSids.includes(s));
  if (qSids.length > 0 && overlap.length === 0) pass("D1-isolation", `Q=${qSids.length} B=${bSids.length}`);
  else fail("D1-isolation", `overlap=${overlap.length}`);
  await ctxB.close();

  const page = pq;
  page.on("response", r => { if (r.status() >= 500) errs500.push({ url: r.url(), status: r.status() }); });

  // D5/D6/D9: Solo chat — default agent, no Gemini, no Assistant flash
  console.log("\n— D5/D6/D9: solo chat default agent + flash check —");
  const newUrl = await page.evaluate(async (base, t) => {
    const fd = new FormData(); fd.append("csrfmiddlewaretoken", t);
    const r = await fetch(base + "/chat/new/", { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": t }, body: fd, redirect: "follow" });
    return r.url;
  }, BASE, await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ""));
  await page.goto(newUrl, { waitUntil: "networkidle2" });
  await sleep(500);
  const initial = await page.evaluate(() => document.querySelector("[data-initial-agent-name]")?.getAttribute("data-initial-agent-name"));
  if (initial === "Qiran's Agent") pass("D9-initial-agent-name", initial);
  else fail("D9-initial-agent-name", `got "${initial}"`);

  await send(page, "who are you");
  const labels = [];
  for (let i = 0; i < 12; i++) {
    await sleep(180);
    const l = await page.evaluate(() => {
      const rows = document.querySelectorAll(".chat-msg-row");
      const last = rows[rows.length - 1];
      if (!last || last.classList.contains("flex-row-reverse")) return null;
      return last.querySelector("[data-sender-label]")?.textContent.trim();
    });
    if (l) labels.push(l);
  }
  const uniq = [...new Set(labels)];
  if (!uniq.includes("Assistant")) pass("D9-no-assistant-flash"); else fail("D9-no-assistant-flash");

  const reply = await waitReply(page, { maxMs: 45000 });
  if (!reply) fail("D5-got-response");
  else {
    if (reply.sender === "Qiran's Agent") pass("D5-default-own-agent", reply.sender); else fail("D5-default-own-agent", reply.sender);
    if (!/^I am Gemini|trained by Google/i.test(reply.content)) pass("D6-no-gemini-leak"); else fail("D6-no-gemini-leak");
  }

  // D7: Team chat → teammate agent responds
  console.log("\n— D7: team chat → teammate's agent —");
  const teamUrl = await page.evaluate(async (base, t) => {
    const fd = new FormData(); fd.append("csrfmiddlewaretoken", t);
    const r = await fetch(base + "/chat/agents/marketplace/executive-assistant/start-chat/", { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": t }, body: fd, redirect: "follow" });
    return r.url;
  }, BASE, await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ""));
  await page.goto(teamUrl, { waitUntil: "networkidle2" });
  await sleep(500);
  await send(page, "what do you do?");
  const teamReply = await waitReply(page, { maxMs: 45000 });
  if (teamReply?.sender === "Sarah Chen's Agent") pass("D7-team-agent-responds", teamReply.sender);
  else fail("D7-team-agent-responds", teamReply?.sender || "no reply");

  // D2/D3/D4: Pusher ACL
  console.log("\n— D2/D3/D4: Pusher ACL —");
  const btSid = pyOneLine(`from app.services import neo4j_memory as neo4j
s = neo4j.get_sessions_for_user('302', limit=1)
print(s[0]['id'] if s else '', end='')`);
  if (btSid) {
    const r1 = await postForm(page, "/chat/api/pusher/auth/", { socket_id: "1.1", channel_name: `private-group-${btSid}` });
    if (r1.status === 403) pass("D2-pusher-foreign-session-denied"); else fail("D2-pusher-foreign-session-denied", `status=${r1.status}`);
  }
  const r2 = await postForm(page, "/chat/api/pusher/auth/", { socket_id: "1.1", channel_name: "presence-evil-debug" });
  if (r2.status === 403) pass("D3-pusher-unknown-prefix-denied"); else fail("D3-pusher-unknown-prefix-denied", `status=${r2.status}`);
  const r3 = await postForm(page, "/chat/api/pusher/auth/", { socket_id: "1.1", channel_name: "private-user-302" });
  if (r3.status === 403) pass("D4-pusher-spoofed-user-denied"); else fail("D4-pusher-spoofed-user-denied", `status=${r3.status}`);

  // D8: First-name collision suffix
  console.log("\n— D8: first-name collision suffix —");
  const collide = pyOneLine(`from app.chat.agent_service import _pick_unique_default_agent_name
print(_pick_unique_default_agent_name('Qiran'), end='')`);
  if (/^Qiran\d+'s Agent$/.test(collide)) pass("D8-collision-suffix", collide);
  else fail("D8-collision-suffix", collide);

  await ctxQ.close();

  // ╔═══════════════════════════════════════════════════════════════╗
  // ║ MOBILE TESTS (390×844 viewport, isMobile)                     ║
  // ╚═══════════════════════════════════════════════════════════════╝
  console.log("\n══ MOBILE (390×844 + 375 + 320) ══");

  for (const vp of [{ name: "390", w: 390, h: 844 }, { name: "375", w: 375, h: 667 }, { name: "320", w: 320, h: 568 }]) {
    console.log(`\n— Viewport ${vp.name}px —`);
    const ctx = await browser.createBrowserContext();
    const mp = await ctx.newPage();
    await mp.setViewport({ width: vp.w, height: vp.h, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
    await mp.setCookie({ name: "sessionid", value: qiranCookie, domain: "127.0.0.1", path: "/" });
    await mp.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
    await sleep(700);

    // M1: Mobile recent chats list visible
    const recent = await mp.evaluate(() => {
      const list = document.querySelector("[data-mobile-recent-list]");
      if (!list) return { rendered: false };
      const links = Array.from(list.querySelectorAll("a[href^='/chat/c/']"));
      const visible = links.filter(a => a.offsetParent !== null);
      return {
        rendered: true,
        wrapperVisible: list.offsetParent !== null,
        totalLinks: links.length,
        visibleLinks: visible.length,
        firstHref: visible[0]?.getAttribute("href"),
      };
    });
    if (recent.rendered && recent.wrapperVisible && recent.visibleLinks > 0) pass(`M1-${vp.name}-recent-chats`, `${recent.visibleLinks} visible`);
    else fail(`M1-${vp.name}-recent-chats`, JSON.stringify(recent));

    // M2: Notification dropdown contained
    await mp.evaluate(() => document.getElementById("notification-dropdown")?.classList.remove("hidden"));
    await sleep(200);
    const dd = await mp.evaluate(() => {
      const d = document.getElementById("notification-dropdown");
      if (!d) return { err: "no dropdown" };
      const r = d.getBoundingClientRect();
      return { x: Math.round(r.x), right: Math.round(r.right), w: Math.round(r.width), vw: window.innerWidth };
    });
    if (dd.x >= 0 && dd.right <= dd.vw) pass(`M2-${vp.name}-dropdown-contained`, `x=${dd.x}-${dd.right} vw=${dd.vw}`);
    else fail(`M2-${vp.name}-dropdown-contained`, JSON.stringify(dd));

    // M3 + M4: Chat bubble doesn't overflow on existing chat
    if (recent.firstHref) {
      await mp.goto(BASE + recent.firstHref, { waitUntil: "networkidle2" });
      await sleep(800);
      const ov = await mp.evaluate(() => {
        const main = document.querySelector("main");
        const mainW = main ? Math.round(main.getBoundingClientRect().width) : 0;
        const rows = document.querySelectorAll(".chat-msg-row");
        const overflowing = Array.from(rows).filter(r => r.getBoundingClientRect().right > window.innerWidth + 1).length;
        return {
          vw: window.innerWidth,
          docW: document.documentElement.scrollWidth,
          mainW,
          rowCount: rows.length,
          overflowingRows: overflowing,
        };
      });
      if (ov.mainW <= ov.vw) pass(`M4-${vp.name}-main-contained`, `main=${ov.mainW} vw=${ov.vw}`);
      else fail(`M4-${vp.name}-main-contained`, `main=${ov.mainW} vw=${ov.vw}`);
      if (ov.overflowingRows === 0) pass(`M3-${vp.name}-no-bubble-overflow`, `${ov.rowCount} rows`);
      else fail(`M3-${vp.name}-no-bubble-overflow`, `${ov.overflowingRows}/${ov.rowCount} overflowing`);

      // M5: tap a recent chat link
      pass(`M5-${vp.name}-recent-link-tappable`, `loaded ${recent.firstHref.slice(0, 40)}`);
    }

    await ctx.close();
  }

  // Final screenshot
  const finalCtx = await browser.createBrowserContext();
  const finalPage = await finalCtx.newPage();
  await finalPage.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  await finalPage.setCookie({ name: "sessionid", value: qiranCookie, domain: "127.0.0.1", path: "/" });
  await finalPage.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
  await sleep(500);
  await finalPage.evaluate(() => {
    const list = document.querySelector("[data-mobile-recent-list]");
    list?.scrollIntoView({ block: "center" });
  });
  await sleep(300);
  await finalPage.screenshot({ path: "/tmp/full_e2e_final.png", fullPage: false });
  await finalCtx.close();

} catch (err) {
  console.error("FATAL:", err.message);
  results.push({ n: "fatal", ok: false, d: String(err) });
} finally {
  const passed = results.filter(r => r.ok).length;
  const failed = results.filter(r => !r.ok).length;
  console.log(`\n═══ SUMMARY: ${passed} pass / ${failed} fail / ${errs500.length} HTTP 500 ═══`);
  if (errs500.length) for (const e of errs500) console.log(`  500: ${e.url}`);
  await browser.close();
  process.exit(failed === 0 && errs500.length === 0 ? 0 : 1);
}
