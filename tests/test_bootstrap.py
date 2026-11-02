from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from ledger.bootstrap import ensure_index, have_index, safe_extract

INDEX = "data/processed/index/table-1024-bge-small"


def _tar(path: Path, members: list[tuple[str, bytes | None, bytes]]) -> Path:
    """Write a .tar.gz of (name, content-or-None-for-symlink, type) members."""
    with tarfile.open(path, "w:gz") as tar:
        for name, content, kind in members:
            info = tarfile.TarInfo(name)
            if kind == b"link":
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
            else:
                data = content or b""
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return path


def test_the_index_is_unpacked(tmp_path: Path) -> None:
    archive = _tar(
        tmp_path / "a.tar.gz",
        [(f"{INDEX}/chunks.jsonl", b"{}\n", b"file"), (f"{INDEX}/vectors.npy", b"x", b"file")],
    )
    root = tmp_path / "app"
    assert safe_extract(archive, root) == 2
    assert have_index(root)


def test_nothing_outside_the_index_folder_is_written(tmp_path: Path) -> None:
    archive = _tar(
        tmp_path / "evil.tar.gz",
        [
            (f"{INDEX}/chunks.jsonl", b"{}\n", b"file"),
            ("ledger/pipeline.py", b"print('pwned')", b"file"),
            ("../escape.txt", b"x", b"file"),
            ("/tmp/absolute.txt", b"x", b"file"),
            (f"{INDEX}/../../../../escape2.txt", b"x", b"file"),
            (f"{INDEX}/link", None, b"link"),
        ],
    )
    root = tmp_path / "app"
    root.mkdir()
    assert safe_extract(archive, root) == 1
    written = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert written == [f"{INDEX}/chunks.jsonl"]
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "escape2.txt").exists()
    assert not (root / "ledger").exists()


def test_ensure_index_leaves_an_existing_index_alone(tmp_path: Path) -> None:
    (tmp_path / INDEX).mkdir(parents=True)
    (tmp_path / INDEX / "chunks.jsonl").write_text("{}\n")
    assert ensure_index(tmp_path, "https://invalid.example/never-fetched") is None


def test_ensure_index_reports_why_it_failed(tmp_path: Path) -> None:
    status = tmp_path / "status.txt"
    assert "https" in str(ensure_index(tmp_path, "http://example.com/x.tar.gz", status))
    assert status.read_text().strip().startswith("LEDGER_INDEX_URL must be an https URL")


@pytest.mark.parametrize("url", ["", "ftp://x/y", "file:///etc/passwd"])
def test_only_https_urls_are_fetched(tmp_path: Path, url: str) -> None:
    assert ensure_index(tmp_path, url, tmp_path / "s.txt") is not None
