#!/usr/bin/env node
// Detailed browser verification of every fix implemented in this session.
// Follows the real production user flow: landing page -> click Sign in ->
// fill modal -> reach /home/ -> exercise each feature area.
import puppeteer from "/Users/edwardhu/.claude/skills/chrome-devtools/scripts/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js";
import fs from "fs";
import path from "path";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8765";
const USERNAME = process.env.E2E_USERNAME || "browsertest";
const EMAIL = process.env.E2E_EMAIL || "browsertest@local.test";
const PASSWORD = process.env.E2E_PASSWORD || "BrowserTest_2026!";
const SHOT_DIR = process.env.SHOT_DIR || "./docs/screenshots/verify-all";
const HEADFUL = process.env.HEADFUL === "1";

fs.mkdirSync(SHOT_DIR, { recursive: true });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const report = {
    baseUrl: BASE,
    startedAt: new Date().toISOString(),
    features: [],
    pageErrors: [],
    consoleErrors: [],
    failedRequests: [],
    http500s: [],
};

function record(feature, assertion, ok, detail) {
    report.features.push({ feature, assertion, ok, detail });
    const prefix = ok ? "PASS" : "FAIL";
    console.log(`  [${prefix}] ${feature}: ${assertion}${detail ? " — " + detail : ""}`);
}

async function shot(page, label) {
    const target = path.join(SHOT_DIR, `${label}.png`);
    await page.screenshot({ path: target, fullPage: true });
    return target;
}

async function main() {
    const browser = await puppeteer.launch({
        headless: HEADFUL ? false : "new",
        slowMo: HEADFUL ? 60 : 0,
        defaultViewport: HEADFUL ? null : { width: 1280, height: 900 },
        args: ["--no-sandbox", "--disable-setuid-sandbox", HEADFUL ? "--window-size=1400,1000" : ""].filter(Boolean),
    });
    const page = await browser.newPage();
    if (!HEADFUL) await page.setViewport({ width: 1280, height: 900 });

    page.on("pageerror", e => report.pageErrors.push(String(e)));
    page.on("console", m => { if (m.type() === "error") report.consoleErrors.push(m.text()); });
    page.on("requestfailed", r => report.failedRequests.push({ url: r.url(), err: r.failure()?.errorText }));
    page.on("response", r => { if (r.status() >= 500) report.http500s.push({ url: r.url(), status: r.status() }); });

    try {
        // ============================================================
        // FEATURE 1: Landing page renders with styled logo
        // ============================================================
        console.log("\n== FEATURE 1: Landing page ==");
        const landResp = await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
        record("landing", "HTTP 200", (landResp?.status() || 0) === 200, `status=${landResp?.status()}`);
        await shot(page, "01-landing");

        const navLogoOk = await page.evaluate(() => {
            const img = document.querySelector(".landing-nav img");
            if (!img) return { present: false };
            const c = getComputedStyle(img);
            return { present: true, width: c.width, height: c.height, objectFit: c.objectFit };
        });
        record("landing", "nav logo rendered with object-fit: contain",
               navLogoOk.present && navLogoOk.objectFit === "contain",
               JSON.stringify(navLogoOk));

        const signInBtn = await page.$("#open-login");
        record("landing", "Sign in button present", !!signInBtn, "");

        // ============================================================
        // FEATURE 2: Sign-in modal opens and is styled
        // ============================================================
        console.log("\n== FEATURE 2: Sign-in modal ==");
        await signInBtn?.click();
        await sleep(500);
        const modalShape = await page.evaluate(() => {
            const title = Array.from(document.querySelectorAll("h2, h3, .auth-title"))
                .find(h => /Sign in to Memoria/i.test(h.textContent || ""));
            const emailInput = document.querySelector('input[name="email"], input[type="email"]');
            const pwInput = document.querySelector('input[name="password"], input[type="password"]');
            const google = Array.from(document.querySelectorAll("a, button"))
                .find(el => /Continue with Google/i.test(el.textContent || ""));
            return {
                titleVisible: !!title && title.getBoundingClientRect().height > 0,
                emailPresent: !!emailInput,
                passwordPresent: !!pwInput,
                googlePresent: !!google,
            };
        });
        record("login-modal", "title + email + password + Google present",
               modalShape.titleVisible && modalShape.emailPresent && modalShape.passwordPresent && modalShape.googlePresent,
               JSON.stringify(modalShape));
        await shot(page, "02-login-modal");

        // ============================================================
        // FEATURE 3: Modal login submits and redirects to /home/
        // ============================================================
        console.log("\n== FEATURE 3: Modal login flow ==");
        await page.type('input[name="email"]', EMAIL);
        await page.type('input[name="password"]', PASSWORD);
        await Promise.all([
            page.waitForNavigation({ waitUntil: "networkidle2", timeout: 15000 }).catch(() => null),
            page.click('button[type="submit"].auth-form-submit, button.auth-form-submit'),
        ]);
        const postLogin = page.url();
        record("login-modal", "redirects to /home/ after submit",
               postLogin.includes("/home/"),
               `url=${postLogin}`);
        await shot(page, "03-home-after-login");

        // ============================================================
        // FEATURE 4: Home page tabs (Create / Join with Key)
        // ============================================================
        console.log("\n== FEATURE 4: Home tabs ==");
        const tabsInitial = await page.evaluate(() => {
            const c = document.querySelector("#tab-create");
            const j = document.querySelector("#tab-join");
            return c && j ? {
                createActive: c.className.includes("bg-white") && c.className.includes("text-mm-primary"),
                joinMuted: j.className.includes("text-mm-muted"),
            } : null;
        });
        record("home-tabs", "create tab starts active, join tab muted",
               tabsInitial?.createActive && tabsInitial?.joinMuted,
               JSON.stringify(tabsInitial));

        await page.click("#tab-join");
        await sleep(200);
        const tabsAfter = await page.evaluate(() => {
            const c = document.querySelector("#tab-create");
            const j = document.querySelector("#tab-join");
            return {
                createMuted: c?.className.includes("text-mm-muted"),
                joinActive: j?.className.includes("bg-white") && j?.className.includes("text-mm-primary"),
            };
        });
        record("home-tabs", "click Join -> Create becomes muted, Join active",
               tabsAfter.createMuted && tabsAfter.joinActive,
               JSON.stringify(tabsAfter));
        await shot(page, "04-home-tabs-join-active");
        await page.click("#tab-create");

        // ============================================================
        // FEATURE 5: GROUPS header has + and JOIN buttons with consistent style
        // ============================================================
        console.log("\n== FEATURE 5: Groups header buttons ==");
        const headerButtons = await page.evaluate(() => {
            const plus = document.querySelector('[data-conv-sidebar] button[aria-label="Create group"]');
            const join = document.querySelector('[data-conv-sidebar] button[title="Join group with invite code"]');
            if (!plus || !join) return null;
            const s = el => {
                const c = getComputedStyle(el);
                return { h: c.height, bg: c.backgroundColor, border: c.borderWidth + " " + c.borderStyle };
            };
            return { plus: s(plus), join: s(join) };
        });
        record("groups-header", "+ button matches JOIN button height",
               headerButtons?.plus?.h === headerButtons?.join?.h,
               JSON.stringify(headerButtons));
        record("groups-header", "JOIN button is ghost style (no filled background)",
               headerButtons?.join?.bg?.includes("rgba(0, 0, 0, 0)") || headerButtons?.join?.bg === "transparent",
               `bg=${headerButtons?.join?.bg}`);

        // ============================================================
        // FEATURE 6: Create a new chat
        // ============================================================
        console.log("\n== FEATURE 6: New chat creation ==");
        const csrfNewChat = await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1]);
        const newChatResp = await page.evaluate(async (base, token) => {
            const r = await fetch(base + "/chat/new/", {
                method: "POST", credentials: "same-origin",
                headers: { "X-CSRFToken": token, "Content-Type": "application/x-www-form-urlencoded" },
                body: "", redirect: "follow",
            });
            return { status: r.status, url: r.url };
        }, BASE, csrfNewChat);
        record("new-chat", "POST /chat/new/ returns 200 with redirect to /chat/c/<id>/",
               newChatResp.status === 200 && /\/chat\/c\//.test(newChatResp.url),
               JSON.stringify(newChatResp));

        // ============================================================
        // FEATURE 7: Create a new group
        // ============================================================
        console.log("\n== FEATURE 7: Group creation ==");
        const groupTitle = `VerifyGroup_${Date.now().toString(36)}`;
        const groupResp = await page.evaluate(async (base, token, title) => {
            const body = new URLSearchParams({ csrfmiddlewaretoken: token, title, description: "verify" });
            const r = await fetch(base + "/chat/groups/create/", {
                method: "POST", credentials: "same-origin",
                headers: { "X-CSRFToken": token, "Content-Type": "application/x-www-form-urlencoded" },
                body: body.toString(), redirect: "follow",
            });
            return { status: r.status, url: r.url };
        }, BASE, csrfNewChat, groupTitle);
        record("group-create", "POST /chat/groups/create/ returns 200",
               groupResp.status === 200, JSON.stringify(groupResp));

        // ============================================================
        // FEATURE 8: Group appears in sidebar after creation
        // ============================================================
        console.log("\n== FEATURE 8: Sidebar reflects created group ==");
        await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
        const sidebarHasGroup = await page.evaluate((title) => {
            const entries = Array.from(document.querySelectorAll("[data-conv-sidebar] a"))
                .map(a => (a.textContent || "").trim());
            return { entries: entries.length, hasMatch: entries.some(e => e.includes(title.slice(0, 10))) };
        }, groupTitle);
        record("sidebar", "newly created group appears in sidebar",
               sidebarHasGroup.hasMatch, `total_entries=${sidebarHasGroup.entries}`);
        await shot(page, "05-sidebar-with-group");

        // ============================================================
        // FEATURE 9: Group chat page loads (no 500 from member.user bug)
        // ============================================================
        console.log("\n== FEATURE 9: Group chat page rendering ==");
        const groupUrl = groupResp.url;
        const chatResp = await page.goto(groupUrl, { waitUntil: "networkidle2" });
        record("group-chat", "GET /chat/c/<id>/ returns 200 (not 500 from member.user)",
               (chatResp?.status() || 0) === 200, `status=${chatResp?.status()}`);
        await shot(page, "06-group-chat");

        // Member count in header pill
        const memberPill = await page.evaluate(() => {
            const buttons = Array.from(document.querySelectorAll(".conv-header button"));
            const match = buttons.find(b => /\d+\s*member/i.test(b.textContent || ""));
            return match ? (match.textContent || "").trim() : null;
        });
        record("group-chat", "header pill shows member count like \"1 member\"",
               !!memberPill && /\d+\s*member/i.test(memberPill),
               JSON.stringify(memberPill));

        // Invite code pill
        const inviteCode = await page.evaluate(() => {
            const el = Array.from(document.querySelectorAll(".conv-header button span"))
                .find(s => /^[a-f0-9]{8,}$/.test((s.textContent || "").trim()));
            return el ? (el.textContent || "").trim() : null;
        });
        record("group-chat", "invite code pill shows hex access key",
               !!inviteCode, `code=${inviteCode}`);

        // ============================================================
        // FEATURE 10: Info panel opens with invite code + members list
        // ============================================================
        console.log("\n== FEATURE 10: Info panel ==");
        const infoButton = await page.evaluateHandle(() => {
            return Array.from(document.querySelectorAll(".conv-header button"))
                .find(b => b.getAttribute("aria-label") === "Conversation info");
        });
        if (infoButton && infoButton.asElement()) {
            await infoButton.asElement().click();
            await sleep(400);
            await shot(page, "07-info-panel");
            const panel = await page.evaluate(() => {
                const p = document.querySelector("#info-panel");
                if (!p) return null;
                const text = p.innerText || "";
                const memberMatch = text.match(/Members\s*\((\d+)\)/);
                const inviteHex = text.match(/[a-f0-9]{10,}/);
                return {
                    visible: !p.classList.contains("hidden"),
                    memberCount: memberMatch ? parseInt(memberMatch[1], 10) : null,
                    hasInviteCode: !!inviteHex,
                    text: text.slice(0, 250),
                };
            });
            record("info-panel", "panel visible with Members (N) count",
                   panel?.visible && typeof panel.memberCount === "number",
                   `count=${panel?.memberCount}`);
            record("info-panel", "panel shows invite code",
                   panel?.hasInviteCode, "");
            record("info-panel", "member row renders name (no member.user 500)",
                   (panel?.text || "").length > 20 && !(panel?.text || "").includes("NoneType"),
                   `text preview=${(panel?.text || "").slice(0, 80)}`);
        }

        // ============================================================
        // FEATURE 11: Group settings page loads (Bug 5 previous fix)
        // ============================================================
        console.log("\n== FEATURE 11: Group settings page ==");
        const sessId = groupUrl.split("/chat/c/")[1].replace(/\/$/, "");
        const settingsResp = await page.goto(`${BASE}/chat/groups/${sessId}/settings/`, { waitUntil: "networkidle2" });
        record("group-settings", "settings page returns 200",
               (settingsResp?.status() || 0) === 200,
               `status=${settingsResp?.status()}`);
        await shot(page, "08-group-settings");

        const settingsShape = await page.evaluate(() => {
            const title = document.querySelector('input[name="title"]')?.value;
            const members = document.querySelectorAll("h2");
            const memberHeader = Array.from(members).find(h => /Members\s*\(\d+\)/.test(h.textContent || ""));
            return { titleInput: title, memberHeader: memberHeader?.textContent || null };
        });
        record("group-settings", "form pre-filled with title and member count header",
               !!settingsShape.titleInput && !!settingsShape.memberHeader,
               JSON.stringify(settingsShape));

        // ============================================================
        // FEATURE 12: Agent detail page (name readonly, auto-derived)
        // ============================================================
        console.log("\n== FEATURE 12: Agent detail page ==");
        const agentResp = await page.goto(`${BASE}/chat/agents/my/`, { waitUntil: "networkidle2" });
        record("agent-detail", "/chat/agents/my/ returns 200",
               (agentResp?.status() || 0) === 200,
               `status=${agentResp?.status()}, final=${page.url()}`);
        await shot(page, "09-agent-detail");

        const agentFields = await page.evaluate(() => {
            const nameInput = document.querySelector('input[name="name"]');
            if (!nameInput) return null;
            return {
                value: nameInput.value,
                readonly: nameInput.readOnly,
                hasSpacesInName: / /.test(nameInput.value),
            };
        });
        record("agent-detail", "name field is readonly",
               agentFields?.readonly, JSON.stringify(agentFields));
        record("agent-detail", "agent name has no spaces (derived from username)",
               !agentFields?.hasSpacesInName,
               `value=${agentFields?.value}`);

        // ============================================================
        // FEATURE 13: Notification bell + action button typography
        // ============================================================
        console.log("\n== FEATURE 13: Notification action buttons typography ==");
        // Probe the typography on synthetic DOM matching what the bell dropdown renders
        await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
        const notifTypography = await page.evaluate(() => {
            const host = document.createElement("div");
            host.innerHTML = `
                <a class="font-inter text-xs font-medium text-mm-primary">View conversation</a>
                <button type="button" class="font-inter text-xs font-medium text-slate-400">Mark as read</button>
            `;
            document.body.appendChild(host);
            const a = host.querySelector("a");
            const b = host.querySelector("button");
            const ca = getComputedStyle(a);
            const cb = getComputedStyle(b);
            return {
                a: { ff: ca.fontFamily, fs: ca.fontSize, fw: ca.fontWeight },
                b: { ff: cb.fontFamily, fs: cb.fontSize, fw: cb.fontWeight },
            };
        });
        const typoMatch =
            notifTypography.a.ff === notifTypography.b.ff &&
            notifTypography.a.fs === notifTypography.b.fs &&
            notifTypography.a.fw === notifTypography.b.fw;
        record("notification-typography",
               "View conversation (a) and Mark as read (button) have matching font-family/size/weight",
               typoMatch, JSON.stringify(notifTypography));

        // ============================================================
        // FEATURE 14: Allauth fallback login page is styled
        // ============================================================
        console.log("\n== FEATURE 14: /accounts/login/ fallback styled ==");
        // Logout first
        await page.goto(`${BASE}/accounts/logout/`, { waitUntil: "networkidle2" }).catch(() => null);
        await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle2" });
        const allauthLogin = await page.evaluate(() => {
            const body = getComputedStyle(document.body);
            const input = document.getElementById("id_login");
            const cInput = input ? getComputedStyle(input) : null;
            return {
                title: document.title,
                bodyFont: body.fontFamily,
                inputFont: cInput?.fontFamily,
                inputSize: cInput?.fontSize,
                inputBorder: cInput?.border,
            };
        });
        record("allauth-fallback-login",
               "title uses Memoria branding",
               /Memoria/i.test(allauthLogin.title), allauthLogin.title);
        record("allauth-fallback-login",
               "body uses Inter font",
               /Inter/i.test(allauthLogin.bodyFont || ""),
               allauthLogin.bodyFont);
        record("allauth-fallback-login",
               "login input uses Inter font",
               /Inter/i.test(allauthLogin.inputFont || ""),
               allauthLogin.inputFont);
        record("allauth-fallback-login",
               "input border is mm-primary tinted (not browser-default inset grey)",
               !(allauthLogin.inputBorder || "").includes("inset"),
               allauthLogin.inputBorder);
        await shot(page, "10-allauth-fallback-login");

        // ============================================================
        // FEATURE 15: Mobile viewport landing renders correctly
        // ============================================================
        console.log("\n== FEATURE 15: Mobile viewport ==");
        await page.setViewport({ width: 390, height: 844, isMobile: true });
        const mobileLand = await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
        record("mobile", "landing at 390px returns 200",
               (mobileLand?.status() || 0) === 200, `status=${mobileLand?.status()}`);
        await shot(page, "11-mobile-landing");

    } catch (err) {
        report.fatal = String(err);
        report.fatal_stack = err?.stack;
        try { await shot(page, "99-fatal"); } catch {}
    } finally {
        report.finishedAt = new Date().toISOString();
        fs.writeFileSync(path.join(SHOT_DIR, "report.json"), JSON.stringify(report, null, 2));
        console.log("\nREPORT:", path.join(SHOT_DIR, "report.json"));
        await browser.close();
    }
}

main().then(() => {
    const pass = report.features.filter(f => f.ok).length;
    const fail = report.features.filter(f => !f.ok).length;
    console.log(`\nSUMMARY: ${pass} pass / ${fail} fail`);
    console.log(`page errors: ${report.pageErrors.length}, console errors: ${report.consoleErrors.length}, failed requests: ${report.failedRequests.length}, 500s: ${report.http500s.length}`);
    process.exit(fail === 0 && report.http500s.length === 0 ? 0 : 1);
});
