# Evaluation results

Run 2026-07-30 01:48 UTC against MSFT 10-K (2024-06-30 → 2025-06-30). AI synthesis: **disabled**.

**21 / 21 scored questions passed** (3 not measured). Pipeline run time 4.2s.

## Measures

| Measure | Result |
|---|---|
| Metric correctness — calculated values match hand-read filing values | 11/11 (100%) |
| Period correctness — compared facts use compatible durations/instants | 2/2 (100%) |
| Retrieval success — expected section/evidence is retrieved | 7/7 (100%) |
| Citation validity — every citation resolves to supplied evidence | 11/11 (100%) |
| Citation support — retrieved excerpt contains the expected terminology | 4/4 (100%) |
| Numerical accuracy — reported changes reproduce deterministic values | 4/4 (100%) |
| Insufficient-evidence handling — the system declines | 3/3 (100%) |
| Unsupported-claim rate — material changes lacking both-period evidence or a caveat | 0/7 |
| Latency — median / slowest scored question | 1 ms / 1 ms |

## Question-level results

| id | type | verdict | detail | ms |
|---|---|---|---|---:|
| q01 | exact_number | PASS | expected 281,724,000,000.00, produced 281,724,000,000.00 | 0 |
| q02 | exact_number | PASS | expected 64,551,000,000.00, produced 64,551,000,000.00 | 0 |
| q03 | exact_number | PASS | expected 88,136,000,000.00, produced 88,136,000,000.00 | 0 |
| q04 | exact_number | PASS | expected 13.64, produced 13.64 | 0 |
| q05 | exact_number | PASS | expected 136,162,000,000.00, produced 136,162,000,000.00 | 0 |
| q06 | calculated_change | PASS | expected +14.932%, produced +14.932% | 0 |
| q07 | calculated_change | PASS | expected +45.135%, produced +45.133% | 0 |
| q08 | calculated_change | PASS | expected -0.939pp, produced -0.941pp | 0 |
| q09 | calculated_change | PASS | expected -3.321%, produced -3.321% | 0 |
| q10 | period_correctness | PASS | both sides duration/annual: True; comparison status=ok | 0 |
| q11 | period_correctness | PASS | both sides instant/instant: True; comparison status=ok | 0 |
| q12 | retrieval | PASS | sections=['item_1_business', 'item_1a_risk_factors'] periods=['earlier', 'later'] section_hit=True term_hit=True both_periods=True | 1 |
| q13 | retrieval | PASS | sections=['item_1a_risk_factors', 'item_7_mdna'] periods=['earlier', 'later'] section_hit=True term_hit=True both_periods=True | 0 |
| q14 | retrieval | PASS | sections=['item_7_mdna'] periods=['earlier', 'later'] section_hit=True term_hit=True both_periods=True | 0 |
| q15 | retrieval | PASS | sections=['item_1a_risk_factors'] periods=['earlier', 'later'] section_hit=True term_hit=True both_periods=True | 0 |
| q16 | cross_period_change | PASS | both_periods=True metric_direction_ok=True surfaced_as_change=True | 0 |
| q17 | cross_period_change | PASS | +2 / -5 headings | 0 |
| q18 | cross_period_change | PASS | both_periods=True metric_direction_ok=True surfaced_as_change=True | 0 |
| q19 | insufficient_evidence | PASS | answer_type=insufficient_evidence, 6 passages retrieved | 0 |
| q20 | insufficient_evidence | not measured | not measured — requires a configured model | 0 |
| q21 | insufficient_evidence | not measured | not measured — requires a configured model | 0 |
| q22 | insufficient_evidence | not measured | not measured — requires a configured model | 0 |
| q23 | insufficient_evidence | PASS | answer_type=insufficient_evidence, 6 passages retrieved | 0 |
| q24 | insufficient_evidence | PASS | answer_type=insufficient_evidence, 6 passages retrieved | 0 |

## Failures

None.

## Not measured

- **q20** — not measured — requires a configured model
- **q21** — not measured — requires a configured model
- **q22** — not measured — requires a configured model

