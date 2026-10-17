"""On the VM (repo root): (1) the deployed model C gives identical predictions after JSON/UBJSON round trips on
this machine; (2) Snap ML retry: train a Snap ML BoostingMachine on the same features/sample and compare PR-AUC and
single-row latency with XGBoost on CPU. Prints JSON; results are recorded in docs/LINUXONE.md."""
import json, sys, time, warnings
import numpy as np, pandas as pd, xgboost as xgb
from sklearn.metrics import average_precision_score
warnings.simplefilter("ignore")
meta = json.load(open("models/meta.json")); F = meta["features"]
tr, te = pd.read_pickle("data/feat_train.pkl"), pd.read_pickle("data/feat_test.pkl")
Xte = te[F].to_numpy(np.float32); y = te.label.values
out = {"byteorder": sys.byteorder}
b = xgb.Booster(); b.load_model("models/model_c.json")
D = xgb.DMatrix(Xte[:20000], feature_names=F); p0 = b.predict(D)
for ext in ("json", "ubj"):
    b.save_model(f"/tmp/mc.{ext}"); b2 = xgb.Booster(); b2.load_model(f"/tmp/mc.{ext}")
    out[f"roundtrip_{ext}_identical_20000_rows"] = bool(np.array_equal(b2.predict(D), p0))
def lat(fn):
    fn(Xte[:1]); t = []
    for i in range(500):
        t0 = time.perf_counter(); fn(Xte[i:i + 1]); t.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": round(float(np.percentile(t, 50)), 4), "p99_ms": round(float(np.percentile(t, 99)), 4)}
m = xgb.XGBClassifier(); m.load_model("models/model_c.json")
out["xgboost_cpu"] = {"pr_auc_test": round(float(average_precision_score(y, m.predict_proba(Xte)[:, 1])), 4), "single_row": lat(lambda r: m.predict_proba(r))}
try:
    import snapml
    pos = tr[tr.label == 1]; neg = tr[tr.label == 0].sample(n=min(200000, (tr.label == 0).sum()), random_state=42)
    s = pd.concat([pos, neg])
    bm = snapml.BoostingMachineClassifier(num_round=300, max_depth=6, learning_rate=0.1, n_jobs=3, random_state=42)
    t0 = time.time(); bm.fit(s[F].to_numpy(np.float32), s.label.values.astype(np.float32)); fit_s = time.time() - t0
    ps = bm.predict_proba(Xte)[:, 1]
    out["snapml_cpu"] = {"trained_on": f"same features, same sample ({len(s):,} rows)", "fit_s": round(fit_s, 1),
                         "pr_auc_test": round(float(average_precision_score(y, ps)), 4), "single_row": lat(lambda r: bm.predict_proba(r))}
    out["snapml_accelerator_path"] = "none exposed: snapml prints 'Falling back to CPU-only mode. IBM Snap ML will not leverage NNPA.'"
except Exception as e:
    out["snapml_error"] = f"{type(e).__name__}: {e}"
print(json.dumps(out, indent=1))
