# Run-to-run noise (same code, same questions)

Runs compared: 2, code hash(es) `05a39647f2216624`, `ae30ebe3474c9f63`. Several hashes are listed because the change between them (for example a type annotation) cannot alter an answer.

| Run | file |
|---|---|
| 1 | `20261013T073749-ledger-test.json` |
| 2 | `20261016T134041-ledger-test-repeat1.json` |

| Metric | run 1 | run 2 | range | std dev |
|---|---|---|---|---|
| Overall accuracy | 78.7% | 77.3% | 1.4 pts | 0.72 |
| FinanceBench accuracy | 56.5% | 52.9% | 3.5 pts | 1.76 |
| XBRL accuracy | 94.3% | 94.3% | 0.0 pts | 0.00 |
| Groundedness | 96.3% | 96.8% | 0.5 pts | 0.27 |

Questions whose result changed between runs: **9 of 217** (4.1%).

| Question | results per run (1 = right) | source |
|---|---|---|
| `financebench_id_04735` | 1.0 0.0 | financebench |
| `financebench_id_00438` | 0.0 1.0 | financebench |
| `financebench_id_00799` | 1.0 0.0 | financebench |
| `financebench_id_00685` | 0.0 1.0 | financebench |
| `financebench_id_00517` | 1.0 0.0 | financebench |
| `financebench_id_02981` | 1.0 0.0 | financebench |
| `financebench_id_00005` | 0.0 1.0 | financebench |
| `financebench_id_00080` | 1.0 0.0 | financebench |
| `financebench_id_06741` | 1.0 0.0 | financebench |

A change between two systems smaller than the range above is inside the noise of the free tier and should not be read as an improvement or a regression.
