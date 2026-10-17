# Deploying the free public demo

A public Ledger demo that costs nothing: a Hugging Face **Docker Space** on the free CPU
tier, the free Gemini API tier for answers, GitHub Actions to build the index, and
(optionally) free Langfuse Cloud for traces. This page is the whole procedure; everything
below happens in a browser except one `git push`.

**Two rules.** Keep billing disabled everywhere (no payment method on Hugging Face, no Cloud
Billing on the Google project behind the Gemini key), and put keys only in the Space or
GitHub secret settings. Never in a file, an issue, a commit or a chat.

## What gets deployed

```text
browser -> Space :7860 -> Streamlit UI -> (127.0.0.1:8000) FastAPI -> Gemini
                                            |- daily quota guard
                                            |- semantic cache, verifier
                                            `- index from data/processed (downloaded at start)
```

A Space exposes one port, so only the UI is public; the API runs inside the container and
is what enforces the daily quota. The Space repo holds three files from
[`deploy/hf-space/`](../deploy/hf-space): `Dockerfile`, `README.md` (Space settings front
matter) and `start.sh`. The Dockerfile clones this repository from GitHub when it builds,
so the repository must be public and the branch it builds (`LEDGER_REF`, default `main`)
must contain `deploy/hf-space/` and the daily-quota code.

## 1. Build the index (GitHub, once)

1. Repository **Actions** tab, **build-demo-index**, **Run workflow**. Defaults index every
   filing the eval questions need plus the filings behind the UI's example questions. It
   needs no secret, and takes a while the first time (EDGAR downloads, embedding on CPU).
2. When it finishes, the run summary prints `LEDGER_INDEX_URL=https://github.com/<you>/ledger/releases/download/demo-index/demo-index.tar.gz`.
   Copy that URL. The workflow keeps a single release named `demo-index` and replaces its
   asset each time you run it.

## 2. Create the Space (Hugging Face)

1. Create a free account at <https://huggingface.co/join>. Do not add a payment method.
2. **New Space**: name `ledger`, SDK **Docker** (Blank template), hardware **CPU basic
   (free)**, visibility **Public**. Never pick an upgraded hardware tier.
3. Space **Settings**, **Variables and secrets**:

   | Kind | Name | Value |
   |---|---|---|
   | Secret | `GEMINI_API_KEY` | a free key from <https://aistudio.google.com/apikey> |
   | Variable | `LEDGER_INDEX_URL` | the URL from step 1 |
   | Secret (optional) | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | see "Tracing" below |
   | Variable (optional) | `LEDGER_DAILY_BUDGET`, `LEDGER_PER_CLIENT_DAILY` | see "Daily budget" below |

4. Put the three files in the Space. Either use **Files, Add file, Upload files** with the
   contents of `deploy/hf-space/`, or from a clone of this repository:

   ```bash
   git clone https://huggingface.co/spaces/<your-user>/ledger hf-ledger
   cp deploy/hf-space/{Dockerfile,README.md,start.sh} hf-ledger/
   cd hf-ledger && git add . && git commit -m "Ledger demo" && git push
   ```

   When git asks for a password, paste a Hugging Face access token (Settings, Access Tokens,
   role *write*) at the prompt. It goes nowhere else.
5. The Space builds (a few minutes: it installs CPU torch and bakes in the embedding model)
   and starts. Open it and ask one of the example questions.

If the repository is not `aaronsunny007/ledger`, change `LEDGER_REPO` (and `LEDGER_REF` if
you build a branch) at the top of the Dockerfile.

## Daily budget

The free Gemini tier allows roughly 500 requests a day on `gemini-3.5-flash-lite` (and far
fewer on the larger retry model), and resets at midnight Pacific. The API protects it:

- `LEDGER_DAILY_BUDGET` (default **300**): questions answered per day across all visitors.
- `LEDGER_PER_CLIENT_DAILY` (default **15**): per visitor, keyed by the first address in
  `X-Forwarded-For`, else the connection's address. The UI forwards the visitor's address to
  the API. Anyone who can forge that header can dodge the per-visitor cap, never the global one.
- Only questions that really call the model count. Semantic-cache hits, investment-advice
  refusals and over-long questions do not.
- When a cap is reached the API returns HTTP 429 with `{"detail": {"error":
  "daily_quota_exhausted", "message": "...resets at 07:00 UTC (midnight Pacific)...",
  "resets_at": ..., "retry_after_seconds": ...}}`, and the UI shows the message. While a cap
  is reached even cache hits are refused (the check runs before the cache lookup). If Google
  itself reports its quota spent first, the same message is shown.
- Counters reset at a fixed 07:00 UTC, which is midnight Pacific during daylight saving. From
  November to March Google's own reset is at 08:00 UTC, so in that first hour our counters have
  reset while Google's quota may still be spent; the provider's refusal is then shown with the
  same message. Change `RESET_HOUR_UTC` in `ledger/api/budget.py` if you care.
- A question the verifier sends back for a second attempt makes two requests, so 300 questions
  can cost more than 300 requests. Lower `LEDGER_DAILY_BUDGET` (say 250) if you want margin.
- Counters live in memory and are also kept in `LEDGER_BUDGET_FILE` (set in the Dockerfile), so
  a restart of the API process within the day keeps them. A Space's disk is wiped whenever the
  container restarts, sleeps and wakes, or rebuilds, which also resets the counters, so the cap
  is a safety rail, not an exact ledger. Only a hash of each visitor's address is stored.

## Tracing

Every request is always written to a local file, `data/traces/requests.jsonl`, with per-stage
timings, tokens, cost, cache hit and verifier result. The UI's **Dashboard** tab reads it.
This needs no network and no account. On a Space the file lives on the container's temporary
disk, so it is lost when the Space restarts.

To also send traces to Langfuse (free Hobby tier, a few clicks):

1. Sign up at <https://cloud.langfuse.com>, create a project, copy its public and secret keys
   (Project settings, API keys).
2. Add them as Space secrets `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`. For the US
   region, add the variable `LANGFUSE_HOST=https://us.cloud.langfuse.com`.
3. Restart the Space. Thumbs up/down in the UI are attached to the traces as scores.

With the keys absent, or if Langfuse is unreachable or its package is missing, Ledger logs a
warning and carries on with the local file only; tracing never blocks an answer.

## Limits to expect

- **Cold start.** A free Space sleeps after a period without visitors (Hugging Face currently says 48 hours) and takes a few
  minutes to wake (container start, index download, model load). The first question after a
  wake-up is slower still.
- **Daily cap.** At most `LEDGER_DAILY_BUDGET` answers a day, then 429s until the reset.
- **Memory and disk.** The free CPU tier has 16 GB RAM, ample for the index, but its disk is
  not persistent. Everything is rebuilt from the release asset on each start.
- **No investment advice.** Ledger reports what filings say and refuses buy/sell questions.
  Answers are not investment advice, may be wrong, and cover only the ingested filings.
- **Public repo and asset.** The index URL must be reachable without a login.

## Troubleshooting

- *UI says no filings are loaded*: `LEDGER_INDEX_URL` is missing or wrong (the UI repeats the
  reason `start.sh` recorded). Fix the variable and restart the Space.
- *Build fails at `git clone`*: the repository is private, or `LEDGER_REF` does not exist.
- *Every answer is a 429 straight away*: check the Space logs for `daily_quota_exhausted`; the
  Gemini key may be exhausted or invalid for the model (set `LLM_MODEL` as a Variable).
