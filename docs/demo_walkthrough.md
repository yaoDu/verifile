# Three-minute demo walkthrough

## Before you start

```bash
export SEC_USER_AGENT="Your Name your@email"
python evaluation/run_evaluation.py > /dev/null    # warms the cache; the demo then runs in ~5s
streamlit run app.py
```

Have open: the app, and a terminal in the repo root.
Decide in advance whether to demo **with** or **without** `API_KEY` — the no-key run is the
stronger story, because it proves the product is not a wrapper.

---

## The sequence

### 0:00 — 0:20 · The problem

> "Every earnings season an analyst does the same thing for company after company: pull the latest 10-K
> and the previous one, read both, reconcile the numbers, work out what changed in management's language,
> then verify every conclusion before it can be used. It's slow, it's repetitive, and it's exactly where
> things get missed. A generic LLM summary makes it worse — fluent prose with numbers you still have to
> re-check line by line."

### 0:20 — 0:45 · One click

Press **Compare latest filings** (MSFT 10-K is the default). Let the status panel run.

> "It picks the two most recent comparable filings, checks they're actually comparable *before* touching
> any arithmetic, pulls SEC XBRL facts, extracts Items 1, 1A, 7 and 7A, and indexes them with full
> provenance. About five seconds warm."

Point at the header while it finishes:

> "Filing dates, reporting periods, accession numbers and links to the originals on EDGAR — visible up
> front, because the first thing an analyst asks is *which documents are these?*"

### 0:45 — 1:20 · The numbers, and who computed them

**Financial snapshot** view.

> "Twenty-one metrics. Every one of these is calculated in Python from XBRL facts — the model never
> produces a number. Revenue up 17.8%. Capital expenditure up **80%**. And free cash flow **down 6.5%**."

*(Those are the FY2026-vs-FY2025 figures the app shows today. Glance at the numbers on screen before you
say them — the default is always the latest pair, so they move when the company files.)*

Expand one provenance panel.

> "Each value is inspectable: the exact XBRL concept, the period, the unit, the accession number it came
> from, and the rule that selected it. Note margins move in percentage *points*, not percent — mixing
> those up is a classic source of quiet errors."

*(If asked about missing data: scroll to a metric showing `N/A` — nothing is ever estimated.)*

### 1:20 — 2:05 · The distinctive part

**Material changes** view. Scroll to the AI investment card.

> "This is the feature I care most about. Every claimed change is anchored on something measured — a
> Python-computed metric move, a normalised change in how prominently a topic is discussed, or both — and
> it shows the earlier and later excerpts **side by side**, each with its section and accession number."

Point at the divergence card:

> "On the current pair, AI emphasis is up 55 mentions per ten thousand tokens **and** capex is up 80% —
> the language and the numbers agree, and it says so. On the previous year's pair they *diverged*: capex
> up 45% while AI mentions fell, because `Copilot` went from 29 mentions to 9. Either way it's a real,
> checkable disclosure change — and the caveat under it says exactly what this measure can and can't
> tell you."

*(To show the divergence case, open the sidebar's "Choose a specific filing pair" and select the FY2025
and FY2024 10-Ks — that is also the pair in the screenshots and the pinned evaluation.)*

Then **Risk factors** view, briefly:

> "Risk headings diffed with fuzzy matching, so a reworded risk counts as retained rather than as one
> addition plus one removal. Four new, two gone on this pair."

### 2:05 — 2:35 · Honest failure

**Ask the filings** view. Type: *"What is the chief executive officer's favourite colour?"*

> "It declines, and it tells you why — best BM25 score, query-term coverage, and which terms appear
> nowhere in the filings. Getting this right took real work: my first version used a score threshold and
> that off-topic question scored *higher* than several genuine ones. The evaluation caught it. The fix
> and the measured evidence are in the code next to the constants."

Now ask something real: *"What did management say about capital expenditures and datacenters?"*

> "Evidence from both filings, each with its accession and a link to the original."

*(If running with no key, point at the banner:)*

> "There's no API key set right now. Everything you've seen is deterministic. The model, when it's
> available, only interprets these measurements — and anything it writes goes through four gates:
> schema, citation validation, numeric grounding against the computed metrics, and a
> no-recommendations check. A claim with an invented number is discarded, not flagged."

### 2:35 — 3:00 · The deliverable and the evidence it works

**Analyst brief** view → **Download Markdown brief**.

> "Nine sections. Every line labelled: verified fact, calculated change, management statement, AI
> interpretation, caveat, open question. Bull and bear are explicitly labelled interpretation, not
> recommendations."

Switch to the terminal:

```bash
pytest -q                              # 162 passed in ~2.5s
python evaluation/run_evaluation.py    # 21/21 scored, 3 not measured
```

> "162 tests, fully offline, no API key needed. And a 22-question evaluation with ground truth read by
> hand from the filings — 100% on metric correctness, period correctness, retrieval and citation
> validity. Three questions are reported as *not measured* rather than passed, because they need a model
> to answer honestly. That's the whole philosophy: report what you measured, and say clearly what you
> didn't."

---

## The one-sentence close

> "I took a repetitive, time-sensitive step in fundamental research and built a dependable workflow
> around it. The numbers are calculated and validated in code, every material claim is one click from its
> source on EDGAR, model interpretation is separated from fact, and where the system can't establish
> something it says so instead of hiding it."

---

## Likely questions

**"How do you know the model isn't making up numbers?"**
Two layers. It is never asked for one — figures are supplied pre-computed and it references them by
`metric_id`. Then `analytics/validation.py` extracts every numeric literal from the generated prose and
checks it against the evidence and the metric table across scale and precision variants. A claim with an
ungrounded number is discarded. There's a test that feeds a fabricated `$91.4 billion` claim through the
pipeline and asserts it's dropped.

**"Why BM25 and not embeddings?"**
Filing questions turn on exact terminology — "capital expenditure", "finance leases", concept names.
BM25 with metadata filters is more predictable there, needs no model download, is reproducible offline,
and made the whole system work with no API key. The cost is paraphrase recall, mitigated by hand-written
query expansions. It's in the trade-offs table, and dense retrieval is a clean addition later.

**"What happens on a company that isn't Microsoft?"**
I measured it rather than guessing — `evaluation/run_coverage_check.py` sweeps 11 large filers and writes
`COVERAGE.md`. 10 of 11 produce a usable comparison with text evidence. That sweep found three real bugs
the single-company demo couldn't: section anchoring assumed upper-case item headings and returned *zero*
evidence for Apple, NVDA, P&G and Berkshire; filing discovery read only the `recent` submissions block and
refused JPMorgan, which files 25,000 documents; and a zero-evidence run was quiet enough to read as
"nothing changed". All three are fixed. What's still uneven is metric coverage by business model — 7/21
for JPM, 9/21 for Berkshire, because banks have no gross profit or PP&E capex to tag. Those degrade to
`N/A` correctly, but I'd be honest that the tool is much less useful for financials.

**"Show me a filer where it's weakest."**
Type `PG` in the sidebar. P&G's 10-K carries no item numbers in the body at all, so extraction falls back
to anchoring on bare section titles — and the app says so, in a warning, with "low confidence" next to it.
That's the design: it still works, and it tells you how much to trust it.

**"What's the weakest part?"**
The deterministic decline gate detects vocabulary gaps but not fact gaps. "What was the closing share
price?" uses words that all appear in the filings. Without a model it returns evidence rather than a
refusal. I kept it in the evaluation suite as a control so it stays visible.

**"Does it break when a new filing comes out?"**
It was tested by accident. Microsoft filed its FY2026 10-K during the build. The app picked it up with no
code change — 21/21 metrics, revenue +17.8%, capex +79.6%, free cash flow −6.5% — and on that newer pair
the AI-emphasis signal and capex now move *together* rather than diverging, which is the correct reading.
The evaluation is pinned by accession to the pair whose ground truth I read by hand, so a new filing
can't silently invalidate the expected values; `--latest-pair` scores against today's pair instead.

**"How long did this take?"**
Built in one focused session, with the deterministic core first and the model layer added on top — which
is also why it degrades cleanly when the model isn't there.
