# Contributing to Verifile

Thanks for considering it. Verifile presents figures that people may act on financially, so the bar for a
change here is a little different from a typical side project: **a contribution has to keep every claim
traceable, or it is a regression regardless of how well it works.**

Please read the two short sections below before opening a pull request. Everything else is ordinary.

## The rules that are not negotiable

These exist because breaking any of them makes the tool confidently wrong, which is worse than useless
for its purpose. Most are enforced by tests, and those tests are not scenery — if one fails, the fix is
the code, not the test.

1. **The model never produces a number.** Every figure comes from SEC XBRL facts and is computed in
   Python. A model may reword and connect measured signals; it may not originate a value. If you find
   yourself passing a calculation to a prompt, stop.
2. **Missing data stays missing.** An untagged or unusually tagged concept renders as `N/A`. Do not
   interpolate, estimate, or fall back to a "close enough" tag without recording the substitution in the
   metric's provenance.
3. **Every claimed change cites both periods.** A claim supported by only one filing is not a change.
   Citations must resolve to evidence that was actually supplied to the model.
4. **Filing text is never rendered as HTML.** `html_to_text` decodes HTML entities, so filing text can
   legitimately contain live-looking markup. It goes through the escaping Markdown path only. Raw-HTML
   rendering is funnelled through one audited function and pinned there by
   `tests/test_rendering_safety.py`.
5. **No recommendations.** No buy/sell language, no price targets, no predictions. This is a research
   aid and must keep saying so.
6. **Show the seams.** Low extraction confidence, restatement flags, blocked metrics and declined
   questions are surfaced on screen — including when they make the tool look worse. Removing a caveat to
   tidy the output is not a cleanup.

## Respecting the SEC

EDGAR is a free public service and is easy to abuse by accident.

- Keep the existing rate limiting and the `SEC_USER_AGENT` identity header. SEC blocks unidentified
  clients, and rightly so.
- Do not add code paths that re-download on every rerun. The HTTP cache exists for this reason.
- Never commit an API key, a real personal email, or bulk EDGAR data. `data/demo_cache.tar.gz` holds a
  deliberately small set of raw responses for four tickers.

## Getting set up

```bash
git clone https://github.com/yaoDu/verifile.git && cd verifile
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env     # set SEC_USER_AGENT to a real "Name email"
```

## Before you open a pull request

```bash
pytest                          # 168 tests, offline, ~2s — must pass
ruff check src tests app.py     # must be clean
ruff format src tests app.py    # only the files you touched
```

If you changed analysis behaviour, also run the evaluation and say what moved:

```bash
python evaluation/run_evaluation.py
python evaluation/run_coverage_check.py
```

A few things reviewers will look for:

- **Tests for behaviour, not for coverage.** A test that pins a real failure mode is worth ten that
  restate the implementation. If you fixed a bug, the test should fail without your fix.
- **Comments that explain why.** The codebase records reasoning where a choice was non-obvious — a
  threshold, a fallback order, a rejected alternative. Match that; skip narrating what the code says.
- **Scope.** One concern per pull request. Please don't bundle a reformat with a behaviour change; it
  makes the diff unreviewable.
- **Honest reporting.** If something is partly done or you could not verify a case, say so in the PR
  description. That is far more useful than a confident summary that turns out to be wrong.

## Reporting a problem

For a **wrong number or a broken citation**, please include the ticker, both accession numbers, the
metric or claim, and what you expected. These are the highest-priority defects in this project.

For a **security issue** — anything that could execute filing-controlled content, leak a key, or abuse
EDGAR — please open a private security advisory on the repository rather than a public issue.

For **anything else**, a normal issue is fine. Questions and "is this intentional?" reports are welcome;
several of the caveats now shown in the app started as somebody being confused by the output.

## Scope

Verifile is a focused prototype, not a platform. Contributions that deepen it — better section
extraction, more filers handled, tighter guardrails, clearer provenance — fit naturally. Contributions
that widen it into portfolio management, screening or anything resembling advice do not, and will be
declined however well built.

## Licence

By contributing you agree that your work is licensed under the repository's [MIT licence](LICENSE).
