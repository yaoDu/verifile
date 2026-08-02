# Screenshots

Captured from a live run of `streamlit run app.py` against the real MSFT FY2025 / FY2024 10-K pair,
with **no `API_KEY` configured** — everything shown is produced deterministically.

| File | View | What it shows |
|---|---|---|
| `01-filing-selection.jpg` | Landing / View A | Ticker and form selection, the single primary action, and the explicit no-key notice |
| `02-financial-snapshot.jpg` | View B | 21/21 metrics compared, 471 chunks indexed, 4.5s run; percent changes for levels and percentage points for ratios |
| `03-financial-snapshot-capex.jpg` | View B | Capex +45.13%, capex ÷ revenue +4.77pp, estimated free cash flow −3.32% — the core finding |
| `04-material-change-side-by-side.jpg` | View C | A material change with earlier and later excerpts side by side, each carrying section, accession number, chunk id and a link to the filing |
| `05-risk-factor-diff.jpg` | Risk factors | 31 vs 34 headings: 2 new, 5 no longer present, 29 retained, with Item 1A length change |
| `06-insufficient-evidence.jpg` | View D | An honest refusal, reporting the measured BM25 score (14.5), query-term coverage (26%) and which terms appear nowhere in the filings |
| `07-analyst-brief.jpg` | View E | The one-page brief with the Markdown download |

`06-insufficient-evidence.jpg` is the one worth looking at twice: the system declines and shows exactly
why, rather than returning fluent text about a fact the filings do not contain.
