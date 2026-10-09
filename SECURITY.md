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
- **Abuse limits (SEC-3, COST-3).** Questions are capped at 500 characters, each IP is
  rate-limited (10 requests/minute by default) and the public demo has a hard daily spend cap.
- **Data kept.** Request logs hold the question, timings, cost and a random request ID. No
  account, name or IP address is stored.

## Known limits

- The rate limiter and spend cap are in memory: they reset on restart and are per process.
  Put the demo behind a single worker, or move both to Redis/Postgres before scaling out.
- Free LLM tiers may retain prompts. Do not send private documents to them.
