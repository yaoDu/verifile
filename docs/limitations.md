# Limitations and failure modes

One page. Every entry states what breaks, how it shows up, and what the system does about it.

## Failure-mode table

| # | Failure mode | How it surfaces | Mitigation in the system | Residual risk |
|---|---|---|---|---|
| 1 | **Fact-level gap not detected.** A question whose words all appear in the filings but whose fact is undisclosed ("what was the closing share price?") | Evidence is returned instead of a refusal in no-LLM mode | Model declines correctly when a key is present; kept as evaluation controls `q20`–`q22` and reported as *not measured*, never as a pass | An analyst without a key could read the excerpts as an answer |
| 2 | **Decline thresholds calibrated on one pair.** Coverage 0.70, score 3.0, ~8% margin | Over- or under-declining on other companies | Measured table and reasoning recorded next to the constants; a test asserts the separation still holds | Untested on other filers |
| 3 | **Emphasis ≠ meaning.** Phrase frequency cannot tell "we invested in AI" from "AI is a risk" | A change described as expanded emphasis that is really reorganised disclosure | Normalised per 10,000 tokens; caveat attached to every change that uses it; divergences flagged rather than smoothed over | Reorganisation still moves the signal |
| 4 | **Filers do not standardise item-heading markup** | Wrong, tiny, or no sections | Three anchoring strategies tried in order (`upper_case` → `mixed_case` → `title_only`), each accepted only if it yields substantial required sections; the strategy used is reported as provenance in the UI and brief; total failure raises a loud warning naming the filing | `title_only` can mistake a cross-reference for a section start, so it is reported at low confidence; measured on 11 filers, not the whole market |
| 4b | **Forms number their items differently** | A 10-Q read with the 10-K map loses MD&A entirely (no Item 7 exists), files the financial statements under "Business", and — because no Item 7 is ever found — rejects the correct anchoring strategy and falls through to `title_only`, which matches the table of contents | Per-form item outlines; anchors matched against the outline as a sequence, so a 10-Q's repeated `Item 1`/`Item 2` resolve by position; acceptance criteria per form; labels name the part (`Part II Item 1A — Risk Factors`) so a citation is checkable | Outlines cover 10-K and 10-Q; other forms fall back to the 10-K outline |
| 4c | **A 10-Q with no item-anchored body** | JPM files its 10-Q as a financial supplement whose items appear only as a cross-reference index at the end; `title_only` then anchors MD&A and Risk Factors in that index | Reported at low extraction confidence with a note that a table-of-contents match is possible; the financial comparison is unaffected | Measured on MSFT, AAPL, NVDA, PG and JPM: MSFT/AAPL/NVDA anchor correctly, PG and JPM produce a usable MD&A but a table-of-contents-sized Item 1A |
| 5 | **XBRL tag not present** | Metric shows `N/A` with the concepts tried | Ordered concept fallbacks; gross profit falls back to revenue − cost of revenue; derived metrics degrade rather than guess | Values visible in the statement HTML but untagged are not recovered |
| 6 | **Restatement or reclassification** | Prior-year figure differs between the two filings | Explicit restatement check comparing as-first-reported vs as-re-tagged, surfaced as an error banner | Only covers metrics in the catalogue |
| 7 | **Incompatible periods** | Comparison would mix a quarter with a year | Structural checks before arithmetic, fact-level checks per metric; blocked comparisons show `N/A` with the reason and a blocking banner in the brief | A filer with a non-standard calendar may be refused when it is genuinely comparable |
| 7c | **Sequential quarters are not seasonally comparable** | A quarter-on-quarter move in a seasonal business reads as a trend when it is the time of year | Sequential is an explicit basis, not a loosened guardrail: the pair records it, the header names it, and every run carries a caveat saying seasonality is not held constant | The caveat cannot say *how much* of a move is seasonal; that needs a multi-year seasonal profile this tool does not build |
| 7b | **A 10-Q narrates two bases** | The grid shows the quarter (or year to date); the MD&A excerpt beside it may quote the other. On MSFT Q3 FY2026 the grid reads cost of revenue +22.4% while the excerpt says "increased $13.0 billion or 20%" — the nine-month figure | Both sides of the comparison are pinned to one length; a chip above the figures names it, read back off the selected facts; any change pairing figures with excerpts carries a caveat naming the basis | The excerpt is quoted verbatim by design, so the reader still has to apply the caveat |
| 8 | **Model invents a figure** | A plausible-sounding number with no source | Every numeric literal in generated prose checked against evidence and computed metrics; the claim is discarded, not annotated | Grounding is lexical: a number that coincidentally matches an unrelated figure would pass |
| 9 | **Model cites a source that does not exist** | Unverifiable citation | Ids validated against supplied chunks; cross-period claims must cite both periods; drops recorded in the run log | — |
| 9b | **Entity-decoded markup in filing text** | A filing writing `&lt;img src=x onerror=…&gt;` yields a literal `<img …>` after tag stripping, because `get_text` decodes entities | Excerpts are rendered through Streamlit's escaping Markdown path; raw-HTML rendering is used nowhere and an AST test fails the build if reintroduced | Excerpts are preserved verbatim by design, so the inert text is still visible to the reader |
| 10 | **Prompt injection inside a filing or a question** | Model follows instructions embedded in a document | Injection markers redacted before prompting; evidence wrapped in delimited blocks with an untrusted-data notice; text never re-rendered as markup | The redactor is pattern-based; a novel phrasing could slip through to the model, though the output gates still apply |
| 11 | **Model unavailable, slow or refusing** | No interpretation | Deterministic pass completes first and is fully displayable; model failures become a run-log entry, never an exception | Interpretive sections are simply absent |
| 12 | **SEC unavailable or rate-limiting** | Analysis cannot start | Throttling below the fair-access ceiling, 30-second timeout, bounded retries with backoff, stale-cache fallback, clear error text | A cold start with SEC down cannot proceed |
| 13 | **One filing document missing** | Half the text evidence gone | Warning recorded; the financial comparison and the brief still complete (tested) | Change detection for that pair is unusable |
| 16 | **A ticker reassigned to a new registrant** | The SEC ticker index points at an entity with no filing history (XOM → "ExxonMobil Holdings Corp") | Refused with an explanation naming the registrant and the likely cause, rather than comparing the wrong entity | The tool cannot follow a ticker to its predecessor entity |
| 14 | **Ground truth goes stale** when a newer 10-K is filed | Evaluation exact-number questions fail | The runner detects the period mismatch and prints a refresh warning instead of reporting silent failures | Requires a manual refresh |
| 15 | **Risk diff is heading-level** | A rewritten risk body under an unchanged heading is missed | Item 1A character counts shown alongside; caveat states the limitation explicitly | Real misses are possible |

## The largest untested surface

**The prompts have not been tuned against real model output.** One live end-to-end run on
`deepseek-v4-flash` produced schema-valid output that passed every gate, with no figure written by
the model. That is evidence the path works, not a measurement of prompt quality. `research/synthesis.py` and the LLM branch of `research/qa.py` are validated with a stubbed
client. That stub does exercise every gate — a fabricated citation, a single-period citation, an invented
`$91.4 billion`, and "investors should buy the stock" are each asserted to be discarded, and timeout,
refusal and truncation each resolve to a run-log entry rather than an exception. What is *not* validated
is how a real model behaves against these prompts: whether it reliably emits schema-conforming JSON,
whether it respects the "never write a figure" instruction often enough for the numeric gate to be a
backstop rather than the primary defence, and whether the citation instructions produce usable ids. The
three `llm_required` evaluation questions are reported as **not measured** for the same reason.

This is why the product was built deterministic-first: the untested layer is the one that can be absent
without the tool losing its value.

## Scope limits (not defects — deliberate boundaries)

* Only Items 1, 1A, 7 and 7A are extracted. Financial-statement notes, segment tables, exhibits and
  Item 5 market information are not indexed.
* Free cash flow is a prototype definition: operating cash flow − purchases of PP&E. It excludes
  acquisitions, finance-lease principal and capitalised software not tagged as PP&E, so it will not match
  a company's own FCF disclosure. The definition is printed next to the number everywhere it appears.
* Ten research topics. A change outside them is not surfaced as a material change, though it remains
  searchable in the Q&A view.
* Coverage measured on 11 large filers (`evaluation/COVERAGE.md`): 10/11 usable. Metric coverage is
  business-model dependent — 7/21 for JPM, 9/21 for Berkshire, because banks and insurance
  conglomerates lack gross profit, cost of revenue and PP&E-style capex. Correct degradation, but the
  tool is much less useful for financials. Correctness ground truth exists for MSFT only.
* 10-Q support is structural only: comparability checks handle it; metrics and topics are tuned for
  annual filings.
* No recommendations, price targets, forecasts, portfolio construction or trading logic — by design.

## What this system does *not* claim

It is not institutional-grade and not production-ready. It does not eliminate hallucination: it
constrains what the model may say, checks its output mechanically, labels what is inference, and reports
what it could not verify. The analyst remains the decision-maker; every number and every quote is one
click from its source on SEC EDGAR.
