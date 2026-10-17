"""Token flow in the browser and on every protected endpoint (real server):
  MULETRACE_URL=http://127.0.0.1:8001 MULETRACE_TOKEN=... python tests/e2e/e2e_auth.py
(a) no token -> one banner, protected polling paused; (b) wrong token -> 'rejected', not stored; (c) correct token,
pasted as the whole env line -> Cases loads without a page reload; (d) refresh keeps working; (e) all pages, no 401s;
(f) every protected read/write endpoint 401 without token, 2xx with it; token never left in the URL; forget/change.
"""
import os, json
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get("MULETRACE_URL", "http://127.0.0.1:8000")
TOKEN = os.environ["MULETRACE_TOKEN"]
H = {"X-MuleTrace-Token": TOKEN, "Content-Type": "application/json"}
n = 0
def ok(msg):
    global n; n += 1; print("PASS", msg, flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(); page = ctx.new_page()
    errors, calls = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: calls.append(r.url) if "/recent" in r.url or "/alerts" in r.url else None)

    # (f) API: protected endpoints, without and with the token
    rq = page.request
    rq.post(f"{URL}/replay/start", headers=H, data=json.dumps({"n": 400, "speed": 500}))
    page.wait_for_timeout(2500); rq.post(f"{URL}/replay/stop", headers=H, data="{}")
    aid = rq.get(f"{URL}/alerts?status=all&limit=1", headers=H).json()[0]["id"]
    reads = ["/alerts", f"/alerts/{aid}", f"/alerts/{aid}/audit", "/graph/070_1004286A8", "/recent"]
    writes = [("/score", {"src": "AUTH_A", "dst": "AUTH_B", "amount": 10}), (f"/alerts/{aid}/action", {"action": "escalate", "note": "auth e2e", "analyst": "e2e"}),
              ("/replay/start", {"n": 1, "speed": 50}), ("/replay/stop", {})]
    for path in reads:
        assert rq.get(URL + path).status == 401 and rq.get(URL + path, headers={"X-MuleTrace-Token": "wrong"}).status == 401
        assert rq.get(URL + path, headers=H).status == 200, path
    for path, body in writes:
        assert rq.post(URL + path, headers={"Content-Type": "application/json"}, data=json.dumps(body)).status == 401
        r = rq.post(URL + path, headers=H, data=json.dumps(body)); assert r.status == 200, (path, r.status, r.text()[:120])
    for path in ("/health", "/system", "/stats", "/evidence"):
        assert rq.get(URL + path).status == 200
    ok(f"(f) {len(reads)} protected reads + {len(writes)} writes: 401 without/wrong token, 200 with; 4 public endpoints 200")

    # (a) no token
    page.goto(f"{URL}/#cases")
    expect(page.locator("#tokIn")).to_be_visible(timeout=15000)
    expect(page.locator("#list")).to_contain_text("API token is needed")
    page.wait_for_timeout(1500); before = len(calls); page.wait_for_timeout(6500)
    assert len(calls) == before, f"protected endpoints still polled while blocked ({len(calls) - before} calls)"
    ok("(a) no token: banner shown once, Cases explains the token, protected polling paused")

    # (b) wrong token
    page.fill("#tokIn", "definitely-not-the-token"); page.click("#tokBtn")
    expect(page.locator("#tokMsg")).to_contain_text("Token rejected", timeout=10000)
    assert page.evaluate("sessionStorage.getItem('mtToken')") is None
    ok("(b) wrong token: 'Token rejected — it may have been rotated', nothing stored")

    # (c) correct token pasted as the whole env line, no reload
    page.evaluate("window.__noReload = 1")
    page.fill("#tokIn", f"MULETRACE_TOKEN={TOKEN}\n"); page.click("#tokBtn")
    expect(page.locator("#banner")).to_be_hidden(timeout=10000)
    expect(page.locator("#list .alert").first).to_be_visible(timeout=5000)
    assert page.evaluate("window.__noReload") == 1, "page reloaded"
    assert page.evaluate("sessionStorage.getItem('mtToken')") == TOKEN
    ok("(c) correct token (pasted as env line) accepted; Cases loaded without a page reload")

    # (d) refresh
    page.reload(); expect(page.locator("#list .alert").first).to_be_visible(timeout=15000)
    expect(page.locator("#banner")).to_be_hidden()
    ok("(d) page refresh keeps working (token kept for this tab)")

    # (e) every page, no 401 banner
    for name in ("overview", "live", "cases", "score", "evidence", "system"):
        page.click(f"#nav button[data-p='{name}']"); page.wait_for_timeout(1200)
        expect(page.locator("#banner")).to_be_hidden()
    assert page.locator("#feed tr").count() > 0, "live feed (protected /recent) did not load"
    ok("(e) all six pages load with the token; no token banner")

    # token never left in the URL after load
    page.goto(f"{URL}/?token={TOKEN}#cases"); expect(page.locator("#mode")).to_have_text("● LIVE", timeout=15000)
    assert TOKEN not in page.url
    ok("token removed from the URL after load")

    # forget / change token
    page.click("#tokMenu summary"); page.click("#tokForget")
    expect(page.locator("#tokMsg")).to_contain_text("forgotten"); assert page.evaluate("sessionStorage.getItem('mtToken')") is None
    expect(page.locator("#list")).to_contain_text("API token is needed", timeout=5000)
    page.fill("#tokIn", TOKEN); page.keyboard.press("Enter")
    expect(page.locator("#list .alert").first).to_be_visible(timeout=10000)
    page.click("#tokMenu summary"); page.click("#tokChange")
    expect(page.locator("#tokMsg")).to_contain_text("new token"); page.fill("#tokIn", "rotated-old"); page.click("#tokBtn")
    expect(page.locator("#tokMsg")).to_contain_text("Token rejected", timeout=10000)
    assert page.evaluate("sessionStorage.getItem('mtToken')") == TOKEN          # a rejected change keeps the working token
    ok("Forget token clears it; Enter submits; Change token rejects a bad value and keeps the working one")
    b.close()

assert not errors, "page errors: " + " | ".join(errors)
print(f"AUTH E2E PASS ({n} checks)")
