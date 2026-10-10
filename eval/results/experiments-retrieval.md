# Retrieval experiments

Recall = share of questions where the passages given to the model contain the gold evidence. MRR = mean reciprocal rank of the first such passage. Test split, filters extracted from the question as in production. No LLM involved.

| Run | What changes | FinanceBench recall | FinanceBench MRR | XBRL recall | XBRL MRR | Passages | Context chars | p50 ms |
|---|---|---|---|---|---|---|---|---|
| `default` | Default: table chunks, hybrid + rerank, statements pinned | 71.8% | 0.667 | 60.7% | 0.522 | 6.59 | 5783 | 12044.1 |
| `no-pin-statements` | Statement pinning off | 28.2% | 0.162 | 47.5% | 0.304 | 5.97 | 4836 | 15055.6 |
| `hybrid-no-rerank` | Reranker off | 68.2% | 0.645 | 51.6% | 0.440 | 6.74 | 5456 | 59.9 |
| `rerank-v2-m3` | Reranker bge-reranker-v2-m3 instead of -base | 76.5% | 0.690 | 62.3% | 0.543 | 6.56 | 6027 | 52104.2 |
| `vector-only` | Vector search only | 71.8% | 0.667 | 62.3% | 0.538 | 6.61 | 5823 | 16056.5 |
| `keyword-only` | Keyword (BM25) search only | 69.4% | 0.653 | 54.1% | 0.455 | 6.68 | 5741 | 7868.6 |
| `section` | Section-aware chunks | 27.1% | 0.144 | 54.1% | 0.372 | 5.97 | 5099 | 11056.0 |
| `fixed-1024` | Fixed 1,024-character chunks | 25.9% | 0.153 | 56.6% | 0.396 | 5.97 | 6083 | 12666.7 |
| `fixed-512` | Fixed 512-character chunks | 10.6% | 0.070 | 45.9% | 0.315 | 5.97 | 3026 | 7105.8 |

Questions: 85 FinanceBench (10-K, test split), 122 XBRL (test split).
Commit: `34f7dc1`.
