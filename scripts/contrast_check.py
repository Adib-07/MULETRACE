"""WCAG 2.x contrast ratios for the console palette, read from the :root tokens in web/index.html.
Run: python scripts/contrast_check.py   -> prints a table, writes eval/contrast.json, exits 1 if any pair < 4.5:1."""
import json, re, sys

css = open("web/index.html").read()
root = css[css.index(":root{"):css.index("}", css.index(":root{"))]
tok = dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{6})", root))
tok.update({"white": "#ffffff", "confirm": "#b91c1c", "escalate": "#b45309", "dismiss": "#475569"})

def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

def ratio(fg, bg):
    a, b = sorted((lum(tok[fg]), lum(tok[bg])), reverse=True)
    return round((a + 0.05) / (b + 0.05), 2)

PAIRS = [(t, b) for t in ("text", "mute", "faint", "pass", "flag", "hold", "blue") for b in ("bg", "panel", "panel2")] + [
    ("pass", "pass-bg"), ("white", "hold-bg"), ("flag-ink", "flag"), ("white", "blue-strong"),
    ("white", "confirm"), ("white", "escalate"), ("white", "dismiss"), ("focus", "bg"), ("focus", "panel")]
rows = [{"fg": f, "bg": b, "fg_hex": tok[f], "bg_hex": tok[b], "ratio": ratio(f, b), "aa_normal_text": ratio(f, b) >= 4.5} for f, b in PAIRS]
json.dump({"standard": "WCAG 2.x contrast ratio, AA normal text >= 4.5", "pairs": rows}, open("eval/contrast.json", "w"), indent=1)
for r in rows:
    print(f"{r['fg']:>10} on {r['bg']:<11} {r['fg_hex']} / {r['bg_hex']}  {r['ratio']:>5}:1  {'AA' if r['aa_normal_text'] else 'FAIL'}")
fails = [r for r in rows if not r["aa_normal_text"]]
print(f"{len(rows) - len(fails)}/{len(rows)} pairs pass AA (4.5:1); min {min(r['ratio'] for r in rows)}:1")
sys.exit(1 if fails else 0)
