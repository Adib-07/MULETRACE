"""Detection delay on IBM's labelled laundering attempts (HI-Small_Patterns.txt), test period only.

For every attempt whose first payment falls inside the test window, find its payments in data/test.pkl
(matched on minute, sender, receiver, amount paid and format among laundering rows), score them with model C
(same features as the live stream), and measure stream-time minutes from the attempt's first payment to the
first FLAG/HOLD on any of its payments. Run on the VM from the repo root:
    python bench/detection_delay.py            -> eval/detection_delay.json
"""
import json, os, sys, time
import numpy as np, pandas as pd
import xgboost as xgb

PAT = "data/HI-Small_Patterns.txt"
meta = json.load(open("models/meta.json"))
FEATS, FLAG, HOLD = meta["features"], meta["flag_threshold"], meta["hold_threshold"]

attempts, cur = [], None
for line in open(PAT):
    line = line.strip()
    if line.startswith("BEGIN LAUNDERING ATTEMPT"):
        kind = line.split(" - ", 1)[1].split(":")[0].strip()
        cur = {"type": kind, "txns": []}
    elif line.startswith("END LAUNDERING ATTEMPT"):
        attempts.append(cur); cur = None
    elif cur is not None and line:
        f = line.split(",")
        cur["txns"].append((pd.Timestamp(f[0].replace("/", "-")), f[1] + "_" + f[2], f[3] + "_" + f[4], round(float(f[7]), 2), f[9]))

test = pd.read_pickle("data/test.pkl")
feat = pd.read_pickle("data/feat_test.pkl")
assert (feat.txn_id.values == test.txn_id.values).all(), "feature rows do not line up with test rows"
model = xgb.XGBClassifier(); model.load_model("models/model_c.json")
p = model.predict_proba(feat[FEATS])[:, 1]
test = test.assign(p=p, key=list(zip(test.ts, test.src, test.dst, test.amount.round(2), test.fmt)))
t_lo, t_hi = test.ts.min(), test.ts.max()
pos = test[test.label == 1]
index = {}
for i, k in zip(pos.index, pos.key):
    index.setdefault(k, []).append(i)

rows, unmatched, in_window_txns, used = [], 0, 0, set()
for a in attempts:
    first = min(t[0] for t in a["txns"])
    if not (t_lo <= first <= t_hi):
        continue
    hits = []
    for t in a["txns"]:
        if not (t_lo <= t[0] <= t_hi):
            continue
        in_window_txns += 1
        cand = [i for i in index.get(t, []) if i not in used]
        if not cand:
            unmatched += 1; continue
        used.add(cand[0]); hits.append(cand[0])
    flagged = sorted((test.at[i, "ts"], test.at[i, "p"]) for i in hits if test.at[i, "p"] >= FLAG)
    rows.append({"type": a["type"], "payments_in_window": sum(t_lo <= t[0] <= t_hi for t in a["txns"]),
                 "matched": len(hits), "detected": bool(flagged), "hold": any(pp >= HOLD for _, pp in flagged),
                 "delay_min": round((flagged[0][0] - first).total_seconds() / 60, 1) if flagged else None})

d = [r["delay_min"] for r in rows if r["detected"]]
by_type = {}
for r in rows:
    t = by_type.setdefault(r["type"].split(" ")[0] if r["type"].startswith(("FAN", "SCATTER", "STACK", "BIPARTITE", "CYCLE", "GATHER", "RANDOM")) else r["type"], [0, 0])
    t[0] += 1; t[1] += r["detected"]
match_rate = 1 - unmatched / max(in_window_txns, 1)
out = {
    "created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "model": "C (models/model_c.json)",
    "thresholds": {"flag": FLAG, "hold": HOLD},
    "test_window": [str(t_lo), str(t_hi)],
    "attempts_in_test_window": len(rows),
    "attempts_detected": sum(r["detected"] for r in rows),
    "detected_pct": round(100 * sum(r["detected"] for r in rows) / max(len(rows), 1), 1),
    "attempts_with_hold": sum(r["hold"] for r in rows),
    "delay_minutes": {"median": float(np.median(d)) if d else None, "p75": float(np.percentile(d, 75)) if d else None,
                      "p90": float(np.percentile(d, 90)) if d else None, "min": min(d) if d else None, "max": max(d) if d else None},
    "pattern_payments_in_window": in_window_txns, "pattern_payments_matched": in_window_txns - unmatched,
    "match_rate": round(match_rate, 4),
    "laundering_rows_in_test": int(len(pos)), "laundering_rows_covered_by_patterns": len(used),
    "by_type": {k: {"attempts": v[0], "detected": v[1]} for k, v in sorted(by_type.items())},
    "status": "VERIFIED" if match_rate >= 0.95 else "UNVERIFIED: fewer than 95% of pattern payments could be matched to test rows",
    "notes": ["Stream time with minute-resolution timestamps; a delay of 0 means the attempt was flagged in the minute it started.",
              "Delay is measured from the attempt's first payment, which may be earlier than its first flagged payment.",
              "Standard (file-order) model; the deployed model. Attempts starting before the test window are excluded.",
              "Not every laundering row in the data belongs to a listed pattern (IBM's patterns file lists the typed attempts)."],
}
json.dump(out, open("eval/detection_delay.json", "w"), indent=1)
print(json.dumps({k: out[k] for k in ("attempts_in_test_window", "attempts_detected", "detected_pct", "delay_minutes", "match_rate", "laundering_rows_covered_by_patterns", "laundering_rows_in_test", "status")}, indent=1))
