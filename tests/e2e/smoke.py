"""Browser smoke test (Playwright). Needs a running server, e.g. the fixture from make_fixture.py:
  MULETRACE_URL=http://127.0.0.1:8003 MULETRACE_TOKEN=... python tests/e2e/smoke.py [screenshot_dir]
"""
import os, sys
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get("MULETRACE_URL", "http://127.0.0.1:8000")
TOKEN = os.environ["MULETRACE_TOKEN"]
OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots"
os.makedirs(OUT, exist_ok=True)
errors = []

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{URL}/?token={TOKEN}#live")
    expect(page.locator("#mode")).to_have_text("● LIVE", timeout=15000)
    expect(page.locator("#machine")).not_to_have_text("machine: –")
    page.click("#speed button[data-v='200']")
    page.click("#startBtn")
    expect(page.locator("#feed tr[data-alert]").first).to_be_visible(timeout=30000)
    page.wait_for_timeout(2500)
    page.screenshot(path=f"{OUT}/live-1440.png", full_page=True)
    page.click("#stopBtn")
    print("live: stream ran, flagged rows visible")

    page.click("#nav button[data-p='cases']")
    page.locator("#list .alert.HOLD, #list .alert.FLAG").first.click()
    expect(page.locator("#case")).to_be_visible()
    expect(page.locator("#graph canvas")).to_be_visible(timeout=10000)
    expect(page.locator("#cRec")).to_contain_text("simulated")
    expect(page.locator("#cAudit")).to_contain_text("created")
    page.click("#cActions button[data-a='confirm']")                 # note is required for Confirm
    expect(page.locator("#noteErr")).to_contain_text("Add a note")
    page.fill("#analyst", "e2e-analyst")
    page.fill("#cNote", "Fan-in ring, forwarded within minutes")
    page.click("#cActions button[data-a='confirm']")
    expect(page.locator("#cAudit")).to_contain_text("confirm by e2e-analyst", timeout=10000)
    page.wait_for_timeout(500)
    page.screenshot(path=f"{OUT}/case-1440.png", full_page=True)
    page.keyboard.press("Escape")
    expect(page.locator("#case")).to_be_hidden()
    print("cases: graph rendered, note enforced, confirm recorded in audit, Esc closes")

    page.click("#nav button[data-p='evidence']")
    expect(page.locator("#evBody table").first).to_be_visible(timeout=10000)
    expect(page.locator("#evBody")).to_contain_text("network-only ablation")
    page.screenshot(path=f"{OUT}/evidence-1440.png", full_page=True)
    page.click("#nav button[data-p='system']")
    expect(page.locator("#sysKv")).to_contain_text("s390x", timeout=10000)
    page.screenshot(path=f"{OUT}/system-1440.png", full_page=True)
    print("evidence + system pages loaded")

    m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    m.on("console", lambda msg: msg.type == "error" and errors.append(msg.text))
    m.on("pageerror", lambda e: errors.append(str(e)))
    for name in ("live", "cases", "evidence", "system"):
        m.goto(f"{URL}/?token={TOKEN}#{name}")
        expect(m.locator("#mode")).to_have_text("● LIVE", timeout=15000)
        m.wait_for_timeout(1200)
        if name == "cases":
            m.locator("#list .alert").first.click()
            m.wait_for_timeout(1200)
        overflow = m.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, f"{name}: horizontal overflow {overflow}px at 390px"
        m.screenshot(path=f"{OUT}/{name}-390.png", full_page=True)
    print("390px: no horizontal scroll on live/cases/evidence/system")
    b.close()

assert not errors, "console errors: " + " | ".join(errors)
print("SMOKE PASS: no console errors")
