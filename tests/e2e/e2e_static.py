"""Static build (GitHub Pages fallback): serve the repo root with any static server, e.g.
  python -m http.server 8765   then   MULETRACE_STATIC_URL=http://127.0.0.1:8765/web/?static=1 python tests/e2e/e2e_static.py
"""
import os
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get("MULETRACE_STATIC_URL", "http://127.0.0.1:8765/web/?static=1")
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: m.type == "error" and errors.append(m.text)); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL)
    expect(page.locator("#banner")).to_contain_text("MOCKED — recorded from the LinuxONE run", timeout=10000)
    expect(page.locator("#mode")).to_contain_text("DEMO"); assert page.locator("#bLive").count() == 0
    expect(page.locator("#ovStrip")).to_contain_text("conservative PR-AUC", timeout=10000)
    page.click("#nav button[data-p='live']"); expect(page.locator("#startBtn")).to_be_disabled()
    page.click("#nav button[data-p='evidence']")
    for t in ("Headline (conservative)", "All models on the test set", "Time to detect", "Latency"):
        expect(page.locator("#evBody")).to_contain_text(t, timeout=10000)
    expect(page.locator("#evSub")).to_contain_text("MOCKED page")
    page.click("#nav button[data-p='cases']"); expect(page.locator("#list .alert").first).to_be_visible()
    page.locator("#list .alert").first.click(); expect(page.locator("#cActions button").first).to_be_disabled()
    page.screenshot(path="docs/screenshots/static-demo-1440.png", full_page=True)
    b.close()
assert not errors, "console errors: " + " | ".join(errors[:5])
print("STATIC E2E PASS: MOCKED banner, no live claims, evidence from eval/ files, actions disabled")
