"""Which fiscal year a filing belongs to, from the period it reports."""

from __future__ import annotations


def fiscal_year_of(report_date: str) -> int:
    """The fiscal year of a period ending on ``report_date`` (YYYY-MM-DD).

    Normally the calendar year the period ends in, which is how FinanceBench names
    filings (Walmart's FY2024 ends in January 2024). 52/53-week companies whose year
    ends on the Sunday nearest 31 December can end on 1-7 January: Johnson & Johnson's
    fiscal 2022 ended on 1 January 2023. Those belong to the year that just finished;
    labelled by the calendar year, two of its filings would share a year (2023) and
    the later one would hide the earlier.
    """
    year, month, day = int(report_date[:4]), int(report_date[5:7]), int(report_date[8:10])
    return year - 1 if month == 1 and day <= 7 else year
