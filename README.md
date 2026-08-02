# Evidence-First Filing Change Analyst

[![Live demo](https://img.shields.io/badge/live%20demo-open%20the%20app-1f4e79?style=flat-square)](LIVE_DEMO_URL)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat-square)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-162%20offline-2e7d32?style=flat-square)](tests/)
[![Runs without an API key](https://img.shields.io/badge/runs%20without%20an%20API%20key-yes-2e7d32?style=flat-square)](#running-without-an-llm)

**What materially changed in this company's latest SEC filing versus the previous comparable one — and what evidence supports every conclusion?**

A working prototype for a fundamental equity team. It compares two consecutive SEC filings, calculates
every financial change in Python, retrieves matched earlier/later evidence for each claimed change, and
produces a citation-backed analyst brief that visibly separates verified facts from model interpretation.

> Research aid, not investment advice. No recommendations, no price targets, no predictions.

### ▶ Try it

**[LIVE_DEMO_URL](LIVE_DEMO_URL)** — no signup, no key, nothing to install.

Press **Compare latest filings** for the default Microsoft 10-K year-over-year comparison.
`MSFT`, `AAPL`, `NVDA` and `PG` are pre-warmed and return in a few seconds; any other US filer with a
10-K is fetched live from EDGAR. The hosted instance runs **without an API key**, which is the honest
configuration — every number, every citation and the entire material-change list on that deployment are
produced deterministically in Python, with no model involved. See
[Running without an LLM](#running-without-an-llm).

---

## The problem

During earnings season a fundamental analyst repeats the same manual loop for company after company:
find the latest and previous comparable filings, read hundreds of pages, reconcile the numbers, notice
what changed in management's language and risk disclosures, then verify every conclusion against the
source before it can be used in an investment discussion.

It is slow, it is repetitive, and it is exactly where things get missed. A generic LLM summary makes it
worse: it produces fluent prose with unverifiable numbers, which an analyst then has to re-check line by
line — no time saved, and new risk introduced.

**Target user:** a fundamental equity analyst doing first-pass review of a 10-K.
**What this does:** compresses the mechanical part of that first pass while keeping the analyst in control
of every judgement.

---

## What it produces

The default action always compares a company's **two most recent comparable filings**. Microsoft filed
its FY2026 10-K on 2026-07-30, during this build — so the live default is now FY2026 vs FY2025, and the
system picked the new filing up with **no code change**:

| | FY2026 vs FY2025 (live default) | FY2025 vs FY2024 (pinned example) |
|---|---|---|
| Financial metrics compared | **21 / 21** | **21 / 21** |
| Evidence chunks indexed | 449 | 471 |
| Material changes surfaced | 8 | 7 |
| Risk-factor headings | 31 → 33 (+4 / −2) | 34 → 31 (+2 / −5) |
| Revenue | $281.72B → $331.84B (**+17.79%**) | $245.12B → $281.72B (+14.93%) |
| Capital expenditure | $64.55B → $115.95B (**+79.62%**) | $44.48B → $64.55B (+45.13%) |
| Estimated free cash flow | $71.61B → $66.99B (**−6.46%**) | $74.07B → $71.61B (−3.32%) |
| Run time, warm cache | ~5 s | ~4.5 s |
| Works with no API key | **Yes** | **Yes** |

The FY2025/FY2024 pair is the *pinned* example: the evaluation ground truth was read by hand from those
two documents, and the screenshots below were captured on that pair. Pinning by accession number is
deliberate — otherwise a newly filed 10-K silently invalidates every expected value in the suite.

A representative finding from the pinned run, produced with no model involved:

> **Reported figures and narrative emphasis diverge on AI investment and monetisation:**
> capital expenditure changed **+45.1%** ($44.48B → $64.55B), while narrative emphasis
> **decreased** (−11.4 mentions per 10,000 tokens).
>
> *Earlier evidence:* FY2024 10-K, Item 1A — Risk Factors, accession `0000950170-24-087843` …
> *Later evidence:* FY2025 10-K, Item 1A — Risk Factors, accession `0000950170-25-100235` …
>
> ⚠️ *Caveat:* Emphasis is a phrase-frequency measure normalised per 10,000 tokens — a prominence
> signal, not a semantic judgement. A divergence may reflect reorganised disclosure rather than a
> change in management's priorities.

That is the kind of thing an analyst wants surfaced: capex up 45% while free cash flow *fell* 3.3%, and
`Copilot` mentions down from 29 to 9 between the two filings. Both are checkable in one click.

On the newest pair the same machinery reads the story differently, and correctly — AI emphasis and capex
now move *together*: "narrative emphasis on AI investment and monetisation increased (+55.5 mentions per
10,000 tokens) and the linked reported figures moved in the same direction."

Full generated briefs for both pairs are committed in [`data/sample/`](data/sample/):
[FY2026](data/sample/MSFT_10-K_2026-06-30_change_brief.md) ·
[FY2025](data/sample/MSFT_10-K_2025-06-30_change_brief.md).

## Screenshots

All captured from a live run with **no API key configured**, on the pinned FY2025/FY2024 pair. Full
index in [`docs/screenshots/`](docs/screenshots/README.md).

**The financial snapshot — every figure calculated in Python, with the capex/FCF divergence visible**

![Financial snapshot](docs/screenshots/03-financial-snapshot-capex.jpg)

**A material change, with earlier and later evidence side by side and full SEC provenance on both**

![Material change](docs/screenshots/04-material-change-side-by-side.jpg)

**Honest refusal — the system declines and shows the measured signals behind the decision**

![Insufficient evidence](docs/screenshots/06-insufficient-evidence.jpg)

**Item 1A risk-factor heading diff**

![Risk factor diff](docs/screenshots/05-risk-factor-diff.jpg)

---

## Quick start

Requires Python 3.11+.

```bash
git clone https://github.com/yaoDu/evidence-first-filing-change-analyst.git
cd evidence-first-filing-change-analyst

python -m venv .venv && source .venv/bin/activate     # or: uv venv && source .venv/bin/activate
pip install -e ".[dev]"                               # or: uv pip install -e ".[dev]"

cp .env.example .env
# Edit .env and set SEC_USER_AGENT to a real "Your Name your@email" value.
# SEC blocks unidentified automated clients. ANTHROPIC_API_KEY is optional.

streamlit run app.py
```

Then press **Compare latest filings**. The default is MSFT 10-K year-over-year.

```bash
pytest                              # 162 tests, fully offline, ~2.5s
ruff check src tests app.py         # lint
python evaluation/run_evaluation.py # 22 questions against the pinned MSFT FY2025/FY2024 pair
python evaluation/run_evaluation.py --latest-pair   # score against today's latest pair instead
python evaluation/run_coverage_check.py             # 11-filer coverage sweep -> evaluation/COVERAGE.md
```

### Worked examples

Every output below is verbatim from a real run against the pinned MSFT FY2025/FY2024 pair, with
**no API key configured**.

#### 1. The comparison you get from one click

| Metric | Previous period | Latest period | % / pp change |
|---|---:|---:|---:|
| Revenue | $245.12B | $281.72B | +14.93% |
| Gross margin | 69.76% | 68.82% | **−0.94 pp** |
| Capital expenditure | $44.48B | $64.55B | **+45.13%** |
| Estimated free cash flow | $74.07B | $71.61B | **−3.32%** |

Note the units: level metrics get a percentage, ratio metrics get percentage **points**. Conflating
those is a classic quiet error, so they are computed and rendered by different code paths.

#### 2. Every number is inspectable down to the XBRL fact

Expanding *Source and provenance — Capital expenditure* in the app shows exactly what was read:

```json
{
  "concept":        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
  "start":          "2024-07-01",
  "end":            "2025-06-30",
  "duration_days":  364,
  "duration_class": "annual",
  "unit":           "USD",
  "form":           "10-K",
  "accession":      "0000950170-25-100235",
  "filed":          "2025-07-30",
  "selection_rule": "filing_scoped_exact_period"
}
```

`selection_rule` is the point: the value shown is the one tagged *in that filing*, not a value
assembled from whichever filing happened to report it most recently.

#### 3. Incompatible periods are refused, not warned about

Pick the FY2023 and FY2025 10-Ks in *Choose a specific filing pair* and the comparison is blocked
before any arithmetic runs:

```
comparability_ok: False
notes: ["Annual periods are 24 months apart (expected ~12).
         This is not a like-for-like year-over-year comparison."]
```

Every metric row then reports `BLOCKED — incompatible periods` and the brief carries a blocking banner.

#### 4. A question it cannot answer

```
> What is the chief executive officer's favourite colour?

Insufficient evidence: no passage in the extracted sections of either filing matched this
question strongly enough to answer it (best BM25 score 14.5, query-term coverage 26%).
Terms not found anywhere in the extracted sections: officer's, favourite, colour.
Try wording the question with terminology the filing itself would use.
```

It reports the measurements behind the refusal, so you can tell a genuine gap from a phrasing problem.

#### 5. A question answered deterministically, with no model at all

"What changed in the risk factors?" is a set difference, not a passage — so it is served straight from
the Item 1A heading diff rather than from retrieval:

```
> Which risks appear new or more prominent?

31 risk-factor headings in the latest filing versus 34 in the previous one: 2 new,
5 no longer present, 29 retained (extraction confidence: high).
Item 1A length 73,473 → 68,711 characters.

New or substantially reworded:
  · Competition laws and new market regulation:
  · Environmental, Social, and Governance:

Present previously, not matched now:
  · If our goodwill or amortizable intangible assets become impaired, we may be
    required to record a significant charge to earnings.
  · Government enforcement under competition laws and new market regulation may
    limit how we design and market our products.
  … 3 more
```

#### 6. Driving it from Python instead of the UI

```python
from filing_change_analyst.pipeline import (
    apply_ai_synthesis, available_filings, pair_from_filings, run_analysis,
)
from filing_change_analyst.research.brief import build_markdown_brief
from filing_change_analyst.research.qa import answer_question

# Pin the pair by accession when you want reproducible output. Calling
# run_analysis("MSFT", "10-K") with no pair always takes the two *most recent*
# filings instead — correct for an analyst, but the numbers move when the
# company files, so scripts and tests should pin.
by_accession = {f.accession: f for f in available_filings("MSFT", "10-K")}
pair = pair_from_filings(
    by_accession["0000950170-24-087843"],   # FY2024
    by_accession["0000950170-25-100235"],   # FY2025
)

bundle = run_analysis("MSFT", "10-K", pair=pair)   # deterministic, complete on its own
bundle = apply_ai_synthesis(bundle)                # optional; a no-op without a key

result = bundle.result
capex = result.comparison_by_id("capex")
print(round(capex.percent_change, 2))              # 45.13
print(capex.later.provenance[0].accession)         # 0000950170-25-100235
print(capex.later.provenance[0].selection_rule)    # filing_scoped_exact_period

qa = answer_question(
    "What did management say about capital expenditures and datacenters?",
    bundle.index, result.pair, result.comparisons,
    risk_delta=result.risk_delta,
)
print(qa.answer_type)                              # llm_unavailable, with no API key
for e in qa.evidence:
    print(e.chunk.section_label, e.chunk.accession, e.chunk.source_url)

open("brief.md", "w").write(build_markdown_brief(result))
```

#### 7. A filer where it is weakest

```bash
# P&G's 10-K carries no item numbers in its body, so extraction falls back to
# anchoring on bare section titles — and the app says so, at low confidence.
streamlit run app.py     # then enter PG
```

```
Section headings located by — earlier: title_only (low confidence) · later: title_only (low confidence)
⚠️ The title_only strategy anchors on bare section titles because the filing body carries no
   item numbers; a cross-reference to a section title can be mistaken for the section itself,
   so treat these excerpts with extra care.
```

It still produces 19/21 metrics, 446 evidence chunks and 5 material changes — and it tells you how much
to trust the text.

### Running without an LLM

Leave `ANTHROPIC_API_KEY` empty. The app states plainly that AI synthesis is disabled and still gives you:

* the full 21-metric comparison with per-fact provenance,
* the risk-factor heading diff,
* all ten topic probes with measured emphasis deltas,
* the material-change list with earlier/later evidence,
* filing search with cited excerpts,
* the downloadable Markdown brief.

Only the interpretive sections (executive summary, bull/bear, questions for management) are omitted, and
the brief says so where they would have been.

---

## Architecture

```mermaid
flowchart TD
    subgraph src["SEC EDGAR"]
        A1["submissions/CIK.json<br/>filing index"]
        A2["companyfacts/CIK.json<br/>XBRL facts"]
        A3["Archives/…/*.htm<br/>filing documents"]
    end

    A1 --> B["Filing selection<br/><i>sec/filings.py</i>"]
    B --> C{"Structural<br/>comparability<br/>checks"}
    C -->|"fail"| CX["Blocked — comparisons suppressed,<br/>reason shown to the analyst"]
    C -->|"pass"| D

    A2 --> D["Fact selection<br/><i>sec/facts.py</i><br/>filing-scoped, transparent rules"]
    D --> E["Period validation<br/><i>analytics/period_matching.py</i>"]
    E --> F["Comparison engine<br/><i>analytics/comparisons.py</i><br/><b>all arithmetic in Python</b>"]
    F --> F2["Restatement check<br/>prior year as-first-reported<br/>vs as-re-tagged"]

    A3 --> G["Section extraction<br/><i>sec/sections.py</i><br/>Items 1, 1A, 7, 7A"]
    G --> H["Provenance-carrying chunks<br/><i>retrieval/chunking.py</i>"]
    H --> I["BM25 index<br/><i>retrieval/index.py</i>"]
    G --> R["Risk-heading diff<br/><i>research/change_detection.py</i>"]

    I --> J["Fixed topic probes<br/><i>retrieval/search.py</i><br/>earlier + later evidence<br/>+ emphasis delta"]
    F --> K
    J --> K["Deterministic material changes<br/><i>research/change_detection.py</i>"]

    K --> L["Evidence package"]
    F --> L
    R --> L

    L --> M{"API key<br/>present?"}
    M -->|"no"| O
    M -->|"yes"| N["Constrained synthesis<br/><i>research/synthesis.py</i>"]
    N --> N2{"Four gates:<br/>schema · citations ·<br/>numeric grounding ·<br/>no recommendations"}
    N2 -->|"rejected"| O
    N2 -->|"accepted"| O["Analyst UI + Markdown brief"]
```

Full walkthrough in [`docs/architecture.md`](docs/architecture.md).

### The three decisions that define this system

**1. Python computes; the model interprets.**
Every displayed figure originates in `analytics/comparisons.py` from XBRL facts with recorded provenance.
The model receives those values pre-computed, is instructed to reference them by `metric_id` and never to
write a figure, and is then *mechanically checked*: `analytics/validation.py` extracts every numeric
literal from the generated prose and rejects any that does not appear in the supplied evidence or the
computed metric table. A claim containing an invented number is discarded, not displayed with a warning.

**2. Change detection is deterministic, so the product works without a model.**
Each of ten research topics is a fixed, versioned query. The system retrieves matched earlier and later
evidence for it and measures a normalised **emphasis delta** — non-overlapping phrase occurrences per
10,000 tokens — alongside the linked metric moves. Material changes are ranked and emitted from those two
measurements. The model, when present, *interprets* them; it cannot create a change out of nothing, and
its output is layered on a result that is already complete and displayable.

**3. Period correctness is a gate, not a footnote.**
Comparing a quarter with a year is the most damaging error this class of tool can make, so structural
checks (`sec/filings.py`) run before any arithmetic, and fact-level checks (`analytics/period_matching.py`)
run per metric. Instant facts never meet duration facts; a 45-day duration mismatch blocks the comparison;
a two-year gap is refused. A blocked comparison shows `N/A` with the reason, and the brief carries a
blocking banner.

---

## Evidence and provenance

Every excerpt carries company, ticker, CIK, form, filing date, reporting period, accession number, section
name, chunk id and a link to the original document on SEC EDGAR. **Page numbers are never fabricated** —
10-K HTML has no stable pagination, so anchoring is by section plus accession.

Every metric value carries the XBRL concept, taxonomy, unit, period start/end, duration class, source form,
accession, filing date and the *selection rule* that chose it. Fact selection is filing-scoped by default:
the value shown for a filing is the value tagged *in that filing*, so the year-over-year comparison is the
one an analyst would read off the two documents.

The comparison also runs a **restatement check** — the prior year as first reported against the same period
as re-tagged in the newer filing — because a silent reclassification makes a naive YoY change wrong.

---

## Six claim types, always visibly labelled

| Label | Meaning |
|---|---|
| ✅ **Verified fact** | Directly reported in a filing |
| 🧮 **Calculated change** | Computed in Python from verified values |
| 💬 **Management statement** | Attributed commentary from a filing |
| 🤖 **AI interpretation** | A reasoned but non-authoritative inference |
| ⚠️ **Caveat** | A limitation or ambiguity — attached to *every* material change |
| ❓ **Open question** | Something the evidence does not establish |

Bull and bear sections are labelled "interpretation, not a recommendation" in both the UI and the brief.

---

## Evaluation results

22 questions against the live MSFT FY2025/FY2024 pair. Ground truth was read by hand from the two filings;
percentage expectations were computed by hand, not copied from the tool's output.
Run with `python evaluation/run_evaluation.py`; the full report regenerates into
[`evaluation/RESULTS.md`](evaluation/RESULTS.md).

**Deterministic-only configuration (no API key) — 21/21 scored questions passed, 3 not measured:**

| Measure | Result |
|---|---|
| Metric correctness — calculated values match hand-read filing values | 11/11 (100%) |
| Period correctness — compared facts use compatible durations/instants | 2/2 (100%) |
| Retrieval success — expected section and evidence retrieved | 7/7 (100%) |
| Citation validity — every citation resolves to supplied evidence | 11/11 (100%) |
| Citation support — retrieved excerpt contains the expected terminology | 4/4 (100%) |
| Numerical accuracy — reported changes reproduce deterministic values | 4/4 (100%) |
| Insufficient-evidence handling — the system declines | 3/3 (100%) |
| Unsupported-claim rate — material changes lacking both-period evidence or a caveat | 0/7 |
| Latency — full pipeline, warm cache | 4.2 s |

The three unmeasured questions are **fact-level gaps** — the words are all present in the filings but the
fact is not disclosed ("what percentage of capex was attributable to AI?"). A lexical retriever cannot
detect those; they need a model, and are reported as *not measured* rather than scored as passes.

### Coverage beyond the default company

`python evaluation/run_coverage_check.py` sweeps 11 large filers across sectors and fiscal calendars.
Measured result: **10/11 produce a usable comparison, all 10 with text evidence** — see
[`evaluation/COVERAGE.md`](evaluation/COVERAGE.md) for the per-filer table.

This sweep is how three real defects were found, none of which the single-company demo could surface:

| Defect | Symptom | Fix |
|---|---|---|
| Section anchoring assumed upper-case item headings | **Zero** text evidence for AAPL, NVDA, P&G and Berkshire — with only a risk-diff warning, so it looked like those filings had no risk factors | Three anchoring strategies tried in order of precision; the one used is reported as provenance |
| Filing discovery read only the `recent` submissions block | JPM refused outright — it files ~25,000 documents, so `recent` spans weeks and holds one 10-K | Fall back to the paginated older shards, with accession dedupe |
| Zero-evidence runs were quiet | A filing with no extractable text produced an empty result that read as "nothing changed" | Loud warning naming the filing and stating that the financial comparison is unaffected |

**How the decline gate was built (a real finding from this evaluation).** The first version used a BM25
score threshold and failed two questions: an off-topic control scored 14.5, higher than several genuine
questions. Measured over 16 answerable and 6 unanswerable questions, neither BM25 score (ranges 5.8–34.4
vs 5.6–14.5) nor raw query coverage (0.41–1.00 vs 0.17–0.67) separates the classes. What worked was
**query coverage over content terms only** — dropping question words like "describe" and "drove", which no
filing contains and which made well-phrased questions look unanswerable. That separates cleanly
(0.76–1.00 vs 0.11–0.67). The reasoning, the measured table and the ~8% margin are recorded in
`research/qa.py` next to the constants.

---

## Testing

162 tests, all offline, ~2.5 s. Fixtures are trimmed real SEC captures (submissions and companyfacts for
CIK 0000789019) plus two synthetic miniature 10-Ks. No test touches the network or needs an API key.

| Area | Covers |
|---|---|
| `test_period_matching.py` | duration classes, instant vs duration, unit mismatch, fiscal drift, 52/53-week calendars, form mismatch, amendments |
| `test_metrics.py` | values vs the filing, percent vs percentage-point changes, derived metrics, gross-profit fallback, missing data, zero denominators, sign flips, provenance completeness |
| `test_sections_and_retrieval.py` | item extraction vs table-of-contents traps, section bleed, risk headings, chunk provenance and stability, BM25 filters, phrase-frequency overlap, metric-reuse cap |
| `test_citations.py` | accession validation, EDGAR URL construction, fabricated-id rejection, both-period requirement, no page numbers |
| `test_llm_guardrails.py` | schema validation, numeric grounding, recommendation detection, prompt-injection redaction, stubbed-model gates, failure/refusal handling, key never logged |
| `test_qa_gating.py` | content-term extraction, decline gate on both signals, risk-question routing, no-LLM behaviour |
| `test_rendering_safety.py` | AST check that no module enables raw-HTML rendering, entity-decoding premise, hostile excerpt survives the pipeline as inert text |
| `test_filing_discovery.py` | older-submissions-shard fallback for high-volume filers, accession dedupe, shard-fetch failure, registrants with no filing history |
| `test_demo_cache.py` | bundled-cache seeding, byte-identical payload round-trip, warm caches never overwritten, idempotence, and refusal of traversal/absolute/symlink archive members |
| `test_end_to_end.py` | full pipeline offline, brief structure and provenance, reproducibility, incompatible pairs, a simulated SEC outage |

---

## Security and reliability

* Secrets and SEC identity come from the environment; `.env` and `.streamlit/secrets.toml` are gitignored
  and nothing sensitive is defaulted into source. The API key is never written to a log or run record
  (there is a test for it). The public deployment carries no key at all.
* The bundled cache archive is validated before extraction — traversal paths, absolute paths, symlinks and
  device nodes are refused rather than trusted, and a corrupt or hostile archive degrades to a slower cold
  start instead of writing outside the cache directory. It arrives over the same clone as the code, so it
  gets the same scrutiny as any other untrusted input.
* SEC calls are identified, throttled below the fair-access ceiling, given a 30-second timeout and bounded
  retries with exponential backoff, and fall back to a stale cache entry rather than failing the demo.
* Filing HTML is stripped to text on ingest and never re-rendered as markup. Streamlit's raw-HTML
  path is not used anywhere, and an AST-level test fails the build if it is reintroduced — entity
  decoding means stripped text can still contain a literal `<img …>`, so escaping is load-bearing.
* Filing text and user questions pass through an injection-marker redactor before entering any prompt, and
  evidence is wrapped in delimited blocks with an explicit untrusted-data notice.
* Structured model output is validated by Pydantic, then by citation, numeric-grounding and
  recommendation gates. A failure at any gate discards the model's contribution and keeps the
  deterministic result.
* Every model call is logged with model id, prompt version, latency, token counts, dropped citations and
  dropped changes — visible in the UI and appended to the brief.
* A missing filing document degrades to "text evidence unavailable for that period" while the financial
  comparison completes (there is a test for this).

---

## Trade-offs

| Decision | Why | What it costs |
|---|---|---|
| Hand-rolled SEC client instead of EdgarTools | Needs the `accn` field on every XBRL fact — that is what makes provenance auditable — plus exact control of caching and offline mode | More code to maintain |
| BM25 instead of embeddings | Filing questions turn on exact terminology; reproducible, no model download, runs offline | Weak paraphrase recall, mitigated by hand-written query expansions |
| XBRL facts instead of parsing statement tables | Units, periods and provenance come for free and are machine-checkable | An untagged concept shows `N/A` instead of being recovered from the HTML table |
| Fixed topic probes instead of open-ended LLM discovery | Reproducible, works with no key, and the model cannot invent a change | Only finds changes in the ten catalogued themes |
| Deterministic layer first, model second | A slow or failing model degrades the product instead of breaking it | Two passes over the evidence |
| Heading-level risk diff | Reliable signal filers actually mark up in bold | A risk whose heading is unchanged but whose body was rewritten is missed |
| Streamlit | Fastest path to an analyst-usable interface | Not a production front end |

---

## Limitations

Honest and specific. Full list with mitigations in [`docs/limitations.md`](docs/limitations.md).

1. **Deterministic decline detects vocabulary gaps, not fact gaps.** "What was the closing share price?"
   uses words that all appear in the filings, so the lexical gate cannot tell the fact is absent. Without
   a model, that question returns evidence rather than a refusal. Measured, and kept in the evaluation
   suite as `q20`/`q21`/`q22`.
2. **Decline thresholds are calibrated on one filing pair** with ~8% margin. They are a genuine tuning
   risk on companies with different vocabulary.
3. **Emphasis delta measures prominence, not meaning.** It cannot distinguish "we invested more in AI"
   from "AI is a risk to us", and it moves when a filing is reorganised. Every change that uses it carries
   this caveat.
4. **Only Items 1, 1A, 7 and 7A are extracted.** Financial-statement notes, segment tables, exhibits and
   Item 5 market information are not searchable.
5. **Section extraction depends on heading markup, which filers do not standardise.** Three anchoring
   strategies are tried in order and the one that worked is reported as provenance in the UI and the
   brief: `upper_case` (MSFT, WMT, UNH, KO, TSLA), `mixed_case` (AAPL, NVDA, JPM, BRK-B) and
   `title_only` (P&G — no item numbers in the body at all, reported at **low** confidence because a
   cross-reference to a section title can be mistaken for the section itself). Anchoring on upper case
   alone — the original implementation — silently produced zero text evidence for four of ten filers.
6. **Free cash flow is a prototype definition** (operating cash flow − purchases of PP&E). It excludes
   acquisitions, finance-lease principal and capitalised software, so it will not match a company's own
   FCF disclosure. The definition is printed next to the number.
7. **Coverage beyond Microsoft is measured, not assumed — and it is uneven.** 10 of 11 large filers
   produce a usable comparison with text evidence ([`evaluation/COVERAGE.md`](evaluation/COVERAGE.md)),
   but metric coverage varies by business model: 21/21 for MSFT and TSLA, 17–19/21 for staples and
   retail, and only 7/21 for JPM and 9/21 for Berkshire, because banks and insurance conglomerates have
   no gross profit, cost of revenue or PP&E-style capex to tag. Those degrade to `N/A` correctly, but the
   tool is much less useful for financials. XOM is refused outright: the SEC ticker index currently points
   XOM at "ExxonMobil Holdings Corp", a registrant with no 10-K history, and the tool will not follow a
   ticker to its predecessor entity.
8. **10-Q support is structural only.** The comparability checks handle it; the metric catalogue and topic
   probes are tuned for annual filings.
9. **The live model path has never been exercised against a real API.** No `ANTHROPIC_API_KEY` was
   available during the build, so `research/synthesis.py` and the LLM branch of `research/qa.py` are
   validated only by stubbed-model tests. Those tests do cover all four gates — fabricated citations,
   single-period citations, invented figures and recommendation language are each asserted to be
   discarded — plus timeout, refusal and truncation handling. But the prompts themselves have not been
   tuned against real model output, and the three `llm_required` evaluation questions are reported as
   *not measured* for the same reason. This is the largest untested surface in the project.
10. **This is a prototype.** Not institutional-grade, not production-ready, and it does not eliminate
   hallucination — it constrains, checks and labels model output, and reports what it could not verify.

---

## Next steps

* Extend the deterministic decline gate with a claim-level entailment check so fact-level gaps are caught
  without a model.
* Validate section extraction across 50+ filers and add a fallback anchoring strategy.
* Add segment-level metrics from XBRL dimensional facts — the single most-requested thing missing from
  the capex story.
* Sentence-level risk-body diffing to catch material rewrites under unchanged headings.
* Batch mode: run a watchlist overnight and surface only the pairs whose signals cross thresholds.

---

## Repository layout

```
app.py                              Streamlit interface (Views A–E)
src/filing_change_analyst/
  config.py  models.py  formatting.py  pipeline.py
  sec/        client.py filings.py facts.py sections.py
  analytics/  metric_definitions.py period_matching.py comparisons.py validation.py
  retrieval/  chunking.py index.py search.py citations.py
  research/   prompts.py change_detection.py synthesis.py qa.py brief.py
  services/   cache.py llm.py demo_cache.py
  ui/         components.py
tests/                              162 offline tests + fixtures
evaluation/                         questions.json, run_evaluation.py, RESULTS.md
docs/                               architecture, limitations, demo walkthrough, screenshots
data/sample/                        committed sample analyst brief
data/demo_cache.tar.gz              pre-warmed SEC responses for the hosted demo
scripts/build_demo_cache.py         regenerates that archive from a warm local cache
requirements.txt                    runtime deps for the hosted deployment
.streamlit/config.toml              deployment configuration (no secrets)
```

## Assumptions recorded during the build

* Microsoft is the default company: a large, well-tagged filer with a clean XBRL history, which makes it
  the fairest starting point for a reviewer who has never seen the tool. Microsoft filed its FY2026 10-K
  (`0001193125-26-323660`) during the build, so the live default pair moved from FY2025/FY2024 to
  FY2026/FY2025 mid-session. The evaluation is pinned by accession to FY2025 (`0000950170-25-100235`)
  vs FY2024 (`0000950170-24-087843`) so its hand-read ground truth stays valid; `--latest-pair`
  overrides that.
* "Comparable" for a 10-K means period ends 10–14 months apart; for a 10-Q it means the same quarter of
  the prior year. Anything else is refused rather than warned about.
* Metrics are read from XBRL rather than the statement HTML; a metric with no usable tag is `N/A`.
* Materiality thresholds: 15% for level metrics, 1.0 percentage point for ratios, 1.5 mentions per 10,000
  tokens for emphasis. One metric may anchor at most two claims, so a single headline number cannot be
  recycled into an apparently long change list.
* The change list is capped at 8 and is allowed to be short. Nothing is padded.

## Deployment

The hosted demo runs on [Streamlit Community Cloud](https://share.streamlit.io) from the `main` branch of
this repository. To stand up your own copy:

1. Fork this repository.
2. At [share.streamlit.io](https://share.streamlit.io), create an app pointing at your fork, with
   `app.py` as the entrypoint and Python **3.11** or newer.
3. Under *Advanced settings → Secrets*, set your SEC identity — SEC blocks unidentified automated
   clients, so this is required, not optional:

   ```toml
   SEC_USER_AGENT = "Your Name your.email@example.com"
   ```

   `ANTHROPIC_API_KEY` is optional. Leave it out and the app runs in deterministic-only mode, which is
   how the public instance is configured: no key means no model spend and no abuse surface on a
   link anyone can open.

`app.py` copies Streamlit secrets into the process environment before settings are built, so the same
configuration works locally through `.env` and on the host through the secrets store, with the local
`.env` taking precedence.

### Why the demo is fast

A cold run pulls ~30 MB from EDGAR, and SEC rate-limits by IP — a shared cloud host is not a friendly IP
to share. So `data/demo_cache.tar.gz` ships the SEC responses for the four demo tickers, and
`services/demo_cache.py` unpacks them into the HTTP cache on first boot. Seeding is skipped whenever the
cache already holds entries, so it never overwrites a warm local cache or affects the test suite.

What is bundled is **the raw bytes EDGAR returned**, keyed by request URL — not canned output. Sections
are still extracted, facts still selected and every figure still computed at request time. Tick
**Bypass cache** in the sidebar to force a live re-fetch and confirm that. Rebuild the archive with
`python scripts/build_demo_cache.py`.

---

## Authorship and provenance

Author: **Yao Du** ([@yaoDu](https://github.com/yaoDu)). Independent portfolio project, built from
scratch; there is no upstream repository and this is not a fork.

Four independent ways to verify that:

| Check | What it shows |
|---|---|
| `git log --show-signature` | Every commit is **cryptographically signed** with the author's SSH key. GitHub renders this as a **Verified** badge. Anyone can type any name into a git author field — a valid signature is the part that cannot be forged without the private key. |
| [`CITATION.cff`](CITATION.cff) | Machine-readable authorship metadata. GitHub renders it as a *Cite this repository* panel on the repository home page. |
| [`LICENSE`](LICENSE) | MIT, © 2026 Yao Du. Grants reuse with attribution while the copyright itself stays asserted. |
| Commit history | The full build is in the history — five substantive commits, including the coverage sweep that found three real defects and the code-review pass that fixed a rendering bug. Development history is much harder to fabricate after the fact than a finished snapshot. |

The quickest check needs no setup at all: open any commit on GitHub and look for the **Verified** badge.

To verify the signatures yourself from a clone, point git at the public keys trusted to sign here.
SSH signature verification requires this — without an allowed-signers file git reports *"gpg.ssh
.allowedSignersFile needs to be configured"* rather than a bad signature:

```bash
git clone https://github.com/yaoDu/evidence-first-filing-change-analyst.git
cd evidence-first-filing-change-analyst

git config gpg.ssh.allowedSignersFile .github/allowed_signers
git log --show-signature
# Good "git" signature for 76980641+yaoDu@users.noreply.github.com with ED25519 key SHA256:eJvaEl/…
```

[`.github/allowed_signers`](.github/allowed_signers) contains only a public key. Cross-check it against
the copy GitHub serves independently at [github.com/yaoDu.keys](https://github.com/yaoDu.keys) — if the
two agree, the signatures were made by the holder of that account's private key.

## License

MIT — see [`LICENSE`](LICENSE). Copyright © 2026 Yao Du.

You may use, modify and distribute this code, including commercially, provided the copyright notice and
licence text are retained. The software is provided without warranty; it is a research prototype, not
investment advice, and it makes no recommendations.
