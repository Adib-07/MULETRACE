import json, os, platform, sys, time
import numpy as np, pandas as pd, xgboost as xgb
from sklearn.metrics import average_precision_score
sys.path.insert(0, ".")
from model.features import TXN_FEATURES, NET_FEATURES, ALL_FEATURES, rule_score

SUFFIX = sys.argv[1] if len(sys.argv) > 1 else ""   # "_shuf" = within-minute shuffle check (evaluation only)
BOOT = int(os.environ.get("MULETRACE_BOOT", "200"))  # bootstrap resamples for the PR-AUC 95% CI (0 = skip)
t_start = time.time()
tr = pd.read_pickle("data/feat_train" + SUFFIX + ".pkl")
va = pd.read_pickle("data/feat_valid" + SUFFIX + ".pkl")
te = pd.read_pickle("data/feat_test" + SUFFIX + ".pkl")
pos = tr[tr.label == 1]
neg = tr[tr.label == 0].sample(n=min(200000, (tr.label == 0).sum()), random_state=42)
trs = pd.concat([pos, neg])
REVIEW = 0.01  # send top 1% of payments to a human

def fit(cols):
    m = xgb.XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.1,
                          subsample=0.8, colsample_bytree=0.8, tree_method="hist",
                          scale_pos_weight=len(neg) / len(pos), n_jobs=3)
    m.fit(trs[cols], trs.label)
    return m

def evaluate(name, s_valid, s_test):
    thr = float(np.quantile(s_valid, 1 - REVIEW))   # threshold chosen on VALID only
    y = te.label.values
    pred = s_test >= thr
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    return {"model": name, "pr_auc": round(float(average_precision_score(y, s_test)), 4),
            "recall": round(tp / max(int(y.sum()), 1), 3),
            "precision": round(tp / max(tp + fp, 1), 3),
            "review_pct": round(100 * float(pred.mean()), 2),
            "fp_per_1000": round(1000 * fp / len(y), 2), "threshold": thr}

if not SUFFIX:
    os.makedirs("models", exist_ok=True)
mA = fit(TXN_FEATURES)
mC = fit(ALL_FEATURES)
mN = fit(NET_FEATURES)
rule = lambda d: d[ALL_FEATURES].apply(lambda r: rule_score(r), axis=1).values
scores = {  # name -> (validation scores, test scores)
    "A: transaction-only model": (mA.predict_proba(va[TXN_FEATURES])[:, 1], mA.predict_proba(te[TXN_FEATURES])[:, 1]),
    "B: simple rules": (rule(va), rule(te)),
    "C: MuleTrace network model": (mC.predict_proba(va[ALL_FEATURES])[:, 1], mC.predict_proba(te[ALL_FEATURES])[:, 1]),
    "N: network-only ablation": (mN.predict_proba(va[NET_FEATURES])[:, 1], mN.predict_proba(te[NET_FEATURES])[:, 1]),
}
res = [evaluate(name, sv_, st_) for name, (sv_, st_) in scores.items()]
sv = scores["C: MuleTrace network model"][0]
meta = {"flag_threshold": float(np.quantile(sv, 1 - REVIEW)),
        "hold_threshold": float(np.quantile(sv, 1 - REVIEW / 5)),
        "features": ALL_FEATURES}
if not SUFFIX:
    mA.save_model("models/model_a.json")
    mC.save_model("models/model_c.json")
    json.dump(meta, open("models/meta.json", "w"), indent=2)
json.dump(res, open("eval/metrics" + SUFFIX + ".json", "w"), indent=2)
print(pd.DataFrame(res).drop(columns="threshold").to_string(index=False))
imp = sorted(zip(ALL_FEATURES, mC.feature_importances_), key=lambda x: -x[1])[:8]
print("Top features (C):", [(k, round(float(v), 3)) for k, v in imp])

# ---------- extended evidence (eval/report*.json + eval/report*.md) ----------
y = te.label.values
day = pd.read_pickle("data/test.pkl")["ts"].dt.date.astype(str).values if os.path.exists("data/test.pkl") else None
rng = np.random.default_rng(42)
boot_idx = [rng.integers(0, len(y), len(y)) for _ in range(BOOT)]
report = {"created_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "machine": platform.machine(), "node": platform.node(),
          "python": platform.python_version(), "xgboost": xgb.__version__, "suffix": SUFFIX or None,
          "rows": {"train": len(tr), "valid": len(va), "test": len(te), "train_sample": len(trs)},
          "positives": {"train": int(tr.label.sum()), "valid": int(va.label.sum()), "test": int(y.sum())},
          "review_budget": REVIEW, "bootstrap_resamples": BOOT, "models": {}}
for name, (s_valid, s_test) in scores.items():
    thr_flag = float(np.quantile(s_valid, 1 - REVIEW))
    thr_hold = float(np.quantile(s_valid, 1 - REVIEW / 5))
    order = np.argsort(-s_test, kind="stable")
    r = {"pr_auc": round(float(average_precision_score(y, s_test)), 4)}
    if BOOT:
        b = [average_precision_score(y[i], s_test[i]) for i in boot_idx if y[i].any()]
        r["pr_auc_ci95"] = [round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]
    r["precision_at_k"] = {str(k): round(float(y[order[:k]].mean()), 4) for k in (100, 500, 1000) if k <= len(y)}
    r["recall_at_k"] = {str(k): round(float(y[order[:k]].sum() / max(y.sum(), 1)), 4) for k in (100, 500, 1000) if k <= len(y)}
    for tag, thr in (("flag", thr_flag), ("hold", thr_hold)):
        p = s_test >= thr
        r["confusion_at_" + tag] = {"threshold": round(thr, 6), "tp": int((p & (y == 1)).sum()), "fp": int((p & (y == 0)).sum()),
                                    "fn": int((~p & (y == 1)).sum()), "tn": int((~p & (y == 0)).sum())}
    if day is not None:
        r["per_day"] = []
        for d in sorted(set(day)):
            m = day == d
            p = s_test[m] >= thr_flag
            yd = y[m]
            r["per_day"].append({"day": d, "payments": int(m.sum()), "laundering": int(yd.sum()),
                                 "pr_auc": round(float(average_precision_score(yd, s_test[m])), 4) if yd.any() else None,
                                 "recall": round(float((p & (yd == 1)).sum() / yd.sum()), 3) if yd.any() else None,
                                 "flagged": int(p.sum()), "tp": int((p & (yd == 1)).sum())})
    report["models"][name] = r
report["top_features_C_gain"] = [[k, round(float(v), 4)] for k, v in imp]
report["seconds"] = round(time.time() - t_start)
json.dump(report, open("eval/report" + SUFFIX + ".json", "w"), indent=2)

lines = [f"# MuleTrace evaluation{' (' + SUFFIX + ')' if SUFFIX else ''}", "",
         f"Generated {report['created_at']} on {report['machine']} by `python model/train.py {SUFFIX}`. "
         f"Test: {len(te):,} payments, {int(y.sum())} laundering. Thresholds from validation only.", "",
         "| Model | PR-AUC | 95% CI | Recall | Precision | Review % | FP/1000 | P@100 | P@500 | P@1000 |",
         "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
for m in res:
    r = report["models"][m["model"]]
    ci = "–".join(map(str, r.get("pr_auc_ci95", []))) or "n/a"
    pk = r["precision_at_k"]
    lines.append(f"| {m['model']} | {m['pr_auc']} | {ci} | {m['recall']:.1%} | {m['precision']:.1%} | {m['review_pct']} | "
                 f"{m['fp_per_1000']} | {pk.get('100', '')} | {pk.get('500', '')} | {pk.get('1000', '')} |")
c = report["models"]["C: MuleTrace network model"]
lines += ["", "Model C confusion counts on test: "
          + "; ".join(f"{t.split('_')[-1].upper()} tp={v['tp']} fp={v['fp']} fn={v['fn']} tn={v['tn']}"
                      for t, v in c.items() if t.startswith("confusion"))]
if c.get("per_day"):
    lines += ["", "| Test day | Payments | Laundering | C PR-AUC | C recall | Flagged |", "|---|---:|---:|---:|---:|---:|"]
    lines += [f"| {d['day']} | {d['payments']:,} | {d['laundering']} | {d['pr_auc']} | {d['recall']} | {d['flagged']} |" for d in c["per_day"]]
open("eval/report" + SUFFIX + ".md", "w").write("\n".join(lines) + "\n")
print("Wrote eval/metrics%s.json, eval/report%s.json, eval/report%s.md in %ds" % (SUFFIX, SUFFIX, SUFFIX, report["seconds"]))
