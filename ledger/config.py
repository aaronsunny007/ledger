"""Settings from environment (.env) plus the YAML experiment configs.

Secrets and deployment choices come from the environment. Experiment knobs
(chunking, k, reranker on/off) live in ``configs/retrieval.yaml`` so an eval
run can record exactly which settings produced its numbers (RET-4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # SEC asks for a contact in the User-Agent: "Name email@example.com".
    sec_user_agent: str = "Ledger research contact@example.com"

    llm_provider: Literal["gemini", "groq", "ollama", "fake"] = "gemini"
    llm_model: str = ""  # empty -> provider default (cheap tier)
    llm_model_large: str = ""  # used for hard / failed-verifier questions (COST-1)
    gemini_api_key: str = ""
    groq_api_key: str = ""
    ollama_url: str = "http://localhost:11434"

    store: Literal["memory", "postgres"] = "memory"
    database_url: str = "postgresql://ledger:ledger@localhost:5432/ledger"
    index_path: Path = ROOT / "data" / "processed" / "index"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    daily_spend_cap_usd: float = 1.0  # COST-3
    rate_limit_per_minute: int = 10  # COST-3, per IP
    max_question_chars: int = 1000  # SEC-3; FinanceBench questions run to ~700

    retrieval_config: Path = ROOT / "configs" / "retrieval.yaml"


class ChunkingConfig(BaseModel):
    strategy: Literal["fixed", "section", "table"] = "table"
    size: int = 1024  # characters for fixed; max size for the others
    overlap: int = 128


class RetrievalConfig(BaseModel):
    embedder: Literal["hashing", "bge-small", "bge-base"] = "bge-small"
    mode: Literal["vector", "keyword", "hybrid"] = "hybrid"
    candidates: int = 30  # RET-3: top 30-50 into the reranker
    rrf_k: int = 60
    rerank: bool = True
    reranker: str = "BAAI/bge-reranker-base"
    top_k: int = 6  # passages given to the generator
    min_score: float = 0.0  # below this after rerank -> refuse (ANS-3)
    # Always include the primary statements a question needs (ingest.statements).
    pin_statements: bool = True
    # "FY2017 vs FY2019" -> search the FY2019 filing, which holds the comparatives.
    latest_year_only: bool = True


class AnswerConfig(BaseModel):
    verify: bool = True
    regenerate_on_failure: bool = True
    max_context_chars: int = 24000


class CacheConfig(BaseModel):
    enabled: bool = True
    threshold: float = 0.92


class LedgerConfig(BaseModel):
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    answer: AnswerConfig = Field(default_factory=AnswerConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    def index_name(self) -> str:
        """Each chunking + embedder combination gets its own saved index."""
        c = self.chunking
        return f"{c.strategy}-{c.size}-{self.retrieval.embedder}"

    @classmethod
    def load(cls, path: Path | None = None) -> LedgerConfig:
        path = path or Settings().retrieval_config
        if not path.exists():
            return cls()
        return cls.model_validate(yaml.safe_load(path.read_text()) or {})
