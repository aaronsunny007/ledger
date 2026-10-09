"""Embedders. The real one (BGE) lives in ``models.py`` behind an optional extra.

``HashingEmbedder`` is a deterministic, dependency-free bag-of-words
embedding. It is not a good retriever; it exists so tests and CI run with
no model download and no network.
"""

from __future__ import annotations

import hashlib
import re
from itertools import pairwise
from typing import Protocol

import numpy as np
import numpy.typing as npt

Vector = npt.NDArray[np.float32]

_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> Vector: ...

    def embed_query(self, text: str) -> Vector: ...


class HashingEmbedder:
    def __init__(self, dim: int = 512):
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _one(self, text: str) -> Vector:
        v = np.zeros(self.dim, dtype=np.float32)
        tokens = tokenize(text)
        for tok in tokens + [a + "_" + b for a, b in pairwise(tokens)]:
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = float(np.linalg.norm(v))
        return v / n if n else v

    def embed_documents(self, texts: list[str]) -> Vector:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._one(t) for t in texts])

    def embed_query(self, text: str) -> Vector:
        return self._one(text)


def get_embedder(name: str) -> Embedder:
    if name == "hashing":
        return HashingEmbedder()
    from ledger.retrieve.models import SentenceTransformerEmbedder

    model = {"bge-small": "BAAI/bge-small-en-v1.5", "bge-base": "BAAI/bge-base-en-v1.5"}.get(
        name, name
    )
    return SentenceTransformerEmbedder(model)
