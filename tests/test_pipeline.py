import json, os, subprocess, sys
import numpy as np, pandas as pd
from xgboost import XGBClassifier
from conftest import ROOT, run
from features import ALL_FEATURES, FlowState


def test_split_is_time_ordered_without_overlap(pipeline_dir):
    tr, va, te = (pd.read_pickle(pipeline_dir / "data" / f"{n}.pkl") for n in ("train", "valid", "test"))
    assert tr.ts.max() <= va.ts.min() and va.ts.max() <= te.ts.min()
    for part in (tr, va, te):
        assert part.ts.is_monotonic_increasing
    ids = [set(p.txn_id) for p in (tr, va, te)]
    assert not (ids[0] & ids[1] or ids[1] & ids[2] or ids[0] & ids[2])
    n = len(tr) + len(va) + len(te)
    assert len(tr) == int(n * 0.6) and len(tr) + len(va) == int(n * 0.8)


RING = [  # (minute, src, dst, amount): fan-in to C, fast forward C->F, loop F->M1, then later traffic
    (0, "M1", "C", 900), (1, "M2", "C", 900), (1, "M3", "C", 900), (2, "M4", "C", 900), (2, "M5", "C", 900),
    (4, "C", "F", 4400), (5, "F", "M1", 4300), (6, "M1", "C", 800), (30, "X", "C", 10), (90, "C", "Y", 5),
]


def features_for(payments):
    s, out = FlowState(), []
    for t, a, b, amt in payments:
        out.append(s.features(t, a, b, amt, "US Dollar", "US Dollar", "ACH"))
        s.update(t, a, b, amt)
    return out


def test_features_use_only_the_past():
    full = features_for(RING)
    for i in range(len(RING)):
        assert features_for(RING[: i + 1])[i] == full[i], f"payment {i} depends on later payments"
    assert full[4]["dst_in_senders"] == 4                       # C already had 4 senders before the 5th
    assert full[5]["fwd_ratio"] > 0.8 and full[5]["fwd_lag"] == 2  # C forwards what it just received
    assert full[6]["cycle3"] == 1                               # F -> M1 closes M1 -> C -> F -> M1
    assert full[7]["cycle2"] == 0 and full[7]["pair_seen"] == 1


def test_cycle3_is_deterministic_across_processes():
    code = ("import sys; sys.path.insert(0, 'model'); from features import FlowState\n"
            "s = FlowState()\n"
            "for i in range(40): s.update(0, 'D', f'R{i}', 1)\n"
            "s.update(1, 'R37', 'S', 1)\n"
            "print(s.features(2, 'S', 'D', 1, 'US Dollar', 'US Dollar', 'ACH')['cycle3'])")
    outs = {subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONHASHSEED=str(seed))).stdout for seed in (1, 2, 3, 4)}
    assert len(outs) == 1, outs


def test_thresholds_come_from_validation_not_test(pipeline_dir, tmp_path):
    meta = json.load(open(pipeline_dir / "models" / "meta.json"))
    m = XGBClassifier(); m.load_model(pipeline_dir / "models" / "model_c.json")
    va = pd.read_pickle(pipeline_dir / "data" / "feat_valid.pkl")
    sv = m.predict_proba(va[ALL_FEATURES])[:, 1]
    assert np.isclose(meta["flag_threshold"], np.quantile(sv, 0.99))
    assert np.isclose(meta["hold_threshold"], np.quantile(sv, 0.998))
    # Same pipeline with the test labels flipped must produce identical thresholds.
    for sub in ("data", "eval", "models"):
        (tmp_path / sub).mkdir()
    for n in ("train", "valid", "test"):
        f = pd.read_pickle(pipeline_dir / "data" / f"feat_{n}.pkl")
        if n == "test":
            f["label"] = 1 - f["label"]
        f.to_pickle(tmp_path / "data" / f"feat_{n}.pkl")
    run("model/train.py", tmp_path)
    flipped = json.load(open(tmp_path / "models" / "meta.json"))
    assert flipped["flag_threshold"] == meta["flag_threshold"] and flipped["hold_threshold"] == meta["hold_threshold"]


def test_meta_feature_order_matches_model(pipeline_dir):
    meta = json.load(open(pipeline_dir / "models" / "meta.json"))
    m = XGBClassifier(); m.load_model(pipeline_dir / "models" / "model_c.json")
    assert meta["features"] == ALL_FEATURES == m.get_booster().feature_names
