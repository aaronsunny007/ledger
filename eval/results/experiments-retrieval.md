# Retrieval experiments

Recall = share of questions where the passages given to the model contain the gold evidence. MRR = mean reciprocal rank of the first such passage. Test split, filters extracted from the question as in production. No LLM involved.

| Run | What changes | FinanceBench recall | FinanceBench MRR | XBRL recall | XBRL MRR | Passages | Context chars | p50 ms |
|---|---|---|---|---|---|---|---|---|
| `default` | Default: table chunks, hybrid + rerank, statements pinned | 74.1% | 0.690 | 60.7% | 0.525 | 6.64 | 5845 | 12514.0 |
| `no-pin-statements` | Statement pinning off | 28.2% | 0.162 | 47.5% | 0.304 | 5.97 | 4836 | 15055.6 |
| `hybrid-no-rerank` | Reranker off | 70.6% | 0.669 | 52.5% | 0.446 | 6.79 | 5492 | 76.1 |
| `rerank-v2-m3` | Reranker bge-reranker-v2-m3 instead of -base | 76.5% | 0.690 | 62.3% | 0.543 | 6.56 | 6027 | 52104.2 |
| `rerank-top10` | Rerank the top 10 candidates instead of 30 | 72.9% | 0.681 | 55.7% | 0.472 | 6.71 | 5629 | 3937.3 |
| `vector-no-rerank` | Vector search only, reranker off | 74.1% | 0.690 | 53.3% | 0.449 | 6.73 | 5466 | 51.3 |
| `vector-only` | Vector search only | 71.8% | 0.667 | 62.3% | 0.538 | 6.61 | 5823 | 16056.5 |
| `keyword-only` | Keyword (BM25) search only | 69.4% | 0.653 | 54.1% | 0.455 | 6.68 | 5741 | 7868.6 |
| `section` | Section-aware chunks | 27.1% | 0.144 | 54.1% | 0.372 | 5.97 | 5099 | 11056.0 |
| `fixed-1024` | Fixed 1,024-character chunks | 25.9% | 0.153 | 56.6% | 0.396 | 5.97 | 6083 | 12666.7 |
| `fixed-512` | Fixed 512-character chunks | 10.6% | 0.070 | 45.9% | 0.315 | 5.97 | 3026 | 7105.8 |

Questions: 85 FinanceBench (10-K, test split), 122 XBRL (test split).
Commit: `bcbd21c`.
