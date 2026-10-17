# MuleTrace evaluation (_shuf)

Generated 2026-10-17 12:06:01 UTC on s390x by `python model/train.py _shuf`. Test: 400,000 payments, 396 laundering. Thresholds from validation only.

| Model | PR-AUC | 95% CI | Recall | Precision | Review % | FP/1000 | P@100 | P@500 | P@1000 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| A: transaction-only model | 0.0104 | 0.0085–0.0164 | 18.4% | 1.6% | 1.14 | 11.23 | 0.04 | 0.018 | 0.018 |
| B: simple rules | 0.0014 | 0.0012–0.0017 | 0.3% | 0.0% | 1.17 | 11.68 | 0.0 | 0.0 | 0.0 |
| C: MuleTrace network model | 0.1369 | 0.1036–0.1857 | 42.2% | 4.8% | 0.87 | 8.31 | 0.47 | 0.15 | 0.096 |
| N: network-only ablation | 0.0488 | 0.032–0.0791 | 16.7% | 2.1% | 0.8 | 7.87 | 0.28 | 0.098 | 0.056 |

Model C confusion counts on test: FLAG tp=167 fp=3323 fn=229 tn=396281; HOLD tp=85 fp=611 fn=311 tn=398993

| Test day | Payments | Laundering | C PR-AUC | C recall | Flagged |
|---|---:|---:|---:|---:|---:|
| 2022-09-02 | 269,370 | 142 | 0.0882 | 0.345 | 2220 |
| 2022-09-03 | 130,630 | 254 | 0.2071 | 0.465 | 1270 |
