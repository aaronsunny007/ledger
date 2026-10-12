# Retrieval experiments

Recall = share of questions where the passages given to the model contain the gold evidence. MRR = mean reciprocal rank of the first such passage. Test split, filters extracted from the question as in production. No LLM involved.

| Run | What changes | FinanceBench recall | FinanceBench MRR | XBRL recall | XBRL MRR | Passages | Context chars | p50 ms |
|---|---|---|---|---|---|---|---|---|
| `default` | Default: table chunks, vector search, no reranker, statements pinned | 74.1% | 0.690 | 64.8% | 0.603 | 6.83 | 5621 | 63.2 |
| `hybrid-rerank` | Previous default: hybrid search + bge-reranker-base | 74.1% | 0.690 | 65.6% | 0.596 | 6.7 | 5936 | 9142.5 |
| `no-pin-statements` | Statement pinning off | 29.4% | 0.174 | 47.5% | 0.310 | 6.0 | 4878 | 14871.4 |
| `hybrid-no-rerank` | Reranker off | 70.6% | 0.669 | 63.9% | 0.598 | 6.89 | 5667 | 77.0 |
| `rerank-v2-m3` | Reranker bge-reranker-v2-m3 instead of -base | 78.8% | 0.714 | 67.2% | 0.607 | 6.67 | 6166 | 42915.9 |
| `rerank-top10` | Rerank the top 10 candidates instead of 30 | 72.9% | 0.681 | 64.8% | 0.598 | 6.8 | 5785 | 3884.6 |
| `vector-no-rerank` | Vector search only, reranker off | 74.1% | 0.690 | 64.8% | 0.603 | 6.83 | 5621 | 63.3 |
| `vector-only` | Vector search only | 74.1% | 0.691 | 64.8% | 0.593 | 6.71 | 5958 | 10103.0 |
| `keyword-only` | Keyword (BM25) search only | 71.8% | 0.677 | 63.1% | 0.591 | 6.83 | 5979 | 14445.0 |
| `section` | Section-aware chunks | 27.1% | 0.144 | 54.1% | 0.372 | 5.97 | 5099 | 11056.0 |
| `fixed-1024` | Fixed 1,024-character chunks | 25.9% | 0.153 | 56.6% | 0.396 | 5.97 | 6083 | 12666.7 |
| `fixed-512` | Fixed 512-character chunks | 10.6% | 0.070 | 45.9% | 0.315 | 5.97 | 3026 | 7105.8 |

Questions: 85 FinanceBench (10-K, test split), 122 XBRL (test split).
Commit: `c22b7a8`.
