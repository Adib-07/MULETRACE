# MuleTrace on IBM LinuxONE

Only measured facts. Sources: [`eval/environment.json`](../eval/environment.json), [`eval/latency.json`](../eval/latency.json), and the VM sessions on 2026-10-17.

## Machine

| Fact | Value | Source |
|---|---|---|
| Architecture (`uname -m`) | s390x (big-endian) | environment.json, `/system` |
| Machine type (`/proc/sysinfo` Type) | 9175 (IBM z17) | environment.json |
| NNPA flag in `/proc/cpuinfo` | present | environment.json |
| vCPUs / RAM | 3 / 7.8 GiB, no swap | environment.json, `free -h` |
| OS / Python | Ubuntu 24.04.5 LTS / 3.12.3 | environment.json |
| Key packages | fastapi==0.143.3, httpx==0.28.1, numpy==1.26.4, pandas==2.1.4+dfsg, pydantic==2.14.1, pytest==7.4.4, scikit-learn==1.4.1.post1, SciPy==1.11.4, snapml==1.17.2, uvicorn==0.54.0, xgboost==3.4.1 | `pip freeze` in environment.json |

## Latency (measured on this VM)

| Measurement | p50 | p95 | p99 | n |
|---|---:|---:|---:|---:|
| In-process decision (features + XGBoost + alert write if flagged) | 1.10 ms | 1.59 ms | 4.06 ms | 20,000 |
| … FLAG/HOLD only (adds pred_contribs explanations + SQLite insert) | 4.08 ms | 4.83 ms | 6.54 ms | 229 |
| HTTP `/score`, 50 req/s for 30 s, server-side | 1.35 ms | 1.95 ms | 4.35 ms | 1,500 |
| … client round trip on the same machine | 2.42 ms | 3.36 ms | 5.71 ms | 1,500 |

HTTP run: 50.0 req/s achieved, errors: 0. Measured 2026-10-17 12:08:40 UTC. Inference: CPU (XGBoost).
Other measurements on the same VM: the feature pass over 2,000,000 payments took 50 s with 2.3 GB peak memory (`/usr/bin/time -v`). The test suite (28 tests) passes on s390x.

## Data egress (measured)

`bench/egress_check.sh` sampled every socket of the uvicorn process with `ss -tunap` and `lsof -i` every 0.2 s while it scored 2,000 replayed payments (20.0 s, 75 samples, 2026-10-17 15:09:49 UTC). Result: **0 non-loopback connections**; the only socket seen was the listener (tcp 127.0.0.1:8001 0.0.0.0:*). Limit: a connection shorter than the sampling interval could be missed; the API code also has no outbound network calls. Source: [`eval/egress.json`](../eval/egress.json).

## Big-endian checks (measured on s390x)

- `tests/test_model_consistency.py` (runs in the VM test suite): XGBoost JSON and UBJSON round trips give identical predictions. `pred_contribs`, which drives the explanations, sums to the model margin.
- `bench/model_consistency_snapml.py` on the deployed model C, `sys.byteorder = big`: JSON and UBJSON round trips give identical predictions on 20,000 test rows. Test PR-AUC is 0.2188, matching `eval/metrics.json`.
- Not verified: a cross-machine comparison against a little-endian host. We had no XGBoost on a little-endian machine.

## s390x issues we hit, and what we did

- **XGBoost has no s390x wheel.** `pip install xgboost` built 3.4.1 from the source distribution. This needed `build-essential` (apt). The pip log shows "Successfully built xgboost" (wheel `xgboost-3.4.1-py3-none-linux_s390x.whl`).
- **Scientific stack from apt.** numpy 1.26.4, pandas 2.1.4, scikit-learn 1.4.1 and scipy 1.11.4 come from Ubuntu packages. The venv uses `--system-site-packages`. `requirements.txt` pins exactly these versions.
- **Big-endian.** No byte-order problems were observed. The pickles and the XGBoost JSON model load and score identically, and all tests pass on s390x.
- **Not s390x-specific:** XGBoost on our macOS dev machines needs `libomp`. Tests were therefore run on the VM.

## On-chip AI (NNPA): measured (2026-10-18)

**Live model:** C (XGBoost) on CPU. **NNPA:** measured as an optional scoring path, with proof that it was used.

How it was enabled, without sudo: Snap ML 1.17.2 ships zDNN builds of its libraries but fell back to CPU because `libzdnn` was missing. We fetched Ubuntu's `libzdnn0` 1.0.1 with `apt-get download` (no install), unpacked it into `~/zdnn` with `dpkg-deb -x`, and pointed Snap ML at it:
```bash
Z=~/zdnn/root/usr/lib/s390x-linux-gnu/libzdnn.so.0
LD_LIBRARY_PATH=$(dirname $Z) SNAPML_ZDNN_LIB=$Z python bench/nnpa_snapml.py     # -> eval/nnpa.json
```
Snap ML then loads `libsnapmllocal3_zdnn` / `libsnapmlutils_zdnn` instead of the CPU build.

Steps that failed on the way:
- Importing XGBoost 3.4.1 JSON (`input_type="xgb_json"`) fails with "no objective defined". A re-ordered copy fails with "parse error 13".
- A freshly fitted Snap ML booster aborts in `optimize_trees` (`tree_ensemble_models.size() > 0` assertion).
- Without `class_weight="balanced"`, Snap ML learns a constant (PR-AUC 0.001). This is the earlier "chance-level" result.

What worked: train Snap ML `BoostingMachineClassifier` (balanced, depth 6, 300 rounds) on the same 20 features and the same train sample as model C, then export to PMML and re-import with `tree_format="zdnn_tensors"`.

**Proof that NNPA was used**, three independent signals in `eval/nnpa.json`:
1. Snap ML reports `optimized_tree_format_ = zdnn_tensors`. The CPU run reports `compress_trees`.
2. zDNN 1.0.1 `zdnn_is_nnpa_installed()` = True.
3. Under `LD_DEBUG=bindings`, a zdnn_tensors predict binds 9 zDNN functions, including `zdnn_matmul_op`, `zdnn_transform_ztensor` and `zdnn_transform_origtensor`.

| Test set (400,000 payments), thresholds from validation | PR-AUC | Recall | Precision | Review | p50 batch 1 | p50 batch 256 |
|---|---:|---:|---:|---:|---:|---:|
| Model C, XGBoost, CPU (live) | 0.2188 | 45.7% | 5.0% | 0.9% | 0.123 ms | 1.66 ms |
| Snap ML, CPU (`compress_trees`) | 0.2012 | 49.0% | 4.6% | 1.05% | 0.011 ms | 0.89 ms |
| **Snap ML, NNPA (`zdnn_tensors`)** | 0.2012 | 49.0% | 4.6% | 1.05% | 0.028 ms | 3.84 ms |

- NNPA and Snap ML CPU scores are identical (max difference 0.0).
- **No NNPA speed-up here:** at batch 1 and 256 the NNPA path is slower than Snap ML's own CPU path (zDNN tensor transforms per call). Larger batches were not measured.
- Model C keeps the higher PR-AUC, so it stays live. The NNPA path is available behind `MULETRACE_SCORER=c-nnpa` (refuses to start unless Snap ML's zDNN build is loaded and the model is placed as `zdnn_tensors`). On the VM, a `c-nnpa` server scored 3,000 replayed payments with 0 errors. That path returns ring-pattern reasons only: the XGBoost contributions would describe a different model.
