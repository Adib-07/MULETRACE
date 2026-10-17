"""Builds a fixture deployment (synthetic data + tiny model) for the browser smoke test. Usage: python tests/e2e/make_fixture.py DIR"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import raw_csv_rows, run

d = sys.argv[1]
for sub in ("data", "eval", "models"):
    os.makedirs(os.path.join(d, sub), exist_ok=True)
raw_csv_rows(6000).to_csv(os.path.join(d, "data", "HI-Small_Trans.csv"), index=False)
for script in ("data/prepare.py", "model/build_features.py", "model/train.py"):
    run(script, d)
meta_path = os.path.join(d, "models", "meta.json")
meta = json.load(open(meta_path))
meta.update(flag_threshold=0.3, hold_threshold=0.9)     # fixture model: make FLAG and HOLD both appear
json.dump(meta, open(meta_path, "w"))
print("fixture ready in", d)
