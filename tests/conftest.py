"""Synthetic fixtures: a tiny payment stream with a planted mule ring, so tests never need the 454 MB dataset."""
import json, os, subprocess, sys
import numpy as np, pandas as pd, pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from features import ALL_FEATURES, FORMATS

COLS = ["Timestamp", "From Bank", "Account", "To Bank", "Account", "Amount Received", "Receiving Currency",
        "Amount Paid", "Payment Currency", "Payment Format", "Is Laundering"]


def raw_csv_rows(n=3000, seed=7):
    """HI-Small-shaped rows over ~2 days, in shuffled file order, with laundering fan-in/forward/loop rings."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2022-09-01 00:00")
    rows = []
    for i in range(n):
        t = start + pd.Timedelta(minutes=int(i * 1.0))
        a, b = rng.choice(40, 2, replace=False)
        amt = round(float(rng.lognormal(7, 1.5)), 2)
        rows.append([t, f"{a % 7:03d}", f"8{a:08X}", f"{b % 7:03d}", f"8{b:08X}", amt, "US Dollar", amt,
                     "US Dollar", FORMATS[int(rng.integers(len(FORMATS)))], 0])
        if i % 100 == 50:                       # a ring: 6 mules -> collector -> forward -> back to a mule
            col, fwd = f"9{i:08X}", f"7{i:08X}"
            for m in range(6):
                rows.append([t, "900", f"6{i:06X}{m}", "901", col, 900.0, "US Dollar", 900.0, "US Dollar", "ACH", 1])
            rows.append([t + pd.Timedelta(minutes=2), "901", col, "902", fwd, 5300.0, "US Dollar", 5300.0, "US Dollar", "ACH", 1])
            rows.append([t + pd.Timedelta(minutes=3), "902", fwd, "900", f"6{i:06X}0", 5000.0, "US Dollar", 5000.0, "US Dollar", "ACH", 1])
    df = pd.DataFrame(rows, columns=COLS)
    df["Timestamp"] = df["Timestamp"].dt.strftime("%Y/%m/%d %H:%M")
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)      # file order is not time order


def run(script, cwd, *args):
    env = dict(os.environ, PYTHONPATH=ROOT)
    r = subprocess.run([sys.executable, os.path.join(ROOT, script), *map(str, args)], cwd=cwd, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"{script} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


@pytest.fixture(scope="session")
def pipeline_dir(tmp_path_factory):
    """Runs the real prepare -> build_features -> train scripts on the synthetic CSV."""
    d = tmp_path_factory.mktemp("pipeline")
    for sub in ("data", "eval", "models"):
        (d / sub).mkdir()
    raw_csv_rows().to_csv(d / "data" / "HI-Small_Trans.csv", index=False)
    run("data/prepare.py", d)
    run("model/build_features.py", d)
    run("model/train.py", d)
    return d


@pytest.fixture(scope="session")
def api_env(pipeline_dir, tmp_path_factory):
    """Env for importing api.main: pipeline data/model, thresholds set so every payment is FLAG (none HOLD)."""
    d = tmp_path_factory.mktemp("api")
    meta = json.load(open(pipeline_dir / "models" / "meta.json"))
    meta.update(flag_threshold=0.0, hold_threshold=2.0)
    (d / "models").mkdir()
    json.dump(meta, open(d / "models" / "meta.json", "w"))
    (d / "models" / "model_c.json").write_bytes((pipeline_dir / "models" / "model_c.json").read_bytes())
    os.environ.update(MULETRACE_MODELS=str(d / "models"), MULETRACE_DATA=str(pipeline_dir / "data"),
                      MULETRACE_DB=str(d / "alerts.db"), MULETRACE_EVAL=str(pipeline_dir / "eval"),
                      MULETRACE_TOKEN="test-token", MULETRACE_LOG_LEVEL="WARNING")
    return d
