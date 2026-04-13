#!/usr/bin/env node
"use strict";

const puppeteer = require("/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer");
const path = require("path");
const fs = require("fs");

const BASE = "http://localhost:8000";
const OUT = path.resolve(__dirname, "../docs/screenshots");
const USER = "tester";
const PASS = "tester123";

const DESKTOP = { width: 1280, height: 800 };
const MOBILE  = { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 };

const delay = ms => new Promise(r => setTimeout(r, ms));

async function login(page) {
    await page.goto(`${BASE}/accounts/login/`, { waitUntil: "domcontentloaded", timeout: 20000 });
    await page.waitForSelector("input[name='login']", { timeout: 10000 });
    await page.type("input[name='login']", USER);
    await page.type("input[name='password']", PASS);
    await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 20000 }),
        page.click("button[type='submit']"),
    ]);
    await delay(800);
}

async function shot(page, filename, viewport) {
    const outPath = path.join(OUT, filename);
    await page.setViewport(viewport);
    await delay(700);
    await page.screenshot({ path: outPath, fullPage: false });
    console.log("  saved", filename);
}

async function goto(page, url, viewport) {
    await page.setViewport(viewport);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
    await delay(500);
}

async function findSession(page) {
    // Try sidebar conversation links
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded", timeout: 15000 });
    await delay(500);
    const href = await page.evaluate(() => {
        const links = Array.from(document.querySelectorAll("a[href*='/chat/c/']"));
        return links.length ? links[0].href : null;
    });
    if (href) return href;

    // Fall back to the chat home URL if no conversations listed
    return BASE + "/";
}

async function main() {
    fs.mkdirSync(OUT, { recursive: true });

    const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox", "--disable-dev-shm-usage"] });

    // ── Landing page screenshots (unauthenticated) ──────────────────────────
    console.log("Landing (unauthenticated)...");
    const anonCtx = await browser.createBrowserContext();
    const anonPage = await anonCtx.newPage();
    await goto(anonPage, BASE + "/", DESKTOP);
    await shot(anonPage, "01-landing-desktop.png", DESKTOP);
    await goto(anonPage, BASE + "/", MOBILE);
    await shot(anonPage, "01-landing-mobile.png", MOBILE);
    await anonCtx.close();

    // ── Authenticated screenshots ────────────────────────────────────────────
    const page = await browser.newPage();
    await page.setViewport(DESKTOP);

    console.log("Logging in...");
    await login(page);

    console.log("Discovering agent and session URLs...");
    // Agent
    await page.goto(BASE + "/chat/agents/my/", { waitUntil: "domcontentloaded", timeout: 15000 });
    await delay(500);
    const agentHref = await page.evaluate(() => {
        const links = Array.from(document.querySelectorAll("a[href*='/chat/agents/']"));
        const detail = links.find(a => /\/chat\/agents\/[0-9a-f-]{36}(\/|$)/.test(a.getAttribute("href") || ""));
        return detail ? detail.href : null;
    });
    // Session
    const sessionHref = await findSession(page);
    console.log("  agent:", agentHref || "(none)");
    console.log("  session:", sessionHref);

    const agentSkillsHref = agentHref
        ? agentHref.replace(/\/?$/, "") + "/skills/"
        : BASE + "/chat/agents/my/";

    const pages = [
        { num: "02", name: "home",             url: BASE + "/home/" },
        { num: "03", name: "dashboard",        url: BASE + "/chat/dashboard/" },
        { num: "04", name: "memory",           url: BASE + "/chat/memory/" },
        { num: "05", name: "analytics",        url: BASE + "/chat/analytics/" },
        { num: "06", name: "agent-detail",     url: agentHref || BASE + "/chat/agents/my/" },
        { num: "07", name: "groups",           url: BASE + "/chat/groups/" },
        { num: "08", name: "activity-log",     url: BASE + "/chat/activity/" },
        { num: "09", name: "skill-marketplace",url: BASE + "/chat/skills/marketplace/" },
        { num: "10", name: "conversation",     url: sessionHref },
        { num: "11", name: "documents",        url: BASE + "/chat/documents/" },
        { num: "12", name: "agent-skills",     url: agentSkillsHref },
    ];

    for (const pg of pages) {
        console.log(`\n${pg.num}-${pg.name}...`);

        await goto(page, pg.url, DESKTOP);
        await shot(page, `${pg.num}-${pg.name}-desktop.png`, DESKTOP);

        await goto(page, pg.url, MOBILE);
        await shot(page, `${pg.num}-${pg.name}-mobile.png`, MOBILE);
    }

    await browser.close();
    console.log("\nAll 24 screenshots saved.");
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
