import pytest

from ledger.verifier import (
    ClaimStatus,
    ClaimVerifier,
    PostHocArithmeticVerifier,
    UnsafeExpressionError,
    safe_eval_arithmetic,
)
from ledger.verifier.arithmetic import find_last_expression
from ledger.verifier.numbers import extract_amounts, extract_final_answer, is_probably_year

# --- Financial-NRF tests, carried over unchanged in substance -------------

EVIDENCE = "Net revenue was $5829 million in 2015 and $5735 million in 2014."


@pytest.fixture
def nrf() -> PostHocArithmeticVerifier:
    return PostHocArithmeticVerifier()


def test_correct_grounded_calculation_verifies(nrf: PostHocArithmeticVerifier) -> None:
    r = nrf.verify(
        "Reasoning: $5829 - $5735 = $94 million\n\nFinal Answer: $94 million\n\nConfidence: 1",
        EVIDENCE,
    )
    assert r.verified is True


def test_arithmetic_slip_caught(nrf: PostHocArithmeticVerifier) -> None:
    r = nrf.verify(
        "Reasoning: $5829 - $5735 = $104 million\n\nFinal Answer: $104 million", EVIDENCE
    )
    assert r.verified is False and r.execution_consistent is False


def test_ungrounded_operand_caught(nrf: PostHocArithmeticVerifier) -> None:
    r = nrf.verify(
        "Reasoning: $5829 - $918.7 = $4910.3 million\n\nFinal Answer: $4910.3 million", EVIDENCE
    )
    assert r.verified is False and r.operands_grounded is False


def test_unparseable_reasoning_flagged(nrf: PostHocArithmeticVerifier) -> None:
    r = nrf.verify("Reasoning: The net revenue increased.\n\nFinal Answer: 94", EVIDENCE)
    assert r.parseable is False and r.verified is False


def test_chained_expression_verifies(nrf: PostHocArithmeticVerifier) -> None:
    r = nrf.verify(
        "Reasoning: (153.7 - 139.9) / 139.9 * 100 = 9.86\n\nFinal Answer: 9.86%",
        "as of 2011 and 2010 were $153.7 million and $139.9 million, respectively.",
    )
    assert r.verified is True


def test_expression_without_inline_result_still_catches_slip(
    nrf: PostHocArithmeticVerifier,
) -> None:
    # Regression from Financial-NRF Experiment 1 (SYY/2006/page_71.pdf-1).
    evidence = (
        "total rental expense under operating leases was $100690000, $92710000, "
        "and $86842000 in fiscal 2006, 2005 and 2004, respectively."
    )
    r = nrf.verify(
        "Reasoning: The total rental expense for fiscal 2005 was $92,710,000 and for fiscal 2006 "
        "it was $100,690,000. So, the calculation is: ((100690000 - 92710000) / 92710000) * 100."
        "\n\nFinal Answer: 10.04%\n\nConfidence: 0.9",
        evidence,
    )
    assert r.parseable is True
    assert r.verified is False and r.execution_consistent is False


def test_sentence_boundary_period_is_not_a_decimal() -> None:
    assert (
        find_last_expression("Total facilities = 56.0. 8.1 / 56.0 * 100 = 14.46")
        == (["8.1 / 56.0 * 100", " 14.46"][0])
    )


def test_final_answer_not_confused_with_confidence() -> None:
    p = extract_final_answer("Reasoning:\n5829 - 5735 = 94\n\nFinal Answer: 94\n\nConfidence: 1")
    assert p is not None and p.value == 94.0


# --- safe evaluation ------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    ["__import__('os').system('ls')", "2 ** 10", "abs(-3)", "1 if 1 else 2", "'a' + 'b'"],
)
def test_safe_eval_rejects_non_arithmetic(expr: str) -> None:
    with pytest.raises((UnsafeExpressionError, SyntaxError)):
        safe_eval_arithmetic(expr)


def test_safe_eval_handles_currency_and_commas() -> None:
    assert safe_eval_arithmetic("($391,035 - $383,285) / $383,285 * 100") == pytest.approx(
        2.0220, rel=1e-4
    )


def test_safe_eval_rejects_huge_input() -> None:
    with pytest.raises(UnsafeExpressionError):
        safe_eval_arithmetic("1+" * 400 + "1")


# --- number parsing additions ----------------------------------------------


def test_amounts_understand_scale_words_and_parentheses() -> None:
    nums = extract_amounts("revenue of $1.2 billion and a loss of (1,234) and 45.6%")
    assert nums[0].magnitude == pytest.approx(1.2e9)
    assert nums[1].value == -1234
    assert nums[2].is_percentage and nums[2].value == 45.6


def test_bare_m_without_currency_is_not_millions() -> None:
    assert extract_amounts("a 10 m wall")[0].magnitude == 10


def test_year_detection() -> None:
    assert is_probably_year(extract_amounts("FY2024")[0])
    assert not is_probably_year(extract_amounts("$2,024")[0])


# --- claim verifier (VER-2) -----------------------------------------------

APPLE_TABLE = (
    "Total net sales | 391,035 | 383,285 | 394,328\n"
    "Gross margin | 180,683 | 169,148 | 170,782\n(in millions)"
)


@pytest.fixture
def cv() -> ClaimVerifier:
    return ClaimVerifier()


def test_claim_with_correct_growth_calculation_verifies(cv: ClaimVerifier) -> None:
    r = cv.verify(
        "Net sales grew from $383.3 billion in FY2023 to $391.0 billion in FY2024, up 2.0%.",
        [APPLE_TABLE],
        expression="(391035 - 383285) / 383285 * 100",
        stated_result=2.02,
    )
    assert r.status is ClaimStatus.VERIFIED, r.message


def test_claim_with_wrong_arithmetic_is_caught(cv: ClaimVerifier) -> None:
    r = cv.verify(
        "Net sales grew 4.5% in FY2024.",
        [APPLE_TABLE],
        expression="(391035 - 383285) / 383285 * 100",
        stated_result=4.5,
    )
    assert r.status is ClaimStatus.MISMATCH
    assert r.recomputed_result == pytest.approx(2.022, rel=1e-3)
    assert "2.02" in r.message


def test_claim_with_invented_operand_is_caught(cv: ClaimVerifier) -> None:
    r = cv.verify(
        "Net sales grew 3.1%.",
        [APPLE_TABLE],
        expression="(395000 - 383285) / 383285 * 100",
        stated_result=3.0565,
    )
    assert r.status is ClaimStatus.UNGROUNDED
    assert "395000" in r.ungrounded_numbers


def test_claim_number_not_in_citation_is_caught(cv: ClaimVerifier) -> None:
    r = cv.verify("Gross margin was $200.1 billion in FY2024.", [APPLE_TABLE])
    assert r.status is ClaimStatus.UNGROUNDED


def test_claim_number_scaled_from_table_is_grounded(cv: ClaimVerifier) -> None:
    r = cv.verify("Gross margin was $180.7 billion in FY2024.", [APPLE_TABLE])
    assert r.passed


def test_claim_without_numbers_passes(cv: ClaimVerifier) -> None:
    assert cv.verify("Apple designs smartphones.", ["Apple designs smartphones."]).status is (
        ClaimStatus.NO_NUMBERS
    )


def test_unsafe_calculation_is_unparseable(cv: ClaimVerifier) -> None:
    r = cv.verify("x", [APPLE_TABLE], expression="__import__('os')", stated_result=1.0)
    assert r.status is ClaimStatus.UNPARSEABLE and not r.passed


# --- plausibility (unit and scale errors the arithmetic check cannot see) --

from ledger.verifier.plausibility import check_plausible, expected_kind  # noqa: E402


@pytest.mark.parametrize(
    ("question", "claim", "result", "flagged"),
    [
        # The two week-3 failures:
        (
            "What is the FY2018 fixed asset turnover ratio for CVS Health?",
            "The FY2018 fixed asset turnover ratio for CVS Health is 1798.24.",
            1798.24,
            True,
        ),
        (
            "What is the FY2017 operating cash flow ratio for Adobe?",
            "The operating cash flow ratio for Adobe in FY2017 is 825.77.",
            None,
            True,
        ),
        # Their correct versions pass:
        (
            "What is the FY2018 fixed asset turnover ratio for CVS Health?",
            "The ratio is 17.98.",
            17.98,
            False,
        ),
        ("What is the FY2017 operating cash flow ratio for Adobe?", "It is 0.83.", None, False),
        # A ratio stated as a percentage is fine:
        ("What is Coca Cola's FY2022 dividend payout ratio?", "It was 80.1%.", None, False),
        ("What is Amazon's FY2017 days payable outstanding?", "DPO was 93.86 days.", 93.86, False),
        ("What is Amazon's FY2017 days payable outstanding?", "DPO was 9386 days.", 9386, True),
        ("What was Best Buy's gross margin in FY2023?", "It was 2141%.", None, True),
        # An amount question has no expected kind; big numbers are fine.
        ("What were Best Buy's inventories in FY2019?", "$5,409 million.", None, False),
        # A scaled amount inside a ratio question is not the answer being checked.
        ("What is the quick ratio for AMD?", "Current assets were $9.6 billion.", None, False),
    ],
)
def test_plausibility(question: str, claim: str, result: float | None, flagged: bool) -> None:
    assert (check_plausible(question, claim, result) is not None) is flagged


def test_expected_kind_order() -> None:
    assert expected_kind("cash conversion cycle ratio")  # days wins over ratio
    assert expected_kind("cash conversion cycle ratio").name == "days"  # type: ignore[union-attr]
    assert expected_kind("What industry is Amcor in?") is None


def test_claim_verifier_flags_implausible_after_arithmetic_passes(cv: ClaimVerifier) -> None:
    table = "Net revenues | 194,579\nProperty and equipment, net | 11,349 | 10,292"
    r = cv.verify(
        "The FY2018 fixed asset turnover ratio for CVS Health is 1798.24.",
        [table],
        expression="194579 / ((11349 + 10292) / 2) * 100",
        stated_result=1798.24,
        question="What is the FY2018 fixed asset turnover ratio for CVS Health?",
    )
    assert r.status is ClaimStatus.IMPLAUSIBLE and "multiply by 100" in r.message
