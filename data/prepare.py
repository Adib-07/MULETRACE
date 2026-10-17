import sys
import pandas as pd

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000000
cols = ["ts", "from_bank", "from_acct", "to_bank", "to_acct",
        "amt_recv", "cur_recv", "amount", "currency", "fmt", "label"]
types = {"from_bank": str, "from_acct": str,
         "to_bank": str, "to_acct": str, "label": "int8"}

df = pd.read_csv("data/HI-Small_Trans.csv", header=0, names=cols, dtype=types)
df["ts"] = pd.to_datetime(df["ts"], format="%Y/%m/%d %H:%M")
df["src"] = df["from_bank"] + "_" + df["from_acct"]
df["dst"] = df["to_bank"] + "_" + df["to_acct"]
df = df.sort_values("ts", kind="stable").head(N).reset_index(drop=True)
df["txn_id"] = df.index.astype(str)

print("Rows kept:", len(df))
print("From:", df.ts.min(), "To:", df.ts.max())
print(df.groupby(df.ts.dt.date)["label"].agg(["count", "sum"]))

n = len(df)
a = int(n * 0.6)
b = int(n * 0.8)
parts = [("train", df.iloc[:a]), ("valid", df.iloc[a:b]), ("test", df.iloc[b:])]
for name, part in parts:
    part.to_pickle("data/" + name + ".pkl")
    print(name, len(part), "rows,", int(part.label.sum()), "laundering,",
          part.ts.min(), "->", part.ts.max())
