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

## s390x issues we hit, and what we did

- **XGBoost has no s390x wheel.** `pip install xgboost` built 3.4.1 from the source distribution. This needed `build-essential` (apt). The pip log shows "Successfully built xgboost" (wheel `xgboost-3.4.1-py3-none-linux_s390x.whl`).
- **Scientific stack from apt.** numpy 1.26.4, pandas 2.1.4, scikit-learn 1.4.1 and scipy 1.11.4 come from Ubuntu packages. The venv uses `--system-site-packages`. `requirements.txt` pins exactly these versions.
- **Big-endian.** No byte-order problems were observed. The pickles and the XGBoost JSON model load and score identically, and all tests pass on s390x.
- **Not s390x-specific:** XGBoost on our macOS dev machines needs `libomp`. Tests were therefore run on the VM.

## On-chip AI (NNPA): what we tried

- The NNPA flag is present (Telum II). **Model C runs on the CPU. We do not claim NNPA acceleration.**
- `pip install snapml` installed IBM Snap ML 1.17.2 (s390x wheel). On import it warns: "Falling back to CPU-only mode. IBM Snap ML will not leverage NNPA." `libzdnn` is not installed on the VM.
- `bench/snapml_try.py`: importing model C with `BoostingMachineClassifier().import_model("models/model_c.json", input_type="xgb_json")` **failed** with `SnapMlLibrary.Error: no objective defined in models/model_c.json`. Snap ML 1.17.2 does not read this XGBoost 3.4.1 JSON model. No Snap ML or NNPA latency was measured.
- For reference, the same script measured XGBoost single-row `predict_proba` on the VM at about 0.135 ms p50 (200 rows). The remainder of the ~1.1 ms decision is feature computation, DataFrame construction and bookkeeping.
- **Next step (not done):** install zDNN, retrain or convert model C into a format Snap ML accepts, and measure CPU vs NNPA on the same 20,000 payments before claiming anything.
