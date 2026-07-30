# Multi-filer coverage check

Run 2026-07-30 01:45 UTC over 11 filers, deterministic-only (no API key).

**10/11 produced a usable comparison; 10/11 also produced text evidence.**

This is a coverage measurement, not a correctness one — there is no hand-read ground truth for these filers. It exists to keep the README's generality claims honest.

| Ticker | Company | Periods | Metrics | Chunks | Changes | Risk headings | Heading strategy | Confidence | Warnings |
|---|---|---|---:|---:|---:|---|---|---|---:|
| MSFT | MICROSOFT CORP | 2025-06-30 → 2026-06-30 | 21/21 | 449 | 8 | 31→33 | `upper_case` | high | 0 |
| AAPL | Apple Inc. | 2024-09-28 → 2025-09-27 | 19/21 | 279 | 5 | 29→28 | `mixed_case` | high | 0 |
| NVDA | NVIDIA CORP | 2025-01-26 → 2026-01-25 | 19/21 | 365 | 8 | 27→28 | `mixed_case` | high | 0 |
| TSLA | Tesla, Inc. | 2024-12-31 → 2025-12-31 | 21/21 | 596 | 7 | 42→41 | `upper_case` | high | 0 |
| WMT | Walmart Inc. | 2025-01-31 → 2026-01-31 | 17/21 | 521 | 7 | 24→23 | `upper_case` | high | 0 |
| UNH | UNITEDHEALTH GROUP INC | 2024-12-31 → 2025-12-31 | 17/21 | 423 | 5 | 20→21 | `upper_case` | high | 0 |
| KO | COCA COLA CO | 2024-12-31 → 2025-12-31 | 17/21 | 866 | 4 | 41→41 | `upper_case` | high | 0 |
| PG | PROCTER & GAMBLE Co | 2024-06-30 → 2025-06-30 | 19/21 | 446 | 5 | 16→16 | `title_only` | low | 0 |
| JPM | JPMORGAN CHASE & CO | 2024-12-31 → 2025-12-31 | 7/21 | 273 | 5 | 42→43 | `mixed_case` | high | 0 |
| BRK-B | BERKSHIRE HATHAWAY INC | 2024-12-31 → 2025-12-31 | 9/21 | 701 | 3 | 14→14 | `mixed_case` | high | 0 |
| **XOM** | — | — | — | — | — | — | — | — | `refused` |

## Refused or crashed

- **XOM** (`refused`): Found 0 10-K filing(s) for XOM; at least 2 are needed for a period-over-period comparison. This can happen when a ticker has just been reassigned to a newly registered entity after a reorganisation — the SEC ticker index points at the new registrant, which has no filing history yet.

## Metrics that degraded to N/A

- **AAPL**: short_term_investments, net_cash
- **NVDA**: short_term_investments, net_cash
- **WMT**: rnd_expense, rnd_intensity, short_term_investments, net_cash
- **UNH**: rnd_expense, rnd_intensity, total_debt, net_cash
- **KO**: rnd_expense, rnd_intensity, total_debt, net_cash
- **PG**: short_term_investments, net_cash
- **JPM**: gross_profit, gross_margin, operating_income, operating_margin, rnd_expense, rnd_intensity, capex, capex_intensity, free_cash_flow, short_term_investments, total_debt, net_cash, cost_of_revenue, sgna_expense
- **BRK-B**: gross_profit, gross_margin, operating_income, operating_margin, diluted_eps, rnd_expense, rnd_intensity, short_term_investments, total_debt, net_cash, cost_of_revenue, sgna_expense

Missing metrics are reported as `N/A` with the concepts that were tried; nothing is estimated. Banks and insurance conglomerates legitimately lack gross profit, cost of revenue and PP&E-style capital expenditure, so a low metric count for those filers is correct behaviour rather than a failure.

## What this check found

- **Section anchoring needed three strategies, not one.** Upper-case item headings (`ITEM 1A.`) work for MSFT, WMT, UNH, KO and TSLA. Workiva-generated filings (AAPL, NVDA, BRK-B) use title case. P&G omits item numbers from the body entirely and needs bare title anchoring, which is reported at low confidence. Before this was fixed, four of ten filers produced **zero** text evidence with only a risk-diff warning.
- **High-volume filers overflow the `recent` submissions block.** JPMorgan files ~25,000 documents, so `recent` spans a few weeks and holds one 10-K; the rest are in the paginated older shards. The tool refused JPM outright until it learned to read them.
- **A reassigned ticker is a real condition.** XOM currently resolves to 'ExxonMobil Holdings Corp' (CIK 0002115436) in the SEC ticker index, a registrant with no 10-K history. The tool refuses with an explanation rather than comparing the wrong entity — the correct outcome, but it cannot follow the ticker to the predecessor.
