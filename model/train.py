import json, os, sys
import numpy as np, pandas as pd, xgboost as xgb
from sklearn.metrics import average_precision_score
sys.path.insert(0, ".")
from model.features import TXN_FEATURES, ALL_FEATURES, rule_score

tr = pd.read_pickle("data/feat_train.pkl")
va = pd.read_pickle("data/feat_valid.pkl")
te = pd.read_pickle("data/feat_test.pkl")
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

os.makedirs("models", exist_ok=True)
mA = fit(TXN_FEATURES)
mC = fit(ALL_FEATURES)
rule = lambda d: d[ALL_FEATURES].apply(lambda r: rule_score(r), axis=1).values
res = [evaluate("A: transaction-only model", mA.predict_proba(va[TXN_FEATURES])[:, 1], mA.predict_proba(te[TXN_FEATURES])[:, 1]),
       evaluate("B: simple rules", rule(va), rule(te)),
       evaluate("C: MuleTrace network model", mC.predict_proba(va[ALL_FEATURES])[:, 1], mC.predict_proba(te[ALL_FEATURES])[:, 1])]
sv = mC.predict_proba(va[ALL_FEATURES])[:, 1]
meta = {"flag_threshold": float(np.quantile(sv, 1 - REVIEW)),
        "hold_threshold": float(np.quantile(sv, 1 - REVIEW / 5)),
        "features": ALL_FEATURES}
mA.save_model("models/model_a.json")
mC.save_model("models/model_c.json")
json.dump(meta, open("models/meta.json", "w"), indent=2)
json.dump(res, open("eval/metrics.json", "w"), indent=2)
print(pd.DataFrame(res).drop(columns="threshold").to_string(index=False))
imp = sorted(zip(ALL_FEATURES, mC.feature_importances_), key=lambda x: -x[1])[:8]
print("Top features (C):", [(k, round(float(v), 3)) for k, v in imp])
