"""Snap ML attempt: import model C into IBM Snap ML and compare inference with XGBoost. Run on the VM from the repo root:
   python -W ignore::ResourceWarning bench/snapml_try.py
Result on 2026-10-17 is recorded in docs/LINUXONE.md."""
import time, warnings, json, numpy as np, pandas as pd
warnings.simplefilter("always")
import xgboost as xgb
meta = json.load(open("models/meta.json")); F = meta["features"]
X = pd.read_pickle("data/feat_test.pkl")[F].head(20000).to_numpy(np.float32)
m = xgb.XGBClassifier(); m.load_model("models/model_c.json")
def bench(fn, rows):
    fn(rows[:1]); t = []
    for i in range(200):
        r = rows[i:i+1]; t0 = time.perf_counter(); fn(r); t.append((time.perf_counter()-t0)*1000)
    return round(float(np.percentile(t,50)),4), round(float(np.percentile(t,99)),4)
px = m.predict_proba(X)[:,1]
print("xgboost single-row p50/p99 ms:", bench(lambda r: m.predict_proba(r), X))
with warnings.catch_warnings(record=True) as w:
    import snapml
    print("snapml imported")
    bm = snapml.BoostingMachineClassifier()
    bm.import_model("models/model_c.json", input_type="xgb_json")
    print("warnings:", sorted({str(x.message) for x in w}))
ps = bm.predict_proba(X)[:,1]
print("max |snapml - xgboost| prob diff:", float(np.abs(ps-px).max()))
print("snapml single-row p50/p99 ms:", bench(lambda r: bm.predict_proba(r), X))
t0=time.perf_counter(); m.predict_proba(X); tx=time.perf_counter()-t0
t0=time.perf_counter(); bm.predict_proba(X); ts=time.perf_counter()-t0
print(f"batch 20000 rows: xgboost {tx*1000:.1f} ms, snapml {ts*1000:.1f} ms")
import inspect; print("import_model/predict params:", [p for p in inspect.signature(bm.predict_proba).parameters])
