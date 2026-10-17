"""Judge mode in the browser (server started with MULETRACE_PUBLIC_DEMO=1), no token:
  MULETRACE_URL=http://127.0.0.1:8001 python tests/e2e/e2e_public.py
"""
import os, sys
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get("MULETRACE_URL", "http://127.0.0.1:8100")
errors, n = [], 0
def ok(m):
    global n; n += 1; print("PASS", m, flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: m.type == "error" and errors.append(m.text)); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{URL}/#live"); expect(page.locator("#mode")).to_have_text("● LIVE", timeout=20000)
    expect(page.locator("#pubBar")).to_be_visible(); expect(page.locator("#pubBar")).to_contain_text("synthetic IBM AML data")
    expect(page.locator("#banner")).to_be_hidden()
    ok("public banner shown; no token prompt")
    expect(page.locator("#speed button[data-v='200']")).to_be_disabled()
    page.click("#speed button[data-v='100']"); page.click("#startBtn")
    expect(page.locator("#replayInfo")).to_contain_text("Streaming", timeout=10000)
    expect(page.locator("#strip button").first).to_be_visible(timeout=60000); page.wait_for_timeout(6000)
    ok("stream capped at 100/s and running without a token")
    page.click("#nav button[data-p='score']"); expect(page.locator("#scoreBtn")).to_be_disabled()
    expect(page.locator("#scoreOut")).to_contain_text("disabled in the public demo")
    ok("single-payment scoring disabled for the public")
    page.click("#nav button[data-p='cases']"); page.click("#bestRing")
    expect(page.locator("#toast")).to_contain_text("counterparties", timeout=60000)
    page.fill("#cNote", "public demo check"); page.click("#cActions button[data-a='escalate']")
    expect(page.locator("#cAudit")).to_contain_text("escalate by", timeout=10000)
    ok("Best ring + analyst action recorded in the demo audit log")
    page.click("#stopBtn") if page.is_visible("#stopBtn") else None
    page.click("#pubReset"); expect(page.locator("#toast")).to_contain_text("Demo reset", timeout=60000)
    page.click("#nav button[data-p='cases']"); page.wait_for_timeout(1500)
    assert page.locator("#list .alert").count() == 0
    mark = len(errors); page.click("#pubReset"); expect(page.locator("#toast")).to_contain_text("reset recently", timeout=10000)
    errors[mark:] = [e for e in errors[mark:] if "status of 429" not in e]        # expected throttle answer
    ok("Reset demo empties the queue; a second reset within 10 min is refused")
    burst = os.environ.get("MULETRACE_BURST_CMD")   # e.g. ssh to the VM and curl /health 200x on loopback
    if burst:                                         # a browser behind a slow tunnel cannot outrun the 15/s refill
        import collections, subprocess
        out = subprocess.run(burst, shell=True, capture_output=True, text=True, timeout=300).stdout.split()
        c = collections.Counter(out); assert c.get("429", 0) > 0, f"no rate limiting observed: {dict(c)}"
        ok(f"per-IP rate limit (server-side burst): {dict(c)}")
    else:
        print("SKIP rate-limit burst (set MULETRACE_BURST_CMD)")
    b.close()
assert not errors, "console errors: " + " | ".join(errors[:5])
print(f"PUBLIC E2E PASS ({n} checks)")
