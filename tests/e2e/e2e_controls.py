"""Click-through of every console control against a real server (complements e2e_real.py / e2e_auth.py):
  MULETRACE_URL=http://127.0.0.1:8001 MULETRACE_TOKEN=... python tests/e2e/e2e_controls.py
Collects failures instead of stopping at the first one, so one run lists every defect.
"""
import os, re
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get("MULETRACE_URL", "http://127.0.0.1:8000")
TOKEN = os.environ["MULETRACE_TOKEN"]
fails, passes, errors = [], [], []

def check(name, fn):
    try:
        fn(); passes.append(name); print("PASS", name, flush=True)
    except Exception as e:
        fails.append(f"{name}: {str(e).splitlines()[0][:200]}"); print("FAIL", name, "-", str(e).splitlines()[0][:200], flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: m.type == "error" and errors.append(m.text)); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{URL}/?token={TOKEN}#live"); expect(page.locator("#mode")).to_have_text("● LIVE", timeout=20000)

    def speed():
        for v in ("20", "100", "200", "50"):
            page.click(f"#speed button[data-v='{v}']")
            assert page.get_attribute(f"#speed button[data-v='{v}']", "aria-pressed") == "true"
        assert page.locator("#speed [aria-pressed='true']").count() == 1
    check("live: speed selector is single-select", speed)

    def stream():
        page.click("#speed button[data-v='200']"); page.click("#startBtn")
        expect(page.locator("#replayInfo")).to_contain_text("Streaming", timeout=10000)
        expect(page.locator("#stopBtn")).to_be_enabled(); expect(page.locator("#startBtn")).to_be_disabled()
        page.wait_for_timeout(9000)
    check("live: start enables stop, disables start", stream)

    def only_flag():
        page.check("#onlyFlag"); page.mouse.move(5, 5); page.wait_for_timeout(2600)
        badges = page.locator("#feed td:first-child").all_inner_texts()
        assert badges and all("PASS" not in t for t in badges), badges[:5]
        page.uncheck("#onlyFlag"); page.wait_for_timeout(2600)
        assert any("PASS" in t for t in page.locator("#feed td:first-child").all_inner_texts())
    check("live: 'FLAG/HOLD only' filters the feed and restores it", only_flag)

    def stop():
        page.click("#stopBtn"); expect(page.locator("#replayInfo")).to_contain_text("Stopped", timeout=10000)
        expect(page.locator("#startBtn")).to_be_enabled()
    check("live: stop", stop)

    page.click("#nav button[data-p='cases']"); expect(page.locator("#list .alert").first).to_be_visible(timeout=15000)

    def dec_filters():
        for v in ("HOLD", "FLAG"):
            page.click(f"#fDec button[data-v='{v}']"); page.wait_for_timeout(6500)   # spans a background refresh (race regression)
            cards = page.locator("#list .alert")
            assert cards.count() == 0 or all(v in c for c in cards.all_inner_texts()), v
        page.click("#fDec button[data-v='all']")
    check("cases: decision filters show only HOLD / FLAG", dec_filters)

    def sorts():
        page.select_option("#fSort", "time"); page.wait_for_timeout(1200)
        ts = page.evaluate("alerts.map(a => a.ts)"); assert ts == sorted(ts, reverse=True), "time sort"
        page.select_option("#fSort", "risk"); page.wait_for_timeout(1200)
        sc = page.evaluate("alerts.map(a => a.score)"); assert sc == sorted(sc, reverse=True), "risk sort"
    check("cases: sort by newest / highest risk", sorts)

    def case_tools():
        page.locator("#list .alert").first.click(); expect(page.locator("#graph canvas")).to_be_visible(timeout=10000)
        page.click("#fitBtn"); page.click("#resetBtn"); page.wait_for_timeout(1500)
        expect(page.locator("#graph canvas")).to_be_visible()
        page.hover("#graph"); page.click("#closeCase"); expect(page.locator("#case")).to_be_hidden()
    check("cases: open, Fit, Reset view, close button", case_tools)

    def note_rules():
        page.locator("#list .alert").first.click(); expect(page.locator("#case")).to_be_visible()
        page.fill("#cNote", ""); page.click("#cActions button[data-a='escalate']")
        expect(page.locator("#noteErr")).to_contain_text("Add a note")
        page.click("#cActions button[data-a='dismiss']")               # dismiss needs no note
        expect(page.locator("#cAudit")).to_contain_text("dismiss by", timeout=10000)
    check("cases: Escalate requires a note, Dismiss does not; audit updated", note_rules)

    def status_filters():
        for v in ("dismiss", "confirm", "escalate", "all", "open"):
            page.click(f"#fStatus button[data-v='{v}']"); page.wait_for_timeout(1000)
            assert "Could not load" not in page.inner_text("#list"), v
        page.click("#fStatus button[data-v='dismiss']"); page.wait_for_timeout(1000)
        assert page.locator("#list .alert").count() >= 1, "dismissed case not listed"
        page.click("#fStatus button[data-v='open']")
    check("cases: every status filter loads; dismissed case appears under Dismissed", status_filters)

    page.click("#nav button[data-p='score']")
    def score_examples():
        page.click("#exNormal"); assert page.input_value("#fSrc") == "0118_8000C6C40"
        page.click("#exHub"); assert page.input_value("#fSrc") == "070_1004286A8"
        page.fill("#fTs", ""); page.click("#scoreBtn")
        expect(page.locator("#scoreOut .result")).to_be_visible(timeout=10000)
        assert re.search(r"(PASS|FLAG|HOLD)", page.inner_text("#scoreOut"))
        assert "SIMULATED" in page.inner_text("#scoreOut")
    check("score: examples fill the form; scoring returns a decision with simulated label", score_examples)

    def score_invalid():
        page.fill("#fAmt", "-5"); page.click("#scoreBtn"); expect(page.locator("#e-amount")).to_contain_text("above 0")
        page.fill("#fAmt", "10"); page.fill("#fTs", "yesterday"); page.click("#scoreBtn"); expect(page.locator("#e-ts")).to_contain_text("YYYY")
        mark = len(errors)
        page.fill("#fTs", "2022-01-01 00:00"); page.click("#scoreBtn")          # valid format, but earlier than the stream
        expect(page.locator("#scoreOut")).to_contain_text("earlier than the latest", timeout=10000)
        errors[mark:] = [e for e in errors[mark:] if "status of 409" not in e]  # the 409 is the expected answer here
        page.fill("#fSrc", "bad id!"); page.fill("#fTs", ""); page.click("#scoreBtn"); expect(page.locator("#e-src")).to_contain_text("Letters")
        page.click("#exNormal")
    check("score: client and server validation messages", score_invalid)

    def tour():
        page.click("#nav button[data-p='overview']"); page.click("#ovTour")
        expect(page.locator("#tourStep")).to_have_text("1 / 5"); page.click("#tourNext"); expect(page.locator("#tourStep")).to_have_text("2 / 5")
        page.click("#tourBack"); expect(page.locator("#tourStep")).to_have_text("1 / 5")
        page.click("#tourSkip"); expect(page.locator("#tourTip")).to_be_hidden()
        page.click("#nav button[data-p='overview']"); page.click("#ovTour"); page.keyboard.press("Escape"); expect(page.locator("#tourTip")).to_be_hidden()
    check("tour: Next, Back, Skip, Esc", tour)

    def evidence():
        page.click("#nav button[data-p='evidence']")
        for t in ("Headline (conservative)", "All models on the test set", "per test day", "Time to detect", "Latency", "Limits"):
            expect(page.locator("#evBody")).to_contain_text(t, timeout=10000)
    check("evidence: every section renders from eval files", evidence)

    def system():
        page.click("#nav button[data-p='system']")
        for t in ("Verified on this machine", "Measured on Telum II", "Simulated", "s390x"):
            expect(page.locator("#p-system")).to_contain_text(t, timeout=10000)
    check("system: machine cards + three Trust panel columns", system)

    def demo():
        d = b.new_page(); d.on("pageerror", lambda e: errors.append(str(e)))
        d.goto(f"{URL}/?demo=1#live"); expect(d.locator("#banner")).to_contain_text("DEMO MODE")
        expect(d.locator("#startBtn")).to_be_disabled(); expect(d.locator("#mode")).to_contain_text("DEMO")
        d.click("#nav button[data-p='evidence']"); expect(d.locator("#evBody")).to_contain_text("not available in demo mode")
        d.click("#bLive"); expect(d.locator("#mode")).to_have_text("● LIVE", timeout=15000); d.close()
    check("demo mode: labelled, actions disabled, no metrics, 'Try live API' returns to live", demo)
    b.close()

if errors: fails.append("console errors: " + " | ".join(errors[:5]))
print(f"\nCONTROLS: {len(passes)} passed, {len(fails)} failed")
for f in fails: print(" -", f)
raise SystemExit(1 if fails else 0)
