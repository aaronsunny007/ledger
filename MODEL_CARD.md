# Model card: Ledger

## What it is

A retrieval-augmented question-answering system over SEC 10-K filings. It drafts answers with a
general-purpose LLM (Gemini, Groq or a local Ollama model), cites the retrieved passages, and
checks every number with a deterministic arithmetic verifier.

## Intended use

Looking up and comparing figures and statements in the annual reports Ledger has ingested, with
the source passage one click away. Portfolio and research use.

## Not intended for

Investment advice, trading, real-time market data, companies or periods not ingested, or any
decision made without reading the cited source.

## Evaluation

See the results table in the README. Accuracy is measured on the FinanceBench open set (10-K
subset), 150 XBRL-generated numeric questions and hand-written unanswerable and trap questions,
against a long-context baseline. Numbers are within 1% (0.5% for XBRL).

## Known failure modes

- **"Verified" is not "correct".** The verifier proves the arithmetic is right and the operands
  are in the cited text. It cannot tell whether the model picked the right line item, year or
  denominator. This limit is inherited, deliberately stated, from Financial-NRF.
- **Fiscal-year ambiguity.** Ledger names fiscal years by the calendar year they end in;
  companies with non-calendar years (Walmart, Nike, Microsoft) can be asked about in ways that
  map to the wrong filing.
- **Units.** Tables report in thousands or millions; the verifier allows scale differences when
  matching, which could, rarely, ground a number at the wrong scale.
- **Company detection** relies on names and aliases in `configs/corpus.yaml`; an unlisted
  nickname means no company filter and weaker retrieval.
- **Out-of-corpus questions** (10-Q, 8-K, earnings calls) should be refused, and are scored that way.
