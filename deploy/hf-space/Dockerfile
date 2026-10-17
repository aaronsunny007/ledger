# Hugging Face Docker Space (free CPU). The Space repo holds only this file,
# README.md and start.sh; the app itself is cloned from GitHub at build time.
# To build a fork or another branch, change:
#   LEDGER_REPO  public GitHub URL of this repository
#   LEDGER_REF   branch or tag to build (it must contain the daily-quota code)
FROM python:3.12-slim

ARG LEDGER_REPO=https://github.com/aaronsunny007/ledger
ARG LEDGER_REF=main

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 --branch "$LEDGER_REF" "$LEDGER_REPO" /app

# CPU-only torch keeps the image small. Editable, so the code's data/ and configs/
# paths resolve to /app. No postgres extra: the demo uses the in-memory index.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install -e ".[models,tracing,ui]"

# Bake the embedding model into the image so a cold start does not download it.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY start.sh /app/start.sh

# Spaces run the container as user 1000.
RUN useradd -m -u 1000 user && mkdir -p data .cache && chown -R user /app
USER user

ENV STORE=memory LEDGER_API=http://127.0.0.1:8000 LEDGER_BUDGET_FILE=/app/data/budget.json
EXPOSE 7860
CMD ["sh", "/app/start.sh"]
