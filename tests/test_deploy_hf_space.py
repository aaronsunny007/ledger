from __future__ import annotations

from pathlib import Path

import pytest

from scripts.deploy_hf_space import SPACE_FILES, deploy

URL = "https://github.com/me/ledger/releases/download/demo-index/demo-index.tar.gz"


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def __getattr__(self, name: str):  # records every call, in order
        def call(*args: object, **kwargs: object) -> object:
            self.calls.append((name, args, kwargs))
            return {"name": "alice"} if name == "whoami" else None

        return call

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


def test_deploy_sets_secrets_before_the_first_build_and_never_asks_for_hardware() -> None:
    api = FakeApi()
    env = {"GEMINI_API_KEY": "k", "LANGFUSE_PUBLIC_KEY": "p", "LEDGER_DAILY_BUDGET": "250"}
    assert deploy(api, "ledger", URL, env, SPACE_FILES) == "alice/ledger"
    names = api.names()
    assert (
        names.index("create_repo") < names.index("add_space_secret") < names.index("upload_folder")
    )
    assert names.index("add_space_variable") < names.index("upload_folder")
    create = next(c for c in api.calls if c[0] == "create_repo")
    assert create[2]["space_sdk"] == "docker" and "space_hardware" not in create[2]
    secrets = {c[1][1] for c in api.calls if c[0] == "add_space_secret"}
    assert secrets == {"GEMINI_API_KEY", "LANGFUSE_PUBLIC_KEY"}  # unset optional keys are skipped
    variables = {c[1][1]: c[1][2] for c in api.calls if c[0] == "add_space_variable"}
    assert variables == {"LEDGER_INDEX_URL": URL, "LEDGER_DAILY_BUDGET": "250"}


def test_deploy_refuses_without_the_gemini_key_or_an_https_index() -> None:
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        deploy(FakeApi(), "ledger", URL, {}, SPACE_FILES)
    with pytest.raises(SystemExit, match="https"):
        deploy(FakeApi(), "ledger", "http://x", {"GEMINI_API_KEY": "k"}, SPACE_FILES)


def test_the_space_folder_has_the_three_files_a_space_needs() -> None:
    names = {p.name for p in Path(SPACE_FILES).iterdir()}
    assert {"Dockerfile", "README.md", "start.sh"} <= names
