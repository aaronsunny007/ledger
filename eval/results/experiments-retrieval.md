# Retrieval experiments

Recall = share of questions where the passages given to the model contain the gold evidence. MRR = mean reciprocal rank of the first such passage. Test split, filters extracted from the question as in production. No LLM involved.

| Run | What changes | FinanceBench recall | FinanceBench MRR | XBRL recall | XBRL MRR | Passages | Context chars | p50 ms |
|---|---|---|---|---|---|---|---|---|
| `section` | Section-aware chunks | 27.1% | 0.140 | 53.3% | 0.367 | 5.97 | 5107 | 13577.7 |
| `fixed-1024` | Fixed 1,024-character chunks | 25.9% | 0.147 | 55.7% | 0.390 | 5.97 | 6082 | 13418.6 |
| `fixed-512` | Fixed 512-character chunks | 10.6% | 0.070 | 45.9% | 0.319 | 5.97 | 3025 | 6590.4 |

Questions: 85 FinanceBench (10-K, test split), 122 XBRL (test split).
Commit: `4a978ef`.
