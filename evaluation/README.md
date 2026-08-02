# Evaluation

A small, credible question set for the default MSFT 10-K pair.

* `questions.json` — 22 questions with hand-read ground truth.
* `run_evaluation.py` — scorer; writes `RESULTS.md` and `results.json`.
* `RESULTS.md` — the latest measured run (regenerated, not hand-written).

```bash
python evaluation/run_evaluation.py            # uses a model if API_KEY is set
python evaluation/run_evaluation.py --no-llm   # force deterministic-only scoring
```

## Composition

| Type | Count | What it checks |
|---|---:|---|
| `exact_number` | 5 | Calculated values match figures read by hand from the filings |
| `calculated_change` | 4 | Percent and percentage-point changes match hand arithmetic |
| `period_correctness` | 2 | Duration vs instant facts are compared correctly |
| `retrieval` | 4 | The expected section and terminology are retrieved from both periods |
| `cross_period_change` | 3 | A change is surfaced with both-period evidence and the right metric direction |
| `insufficient_evidence` | 4 | The system declines instead of guessing |

The four `insufficient_evidence` questions are deliberately split:

* **q19, q23, q24** are *vocabulary-level* gaps — the distinctive query terms appear nowhere in the
  filings, so the deterministic query-coverage gate can decline without a model.
* **q20, q21, q22** are *fact-level* gaps — every word of the question appears in the filings but the
  fact does not. A lexical retriever cannot detect these. They are marked `llm_required` and reported as
  **not measured** when no key is configured, rather than being scored as passes.

## Ground truth

All expected values were read by hand from Microsoft's FY2025 Form 10-K
(accession `0000950170-25-100235`) and FY2024 Form 10-K (`0000950170-24-087843`). Percentage-change and
percentage-point expectations were computed by hand from those figures — not copied from this tool's
output — so the suite genuinely tests the calculation engine.

If Microsoft files a newer 10-K, the runner prints a warning that the ground truth needs refreshing
rather than silently reporting failures.
