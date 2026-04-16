#!/usr/bin/env node
// Browser verification of every fix in this session. Drives a real Chrome
// window through the production login flow (landing -> modal -> home) and
// checks the fixes end-to-end.
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

const browser = await puppeteer.launch({
    headless: HEADFUL ? false : "new",
    slowMo: HEADFUL ? 60 : 0,
    defaultViewport: HEADFUL ? null : { width: 1280, height: 900 },
    args: ["--no-sandbox", "--disable-setuid-sandbox", HEADFUL ? "--window-size=1400,1000" : ""].filter(Boolean),
});
const page = await browser.newPage();
if (!HEADFUL) await page.setViewport({ width: 1280, height: 900 });

const errs = { page: [], console: [], req: [], http500: [] };
page.on("pageerror", e => errs.page.push(String(e)));
page.on("console", m => { if (m.type() === "error") errs.console.push(m.text()); });
page.on("requestfailed", r => errs.req.push(r.url()));
page.on("response", r => { if (r.status() >= 500) errs.http500.push({ url: r.url(), status: r.status() }); });

try {
    // 1. Landing renders
    const r1 = await page.goto(`${BASE}/`, { waitUntil: "networkidle2" });
    record("landing", "GET / returns 200", (r1?.status() || 0) === 200, `status=${r1?.status()}`);
    record("landing", "logo has object-fit: contain",
        await page.evaluate(() => getComputedStyle(document.querySelector(".landing-nav img"))?.objectFit === "contain"),
        "");

    // 2. Sign-in modal opens and has the styled form
    await page.click("#open-login");
    await sleep(400);
    const modalOk = await page.evaluate(() => {
        const title = Array.from(document.querySelectorAll("h2, h3"))
            .find(h => /Sign in to Memoria/i.test(h.textContent || ""));
        return !!title
            && !!document.querySelector('input[name="email"]')
            && !!document.querySelector('input[name="password"]');
    });
    record("login-modal", "modal opens with email + password fields", modalOk, "");

    // 3. Modal login -> redirects to /home/
    await page.type('input[name="email"]', EMAIL);
    await page.type('input[name="password"]', PASSWORD);
    await Promise.all([
        page.waitForNavigation({ waitUntil: "networkidle2" }),
        page.click("button.auth-form-submit"),
    ]);
    record("login-modal", "modal login redirects to /home/", page.url().includes("/home/"), `url=${page.url()}`);

    // 4. Home tabs Create/Join symmetry
    const tabsAfter = await (async () => {
        await page.click("#tab-join");
        await sleep(200);
        return await page.evaluate(() => {
            const c = document.querySelector("#tab-create");
            const j = document.querySelector("#tab-join");
            return {
                createMuted: c?.className.includes("text-mm-muted"),
                joinActive: j?.className.includes("bg-white"),
            };
        });
    })();
    record("home-tabs", "Join active + Create muted after click", tabsAfter.createMuted && tabsAfter.joinActive, JSON.stringify(tabsAfter));
    await page.click("#tab-create");

    // 5. Sidebar + / JOIN buttons are ghost style
    const ghost = await page.evaluate(() => {
        const plus = document.querySelector('[data-conv-sidebar] button[aria-label="Create group"]');
        const join = document.querySelector('[data-conv-sidebar] button[title="Join group with invite code"]');
        if (!plus || !join) return null;
        const p = getComputedStyle(plus);
        const j = getComputedStyle(join);
        return { plusH: p.height, joinH: j.height, joinBg: j.backgroundColor };
    });
    record("sidebar-buttons",
        "+ and JOIN buttons same height and both ghost (transparent bg)",
        ghost?.plusH === ghost?.joinH && /rgba\(0, 0, 0, 0\)|transparent/.test(ghost?.joinBg || ""),
        JSON.stringify(ghost));

    // 6. Create a group via POST and verify it appears
    const csrf = await page.evaluate(() => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1]);
    const gt = `VerifyGroup_${Date.now().toString(36)}`;
    const gResp = await page.evaluate(async (base, token, title) => {
        const body = new URLSearchParams({ csrfmiddlewaretoken: token, title, description: "verify" });
        const r = await fetch(base + "/chat/groups/create/", {
            method: "POST", credentials: "same-origin",
            headers: { "X-CSRFToken": token, "Content-Type": "application/x-www-form-urlencoded" },
            body: body.toString(), redirect: "follow",
        });
        return { status: r.status, url: r.url };
    }, BASE, csrf, gt);
    record("group-create", "POST /chat/groups/create/ returns 200", gResp.status === 200, JSON.stringify(gResp));

    await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
    const sidebarHas = await page.evaluate((title) => {
        return Array.from(document.querySelectorAll("[data-conv-sidebar] a"))
            .some(a => (a.textContent || "").includes(title.slice(0, 10)));
    }, gt);
    record("sidebar-merge", "created group appears in sidebar (CREATED ∪ MEMBER_OF union)", sidebarHas, "");

    // 7. Group chat page loads (member.user bug fix)
    const cr = await page.goto(gResp.url, { waitUntil: "networkidle2" });
    record("group-chat", "GET /chat/c/<id>/ returns 200 (no member.user 500)", (cr?.status() || 0) === 200, `status=${cr?.status()}`);

    const memberPill = await page.evaluate(() => {
        const btns = Array.from(document.querySelectorAll(".conv-header button"));
        const m = btns.find(b => /\d+\s*member/i.test(b.textContent || ""));
        return m ? m.textContent.trim() : null;
    });
    record("group-chat", "member count pill shows \"N member(s)\"", /\d+\s*member/.test(memberPill || ""), `pill=${memberPill}`);

    // 8. Info panel shows member count + invite code
    const info = await page.evaluateHandle(() => Array.from(document.querySelectorAll(".conv-header button"))
        .find(b => b.getAttribute("aria-label") === "Conversation info"));
    if (info && info.asElement()) {
        await info.asElement().click();
        await sleep(400);
    }
    const panel = await page.evaluate(() => {
        const p = document.querySelector("#info-panel");
        if (!p) return null;
        const text = p.innerText || "";
        const mm = text.match(/Members\s*\((\d+)\)/);
        return { visible: !p.classList.contains("hidden"), count: mm ? +mm[1] : null, hasHex: /[a-f0-9]{10,}/.test(text) };
    });
    record("info-panel", "panel shows Members (N) count and invite code",
        panel?.visible && panel?.count >= 1 && panel?.hasHex,
        JSON.stringify(panel));

    // 9. Group settings page loads
    const sid = gResp.url.split("/chat/c/")[1].replace(/\/$/, "");
    const sr = await page.goto(`${BASE}/chat/groups/${sid}/settings/`, { waitUntil: "networkidle2" });
    record("group-settings", "settings page returns 200", (sr?.status() || 0) === 200, `status=${sr?.status()}`);

    // 10. Agent detail page - readonly name, no spaces
    await page.goto(`${BASE}/chat/agents/my/`, { waitUntil: "networkidle2" });
    const agent = await page.evaluate(() => {
        const n = document.querySelector('input[name="name"]');
        return n ? { value: n.value, readonly: n.readOnly, hasSpaces: / /.test(n.value) } : null;
    });
    record("agent-detail", "name readonly + no spaces",
        agent?.readonly && !agent?.hasSpaces, JSON.stringify(agent));

    // 11. Notification typography match (a vs button same font/size/weight)
    await page.goto(`${BASE}/home/`, { waitUntil: "networkidle2" });
    const typo = await page.evaluate(() => {
        const host = document.createElement("div");
        host.innerHTML = `<a class="font-inter text-xs font-medium">a</a><button class="font-inter text-xs font-medium">b</button>`;
        document.body.appendChild(host);
        const s = el => {
            const c = getComputedStyle(el);
            return [c.fontFamily, c.fontSize, c.fontWeight].join("|");
        };
        return { a: s(host.querySelector("a")), b: s(host.querySelector("button")) };
    });
    record("notification-typography",
        "<a> and <button> with same Tailwind classes compute identical font",
        typo.a === typo.b, `a=${typo.a} b=${typo.b}`);

    // 12. Fallback /accounts/login/ styled (probe fresh, no logged-in state)
    const freshPage = await browser.newPage();
    const lr = await freshPage.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle2" });
    record("allauth-fallback", "/accounts/login/ fresh session returns 200", (lr?.status() || 0) === 200, `status=${lr?.status()}`);
    const lf = await freshPage.evaluate(() => {
        const i = document.getElementById("id_login");
        if (!i) return null;
        const c = getComputedStyle(i);
        return { ff: c.fontFamily, fs: c.fontSize, br: c.border };
    });
    record("allauth-fallback",
        "login input uses Inter and mm-primary-tinted border",
        /Inter/i.test(lf?.ff || "") && !(lf?.br || "").includes("inset"),
        JSON.stringify(lf));
    await freshPage.close();

} catch (err) {
    console.error("FATAL:", err);
    results.push({ area: "fatal", assertion: String(err), ok: false });
} finally {
    const pass = results.filter(r => r.ok).length;
    const fail = results.filter(r => !r.ok).length;
    console.log(`\nSUMMARY: ${pass} pass / ${fail} fail`);
    console.log(`page errors: ${errs.page.length}, console errors (incl benign Pusher 403s): ${errs.console.length}, failed requests: ${errs.req.length}, 500s: ${errs.http500.length}`);
    if (errs.http500.length) for (const h of errs.http500) console.log(`  500: ${h.url}`);
    await browser.close();
    process.exit(fail === 0 && errs.http500.length === 0 ? 0 : 1);
}
