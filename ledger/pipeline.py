"""The online question path: parse -> cache -> retrieve -> draft -> verify -> answer.

No number reaches the user until the NRF verifier has checked it. A claim
that fails is sent back to the model once with the verifier's correction
(VER-3); if it still fails the answer is returned flagged as unverified.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ledger.answer.citations import to_citation
from ledger.answer.generate import Draft, DraftClaim, Generator
from ledger.answer.llm import LLM, LLMError, LLMResult, QuotaExhausted
from ledger.cache.semantic_cache import SemanticCache
from ledger.config import LedgerConfig
from ledger.obs.tracing import Trace, Tracer
from ledger.retrieve.filters import CompanyRegistry, Filters, filters_from_question
from ledger.retrieve.hybrid import Retriever
from ledger.types import Answer, Citation, Claim, ScoredChunk
from ledger.verifier import ClaimCheck, ClaimVerifier

log = logging.getLogger(__name__)
verifier_log = logging.getLogger("ledger.verifier")

NOT_IN_FILINGS = "I could not find this in the filings I have."


class QuestionTooLong(ValueError):
    pass


@dataclass
class _Checked:
    claim: DraftClaim
    check: ClaimCheck | None
    problems: list[str] = field(default_factory=list)


@dataclass
class Ledger:
    retriever: Retriever
    generator: Generator
    config: LedgerConfig
    registry: CompanyRegistry | None = None
    verifier: ClaimVerifier = field(default_factory=ClaimVerifier)
    cache: SemanticCache | None = None
    tracer: Tracer = field(default_factory=Tracer)
    large_llm: LLM | None = None  # COST-1: used for the regeneration attempt
    max_question_chars: int = 1000

    # -- helpers -----------------------------------------------------------

    def _check(
        self, draft: Draft, passages: list[ScoredChunk], question: str = ""
    ) -> list[_Checked]:
        out = []
        for claim in draft.claims:
            problems = []
            valid = [n for n in claim.citations if 1 <= n <= len(passages)]
            if not valid:
                problems.append(f'The claim "{claim.text}" has no valid citation (ANS-1).')
                out.append(_Checked(claim, None, problems))
                continue
            check = None
            if self.config.answer.verify:
                check = self.verifier.verify(
                    claim.text,
                    [passages[n - 1].chunk.text for n in valid],
                    expression=claim.calculation,
                    stated_result=claim.result,
                    question=question or None,
                )
                if not check.passed:
                    problems.append(f'Claim "{claim.text}": {check.message}')
            out.append(_Checked(claim, check, problems))
        return out

    @staticmethod
    def _refusal(question: str, reason: str, passages: list[ScoredChunk]) -> Answer:
        return Answer(
            question=question,
            answer=NOT_IN_FILINGS,
            refused=True,
            refusal_reason=reason,
            closest_passages=[to_citation(i, p.chunk) for i, p in enumerate(passages[:3], 1)],
        )

    def _assemble(
        self, question: str, draft: Draft, checked: list[_Checked], passages: list[ScoredChunk]
    ) -> Answer:
        # Uncited claims are dropped (ANS-1); verifier failures are kept but flagged.
        kept = [c for c in checked if c.check is not None or not c.problems]
        if not kept:
            return self._refusal(question, "No claim could be supported with a citation.", passages)
        renumber: dict[int, int] = {}
        citations: list[Citation] = []
        claims: list[Claim] = []
        sentences = []
        for c in kept:
            nums = []
            for n in c.claim.citations:
                if not 1 <= n <= len(passages):
                    continue
                if n not in renumber:
                    renumber[n] = len(renumber) + 1
                    citations.append(to_citation(renumber[n], passages[n - 1].chunk))
                nums.append(renumber[n])
            verified = None if c.check is None else c.check.passed
            if c.check is not None and c.check.status.value == "no_numbers":
                verified = None
            claims.append(
                Claim(
                    text=c.claim.text,
                    citations=nums,
                    calculation=c.claim.calculation,
                    result=c.claim.result,
                    verified=verified,
                    verifier_status=c.check.status.value if c.check else None,
                )
            )
            sentences.append(c.claim.text + " " + "".join(f"[{n}]" for n in nums))
        flags = [cl.verified for cl in claims if cl.verified is not None]
        return Answer(
            question=question,
            answer=" ".join(sentences),
            claims=claims,
            citations=citations,
            confidence=draft.confidence,  # type: ignore[arg-type]
            verified=all(flags) if flags else None,
        )

    # -- main entry point ----------------------------------------------------

    def ask(self, question: str, filters: Filters | None = None) -> Answer:
        question = question.strip()
        if len(question) > self.max_question_chars:
            raise QuestionTooLong(f"Questions are limited to {self.max_question_chars} characters.")
        trace = self.tracer.start(question)
        llm_calls: list[LLMResult] = []

        with trace.span("parse") as s:
            f = filters_from_question(question, self.registry, filters)
            s.attrs.update(tickers=f.tickers, years=f.years)

        cached = None
        if self.cache is not None and self.config.cache.enabled:
            with trace.span("cache") as s:
                cached, sim = self.cache.lookup(question, f)
                s.attrs.update(hit=cached is not None, similarity=round(sim, 4))
        if cached is not None:
            answer = cached.model_copy(
                update={
                    "question": question,
                    "cache_hit": True,
                    "cost_usd": 0.0,
                    "regenerated": False,
                }
            )
            return self._finish(trace, answer, llm_calls)

        with trace.span("retrieve") as s:
            passages = self.retriever.retrieve(question, f)
            s.attrs.update(
                n=len(passages),
                chunk_ids=[p.chunk.id for p in passages],
                ranks=[p.ranks for p in passages],
            )

        min_score = self.config.retrieval.min_score
        if not passages or (
            self.retriever.reranker is not None and min_score and passages[0].score < min_score
        ):
            answer = self._refusal(question, "No relevant passage found.", passages)
            return self._finish(trace, answer, llm_calls, passages)

        with trace.span("generate") as s:
            draft, res = self.generator.draft(question, passages)
            llm_calls.append(res)
            s.attrs.update(
                model=res.model, input_tokens=res.input_tokens, output_tokens=res.output_tokens
            )

        if not draft.answerable:
            answer = self._refusal(question, draft.refusal_reason or "Not answerable.", passages)
            return self._finish(trace, answer, llm_calls, passages)

        with trace.span("verify") as s:
            checked = self._check(draft, passages, question)
            problems = [p for c in checked for p in c.problems]
            s.attrs.update(problems=len(problems))
        self._log_verifier(trace.request_id, checked, attempt=1)

        regenerated = False
        if problems and self.config.answer.regenerate_on_failure:
            regenerated = True
            with trace.span("generate_retry") as s:
                draft2, res2 = self._redraft(question, passages, problems)
                llm_calls.append(res2)
                s.attrs.update(
                    model=res2.model,
                    input_tokens=res2.input_tokens,
                    output_tokens=res2.output_tokens,
                )
            if draft2.answerable:
                with trace.span("verify_retry"):
                    checked2 = self._check(draft2, passages, question)
                self._log_verifier(trace.request_id, checked2, attempt=2)
                draft, checked = draft2, checked2
            elif not draft2.parse_error:
                answer = self._refusal(
                    question, draft2.refusal_reason or "Not answerable.", passages
                )
                return self._finish(trace, answer, llm_calls, passages)

        answer = self._assemble(question, draft, checked, passages)
        answer.regenerated = regenerated
        if self.cache is not None and self.config.cache.enabled and answer.verified is not False:
            self.cache.store(question, f, answer, {p.chunk.doc_id for p in passages})
        return self._finish(trace, answer, llm_calls, passages)

    def _redraft(
        self, question: str, passages: list[ScoredChunk], problems: list[str]
    ) -> tuple[Draft, LLMResult]:
        """Regenerate with the large model, falling back to the default one.

        Free tiers give the large model far fewer requests (Gemini: 20 a day),
        so a failure there must not cost the answer.
        """
        if self.large_llm is not None:
            try:
                return self.generator.draft(question, passages, problems, self.large_llm)
            except LLMError as e:
                log.warning("large model failed (%s); regenerating with the default model", e)
                if isinstance(e, QuotaExhausted):
                    self.large_llm = None  # spent for the day; stop asking
        return self.generator.draft(question, passages, problems)

    def _finish(
        self,
        trace: Trace,
        answer: Answer,
        calls: list[LLMResult],
        passages: list[ScoredChunk] | None = None,
    ) -> Answer:
        if passages:
            answer.retrieved = [p.chunk for p in passages]
        answer.request_id = trace.request_id
        answer.latency_ms = trace.elapsed_ms()
        if calls:
            answer.cost_usd = round(sum(c.cost_usd for c in calls), 6)
            answer.model = calls[-1].model
        trace.fields.update(
            answer=answer.answer,
            refused=answer.refused,
            verified=answer.verified,
            regenerated=answer.regenerated,
            cache_hit=answer.cache_hit,
            cost_usd=answer.cost_usd,
            model=answer.model,
            input_tokens=sum(c.input_tokens for c in calls),
            output_tokens=sum(c.output_tokens for c in calls),
        )
        self.tracer.finish(trace)
        return answer

    @staticmethod
    def _log_verifier(request_id: str, checked: list[_Checked], attempt: int) -> None:
        """VER-4: every verifier decision is logged so catch and false-alarm
        rates can be computed from the logs."""
        for c in checked:
            if c.check is None:
                continue
            verifier_log.info(
                "verifier_decision",
                extra={
                    "request_id": request_id,
                    "trace": {"attempt": attempt, "claim": c.claim.text, **c.check.as_dict()},
                },
            )
