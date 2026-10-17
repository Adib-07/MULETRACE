import json, sys, time, urllib.request
import pandas as pd
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
SPEED = float(sys.argv[2]) if len(sys.argv) > 2 else 50
df = pd.read_pickle("data/test.pkl").head(N)
url = "http://localhost:8000/score"
seen = {"ALLOW": 0, "REVIEW": 0, "HOLD": 0}
for i, r in enumerate(df.itertuples(index=False), 1):
    body = {"txn_id": str(r.txn_id), "ts": str(r.ts), "src": r.src, "dst": r.dst, "amount": float(r.amount),
            "currency": r.currency, "cur_recv": r.cur_recv, "fmt": r.fmt, "label": int(r.label)}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    res = json.load(urllib.request.urlopen(req))
    seen[res["decision"]] += 1
    if res["decision"] != "ALLOW":
        print(res["decision"], res["score"], r.src, "->", r.dst, round(r.amount, 2), "|", "; ".join(res["reasons"]))
    if i % 500 == 0:
        print("--", i, "payments sent", seen)
    time.sleep(1 / SPEED)
print("Done", seen)
