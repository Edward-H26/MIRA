#!/usr/bin/env node
"use strict";

const puppeteer = require("/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer");
const path = require("path");

const BASE = "http://localhost:8000";
const OUT = path.resolve(__dirname, "../docs/screenshots");
const DESKTOP = { width: 1280, height: 800 };
const MOBILE  = { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 };
const delay = ms => new Promise(r => setTimeout(r, ms));

async function main() {
    const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox", "--disable-dev-shm-usage"] });
    const page = await browser.newPage();

    // Login
    await page.setViewport(DESKTOP);
    await page.goto(`${BASE}/accounts/login/`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("input[name='login']");
    await page.type("input[name='login']", "tester");
    await page.type("input[name='password']", "tester123");
    await Promise.all([
        page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 20000 }),
        page.click("button[type='submit']"),
    ]);
    await delay(800);

    // Desktop
    await page.setViewport(DESKTOP);
    await page.goto(`${BASE}/home/`, { waitUntil: "domcontentloaded" });
    await delay(700);
    await page.screenshot({ path: path.join(OUT, "02-home-desktop.png") });
    console.log("saved 02-home-desktop.png");

    // Mobile
    await page.setViewport(MOBILE);
    await page.goto(`${BASE}/home/`, { waitUntil: "domcontentloaded" });
    await delay(700);
    await page.screenshot({ path: path.join(OUT, "02-home-mobile.png") });
    console.log("saved 02-home-mobile.png");

    await browser.close();
}

main().catch(err => { console.error(err); process.exit(1); });
