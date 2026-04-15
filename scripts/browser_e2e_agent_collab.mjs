#!/usr/bin/env node
// End-to-end browser test of agent-to-agent collaboration.
// Logs in as browsertest, starts a new chat, sends different prompts,
// and captures screenshots + console + network traces of each interaction.
import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import fs from "fs";
import path from "path";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8765";
const USERNAME = process.env.E2E_USERNAME || "browsertest";
const PASSWORD = process.env.E2E_PASSWORD || "BrowserTest_2026!";
const SHOT_DIR = process.env.SHOT_DIR || "./docs/screenshots/browser-e2e";
const WAIT_FOR_RESPONSE_MS = Number(process.env.WAIT_FOR_RESPONSE_MS || 45000);

const prompts = [
    { label: "01-single-mention", text: "@Alice what is the one-sentence elevator pitch for Memoria?" },
    { label: "02-agent-chain",    text: "@Alice please give a short summary, and also hand off to @Bob for the supporting details." },
    { label: "03-self-continue",  text: "@Alice think step by step and @Alice continue if you need more turns." },
    { label: "04-invalid-mention",text: "@Nobody_1234 tell me a joke." },
    { label: "05-no-mention",     text: "Summarize in two bullet points: the benefits of persistent memory for AI agents." },
    { label: "06-mid-stream-nav", text: "@Alice write a long detailed paragraph about your memory architecture.", _navigateAfterMs: 1500 },
];

fs.mkdirSync(SHOT_DIR, { recursive: true });

async function captureShot(page, label) {
    const target = path.join(SHOT_DIR, `${label}.png`);
    await page.screenshot({ path: target, fullPage: true });
    return target;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const runReport = { baseUrl: BASE, startedAt: new Date().toISOString(), steps: [] };

async function main() {
    const browser = await puppeteer.launch({
        headless: "new",
        args: ["--no-sandbox", "--disable-setuid-sandbox"],
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });

    const consoleMessages = [];
    page.on("console", m => consoleMessages.push({ type: m.type(), text: m.text() }));
    const pageErrors = [];
    page.on("pageerror", e => pageErrors.push(String(e)));
    const failedRequests = [];
    page.on("requestfailed", r => failedRequests.push({ url: r.url(), failure: r.failure()?.errorText }));

    try {
        // --- Login ---
        await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle2" });
        await captureShot(page, "00-login");
        await page.waitForSelector("#id_login", { timeout: 10000 });
        await page.type("#id_login", USERNAME);
        await page.type("#id_password", PASSWORD);
        await Promise.all([
            page.waitForNavigation({ waitUntil: "networkidle2", timeout: 15000 }),
            page.click("form button[type=submit], form input[type=submit]"),
        ]);
        const postLoginUrl = page.url();
        runReport.steps.push({ step: "login", url: postLoginUrl });
        await captureShot(page, "01-post-login");

        if (postLoginUrl.includes("/accounts/login/")) {
            throw new Error(`Login appears to have failed (still on login page: ${postLoginUrl})`);
        }

        // --- Start a new chat ---
        await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
        await captureShot(page, "02-home");

        // Prefer direct POST to /chat/new/ via a form simulation
        const csrf = await page.evaluate(() => {
            const m = document.cookie.match(/csrftoken=([^;]+)/);
            return m ? m[1] : null;
        });
        if (!csrf) throw new Error("csrftoken cookie missing");
        const newChatResp = await page.evaluate(async (base, token) => {
            const resp = await fetch(base + "/chat/new/", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": token,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body: "",
                redirect: "follow",
            });
            return { status: resp.status, url: resp.url };
        }, BASE, csrf);
        runReport.steps.push({ step: "new_chat", ...newChatResp });
        await page.goto(newChatResp.url, { waitUntil: "networkidle2" });
        await captureShot(page, "03-new-chat-empty");

        // --- Send each prompt, wait for the "done" payload, capture the state ---
        for (const { label, text, _navigateAfterMs } of prompts) {
            const inputSelector = "#conversation-message-input";
            const submitSelector = "#conversation-submit-button";
            await page.waitForSelector(inputSelector, { timeout: 10000 });
            await page.click(inputSelector, { clickCount: 3 });
            await page.type(inputSelector, text);
            await captureShot(page, `${label}-before-send`);

            // Both template-rendered AND JS-injected messages share .chat-msg-row.
            const beforeCount = await page.$$eval(".chat-msg-row", els => els.length);
            await page.click(submitSelector);

            // Mid-stream navigation regression test: navigate away to /home/
            // a short interval after submit, then navigate back. Streaming
            // should keep working in the background and the reconnect endpoint
            // should re-attach our subscription.
            let midStreamNav = null;
            if (_navigateAfterMs && _navigateAfterMs > 0) {
                await sleep(_navigateAfterMs);
                const beforeNavUrl = page.url();
                try {
                    await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2", timeout: 8000 });
                    await sleep(800);
                    await page.goto(beforeNavUrl, { waitUntil: "networkidle2", timeout: 12000 });
                    midStreamNav = { ok: true, beforeNavUrl };
                } catch (navErr) {
                    midStreamNav = { ok: false, error: String(navErr) };
                }
            }

            // Two-phase wait: (a) streaming finishes (button re-enables AND
            // first response row appears), (b) row count stabilizes for 2.5s
            // to capture all of revealAgentTurns' staggered appends.
            const start = Date.now();
            let finalCount = beforeCount;
            let streamingDone = false;
            while (Date.now() - start < WAIT_FOR_RESPONSE_MS) {
                await sleep(500);
                finalCount = await page.$$eval(".chat-msg-row", els => els.length);
                const streaming = await page.$eval(
                    submitSelector,
                    btn => btn.disabled
                ).catch(() => true);
                if (!streaming && finalCount >= beforeCount + 2) {
                    streamingDone = true;
                    break;
                }
            }
            // Phase B: settle. Wait until the count is stable for 2500ms or 8s elapses.
            if (streamingDone) {
                let stableSince = Date.now();
                let lastCount = finalCount;
                const settleDeadline = Date.now() + 8000;
                while (Date.now() < settleDeadline) {
                    await sleep(500);
                    const now = await page.$$eval(".chat-msg-row", els => els.length);
                    if (now !== lastCount) {
                        lastCount = now;
                        stableSince = Date.now();
                    } else if (Date.now() - stableSince >= 2500) {
                        break;
                    }
                }
                finalCount = lastCount;
            }
            const elapsed = Date.now() - start;

            // Extract the last visible message; every row has either
            // .message-content or .message-content-markdown inside.
            const lastAssistantText = await page.evaluate(() => {
                const rows = document.querySelectorAll(".chat-msg-row");
                if (!rows.length) return "";
                const last = rows[rows.length - 1];
                return (last.innerText || "").trim().slice(0, 400);
            });

            runReport.steps.push({
                step: label,
                prompt: text,
                beforeCount,
                finalCount,
                assistant_delta: finalCount - beforeCount,
                elapsed_ms: elapsed,
                last_assistant_text_preview: lastAssistantText,
                ...(midStreamNav ? { mid_stream_navigation: midStreamNav } : {}),
            });
            await captureShot(page, `${label}-after-response`);
        }

        // --- Sidebar navigation test: click back to home, confirm no errors ---
        const sidebarTitle = await page.evaluate(() => {
            const link = document.querySelector("#conv-header-title, .conv-header");
            return link ? (link.innerText || "").trim().slice(0, 120) : "";
        });
        runReport.steps.push({ step: "final_header", sidebarTitle });
        await captureShot(page, "99-final-state");
    } catch (err) {
        runReport.error = String(err);
        runReport.stack = err?.stack;
        try { await captureShot(page, "99-failure"); } catch {}
    } finally {
        runReport.consoleMessages = consoleMessages.slice(-60);
        runReport.pageErrors = pageErrors;
        runReport.failedRequests = failedRequests;
        runReport.finishedAt = new Date().toISOString();
        const reportPath = path.join(SHOT_DIR, "run-report.json");
        fs.writeFileSync(reportPath, JSON.stringify(runReport, null, 2));
        console.log("REPORT:", reportPath);
        await browser.close();
    }
}

main().then(
    () => {
        if (runReport.error) {
            console.error("FAIL:", runReport.error);
            process.exit(1);
        }
        const ok = runReport.steps.filter(s => typeof s.assistant_delta === "number" && s.assistant_delta > 0).length;
        console.log(`DONE: ${ok}/${prompts.length} prompts produced an assistant response`);
    },
    err => {
        console.error("FATAL:", err);
        process.exit(1);
    },
);
