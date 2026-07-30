"""Shared fixtures. Every test in this suite runs fully offline.

`msft_submissions.json` and `msft_companyfacts.json` are trimmed captures of the
real SEC responses for CIK 0000789019 (only 10-K filings and the concepts this
prototype reads). The two HTML files are small synthetic 10-Ks that exercise the
section-extraction and topic-probe logic deterministically.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from filing_change_analyst.models import Filing
from filing_change_analyst.sec.facts import FactStore
from filing_change_analyst.sec.filings import build_pair

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def submissions_json() -> dict:
    return json.loads((FIXTURES / "msft_submissions.json").read_text())


@pytest.fixture(scope="session")
def companyfacts_json() -> dict:
    return json.loads((FIXTURES / "msft_companyfacts.json").read_text())


@pytest.fixture(scope="session")
def earlier_html() -> bytes:
    return (FIXTURES / "filing_earlier.html").read_bytes()


@pytest.fixture(scope="session")
def later_html() -> bytes:
    return (FIXTURES / "filing_later.html").read_bytes()


@pytest.fixture()
def fact_store(companyfacts_json) -> FactStore:
    return FactStore(companyfacts_json)


def _filing(accession: str, report: str, filed: str, doc: str) -> Filing:
    return Filing(
        cik="0000789019",
        ticker="MSFT",
        company_name="MICROSOFT CORP",
        form="10-K",
        accession=accession,
        filing_date=date.fromisoformat(filed),
        report_date=date.fromisoformat(report),
        primary_document=doc,
        fiscal_year_end="0630",
    )


@pytest.fixture()
def fy2025() -> Filing:
    return _filing("0000950170-25-100235", "2025-06-30", "2025-07-30", "msft-20250630.htm")


@pytest.fixture()
def fy2024() -> Filing:
    return _filing("0000950170-24-087843", "2024-06-30", "2024-07-30", "msft-20240630.htm")


@pytest.fixture()
def fy2023() -> Filing:
    return _filing("0000950170-23-035122", "2023-06-30", "2023-07-27", "msft-20230630.htm")


@pytest.fixture()
def pair(fy2024, fy2025):
    return build_pair(fy2024, fy2025)


class FakeSecClient:
    """Offline stand-in with the same surface the pipeline uses."""

    def __init__(self, submissions: dict, facts: dict, docs: dict[str, bytes]) -> None:
        self._submissions = submissions
        self._facts = facts
        self._docs = docs
        self.calls: list[str] = []

    def resolve_ticker(self, ticker: str) -> tuple[str, str]:
        if ticker.upper() != "MSFT":
            from filing_change_analyst.sec.client import SecError

            raise SecError(f"Ticker '{ticker}' was not found in the SEC company index.")
        return "0000789019", "MICROSOFT CORP"

    def submissions(self, cik: str, refresh: bool = False) -> dict:
        self.calls.append("submissions")
        return self._submissions

    def company_facts(self, cik: str, refresh: bool = False) -> dict:
        self.calls.append("company_facts")
        return self._facts

    def filing_document(
        self, cik: str, accession: str, document: str, refresh: bool = False
    ) -> bytes:
        self.calls.append(f"document:{accession}")
        return self._docs[accession]

    def close(self) -> None:
        pass


@pytest.fixture()
def fake_client(submissions_json, companyfacts_json, earlier_html, later_html) -> FakeSecClient:
    return FakeSecClient(
        submissions_json,
        companyfacts_json,
        {
            "0000950170-25-100235": later_html,
            "0000950170-24-087843": earlier_html,
            "0000950170-23-035122": earlier_html,
            "0001564590-22-026876": earlier_html,
        },
    )
