import json, os, sys, time, urllib.error, urllib.request
import pandas as pd
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
SPEED = float(sys.argv[2]) if len(sys.argv) > 2 else 50
df = pd.read_pickle("data/test.pkl").head(N)
url = os.environ.get("MULETRACE_URL", "http://127.0.0.1:8000") + "/score"
headers = {"Content-Type": "application/json"}
if os.environ.get("MULETRACE_TOKEN"):
    headers["X-MuleTrace-Token"] = os.environ["MULETRACE_TOKEN"]
seen = {"PASS": 0, "FLAG": 0, "HOLD": 0, "rejected": 0}
for i, r in enumerate(df.itertuples(index=False), 1):
    body = {"txn_id": str(r.txn_id), "ts": str(r.ts), "src": r.src, "dst": r.dst, "amount": float(r.amount),
            "currency": r.currency, "cur_recv": r.cur_recv, "fmt": r.fmt, "label": int(r.label)}
    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
    try:
        res = json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        if e.code not in (409, 422):        # out of order / duplicate: count it, anything else is a real error
            raise
        seen["rejected"] += 1
        print("REJECTED", e.code, r.txn_id, json.load(e).get("detail"))
        continue
    seen[res["decision"]] += 1
    if res["decision"] != "PASS":
        print(res["decision"], res["score"], r.src, "->", r.dst, round(r.amount, 2), "|", "; ".join(res["reasons"]))
    if i % 500 == 0:
        print("--", i, "payments sent", seen)
    time.sleep(1 / SPEED)
print("Done", seen)
