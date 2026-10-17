# MuleTrace evaluation

Generated 2026-10-17 12:03:47 UTC on s390x by `python model/train.py `. Test: 400,000 payments, 396 laundering. Thresholds from validation only.

| Model | PR-AUC | 95% CI | Recall | Precision | Review % | FP/1000 | P@100 | P@500 | P@1000 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| A: transaction-only model | 0.0094 | 0.0078–0.012 | 19.4% | 1.6% | 1.18 | 11.62 | 0.01 | 0.01 | 0.017 |
| B: simple rules | 0.0021 | 0.0018–0.0024 | 0.3% | 0.0% | 1.17 | 11.68 | 0.0 | 0.0 | 0.0 |
| C: MuleTrace network model | 0.2188 | 0.1753–0.2643 | 45.7% | 5.0% | 0.9 | 8.57 | 0.74 | 0.218 | 0.133 |
| N: network-only ablation | 0.0686 | 0.0475–0.0963 | 28.5% | 3.5% | 0.8 | 7.72 | 0.31 | 0.16 | 0.097 |

Model C confusion counts on test: FLAG tp=181 fp=3430 fn=215 tn=396174; HOLD tp=120 fp=563 fn=276 tn=399041

| Test day | Payments | Laundering | C PR-AUC | C recall | Flagged |
|---|---:|---:|---:|---:|---:|
| 2022-09-02 | 269,370 | 142 | 0.1213 | 0.394 | 2333 |
| 2022-09-03 | 130,630 | 254 | 0.3134 | 0.492 | 1278 |
