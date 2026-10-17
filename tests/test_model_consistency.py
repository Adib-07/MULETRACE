"""Model serialisation is byte-order safe: JSON and UBJSON round trips give identical predictions, and
pred_contribs (used for explanations) sum to the raw margin. Runs on s390x (big-endian) in CI on the VM."""
import os, sys
import numpy as np, pandas as pd, xgboost as xgb


def test_model_roundtrip_and_contribs(pipeline_dir, tmp_path):
    feats = pd.read_pickle(pipeline_dir / "data" / "feat_test.pkl")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model"))
    from features import ALL_FEATURES
    X = xgb.DMatrix(feats[ALL_FEATURES].to_numpy(np.float32), feature_names=ALL_FEATURES)
    b = xgb.Booster(); b.load_model(str(pipeline_dir / "models" / "model_c.json"))
    p0 = b.predict(X)
    for ext in ("json", "ubj"):
        path = str(tmp_path / f"m.{ext}"); b.save_model(path)
        b2 = xgb.Booster(); b2.load_model(path)
        assert np.array_equal(b2.predict(X), p0), f"{ext} round trip changed predictions on {sys.byteorder}-endian"
    contribs = b.predict(X, pred_contribs=True)
    margin = b.predict(X, output_margin=True)
    assert np.allclose(contribs.sum(axis=1), margin, atol=1e-4)
    assert ((p0 >= 0) & (p0 <= 1)).all()
