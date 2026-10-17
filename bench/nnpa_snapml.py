"""NNPA scoring path ("C-nnpa"): IBM Snap ML boosted trees on the same 20 features, executed as zDNN tensors on the
Telum II on-chip accelerator, compared with model C (XGBoost, CPU). Run on the VM from the repo root with the zDNN
library visible to Snap ML (no sudo; see docs/LINUXONE.md):
    Z=~/zdnn/root/usr/lib/s390x-linux-gnu/libzdnn.so.0
    LD_LIBRARY_PATH=$(dirname $Z) SNAPML_ZDNN_LIB=$Z python bench/nnpa_snapml.py      -> eval/nnpa.json
"""
import ctypes, json, os, subprocess, sys, time, warnings
import numpy as np, pandas as pd, xgboost as xgb
from sklearn.metrics import average_precision_score
warnings.simplefilter("ignore")
import snapml

PROBE = len(sys.argv) > 1 and sys.argv[1] == "--probe"      # child process: one zdnn_tensors predict under LD_DEBUG
meta = json.load(open("models/meta.json")); F = meta["features"]
tr, va, te = (pd.read_pickle(f"data/feat_{n}.pkl") for n in ("train", "valid", "test"))
s = pd.concat([tr[tr.label == 1], tr[tr.label == 0].sample(n=min(200000, int((tr.label == 0).sum())), random_state=42)])
Xs, ys = s[F].to_numpy(np.float32), s.label.values.astype(np.float64)
Xv, Xt, yt = va[F].to_numpy(np.float32), te[F].to_numpy(np.float32), te.label.values
CFG = {"class_weight": "balanced", "max_depth": 6, "num_round": 300, "learning_rate": 0.1, "n_jobs": 3, "random_state": 42}

PMML = "/tmp/muletrace_snapml_bm.pmml"
def load(fmt):          # a freshly fitted booster cannot be re-formatted; export -> import is Snap ML's supported route
    m = snapml.BoostingMachineClassifier(); m.import_model(PMML, input_type="pmml", tree_format=fmt, X=Xs[:2000]); return m
if PROBE:
    load("zdnn_tensors").predict_proba(Xt[:256]); sys.exit(0)
t0 = time.time(); fitted = snapml.BoostingMachineClassifier(**CFG); fitted.fit(Xs, ys); fit_s = time.time() - t0
fitted.export_model(PMML, output_type="pmml")

def metrics(pv, pt):
    flag, hold = float(np.quantile(pv, 0.99)), float(np.quantile(pv, 0.998))
    pred = pt >= flag; tp = int((pred & (yt == 1)).sum()); fp = int((pred & (yt == 0)).sum())
    return {"pr_auc": round(float(average_precision_score(yt, pt)), 4), "recall": round(tp / int(yt.sum()), 3),
            "precision": round(tp / max(tp + fp, 1), 3), "review_pct": round(100 * float(pred.mean()), 2),
            "fp_per_1000": round(1000 * fp / len(yt), 2), "flag_threshold": flag, "hold_threshold": hold}

def lat(fn, batch, iters):
    fn(Xt[:batch]); t = []
    for i in range(iters):
        r = Xt[(i * batch) % (len(Xt) - batch):][:batch]
        t0 = time.perf_counter(); fn(r); t.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": round(float(np.percentile(t, 50)), 4), "p99_ms": round(float(np.percentile(t, 99)), 4), "iterations": iters}

out = {"created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "machine": os.uname().machine,
       "snapml_variant_loaded": sorted(m for m in sys.modules if m.startswith("snapml.libsnapml")),
       "zdnn_library": os.environ.get("SNAPML_ZDNN_LIB"),
       "model": {"library": "IBM Snap ML BoostingMachineClassifier", "config": CFG, "train_rows": len(s), "fit_s": round(fit_s, 1),
                 "features": "same 20 features as model C, same train sample, thresholds = validation quantiles (same method)"}}

c = xgb.XGBClassifier(); c.load_model("models/model_c.json")
cv, ct = c.predict_proba(va[F])[:, 1], c.predict_proba(te[F])[:, 1]
out["model_C_xgboost_cpu"] = metrics(cv, ct)
preds = {}
pf = fitted.predict_proba(Xt)[:, 1]
for fmt in ("compress_trees", "zdnn_tensors"):
    bm = load(fmt)
    used = bm.booster_.optimized_tree_format_
    pv, pt = bm.predict_proba(Xv)[:, 1], bm.predict_proba(Xt)[:, 1]
    preds[fmt] = pt
    if fmt == "zdnn_tensors":                  # artefacts for the optional API scorer (MULETRACE_SCORER=c-nnpa)
        import shutil; shutil.copy(PMML, "models/c_nnpa.pmml")
        m = metrics(pv, pt); json.dump({"features": F, "flag_threshold": m["flag_threshold"], "hold_threshold": m["hold_threshold"],
                                        "source": "bench/nnpa_snapml.py", "tree_format": used}, open("models/c_nnpa_meta.json", "w"), indent=1)
    out[f"snapml_{fmt}"] = {"requested_tree_format": fmt, "library_reported_tree_format": used, **metrics(pv, pt),
                            "latency_batch1": lat(lambda r: bm.predict_proba(r), 1, 500),
                            "latency_batch256": lat(lambda r: bm.predict_proba(r), 256, 200)}
out["model_C_xgboost_cpu"]["latency_batch1"] = lat(lambda r: c.predict_proba(r), 1, 500)
out["model_C_xgboost_cpu"]["latency_batch256"] = lat(lambda r: c.predict_proba(r), 256, 200)
out["max_abs_diff_cpu_vs_nnpa_scores"] = float(np.abs(preds["compress_trees"] - preds["zdnn_tensors"]).max())
out["max_abs_diff_fitted_vs_imported_cpu"] = float(np.abs(pf - preds["compress_trees"]).max())

# Proof that NNPA was used: (1) Snap ML reports zdnn_tensors; (2) zDNN reports the NNPA facility installed;
# (3) the dynamic linker binds zdnn_* functions while a zdnn_tensors model predicts.
z = ctypes.CDLL(os.environ["SNAPML_ZDNN_LIB"]); z.zdnn_is_nnpa_installed.restype = ctypes.c_bool
z.zdnn_get_library_version_str.restype = ctypes.c_char_p; z.zdnn_init()
env = dict(os.environ, LD_DEBUG="bindings")
r = subprocess.run([sys.executable, __file__, "--probe"], env=env, capture_output=True, text=True, timeout=900)
bound = sorted({l.split("`")[1].split("'")[0] for l in r.stderr.splitlines() if "libzdnn" in l and "`zdnn_" in l})
out["nnpa_proof"] = {"snapml_reported_tree_format": out["snapml_zdnn_tensors"]["library_reported_tree_format"],
                     "zdnn_is_nnpa_installed": bool(z.zdnn_is_nnpa_installed()),
                     "zdnn_library_version": z.zdnn_get_library_version_str().decode(),
                     "zdnn_functions_bound_during_predict": bound}
out["nnpa_used"] = (out["nnpa_proof"]["snapml_reported_tree_format"] == "zdnn_tensors" and out["nnpa_proof"]["zdnn_is_nnpa_installed"]
                    and len(bound) > 0)
json.dump(out, open("eval/nnpa.json", "w"), indent=1)
print(json.dumps({k: out[k] for k in ("nnpa_used", "nnpa_proof", "max_abs_diff_cpu_vs_nnpa_scores")}, indent=1))
for k in ("model_C_xgboost_cpu", "snapml_compress_trees", "snapml_zdnn_tensors"):
    v = out[k]; print(k, {x: v[x] for x in ("pr_auc", "recall", "precision", "review_pct")}, "b1", v["latency_batch1"], "b256", v["latency_batch256"])
