"""Start the demo inside one process: fetch the prebuilt index, then run the API on loopback.

Streamlit Community Cloud runs a single command, ``streamlit run ui/streamlit_app.py``, so the
UI starts the API itself (``LEDGER_API=embedded``). The API keeps enforcing the daily quota; it
is only reachable on 127.0.0.1, so visitors go through the UI.
"""

from __future__ import annotations

import os
import tarfile
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath

import httpx

DEFAULT_INDEX_URL = (
    "https://github.com/aaronsunny007/ledger/releases/download/demo-index/demo-index.tar.gz"
)
INDEX_DIR = "data/processed/index"
MAX_INDEX_BYTES = 800_000_000  # the demo index is about 155 MB; refuse anything absurd


def have_index(root: Path) -> bool:
    return any((root / INDEX_DIR).glob("*/chunks.jsonl"))


def safe_extract(archive: Path, dest: Path) -> int:
    """Unpack only regular files and folders under ``data/processed/index`` from ``archive``.

    Anything else (other paths, absolute or ``..`` names, links, devices) is skipped, so a
    tampered archive cannot write outside the index folder or replace code. Returns the number
    of files written.
    """
    written = 0
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            inside = parts[: len(PurePosixPath(INDEX_DIR).parts)] == PurePosixPath(INDEX_DIR).parts
            clean = not PurePosixPath(member.name).is_absolute() and ".." not in parts
            if not (inside and clean and (member.isfile() or member.isdir())):
                continue
            tar.extract(member, dest, filter="data")
            written += member.isfile()
    return written


def ensure_index(root: Path, url: str, status_file: Path | None = None) -> str | None:
    """Make sure an index is under ``root``; return ``None`` on success or the reason it failed.

    The reason is also written to ``status_file`` (the UI shows it); success removes the file.
    """
    status_file = status_file or root / "data" / "index-status.txt"
    if have_index(root):
        status_file.unlink(missing_ok=True)
        return None
    reason = _download_index(root, url)
    if reason:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(reason + "\n")
        return reason
    status_file.unlink(missing_ok=True)
    return None


def _download_index(root: Path, url: str) -> str | None:
    if not url.startswith("https://"):
        return "LEDGER_INDEX_URL must be an https URL."
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            size = 0
            with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_INDEX_BYTES:
                        return "The index download is larger than expected; refusing it."
                    tmp.write(chunk)
        try:
            if safe_extract(tmp_path, root) == 0 or not have_index(root):
                return "The index archive did not contain an index."
        finally:
            tmp_path.unlink(missing_ok=True)
    except (httpx.HTTPError, tarfile.TarError, OSError) as e:
        return f"Downloading or unpacking the index failed ({type(e).__name__})."
    return None


def set_demo_defaults(root: Path) -> None:
    """Interactive limits for a public demo, unless the owner already chose otherwise."""
    os.environ.setdefault("STORE", "memory")
    os.environ.setdefault("LEDGER_BUDGET_FILE", str(root / "data" / "budget.json"))
    os.environ.setdefault("LLM_MAX_RETRY_WAIT", "15")
    os.environ.setdefault("LLM_TIMEOUT", "45")


def start_api(port: int = 8000, wait: float = 120.0) -> str:
    """Run the API in a background thread of this process; return its base URL once healthy."""
    import uvicorn

    base = f"http://127.0.0.1:{port}"
    config = uvicorn.Config("ledger.api.main:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="ledger-api", daemon=True).start()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                return base
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("The Ledger API did not start in time.")
