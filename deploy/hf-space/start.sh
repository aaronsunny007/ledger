#!/bin/sh
# Start the demo: fetch the prebuilt index if there is none, run the API on
# 127.0.0.1:8000 (it enforces the daily quota) and the Streamlit UI on the
# one port a Space exposes, 7860. The UI reaches the API at LEDGER_API.
# Only data/processed/index is unpacked from the download, so a tampered archive cannot overwrite code.
set -u
cd /app
mkdir -p data/traces

status=data/index-status.txt  # the UI shows this when no index could be loaded
have_index() { ls data/processed/index/*/chunks.jsonl > /dev/null 2>&1; }

if have_index; then
  rm -f "$status"
elif [ -z "${LEDGER_INDEX_URL:-}" ]; then
  echo "LEDGER_INDEX_URL is not set." > "$status"
else
  echo "Downloading the index from LEDGER_INDEX_URL ..."
  if curl -fsSL --retry 3 --max-time 600 "$LEDGER_INDEX_URL" -o /tmp/index.tar.gz \
    && tar -xzf /tmp/index.tar.gz -C /app --no-same-owner --no-same-permissions \
      data/processed/index && have_index; then
    rm -f "$status" /tmp/index.tar.gz
  else
    echo "Downloading or unpacking the index from LEDGER_INDEX_URL failed." > "$status"
  fi
fi
[ -f "$status" ] && echo "WARNING: $(cat "$status") The UI will say so." >&2

uvicorn ledger.api.main:app --host 127.0.0.1 --port 8000 &
for _ in $(seq 60); do  # let the API come up before the first page load
  curl -fs http://127.0.0.1:8000/health > /dev/null 2>&1 && break
  sleep 1
done
exec streamlit run ui/streamlit_app.py --server.port 7860 --server.address 0.0.0.0 \
  --server.headless true --server.enableCORS false --server.enableXsrfProtection false \
  --browser.gatherUsageStats false
