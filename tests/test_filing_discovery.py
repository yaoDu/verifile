"""Filing discovery: high-volume filers, amendments and reassigned tickers.

These cases were all found by running the pipeline against ten large filers
(`evaluation/run_coverage_check.py`) rather than by reading the SEC docs.
"""

from __future__ import annotations

import pytest

from filing_change_analyst.sec.client import SecError
from filing_change_analyst.sec.filings import list_filings, select_filing_pair
from tests.conftest import FakeSecClient


class ShardedClient(FakeSecClient):
    """Serves a trimmed `recent` block plus one older submissions shard."""

    def __init__(self, subs: dict, shard: dict, facts: dict, docs: dict) -> None:
        super().__init__(subs, facts, docs)
        self._shard = shard
        self.shard_fetches: list[str] = []

    def fetch_json(self, url: str, *, ttl=None, refresh: bool = False):  # noqa: ANN001
        self.shard_fetches.append(url)
        return self._shard


def _client(sharded_submissions, companyfacts_json, later_html, earlier_html) -> ShardedClient:
    return ShardedClient(
        sharded_submissions["subs"],
        sharded_submissions["shard"],
        companyfacts_json,
        {
            "0000950170-25-100235": later_html,
            "0000950170-24-087843": earlier_html,
            "0000950170-23-035122": earlier_html,
            "0001564590-22-026876": earlier_html,
        },
    )


def _quarterly(accession: str, report: str, filed: str):  # noqa: ANN202
    from datetime import date

    from filing_change_analyst.models import Filing

    return Filing(
        cik="0000789019",
        ticker="MSFT",
        company_name="MICROSOFT CORP",
        form="10-Q",
        accession=accession,
        filing_date=date.fromisoformat(filed),
        report_date=date.fromisoformat(report),
        primary_document="msft.htm",
        fiscal_year_end="0630",
    )


class _StubClient:
    """Serves a fixed filing list, so pair *selection* can be tested on its own."""

    def __init__(self, filings) -> None:  # noqa: ANN001
        self.filings = filings


def test_quarterly_default_pairs_the_same_quarter_a_year_earlier(monkeypatch):
    """The 10-Q default must not select two consecutive quarters.

    Selecting the two newest filings is right for a 10-K and wrong for a 10-Q:
    consecutive quarters are three months apart, and a quarter is only
    comparable with the same quarter a year earlier. Before this was fixed the
    default 10-Q run refused itself every time, so the form was reachable only
    through the manual pair picker.
    """
    from filing_change_analyst.sec import filings as mod

    history = [
        _quarterly("acc-2026q3", "2026-03-31", "2026-04-28"),
        _quarterly("acc-2026q2", "2025-12-31", "2026-01-27"),
        _quarterly("acc-2026q1", "2025-09-30", "2025-10-28"),
        _quarterly("acc-2025q3", "2025-03-31", "2025-04-29"),
    ]
    monkeypatch.setattr(mod, "list_filings", lambda *a, **k: history)

    pair = mod.select_filing_pair(object(), "MSFT", "10-Q")

    assert pair.later.accession == "acc-2026q3"
    assert pair.earlier.accession == "acc-2025q3", "should skip back four filings, not one"
    assert pair.comparability_ok, pair.comparability_notes


def test_annual_default_still_takes_the_immediately_preceding_year(monkeypatch):
    """The 10-K path is unchanged by the quarterly fix."""
    from filing_change_analyst.sec import filings as mod
    from tests.conftest import _filing

    history = [
        _filing("acc-fy2025", "2025-06-30", "2025-07-30", "a.htm"),
        _filing("acc-fy2024", "2024-06-30", "2024-07-30", "b.htm"),
        _filing("acc-fy2023", "2023-06-30", "2023-07-27", "c.htm"),
    ]
    monkeypatch.setattr(mod, "list_filings", lambda *a, **k: history)

    pair = mod.select_filing_pair(object(), "MSFT", "10-K")

    assert (pair.later.accession, pair.earlier.accession) == ("acc-fy2025", "acc-fy2024")
    assert pair.comparability_ok


def test_no_comparable_counterpart_still_reports_the_refusal(monkeypatch):
    """With nothing in range, fall back to the newest pair and explain why."""
    from filing_change_analyst.sec import filings as mod

    history = [
        _quarterly("acc-b", "2026-03-31", "2026-04-28"),
        _quarterly("acc-a", "2025-12-31", "2026-01-27"),
    ]
    monkeypatch.setattr(mod, "list_filings", lambda *a, **k: history)

    pair = mod.select_filing_pair(object(), "MSFT", "10-Q")

    assert not pair.comparability_ok
    assert any("3 months apart" in n for n in pair.comparability_notes)


def test_recent_block_alone_would_find_only_one_filing(sharded_submissions):
    """Guards the premise: the trimmed fixture really does hold a single 10-K."""
    recent = sharded_submissions["subs"]["filings"]["recent"]
    assert len([f for f in recent["form"] if f.startswith("10-K")]) == 1


def test_older_shards_are_read_when_recent_is_insufficient(
    sharded_submissions, companyfacts_json, later_html, earlier_html
):
    client = _client(sharded_submissions, companyfacts_json, later_html, earlier_html)
    filings = list_filings(client, "MSFT", "10-K")
    assert len(filings) >= 2
    assert client.shard_fetches, "the older submissions shard was never requested"
    assert "CIK0000789019-submissions-001.json" in client.shard_fetches[0]


def test_pair_selection_succeeds_for_a_high_volume_filer(
    sharded_submissions, companyfacts_json, later_html, earlier_html
):
    client = _client(sharded_submissions, companyfacts_json, later_html, earlier_html)
    pair = select_filing_pair(client, "MSFT", "10-K")
    assert pair.later.report_date.year == 2025
    assert pair.earlier.report_date.year == 2024
    assert pair.comparability_ok


def test_accessions_are_deduped_across_recent_and_shards(
    sharded_submissions, companyfacts_json, later_html, earlier_html
):
    """A shard that overlaps `recent` must not produce duplicate filings."""
    overlapping = dict(sharded_submissions)
    overlapping["shard"] = sharded_submissions["full"]["filings"]["recent"]
    client = ShardedClient(
        sharded_submissions["subs"],
        overlapping["shard"],
        companyfacts_json,
        {"0000950170-25-100235": later_html, "0000950170-24-087843": earlier_html},
    )
    filings = list_filings(client, "MSFT", "10-K")
    accessions = [f.accession for f in filings]
    assert len(accessions) == len(set(accessions))


def test_shard_fetch_failure_does_not_break_discovery(
    sharded_submissions, companyfacts_json, later_html, earlier_html
):
    class Broken(ShardedClient):
        def fetch_json(self, url, *, ttl=None, refresh=False):  # noqa: ANN001
            raise SecError("simulated 503 on the older shard")

    client = Broken(
        sharded_submissions["subs"],
        sharded_submissions["shard"],
        companyfacts_json,
        {"0000950170-25-100235": later_html},
    )
    # Discovery degrades to what `recent` held rather than raising.
    filings = list_filings(client, "MSFT", "10-K")
    assert len(filings) == 1
    with pytest.raises(SecError) as exc:
        select_filing_pair(client, "MSFT", "10-K")
    assert "at least 2 are needed" in str(exc.value)


def test_registrant_with_no_filing_history_is_explained(companyfacts_json, later_html):
    """A reassigned ticker (XOM → 'ExxonMobil Holdings Corp') must be explained."""
    empty = {
        "cik": "0002115436",
        "name": "ExxonMobil Holdings Corp",
        "tickers": ["MSFT"],
        "fiscalYearEnd": "1231",
        "filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-07-01"],
                               "reportDate": ["2026-07-01"],
                               "accessionNumber": ["0000000000-26-000001"],
                               "primaryDocument": ["x.htm"]}, "files": []},
    }
    client = FakeSecClient(empty, companyfacts_json, {"x": later_html})
    with pytest.raises(SecError) as exc:
        select_filing_pair(client, "MSFT", "10-K")
    msg = str(exc.value)
    assert "Found 0 10-K filing(s)" in msg
    assert "newly registered entity" in msg


def test_completely_empty_registrant_is_reported(companyfacts_json, later_html):
    empty = {"cik": "0000000001", "name": "Shell Co", "tickers": ["MSFT"],
             "fiscalYearEnd": "1231", "filings": {"recent": {}, "files": []}}
    client = FakeSecClient(empty, companyfacts_json, {})
    with pytest.raises(SecError) as exc:
        list_filings(client, "MSFT", "10-K")
    assert "no filing history" in str(exc.value)
