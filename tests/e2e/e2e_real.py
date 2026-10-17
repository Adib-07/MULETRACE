"""End-to-end test against a real MuleTrace server (real model + real data), e.g. through an SSH tunnel:
  MULETRACE_URL=http://127.0.0.1:8001 MULETRACE_TOKEN=... python tests/e2e/e2e_real.py [screenshot_dir]
Covers: overview live numbers, start investigation, tour, best ring, node expansion, keyboard-only decision,
audit, evidence, system, back/forward, keyboard nav, 390px layout, token not kept in the URL, zero console errors.
"""
import os, subprocess, sys, time
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get("MULETRACE_URL", "http://127.0.0.1:8000")
TOKEN = os.environ["MULETRACE_TOKEN"]
OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots"
os.makedirs(OUT, exist_ok=True)
errors, results = [], []

def ok(msg):
    results.append(msg); print("PASS", msg, flush=True)

def watch(pg):
    pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
    pg.on("pageerror", lambda e: errors.append(str(e)))

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900}); watch(page)
    page.goto(f"{URL}/?token={TOKEN}")
    expect(page.locator("#mode")).to_have_text("● LIVE", timeout=20000)
    assert TOKEN not in page.url, "token left in the URL"
    ok("token removed from the URL after load")
    expect(page.locator("#p-overview")).to_be_visible()
    expect(page.locator("#ovStrip")).to_contain_text("s390x", timeout=10000)
    expect(page.locator("#ovAcc")).not_to_have_text("–", timeout=10000)
    acc = int(page.inner_text("#ovAcc").replace(",", ""))
    assert acc > 0
    page.wait_for_timeout(600)
    page.screenshot(path=f"{OUT}/overview-1440.png", full_page=True)
    ok(f"overview: live numbers ({acc:,} accounts tracked), platform strip shows s390x")

    page.click("#ovStart")
    expect(page.locator("#p-live")).to_be_visible(timeout=10000)
    expect(page.locator("#replayInfo")).to_contain_text("Streaming", timeout=10000)
    ok("Start live investigation: stream running, Live page shown")

    page.click("#nav button[data-p='overview']"); page.click("#ovTour")
    for i in range(5):
        expect(page.locator("#tourTip")).to_be_visible()
        expect(page.locator("#tourStep")).to_have_text(f"{i + 1} / 5")
        page.keyboard.press("Enter")            # Next/Finish has focus: keyboard-only tour
    expect(page.locator("#tourTip")).to_be_hidden()
    assert page.evaluate("sessionStorage.getItem('mtTour')") == "done"
    ok("tour: 5 steps completed by keyboard, completion stored in sessionStorage")

    page.click("#nav button[data-p='live']")
    expect(page.locator("#strip button").first).to_be_visible(timeout=60000)
    page.wait_for_timeout(8000)                 # let the stream build some rings
    page.screenshot(path=f"{OUT}/live-1440.png", full_page=True)
    page.click("#nav button[data-p='cases']")
    page.click("#bestRing")
    expect(page.locator("#toast")).to_contain_text("counterparties", timeout=60000)
    expect(page.locator("#graph canvas")).to_be_visible(timeout=10000)
    page.wait_for_timeout(1500)
    ok("best ring: " + page.inner_text("#toast"))

    n0 = page.evaluate("gLevel.size")
    cands = page.evaluate("""async () => {     // nodes whose own flows include accounts not yet on the graph
        const ids = [...gLevel.keys()].filter(k => k !== gCase.src && k !== gCase.dst), out = [];
        for(const id of ids){ const g = await api(`/graph/${encodeURIComponent(id)}?limit=10`);
          const fresh = new Set(g.edges.flatMap(e => [e.from, e.to]).filter(x => x !== id && !gLevel.has(x)));
          if(fresh.size) out.push([fresh.size, id]); }
        return out.sort((a, b) => b[0] - a[0]).map(x => x[1]); }""")
    assert cands, "no node on this case has unseen counterparties in the last hour"
    grown = False
    for cid in cands[:2]:                        # real mouse click on the node's canvas position
        x, y = page.evaluate("id => { const p = network.canvasToDOM(network.getPositions([id])[id]); return [p.x, p.y]; }", cid)
        box = page.locator("#graph").bounding_box()
        page.mouse.click(box["x"] + x, box["y"] + y)
        expect(page.locator("#gInfo")).to_contain_text("Expanded", timeout=10000)
        page.wait_for_timeout(500)
        if page.evaluate("gLevel.size") > n0:
            grown = True; break
    n1 = page.evaluate("gLevel.size")
    assert grown, f"node expansion added no accounts ({n0} -> {n1})"
    ok(f"graph: clicked node expanded, accounts {n0} -> {n1}")

    expect(page.locator("#cNet li").first).to_be_visible()
    assert "Not available" not in page.inner_text("#cNet") + page.inner_text("#cPay")
    assert page.evaluate("document.getElementById('cNet').compareDocumentPosition(document.getElementById('cPay')) & 4"), "network signals must come before payment context"
    assert page.locator("#cPay").evaluate("el => el.previousElementSibling.textContent").startswith("Payment context")
    ok(f"explanations: {page.locator('#cNet li').count()} network signals listed before {page.locator('#cPay li').count()} payment-context items")
    case_id = page.evaluate("selected.id")
    page.focus("#cNote"); page.keyboard.type("e2e: fan-in then fast forwarding, checked graph")
    page.keyboard.press("Tab")                   # -> Confirm laundering
    assert page.evaluate("document.activeElement.dataset.a") == "confirm"
    page.fill("#analyst", "e2e-real"); page.focus("#cActions button[data-a='confirm']")
    page.keyboard.press("Enter")
    expect(page.locator("#cAudit")).to_contain_text("confirm by e2e-real", timeout=10000)
    page.wait_for_timeout(800)
    page.screenshot(path=f"{OUT}/case-1440.png", full_page=False)
    ok("decision by keyboard: confirm with note -> audit entry visible")
    page.keyboard.press("Escape")
    expect(page.locator("#case")).to_be_hidden()

    page.focus("#nav button[data-p='overview']")
    order = []
    for _ in range(5):
        page.keyboard.press("Tab"); order.append(page.evaluate("document.activeElement.dataset.p || ''"))
    assert order == ["live", "cases", "score", "evidence", "system"], order
    page.keyboard.press("Shift+Tab"); page.keyboard.press("Enter")
    expect(page.locator("#p-evidence")).to_be_visible()
    expect(page.locator("#evBody")).to_contain_text("Headline (conservative)", timeout=10000)
    page.screenshot(path=f"{OUT}/evidence-1440.png", full_page=True)
    page.focus("#nav button[data-p='system']"); page.keyboard.press("Enter")
    expect(page.locator("#trust")).to_contain_text("Verified on this machine", timeout=10000)
    expect(page.locator("#trust")).to_contain_text("Simulated")
    expect(page.locator("#trust")).to_contain_text("Measured on Telum II")
    expect(page.locator("#trust")).to_contain_text("no speed-up")
    page.screenshot(path=f"{OUT}/system-1440.png", full_page=True)
    ok("keyboard nav order correct; Evidence and System (Trust panel) render")

    page.go_back(); expect(page.locator("#p-evidence")).to_be_visible(timeout=5000)
    page.go_forward(); expect(page.locator("#p-system")).to_be_visible(timeout=5000)
    ok("back/forward switch pages")

    anon = b.new_context().new_page()                        # no token: account data hidden, prompt shown
    anon.goto(f"{URL}/#cases"); expect(anon.locator("#tokIn")).to_be_visible(timeout=15000)
    expect(anon.locator("#mode")).to_have_text("● LIVE")
    assert anon.locator("#list .alert").count() == 0 and anon.get_attribute("#list", "role") is None
    anon.close()
    ok("without token: Cases shows the token prompt, no account data, no empty listbox role")

    m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2); watch(m)
    for name in ("overview", "live", "cases", "evidence", "system"):
        m.goto(f"{URL}/?token={TOKEN}#{name}")
        expect(m.locator("#mode")).to_have_text("● LIVE", timeout=20000)
        m.wait_for_timeout(1200)
        if name == "cases":
            m.locator("#list .alert").first.click(); m.wait_for_timeout(1500)
        over = m.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert over <= 0, f"{name}: {over}px horizontal overflow at 390px"
        m.screenshot(path=f"{OUT}/{name}-390.png", full_page=True)
    ok("390px: no horizontal scroll on overview/live/cases/evidence/system")

    H = {"X-MuleTrace-Token": TOKEN}
    page.request.post(f"{URL}/replay/stop", headers={**H, "Content-Type": "application/json"}, data="{}")
    restart = os.environ.get("MULETRACE_RESTART_CMD")        # restarts the server keeping alerts.db
    if restart:
        audit_before = page.request.get(f"{URL}/alerts/{case_id}/audit", headers=H).json()
        mark = len(errors)
        subprocess.run(restart, shell=True, check=True, stdout=subprocess.DEVNULL)
        for _ in range(60):
            try:
                if page.request.get(f"{URL}/health").ok: break
            except Exception: pass
            time.sleep(1)
        assert page.request.get(f"{URL}/health").json()["uptime_s"] < 60, "server did not restart"
        page.wait_for_timeout(2500)              # open pages poll while the server is deliberately down
        down = [e for e in errors[mark:] if "net::ERR_CONNECTION" in e]
        errors[mark:] = [e for e in errors[mark:] if "net::ERR_CONNECTION" not in e]
        print(f"note: ignored {len(down)} connection errors raised during the intentional restart", flush=True)
        assert page.request.get(f"{URL}/alerts/{case_id}", headers=H).json()["status"] == "confirm"
        assert page.request.get(f"{URL}/alerts/{case_id}/audit", headers=H).json() == audit_before
        page.goto(f"{URL}/#cases"); expect(page.locator("#mode")).to_have_text("● LIVE", timeout=20000)
        page.click("#fStatus button[data-v='confirm']")
        page.locator(f"#list .alert[data-id='{case_id}']").click()
        expect(page.locator("#cAudit")).to_contain_text("confirm by e2e-real", timeout=10000)
        page.screenshot(path=f"{OUT}/case-after-restart-1440.png")
        ok(f"restart: case #{case_id} still 'confirm', audit trail identical ({len(audit_before)} entries), visible in UI")
    else:
        print("SKIP restart persistence (set MULETRACE_RESTART_CMD)")
    b.close()

assert not errors, "console errors: " + " | ".join(errors)
ok("zero console errors")
print(f"E2E PASS ({len(results)} checks)")
