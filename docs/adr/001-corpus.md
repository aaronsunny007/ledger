# ADR-001: Corpus — SEC 10-K filings, ~40 companies, 3 fiscal years

**Status:** accepted · **Date:** 2026-10-09

## Context

Ledger needs a corpus where answers can be checked against something other than our own
judgement, that is free to obtain, and that matches a public benchmark so our accuracy means
something to outsiders.

## Decision

- **US SEC 10-K annual reports**, downloaded as **HTML** from EDGAR (not PDF), for about
  **40 companies over 3 fiscal years** (`configs/corpus.yaml`).
- The company list starts from **every company in the FinanceBench open set**, so the
  150 public questions can be scored. Ten extra large caps feed the XBRL-generated questions.
- **Fiscal year = the calendar year the reporting period ends in** (Walmart's FY2024 ends
  January 2024). This matches how FinanceBench names documents and how XBRL `end` dates work.
- The corpus is frozen at 40 companies until week 8; then 5–10 **FTSE 100 annual reports**
  (PDF) test whether the system generalises.

## Why

- **HTML keeps tables as tables.** Financial questions are mostly about tables; PDF table
  extraction is the riskiest part of the project (PRF risk: "table parsing eats weeks").
- **XBRL company facts give free ground truth.** The SEC publishes the numbers each company
  tagged in its own filing, so ~150 numeric questions have answers that are not ours.
- **FinanceBench overlap** makes our score comparable with published numbers (GPT-4-Turbo
  shared-store RAG: 19%; per-document RAG: 50%; long context: 79%).

## Consequences

- FinanceBench also asks about 10-Qs, 8-Ks and earnings releases. Those items are tagged
  `out-of-corpus` and reported separately rather than dropped silently. Adding 10-Qs later
  only needs `form: 10-Q` in the downloader.
- FinanceBench evidence is quoted from PDF pages; our chunks come from HTML. Retrieval recall is
  therefore measured by token overlap with the evidence text, not by page number.
- FinanceBench is CC BY-NC 4.0: fine for a portfolio, not for paid client work.

## Alternatives considered

- **UK annual reports first.** Closer to a UK job market, but PDFs only, no free structured
  answers, no public benchmark. Moved to week 8 as the generalisation test.
- **More companies.** More data does not improve the measurement; scope creep is a listed risk.
