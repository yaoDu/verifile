"""Design tokens and the single global stylesheet.

Everything in this module is static CSS authored in this repository. No
filing-derived text is ever interpolated into it, and no filing text is
rendered through ``unsafe_allow_html`` anywhere in the UI — see the docstring
on :func:`render` and on ``components.evidence_card`` for why that matters.

**The palette.** Near-black ground, warm off-white ink, one lime accent, one
cyan counter-accent, hairline borders at 4–10% white. Two deliberate choices
follow from it:

*Direction hues are lime and cyan, not green and red.* Financial UIs habitually
paint "up" green and "down" red, which asserts that rising capex or rising debt
is good news. This app measures changes and refuses to grade them. Lime against
cyan reads as two directions rather than a pass and a fail, and it survives
deuteranopia far better than the red/green pair it replaces.

*Contrast is checked against the ground, not assumed.* On ``#0F1115`` the ink
``#E8E8E5`` runs about 15:1 and the dimmest supporting text about 5.4:1, so
every text token clears WCAG AA at the sizes used here.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------- #
# Tokens — importable so chart-building code and the CSS share one palette
# --------------------------------------------------------------------------- #

GROUND = "#0F1115"
SURFACE = "#141820"
SURFACE_2 = "#181D26"
LINE = "rgba(255,255,255,0.07)"
LINE_STRONG = "rgba(255,255,255,0.14)"

INK = "#E8E8E5"
INK_MUTED = "rgba(232,232,229,0.66)"
INK_DIM = "#8A93A3"

ACCENT = "#A3E635"  # lime — primary accent and "increased"
ACCENT_DEEP = "#7CB518"
COUNTER = "#22D3EE"  # cyan — "decreased"

UP = ACCENT
DOWN = COUNTER
FLAT = "#5C6675"

WARN = "#FBBF24"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@300;400;500;600;700&family=Google+Sans+Code:wght@400;500&display=swap');

:root {{
  --ground: {GROUND};
  --surface: {SURFACE};
  --surface-2: {SURFACE_2};
  --line: {LINE};
  --line-strong: {LINE_STRONG};
  --ink: {INK};
  --ink-muted: {INK_MUTED};
  --ink-dim: {INK_DIM};
  --accent: {ACCENT};
  --accent-deep: {ACCENT_DEEP};
  --counter: {COUNTER};
  --up: {UP};
  --down: {DOWN};
  --flat: {FLAT};
  --warn: {WARN};
  --radius: 12px;
  --radius-sm: 6px;
  --ease: cubic-bezier(0.4, 0, 0.2, 1);
  --sans: 'Be Vietnam Pro', ui-sans-serif, system-ui, sans-serif;
  --mono: 'Google Sans Code', ui-monospace, SFMono-Regular, Menlo, monospace;
}}

/* ---------- Ground and the aurora ---------------------------------------- */

/* The signature element: lime bleeding down from the top of the page, fading
   to ground by ~70%. Sized to the first ~900px so it scrolls away rather than
   tinting the whole document. */
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(105% 58% at 50% -2%,
      rgba(163, 230, 53, 0.20) 0%,
      rgba(163, 230, 53, 0.075) 26%,
      rgba(163, 230, 53, 0.018) 48%,
      rgba(15, 17, 21, 0) 72%),
    var(--ground);
  background-repeat: no-repeat;
  background-size: 100% 820px, auto;
}}

html, body, [data-testid="stAppViewContainer"] {{ font-family: var(--sans); color: var(--ink); }}
code, kbd, pre, .fca-mono {{ font-family: var(--mono) !important; }}

.block-container {{ padding-top: 2.2rem; padding-bottom: 6rem; max-width: 1340px; }}

h1, h2, h3, h4 {{ letter-spacing: -0.02em; color: var(--ink); font-family: var(--sans); }}
h1 {{ font-size: 1.9rem !important; font-weight: 600 !important; padding-top: 0 !important; }}
h2 {{ font-size: 1.3rem !important; font-weight: 600 !important; }}
h3 {{ font-size: 1.05rem !important; font-weight: 600 !important; }}

/* ---------- Motion -------------------------------------------------------- */

@keyframes fca-rise {{
  from {{ opacity: 0; transform: translateY(9px); }}
  to   {{ opacity: 1; transform: none; }}
}}
@keyframes fca-grow-r {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
@keyframes fca-grow-l {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
@keyframes fca-shimmer {{ 0% {{ background-position: -420px 0; }} 100% {{ background-position: 420px 0; }} }}
@keyframes fca-pulse {{
  0%, 100% {{ opacity: 0.55; transform: scale(1); }}
  50%      {{ opacity: 1; transform: scale(1.35); }}
}}

.fca-rise {{ animation: fca-rise 0.5s var(--ease) both; }}

/* Anything that animates on entry must also be legible without the animation.
   Bars use scaleX, so `both` fill would leave them at scaleX(0) if animation is
   suppressed — hence explicit `none` plus a reset transform here. */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation: none !important;
    transition: none !important;
    scroll-behavior: auto !important;
  }}
  .fca-rise, .fca-bar-fill, .fca-emph-fill, .fca-risk-seg {{
    opacity: 1 !important; transform: none !important;
  }}
}}

/* ---------- Section heading ---------------------------------------------- */

.fca-sec {{ margin: 0.35rem 0 1.2rem 0; }}
.fca-sec-title {{
  font-size: 1.18rem; font-weight: 600; color: var(--ink);
  letter-spacing: -0.02em; margin-bottom: 0.3rem;
}}
.fca-sec-note {{ font-size: 0.845rem; color: var(--ink-muted); line-height: 1.6; max-width: 78ch; }}

.fca-eyebrow {{
  font-family: var(--mono); font-size: 0.68rem; text-transform: uppercase;
  letter-spacing: 0.14em; color: var(--accent); font-weight: 500;
}}

/* ---------- Wordmark ------------------------------------------------------ */

.fca-wordmark {{
  display: flex; align-items: center; gap: 0.6rem;
  font-size: 1.32rem; font-weight: 600; letter-spacing: -0.025em;
  color: var(--ink); margin-bottom: 0.42rem;
}}

/* ---------- Result header ------------------------------------------------- */

/* Name and run-mode chips share one baseline; the chips replace what used to be
   a caption line and a full-width banner stacked beneath the name. */
.fca-result-head {{
  display: flex; align-items: baseline; flex-wrap: wrap;
  gap: 0.5rem 0.9rem; margin-bottom: 0.8rem;
}}
.fca-result-name {{
  font-size: 1.6rem; font-weight: 600; letter-spacing: -0.03em; color: var(--ink);
}}
.fca-result-name .tk {{ color: var(--accent); font-weight: 400; }}
.fca-result-head .fca-chips {{ position: relative; top: -0.15rem; }}
.fca-wordmark-mark {{
  width: 11px; height: 11px; flex: 0 0 auto;
  background: var(--accent); transform: rotate(45deg); border-radius: 2px;
  box-shadow: 0 0 14px rgba(163, 230, 53, 0.5);
}}

/* ---------- Filing context bar ------------------------------------------- */

/* Two filing cards, not a table row.
   The previous layout was one wide strip of cells whose two records differed by
   a single character — `2025-06-30` against `2026-06-30` — so telling them
   apart meant reading digit by digit. Each filing is now its own block led by a
   large month-and-year, which is the part that actually differs (the year for a
   year-on-year 10-K pair, the month for two 10-Qs), with dates and accession
   demoted to supporting metadata. Colour does the rest: the current filing
   carries the accent, the previous one stays muted. */
.fca-cmp {{
  border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--surface); overflow: hidden; margin-bottom: 1.1rem;
}}
.fca-cmp-head {{
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; padding: 0.55rem 0.95rem;
  border-bottom: 1px solid var(--line); background: rgba(255, 255, 255, 0.022);
}}
.fca-cmp-form {{
  font-family: var(--mono); font-size: 0.7rem; font-weight: 500;
  letter-spacing: 0.08em; color: var(--accent);
  border: 1px solid rgba(163, 230, 53, 0.32); background: rgba(163, 230, 53, 0.09);
  padding: 0.14rem 0.55rem; border-radius: 999px;
}}
.fca-cmp-gap {{
  font-family: var(--mono); font-size: 0.66rem; color: var(--ink-dim);
  letter-spacing: 0.08em; text-transform: uppercase;
}}

.fca-cmp-body {{
  display: grid; grid-template-columns: 1fr auto 1fr;
  align-items: stretch; padding: 0.8rem; gap: 0;
}}
.fca-cmp-card {{
  border: 1px solid var(--line); border-radius: var(--radius-sm);
  padding: 0.85rem 1rem 0.9rem; min-width: 0;
  transition: border-color 0.2s var(--ease);
}}
.fca-cmp-card.curr {{
  background: rgba(163, 230, 53, 0.04); border-color: rgba(163, 230, 53, 0.22);
}}
.fca-cmp-k {{
  font-family: var(--mono); font-size: 0.59rem; text-transform: uppercase;
  letter-spacing: 0.13em; color: var(--ink-dim); margin-bottom: 0.4rem;
}}
.fca-cmp-period {{
  font-size: 1.45rem; font-weight: 600; letter-spacing: -0.032em;
  line-height: 1; margin-bottom: 0.55rem; white-space: nowrap;
}}
.fca-cmp-card.prev .fca-cmp-period {{ color: var(--ink-muted); }}
.fca-cmp-card.curr .fca-cmp-period {{ color: var(--accent); }}
.fca-cmp-meta {{
  font-size: 0.775rem; color: var(--ink-muted); line-height: 1.6;
  font-variant-numeric: tabular-nums;
}}
.fca-cmp-meta .lbl {{ color: var(--ink-dim); }}
.fca-cmp-acc {{ margin-top: 0.5rem; font-family: var(--mono); font-size: 0.68rem; }}
.fca-cmp-acc a {{
  color: var(--ink-dim); text-decoration: none;
  transition: color 0.15s var(--ease); word-break: break-all;
}}
.fca-cmp-acc a:hover {{ color: var(--accent); }}

/* The connector is a marker, not a feature: a small chip, no rules or borders
   competing with the two cards it sits between. */
.fca-cmp-join {{ display: flex; align-items: center; justify-content: center; padding: 0 0.7rem; }}
.fca-cmp-arrow {{
  width: 24px; height: 24px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--line-strong); color: var(--ink-dim); font-size: 0.75rem;
}}

/* Stack rather than compress: below this width the two cards squeeze the
   month-and-year onto two lines, which defeats the point of leading with it. */
@media (max-width: 900px) {{
  .fca-cmp-body {{ grid-template-columns: 1fr; }}
  .fca-cmp-join {{ padding: 0.45rem 0; }}
  .fca-cmp-arrow {{ transform: rotate(90deg); }}
}}

/* ---------- Headline movers ---------------------------------------------- */

.fca-movers {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; margin-bottom: 1.4rem; }}
@media (max-width: 1100px) {{ .fca-movers {{ grid-template-columns: repeat(2, 1fr); }} }}

.fca-mover {{
  position: relative; overflow: hidden;
  border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--surface); padding: 0.9rem 1rem 0.95rem;
  transition: border-color 0.2s var(--ease), transform 0.2s var(--ease), background 0.2s var(--ease);
}}
.fca-mover::before {{
  content: ''; position: absolute; inset: 0 0 auto 0; height: 2px;
  background: var(--flat);
}}
.fca-mover.up::before {{ background: linear-gradient(90deg, var(--up), rgba(163,230,53,0)); }}
.fca-mover.down::before {{ background: linear-gradient(90deg, var(--down), rgba(34,211,238,0)); }}
.fca-mover:hover {{ transform: translateY(-2px); border-color: var(--line-strong); background: var(--surface-2); }}
.fca-mover-k {{
  font-family: var(--mono); font-size: 0.64rem; color: var(--ink-dim);
  text-transform: uppercase; letter-spacing: 0.1em;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 0.42rem;
}}
.fca-mover-v {{
  font-size: 1.7rem; font-weight: 600; letter-spacing: -0.035em;
  font-variant-numeric: tabular-nums; line-height: 1.02; margin-bottom: 0.34rem;
}}
.fca-mover-v.up {{ color: var(--up); }}
.fca-mover-v.down {{ color: var(--down); }}
.fca-mover-sub {{
  font-family: var(--mono); font-size: 0.735rem; color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
}}
.fca-mover-sub .arw {{ color: var(--ink-dim); padding: 0 0.22rem; }}

/* ---------- Metric grid --------------------------------------------------- */

.fca-grid {{
  border: 1px solid var(--line); border-radius: var(--radius);
  overflow-x: auto; background: var(--surface); margin-bottom: 0.6rem;
}}
.fca-grid table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
.fca-grid thead th {{
  font-family: var(--mono); font-size: 0.6rem; text-transform: uppercase;
  letter-spacing: 0.12em; color: var(--ink-dim); font-weight: 500; text-align: right;
  padding: 0.66rem 0.9rem; background: var(--surface-2);
  border-bottom: 1px solid var(--line); white-space: nowrap;
}}
.fca-grid thead th.l {{ text-align: left; }}
.fca-grid td {{
  padding: 0.5rem 0.9rem; font-size: 0.85rem; color: var(--ink);
  border-bottom: 1px solid var(--line); text-align: right;
  font-variant-numeric: tabular-nums; white-space: nowrap;
  transition: background 0.12s var(--ease);
}}
.fca-grid tbody tr:last-child td {{ border-bottom: 0; }}
.fca-grid tbody tr:hover td {{ background: rgba(255,255,255,0.028); }}
.fca-grid td.l {{ text-align: left; font-weight: 450; white-space: normal; }}
.fca-grid td.num {{ font-family: var(--mono); font-size: 0.8rem; color: var(--ink-muted); }}
.fca-grid td.dim {{ color: var(--ink-dim); }}

.fca-grp td {{
  background: rgba(255,255,255,0.022) !important; padding: 0.46rem 0.9rem;
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
}}
.fca-grp-l {{
  font-family: var(--mono); font-size: 0.63rem; text-transform: uppercase;
  letter-spacing: 0.14em; color: var(--accent); font-weight: 500;
}}
.fca-grp-scale {{
  font-family: var(--mono); font-size: 0.63rem; color: var(--ink-dim);
  letter-spacing: 0.06em;
}}

.fca-chg {{ font-family: var(--mono); font-weight: 500; font-size: 0.815rem; }}
.fca-chg.up {{ color: var(--up); }}
.fca-chg.down {{ color: var(--down); }}
.fca-chg.na {{ color: var(--ink-dim); font-size: 0.72rem; }}

/* Diverging bar. The axis is a visible hairline at the cell's centre; bars grow
   outward from it on load, which is what makes a long column of them read as
   one chart rather than as decoration in a table. */
.fca-bar {{ width: 200px; padding-right: 1.2rem !important; }}
.fca-bar-track {{
  position: relative; height: 16px; width: 100%;
  background: linear-gradient(rgba(255,255,255,0.16), rgba(255,255,255,0.16)) center / 1px 100% no-repeat;
}}
.fca-bar-fill {{
  position: absolute; top: 3.5px; height: 9px; border-radius: 2px; min-width: 2px;
  animation: fca-grow-r 0.62s var(--ease) both;
}}
.fca-bar-fill.up {{
  background: linear-gradient(90deg, rgba(163,230,53,0.55), var(--up));
  transform-origin: left center;
  box-shadow: 0 0 12px rgba(163,230,53,0.22);
}}
.fca-bar-fill.down {{
  background: linear-gradient(270deg, rgba(34,211,238,0.55), var(--down));
  transform-origin: right center;
  animation-name: fca-grow-l;
  box-shadow: 0 0 12px rgba(34,211,238,0.2);
}}
.fca-bar-clip {{
  position: absolute; top: 1px; font-size: 0.62rem; line-height: 14px;
  color: var(--ink-dim); font-weight: 700;
}}

.fca-legend {{
  display: flex; gap: 1.2rem; flex-wrap: wrap; align-items: center;
  font-size: 0.755rem; color: var(--ink-muted); margin: 0.2rem 0 1.5rem 0;
}}
.fca-legend .sw {{
  display: inline-block; width: 22px; height: 7px; border-radius: 2px;
  vertical-align: middle; margin-right: 0.42rem;
}}

/* ---------- Emphasis chart ------------------------------------------------ */

.fca-emph {{
  border: 1px solid var(--line); border-radius: var(--radius);
  background: var(--surface); padding: 0.35rem 0 0.4rem; overflow: hidden;
}}
.fca-emph-row {{
  display: grid; grid-template-columns: minmax(120px, 250px) 1fr 84px;
  align-items: center; gap: 0.85rem; padding: 0.35rem 1.1rem;
  transition: background 0.12s var(--ease);
}}
.fca-emph-row:hover {{ background: rgba(255,255,255,0.028); }}
.fca-emph-l {{
  font-size: 0.83rem; color: var(--ink); font-weight: 450;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.fca-emph-v {{
  font-family: var(--mono); font-size: 0.8rem; text-align: right; font-weight: 500;
  font-variant-numeric: tabular-nums;
}}
.fca-emph-v.up {{ color: var(--up); }}
.fca-emph-v.down {{ color: var(--down); }}
.fca-emph-v.flat {{ color: var(--ink-dim); }}
.fca-emph-track {{
  position: relative; height: 14px;
  background: linear-gradient(rgba(255,255,255,0.16), rgba(255,255,255,0.16)) center / 1px 100% no-repeat;
}}
.fca-emph-fill {{
  position: absolute; top: 2.5px; height: 9px; border-radius: 2px; min-width: 2px;
  animation: fca-grow-r 0.62s var(--ease) both;
}}
.fca-emph-fill.up {{
  background: linear-gradient(90deg, rgba(163,230,53,0.5), var(--up));
  transform-origin: left center; box-shadow: 0 0 12px rgba(163,230,53,0.2);
}}
.fca-emph-fill.down {{
  background: linear-gradient(270deg, rgba(34,211,238,0.5), var(--down));
  transform-origin: right center; animation-name: fca-grow-l;
  box-shadow: 0 0 12px rgba(34,211,238,0.18);
}}
.fca-emph-fill.thr {{ opacity: 0.34; box-shadow: none; }}

/* ---------- Risk composition ---------------------------------------------- */

.fca-risk-bar {{
  display: flex; height: 32px; border-radius: var(--radius-sm); overflow: hidden;
  border: 1px solid var(--line); margin-bottom: 0.6rem;
}}
.fca-risk-seg {{
  display: flex; align-items: center; justify-content: center;
  font-family: var(--mono); font-size: 0.74rem; font-weight: 500; min-width: 2px;
  animation: fca-rise 0.5s var(--ease) both;
}}
.fca-risk-seg.add {{ background: var(--up); color: #10240a; }}
.fca-risk-seg.keep {{ background: rgba(255,255,255,0.16); color: var(--ink); }}
.fca-risk-seg.rem {{ background: var(--down); color: #04262c; }}
.fca-risk-key {{
  display: flex; gap: 1.4rem; flex-wrap: wrap; font-size: 0.79rem;
  color: var(--ink-muted); margin-bottom: 1.3rem;
}}
.fca-risk-key b {{ color: var(--ink); font-variant-numeric: tabular-nums; }}
.fca-risk-key .sw {{
  display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  margin-right: 0.42rem; vertical-align: baseline;
}}

/* ---------- Change card --------------------------------------------------- */

.fca-card-head {{
  border-left: 2px solid var(--accent); padding: 0.1rem 0 0.85rem 0.85rem;
  margin-bottom: 0.75rem; border-bottom: 1px solid var(--line);
}}
.fca-card-head.up {{ border-left-color: var(--up); }}
.fca-card-head.down {{ border-left-color: var(--down); }}
.fca-card-t {{
  font-size: 1.06rem; font-weight: 600; color: var(--ink);
  letter-spacing: -0.02em; margin-bottom: 0.55rem;
}}
.fca-chips {{ display: flex; gap: 0.42rem; flex-wrap: wrap; }}
.fca-chip {{
  font-family: var(--mono); font-size: 0.66rem; font-weight: 400;
  padding: 0.2rem 0.55rem; border-radius: 999px;
  border: 1px solid var(--line-strong); color: var(--ink-muted);
  background: rgba(255,255,255,0.03); white-space: nowrap;
  transition: border-color 0.15s var(--ease), color 0.15s var(--ease);
}}
.fca-chip.k {{ background: rgba(163,230,53,0.09); border-color: rgba(163,230,53,0.32); color: var(--accent); }}
.fca-chip.s-high {{ background: rgba(163,230,53,0.09); border-color: rgba(163,230,53,0.32); color: var(--accent); }}
.fca-chip.s-moderate {{ background: rgba(251,191,36,0.09); border-color: rgba(251,191,36,0.3); color: var(--warn); }}
.fca-chip.s-low {{ background: rgba(34,211,238,0.09); border-color: rgba(34,211,238,0.3); color: var(--down); }}

.fca-side {{
  font-family: var(--mono); font-size: 0.62rem; text-transform: uppercase;
  letter-spacing: 0.13em; color: var(--ink-dim); margin-bottom: 0.5rem;
}}
.fca-side .dt {{ color: var(--accent); }}

/* ---------- Evidence timeline --------------------------------------------- */

/* Replaces a two-column earlier|later split. The excerpts are two independently
   retrieved passages, not one paragraph edited, so columns implied a
   line-for-line comparison that does not exist — while halving the measure to
   ~45 characters and leaving the two citation lines permanently misaligned.
   Stacked chronologically, the evidence keeps a full reading measure, aligns to
   one left edge, and expresses before/after as vertical progression.

   Period markers are deliberately neutral (dim vs bright ink). Lime and cyan
   mean "increased" and "decreased" everywhere else in this app, and reusing
   them for "earlier" and "later" would collide with that. */
.fca-ev {{ display: flex; align-items: center; gap: 0.6rem; margin: 0 0 0.4rem; }}
.fca-ev-dot {{ width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }}
.fca-ev-dot.earlier {{ background: var(--ink-dim); }}
.fca-ev-dot.later {{ background: var(--ink); box-shadow: 0 0 9px rgba(232, 232, 229, 0.4); }}
.fca-ev-k {{
  font-family: var(--mono); font-size: 0.62rem; text-transform: uppercase;
  letter-spacing: 0.13em; flex: 0 0 auto;
}}
.fca-ev-k.earlier {{ color: var(--ink-dim); }}
.fca-ev-k.later {{ color: var(--ink); }}
.fca-ev-date {{
  font-family: var(--mono); font-size: 0.72rem; color: var(--ink-muted); flex: 0 0 auto;
}}
.fca-ev-sec {{
  font-size: 0.75rem; color: var(--ink-dim); min-width: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.fca-ev-rule {{ flex: 1 1 auto; height: 1px; background: var(--line); min-width: 1rem; }}

/* The excerpt now spans the container, so cap the measure — a 110-character
   line is as hard to track back as a 45-character one. */
[data-testid="stMarkdownContainer"] blockquote {{ max-width: 88ch; }}

/* The risk-heading ledger deliberately has no styles here. Its rows are filing
   text, which must stay on the escaped Markdown path, so only the +/- marker is
   coloured and that is done with Streamlit's own `:colour[…]` directive rather
   than injected markup — the row needs no raw HTML at all. */

/* Excerpt quotes need to read as *quoted filing text*, distinct from our prose. */
[data-testid="stMarkdownContainer"] blockquote {{
  border-left: 2px solid var(--line-strong);
  background: rgba(255,255,255,0.028);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  padding: 0.7rem 0.9rem; margin: 0 0 0.4rem 0;
  color: var(--ink-muted); font-size: 0.845rem; line-height: 1.65;
}}
[data-testid="stMarkdownContainer"] blockquote p {{ margin-bottom: 0; }}

/* ---------- Landing ------------------------------------------------------- */

.fca-hero-h {{
  font-size: 3.05rem; font-weight: 600; letter-spacing: -0.045em;
  line-height: 1.08; color: var(--ink); max-width: 17ch; margin-bottom: 1.05rem;
}}
.fca-hero-h em {{ font-style: normal; color: var(--accent); }}
.fca-hero-p {{
  font-size: 1.05rem; color: var(--ink-muted); line-height: 1.65; max-width: 60ch;
}}
.fca-steps {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.8rem; margin-bottom: 2rem; }}
@media (max-width: 1000px) {{ .fca-steps {{ grid-template-columns: repeat(2, 1fr); }} }}
.fca-step {{
  border: 1px solid var(--line); border-radius: var(--radius);
  padding: 1rem 1.1rem; background: var(--surface);
  transition: border-color 0.2s var(--ease), transform 0.2s var(--ease), background 0.2s var(--ease);
  animation: fca-rise 0.5s var(--ease) both;
}}
.fca-step:hover {{ transform: translateY(-2px); border-color: rgba(163,230,53,0.3); background: var(--surface-2); }}
.fca-step-n {{
  font-family: var(--mono); font-size: 0.68rem; color: var(--accent);
  letter-spacing: 0.12em; margin-bottom: 0.4rem;
}}
.fca-step-t {{ font-size: 0.95rem; font-weight: 600; color: var(--ink); margin-bottom: 0.35rem; }}
.fca-step-d {{ font-size: 0.83rem; color: var(--ink-muted); line-height: 1.6; }}

.fca-cta {{
  margin: 1.8rem 0 2.2rem; padding: 0.9rem 1.2rem; border-radius: var(--radius);
  background: rgba(163,230,53,0.055); border: 1px solid rgba(163,230,53,0.24);
  font-size: 0.93rem; color: var(--ink-muted);
}}
.fca-cta b {{ color: var(--accent); font-weight: 500; }}

/* A live dot, so the pre-analysis screen does not read as a static poster. */
.fca-dot {{
  display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent); margin-right: 0.5rem; vertical-align: middle;
  animation: fca-pulse 2.4s var(--ease) infinite;
}}

/* ---------- Streamlit chrome ---------------------------------------------- */

/* ---------- Command bar --------------------------------------------------- */

/* The first bordered container on the page is the command bar. Widget labels
   inside it are compressed so the row reads as one control strip rather than as
   six stacked form fields. */
.block-container > div > div > [data-testid="stVerticalBlockBorderWrapper"]:first-of-type {{
  background: var(--surface);
  margin-bottom: 1.5rem;
}}
.block-container [data-testid="stVerticalBlockBorderWrapper"]:first-of-type
  [data-testid="stWidgetLabel"] p {{
  font-family: var(--mono); font-size: 0.6rem !important;
  text-transform: uppercase; letter-spacing: 0.11em; color: var(--ink-dim) !important;
}}

/* Popover triggers are peers of the primary button; keep them quiet. */
[data-testid="stPopover"] button {{
  background: transparent; border: 1px solid var(--line-strong); color: var(--ink-muted);
  font-weight: 450;
  transition: border-color 0.15s var(--ease), color 0.15s var(--ease);
}}
[data-testid="stPopover"] button:hover {{ border-color: var(--accent); color: var(--accent); }}

[data-testid="stMetricValue"] {{
  font-size: 1.6rem; font-weight: 600; letter-spacing: -0.03em; color: var(--ink);
}}
[data-testid="stMetricLabel"] p {{
  font-family: var(--mono); font-size: 0.64rem !important; text-transform: uppercase;
  letter-spacing: 0.1em; color: var(--ink-dim) !important;
}}

[data-testid="stExpander"] details {{
  border: 1px solid var(--line) !important; border-radius: var(--radius) !important;
  background: var(--surface);
}}
[data-testid="stExpander"] summary {{ font-size: 0.85rem; font-weight: 450; }}
[data-testid="stExpander"] summary:hover {{ color: var(--accent); }}

div[data-testid="stElementContainer"] hr {{ margin: 1.2rem 0; border-color: var(--line); }}

/* Streamlit's dark alerts read as muddy slabs. These are tinted panels with a
   left accent instead — the caveat and warning copy is load-bearing in this app
   and needs to look deliberate rather than like an error state. */
/* `stAlertContainer` is the element that paints; `stAlert` is only its wrapper. */
[data-testid="stAlertContainer"] {{
  border-radius: var(--radius-sm) !important; font-size: 0.85rem;
  border: 1px solid var(--line) !important; border-left-width: 2px !important;
  background: rgba(255,255,255,0.028) !important; color: var(--ink-muted) !important;
  box-shadow: none !important;
}}
[data-testid="stAlertContainer"] p {{ color: var(--ink-muted); }}
[data-testid="stAlertContainer"] strong {{ color: var(--ink); font-weight: 600; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{
  border-left-color: var(--warn) !important; background: rgba(251,191,36,0.05) !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{
  border-left-color: #F87171 !important; background: rgba(248,113,113,0.055) !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {{
  border-left-color: var(--accent) !important; background: rgba(163,230,53,0.055) !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
  border-left-color: var(--counter) !important; background: rgba(34,211,238,0.05) !important;
}}

/* Primary button: lime fill with a ripple on press, the reference's CTA idiom. */
.stButton button[kind="primary"] {{
  position: relative; overflow: hidden;
  background: var(--accent); color: #10240a; border: 0; font-weight: 600;
  transition: background 0.15s var(--ease), box-shadow 0.2s var(--ease), transform 0.12s var(--ease);
}}
.stButton button[kind="primary"]:hover {{
  background: #B4F04A; box-shadow: 0 0 22px rgba(163,230,53,0.3); color: #10240a;
}}
.stButton button[kind="primary"]:active {{ transform: scale(0.985); }}
.stButton button[kind="secondary"] {{
  background: transparent; border: 1px solid var(--line-strong); color: var(--ink-muted);
  transition: border-color 0.15s var(--ease), color 0.15s var(--ease);
}}
.stButton button[kind="secondary"]:hover {{ border-color: var(--accent); color: var(--accent); }}

/* Segmented control is the primary view switch, so it gets real presence. */
[data-testid="stButtonGroup"] button p {{ font-size: 0.86rem !important; font-weight: 450; }}
[data-testid="stButtonGroup"] button {{ transition: color 0.15s var(--ease), background 0.15s var(--ease); }}

[data-testid="stTextInput"] input, [data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
  background: var(--surface) !important; border-color: var(--line) !important;
}}
[data-testid="stTextInput"] input:focus {{ border-color: var(--accent) !important; }}

/* Loading state, borrowed from the reference's skeleton shimmer. */
[data-testid="stSpinner"] > div, [data-testid="stStatusWidget"] {{
  background-image: linear-gradient(90deg,
    rgba(255,255,255,0) 0%, rgba(163,230,53,0.07) 50%, rgba(255,255,255,0) 100%);
  background-size: 420px 100%; background-repeat: no-repeat;
  animation: fca-shimmer 1.8s ease-in-out infinite;
}}
</style>
"""


def render(markup: str) -> None:
    """The one place in this codebase that renders raw HTML. Chrome only.

    Streamlit has no primitive for a diverging bar, a grouped numeric table or a
    proportional stacked bar, and an analyst reading twenty-one undifferentiated
    rows of grey text is a worse outcome than the risk this function carries. So
    the project renders its own chrome as markup — but funnels every such call
    through here, so the question "can filing text reach the raw-HTML path?" is
    answered by auditing one function rather than every ``st.markdown`` in the
    UI. ``tests/test_rendering_safety.py`` enforces that there is exactly one.

    **The contract for callers.** ``markup`` must be built only from string
    literals in this repository and from values passed through
    :func:`html.escape`. Filing-derived text — excerpts, extracted headings,
    model-generated claims — must never be interpolated into it, no matter how
    it was cleaned first. Those go through the escaping Markdown path in
    :mod:`.components` instead, which is why ``html_to_text`` decoding
    ``&lt;img onerror=…&gt;`` back into live markup cannot hurt us.
    """
    st.markdown(markup, unsafe_allow_html=True)


def inject() -> None:
    """Install the stylesheet once per rerun. Static CSS only."""
    render(_CSS)
