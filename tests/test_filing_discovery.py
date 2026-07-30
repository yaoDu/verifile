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
