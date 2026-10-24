"""Create or update the free Hugging Face Docker Space that serves the demo.

    HF_TOKEN=... GEMINI_API_KEY=... python scripts/deploy_hf_space.py --index-url URL

Run by the ``deploy-hf-space`` workflow, which hands the keys over from GitHub secrets so they
never pass through a chat or a file. Creates ``<your-user>/<space>`` on the free CPU tier (no
hardware is ever requested), sets the Space's secrets and variables first so the first build
already has them, then uploads ``deploy/hf-space/``. Safe to run again: it updates in place.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SPACE_FILES = ROOT / "deploy" / "hf-space"

# Space secrets (hidden after being set) and variables, by environment variable.
SECRETS = ("GEMINI_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
VARIABLES = ("LEDGER_DAILY_BUDGET", "LEDGER_PER_CLIENT_DAILY", "TRUSTED_PROXY_HOPS")


def deploy(api: Any, space: str, index_url: str, env: dict[str, str], folder: Path) -> str:
    """Create/update the Space and return its repo id (``user/space``)."""
    if not env.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is not set: add it as a repository secret first.")
    if not index_url.startswith("https://"):
        raise SystemExit("--index-url must be the https URL of the demo-index release asset.")
    repo_id = f"{api.whoami()['name']}/{space}"
    # No space_hardware: the default is the free CPU tier. Billing stays off.
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    for key in SECRETS:
        if env.get(key):
            api.add_space_secret(repo_id, key, env[key])
    api.add_space_variable(repo_id, "LEDGER_INDEX_URL", index_url)
    for key in VARIABLES:
        if env.get(key):
            api.add_space_variable(repo_id, key, env[key])
    api.upload_folder(
        folder_path=str(folder),
        repo_id=repo_id,
        repo_type="space",
        commit_message="Deploy the Ledger demo",
    )
    return repo_id


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--space", default="ledger", help="Space name under your account")
    p.add_argument("--index-url", required=True, help="URL of the demo-index release asset")
    args = p.parse_args()
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        raise SystemExit(
            "HF_TOKEN is not set: add a Hugging Face write token as a repository secret."
        )
    from huggingface_hub import HfApi

    repo_id = deploy(HfApi(token=token), args.space, args.index_url, dict(os.environ), SPACE_FILES)
    print(f"Deployed: https://huggingface.co/spaces/{repo_id}")
    print("The first build takes several minutes; the Space shows 'Building' until then.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
