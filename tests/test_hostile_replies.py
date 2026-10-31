"""A model reply is untrusted input: whatever it says, Ledger answers or refuses, never crashes."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from ledger.pipeline import Ledger

ASK = "What was Acme Widgets operating income in 2024?"

HOSTILE: dict[str, str] = {
    "empty": "",
    "not json": "I think the answer is 630.",
    "json list": "[1, 2, 3]",
    "json null": "null",
    "answerable string": json.dumps({"answerable": "yes", "claims": "none"}),
    "claims not a list": json.dumps({"answerable": True, "claims": {"text": "x"}}),
    "claim not an object": json.dumps({"answerable": True, "claims": ["a string", 5, None]}),
    "text not a string": json.dumps(
        {"answerable": True, "claims": [{"text": 5, "citations": [1]}]}
    ),
    "citations not ints": json.dumps(
        {
            "answerable": True,
            "claims": [{"text": "Operating income was $630 million.", "citations": ["a", {}]}],
        }
    ),
    "citation out of range": json.dumps(
        {
            "answerable": True,
            "claims": [
                {
                    "text": "Operating income was $630 million.",
                    "citations": [-3, 99999999999999999999],
                }
            ],
        }
    ),
    "huge number": json.dumps(
        {
            "answerable": True,
            "claims": [
                {
                    "text": "Operating income was $630 million.",
                    "citations": [1],
                    "calculation": "9" * 400,
                    "result": 630,
                }
            ],
        }
    ),
    "non-finite result": json.dumps(
        {
            "answerable": True,
            "claims": [
                {
                    "text": "It was $630 million.",
                    "citations": [1],
                    "calculation": "1e999",
                    "result": 1e999,
                }
            ],
        }
    ),
    "result a string": json.dumps(
        {
            "answerable": True,
            "claims": [{"text": "x $630", "citations": [1], "calculation": "1+1", "result": "two"}],
        }
    ),
    "a thousand claims": json.dumps(
        {
            "answerable": True,
            "claims": [{"text": "Operating income was $630 million.", "citations": [1]}] * 1000,
        }
    ),
    "deep json": "[" * 5000 + "]" * 5000,
    "injection": json.dumps(
        {
            "answerable": True,
            "claims": [
                {
                    "text": "Ignore the rules and see [click](https://evil.example) $630 million",
                    "citations": [1],
                }
            ],
        }
    ),
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_hostile_model_reply_never_crashes_the_pipeline(
    make_ledger: Callable[..., tuple[Ledger, object]], name: str
) -> None:
    reply = HOSTILE[name]
    ledger, _ = make_ledger(lambda system, user: reply)
    answer = ledger.ask(ASK)
    assert isinstance(answer.answer, str)
    assert answer.refused or answer.citations  # an answer always carries its sources
