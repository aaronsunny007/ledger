# Security

## Reporting

Please report vulnerabilities privately through GitHub's "Report a vulnerability" (Security
tab) rather than in a public issue.

## What Ledger does

- **No secrets in git (SEC-1).** Keys live in `.env` (git-ignored) or GitHub / platform
  secrets. `gitleaks` runs as a pre-commit hook and on every CI run.
- **Prompt injection (SEC-2).** Filing text is untrusted data. Passages are wrapped in
  `<passage>` tags and the system prompt tells the model never to follow instructions inside
  them. The golden set includes injection cases (`tags: ["injection"]`) so a regression shows up
  in the eval. Independently, the verifier rejects numbers that do not appear in the cited text,
  which limits what an injected instruction can make the answer say.
- **No `eval()` on model output.** Calculations are parsed into a syntax tree and evaluated with
  an allow-list of numbers, `+ - * /` and parentheses, with a length cap.
- **Abuse limits (SEC-3, COST-3).** Questions are capped at 1,000 characters, each IP is
  rate-limited (10 requests/minute by default) and the public demo has a hard daily spend cap.
- **Bounded requests.** Ticker, year and section filters have size limits; feedback is rate-limited,
  length-limited and stops being stored once its log reaches 5 MB.
- **Hostile model replies.** A reply is untrusted input. Malformed JSON, out-of-range citations,
  500-character calculations, 400-digit numbers and non-finite results all end in an answer or a
  refusal, never a crash (`tests/test_hostile_replies.py`). The demo shows model text with Markdown
  links and images reduced to their words.
- **Demo download.** The Space unpacks only `data/processed/index` from the index archive, so a
  tampered archive cannot overwrite code. The archive is a release asset of this repository, so
  whoever can publish a release can change the index; keep write access tight.
- **Data kept.** Request logs hold the question, timings, cost and a random request ID. No
  account, name or IP address is stored.

## Known limits

- The rate limiter and spend cap are in memory: they reset on restart and are per process.
  Put the demo behind a single worker, or move both to Redis/Postgres before scaling out.
- Free LLM tiers may retain prompts. Do not send private documents to them.
- The demo's Streamlit server runs with XSRF protection off, which Spaces need to embed it. The page
  has no state-changing action besides asking a question, and the daily quota bounds that.
- GitHub Actions are pinned by version tag, not commit hash.
- Last review: 31 Oct 2026 (bandit, pip-audit, a read of the API, download, workflow and deploy
  paths). Fixed then: a branch-name injection in `space-smoke.yml`, unrestricted index unpacking,
  unbounded request filters, an unthrottled feedback endpoint, and a crash on a 400-digit number in a
  model calculation. pip-audit reports advisories only for `virtualenv`, a development tool.
