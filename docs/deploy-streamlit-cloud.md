# Deploying the free demo on Streamlit Community Cloud

Free, no card, deploys straight from this public GitHub repository. The app starts the Ledger API
inside the same process (`LEDGER_API=embedded`), so the daily quota guard still applies.

**Two rules.** Keep billing off everywhere, and put the Gemini key only in Streamlit's Secrets box.
Never in a file, a commit, an issue or a chat.

## What you need first

- This repository on `main`, public.
- The `demo-index` release (it holds `demo-index.tar.gz`, about 155 MB). It exists already; run the
  **build-demo-index** workflow again only if you change the corpus.
- A free Gemini key from <https://aistudio.google.com/apikey> (the one your evals already use).

## Steps (about 5 minutes)

1. Go to <https://share.streamlit.io> and sign in **with GitHub**. Allow it to read your public
   repositories when it asks.
2. **Create app**, then *Deploy a public app from GitHub*:
   - Repository: `aaronsunny007/ledger`
   - Branch: `main`
   - Main file path: `ui/streamlit_app.py`
   - **Advanced settings**: Python version **3.12**, and in **Secrets** paste:

     ```toml
     LEDGER_API = "embedded"
     GEMINI_API_KEY = "paste-your-free-key-here"
     ```

3. **Deploy**. The first build installs the packages (a few minutes, mostly CPU PyTorch). The first
   page load then downloads the index and the embedding model (about two minutes more); later
   visits are quick.

Secrets can be edited later: app menu, *Settings*, *Secrets*. The placeholders live in
`.streamlit/secrets.toml.example`.

## Checking it works

Open the app. The sidebar should list "Companies loaded (39)". Ask "Should I buy Tesla stock?"
(refused) and "What was Apple's revenue in fiscal year 2023?" (answered with a cited figure). Before
you deploy, the **streamlit-smoke** workflow does the same in a clean environment and prints memory.

## The per-visitor limit

Each visitor may ask `LEDGER_PER_CLIENT_DAILY` questions a day (default 15) and the whole demo
`LEDGER_DAILY_BUDGET` (default 300). A visitor is the address the hosting proxy appended to
`X-Forwarded-For` (the last entry; `TRUSTED_PROXY_HOPS`, default 1). Open the sidebar's
*About this demo*: it says how many forwarding entries your connection shows.

- **1 entry**: the default is right.
- **2 or more**: the hosting platform has more than one proxy in front of the app. Add
  `TRUSTED_PROXY_HOPS = "2"` (use the number shown) to the Secrets box, or every visitor would share
  one quota.
- **0 entries**: no proxy header reaches the app, so all visitors share one address. The overall
  daily cap still protects the free quota; the per-visitor cap does not separate people.

## Limits to expect

- **Sleep.** A free app sleeps after about a day without visitors and wakes on the next visit with a
  "this app has gone to sleep" button and a few minutes of start-up.
- **Memory.** Community Cloud allows about 2.7 GB (its published figure at the time of writing, it may
  change). The demo uses about 1.2 GB.
- **Public repository.** The index and the code come from public GitHub URLs.
- **Counters.** The daily counters live in memory and in a file on the app's temporary disk, so they
  reset when the app restarts or sleeps. The cap is a safety rail, not an exact ledger.
- **No investment advice.** Ledger reports what filings say and refuses buy/sell questions.
