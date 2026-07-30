# Resume-ready bullets

All figures below are measured, not estimated. Sources: `evaluation/RESULTS.md`, `pytest -q`, and the
default MSFT FY2025/FY2024 run.

## Primary bullet

> Built an evidence-first equity-research application that compares consecutive SEC filings, calculates
> 21 financial metrics deterministically from XBRL facts with full provenance, detects material changes
> in management commentary and risk disclosures, and generates citation-backed analyst briefs that
> separate verified facts from model interpretation — 100% metric, period, retrieval and citation
> accuracy across a 22-question evaluation.

## Alternates by emphasis

**Reliability / correctness**

> Designed a filing-comparison engine where all financial arithmetic is performed in Python from SEC XBRL
> facts and period compatibility is validated before any calculation, eliminating the quarter-vs-year and
> percent-vs-percentage-point errors that silently corrupt period-over-period analysis; 131 offline tests
> and a 22-question evaluation, both runnable with no API key.

**AI engineering**

> Engineered a constrained LLM layer behind four mechanical gates — schema validation, citation
> resolution, numeric grounding against pre-computed metrics, and recommendation detection — so that a
> model claim containing an unsourced figure is discarded rather than displayed; the deterministic
> analysis is complete and usable before the first model token is requested.

**Product judgement**

> Identified a repetitive, time-sensitive step in fundamental equity research and shipped a working
> analyst tool for it: one-click comparison of a company's two most recent filings, earlier and later
> evidence shown side by side with SEC accession-level provenance, explicit insufficient-evidence
> outcomes, and a downloadable nine-section brief that labels every line as fact, calculation,
> management statement, interpretation, caveat or open question.

**Retrieval**

> Built a reproducible section-aware retrieval layer over SEC filings (BM25 with metadata filters,
> provenance-carrying chunks, fixed topic probes) and diagnosed via evaluation that BM25 score alone
> cannot separate answerable from unanswerable questions — replacing it with IDF-weighted content-term
> coverage, which separated 16 answerable from 6 unanswerable questions cleanly.

**Data engineering**

> Implemented transparent XBRL fact selection with filing-scoped resolution rules, duplicate and conflict
> handling, 52/53-week calendar tolerance, and an automatic restatement check that flags when a prior
> period was re-tagged in the newer filing — so a reclassification is surfaced rather than absorbed into
> a year-over-year change.

## Measured facts available to quote

| Claim | Evidence |
|---|---|
| 21 financial metrics compared, all computed in Python | `analytics/metric_definitions.py`; `DISPLAY_ORDER` |
| 100% on metric correctness, period correctness, retrieval success, citation validity, citation support, numerical accuracy | `evaluation/RESULTS.md` (11/11, 2/2, 7/7, 11/11, 4/4, 4/4) |
| 0 of 7 material changes lacking both-period evidence or a caveat | `evaluation/RESULTS.md`, unsupported-claim rate |
| 142 automated tests, fully offline, ~1.5 s | `pytest -q` |
| 10/11 large filers produce a usable comparison with text evidence | `evaluation/COVERAGE.md` |
| Full pipeline in ~4–5 s warm | `evaluation/RESULTS.md`, pipeline run time |
| 471 provenance-carrying evidence chunks indexed for the default pair | default MSFT run |
| Risk diff: 34 → 31 headings, 2 new / 5 removed / 29 retained | default MSFT run |

**Generalisation, measured**

> Measured coverage across 11 large filers rather than asserting generality, which surfaced three defects
> a single-company demo could not: heading-markup assumptions that produced zero text evidence for four
> filers, a filing-discovery path that refused high-volume filers whose 10-Ks fall outside the recent
> submissions index, and a silent zero-evidence result; raised coverage from 6/11 to 10/11.

## Second talking point

Microsoft filed its FY2026 10-K during the build. The system consumed the new filing with no code change
(21/21 metrics; revenue +17.8%, capex +79.6%, free cash flow −6.5%), and the evaluation stayed valid
because it pins the filing pair by accession number rather than always taking "the latest" — so newly
published data cannot silently invalidate hand-read ground truth.

## Talking point worth keeping

The evaluation caught a real defect: the first insufficient-evidence gate used a BM25 score threshold, and
an off-topic control question scored higher than several genuine ones. Measuring 16 answerable against 6
unanswerable questions showed neither BM25 score nor raw query coverage separates the two classes; what
worked was coverage over *content terms only*, after dropping question words that no filing contains. The
measured table and the reasoning live in the code beside the constants — the evaluation changed the
design rather than just scoring it.
