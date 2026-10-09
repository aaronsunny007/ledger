"""Build a ``Ledger`` from settings + config. Shared by the API, CLI and eval."""

from __future__ import annotations

from pathlib import Path

from ledger.answer.generate import Generator
from ledger.answer.llm import DEFAULT_MODELS, LLM, make_llm
from ledger.cache.semantic_cache import SemanticCache
from ledger.config import ROOT, LedgerConfig, Settings
from ledger.obs.tracing import JsonlSink, Tracer, TraceSink
from ledger.pipeline import Ledger
from ledger.retrieve.embed import Embedder, get_embedder
from ledger.retrieve.filters import CompanyRegistry
from ledger.retrieve.hybrid import Retriever
from ledger.retrieve.rerank import get_reranker
from ledger.retrieve.store import Index, InMemoryIndex

TRACE_LOG = ROOT / "data" / "traces" / "requests.jsonl"


def build_index(settings: Settings, embedder: Embedder, config: LedgerConfig) -> Index:
    if settings.store == "postgres":
        from ledger.retrieve.pgstore import PgVectorIndex

        return PgVectorIndex(settings.database_url, embedder.dim)
    return InMemoryIndex.load(settings.index_path / config.index_name())


def build_llms(settings: Settings) -> tuple[LLM, LLM | None]:
    small, large = DEFAULT_MODELS[settings.llm_provider]
    kw = {
        "gemini_api_key": settings.gemini_api_key,
        "groq_api_key": settings.groq_api_key,
        "ollama_url": settings.ollama_url,
    }
    llm = make_llm(settings.llm_provider, settings.llm_model or small, **kw)
    large_name = settings.llm_model_large or large
    big = make_llm(settings.llm_provider, large_name, **kw) if large_name != llm.model else None
    return llm, big


def build_ledger(
    settings: Settings | None = None,
    config: LedgerConfig | None = None,
    *,
    llm: LLM | None = None,
    large_llm: LLM | None = None,
    index: Index | None = None,
    embedder: Embedder | None = None,
    trace_log: Path | None = TRACE_LOG,
) -> Ledger:
    settings = settings or Settings()
    config = config or LedgerConfig.load(settings.retrieval_config)
    embedder = embedder or get_embedder(config.retrieval.embedder)
    index = index if index is not None else build_index(settings, embedder, config)
    reranker = get_reranker(config.retrieval.reranker) if config.retrieval.rerank else None
    if llm is None:
        llm, large_llm = build_llms(settings)

    sinks: list[TraceSink] = [JsonlSink(trace_log)] if trace_log else []
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        from ledger.obs.langfuse_sink import LangfuseSink

        sinks.append(
            LangfuseSink(
                settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_host
            )
        )

    corpus = ROOT / "configs" / "corpus.yaml"
    return Ledger(
        retriever=Retriever(index, embedder, config.retrieval, reranker),
        generator=Generator(llm, config.answer.max_context_chars),
        config=config,
        registry=CompanyRegistry.from_yaml(corpus) if corpus.exists() else None,
        cache=SemanticCache(embedder, config.cache.threshold) if config.cache.enabled else None,
        tracer=Tracer(sinks),
        large_llm=large_llm,
        max_question_chars=settings.max_question_chars,
    )
