import sys, time
import pandas as pd
sys.path.insert(0, ".")
from model.features import FlowState, ALL_FEATURES

state = FlowState()  # one continuous stream: train -> valid -> test
for name in ["train", "valid", "test"]:
    df = pd.read_pickle("data/" + name + ".pkl")
    t0 = time.time()
    mins = df.ts.values.astype("datetime64[m]").astype("int64").tolist()
    rows = []
    for t, s, d, a, cp, cr, fm in zip(mins, df.src.tolist(), df.dst.tolist(),
                                       df.amount.tolist(), df.currency.tolist(),
                                       df.cur_recv.tolist(), df.fmt.tolist()):
        f = state.features(t, s, d, a, cp, cr, fm)   # BEFORE adding this payment
        rows.append([f[k] for k in ALL_FEATURES])
        state.update(t, s, d, a)
    X = pd.DataFrame(rows, columns=ALL_FEATURES, dtype="float32")
    X["label"] = df.label.values
    X["txn_id"] = df.txn_id.values
    X.to_pickle("data/feat_" + name + ".pkl")
    print(name, len(X), "rows done in", round(time.time() - t0), "seconds")
