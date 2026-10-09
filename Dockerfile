# DEP-1: one image for the API, the ingestion job and the Streamlit UI.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app
COPY pyproject.toml README.md ./
COPY ledger ./ledger
# CPU-only torch keeps the image ~1.5 GB smaller than the default CUDA build.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install ".[models,postgres,pdf,tracing,ui]"

COPY configs ./configs
COPY ui ./ui
COPY eval ./eval
COPY scripts ./scripts

RUN useradd -m -u 1000 ledger && mkdir -p data .cache && chown -R ledger /app
USER ledger

EXPOSE 8000 8501
CMD ["uvicorn", "ledger.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
