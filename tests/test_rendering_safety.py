"""Filing content must never reach the UI as renderable markup.

`html_to_text` strips tags, but BeautifulSoup's `get_text` also *decodes HTML
entities* — so a filing that legitimately writes `&lt;img src=x onerror=...&gt;`
(a 10-K quoting markup, or using `&lt;` in a formula) yields a raw `<img …>` in
the extracted text. An earlier version of `evidence_card` passed that straight
into Streamlit's raw-HTML rendering path.

The checks below parse the AST rather than grepping the source, so a docstring
explaining the hazard does not count as committing it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from filing_change_analyst.sec.sections import html_to_text
from filing_change_analyst.ui import components

PACKAGE_DIR = Path(components.__file__).resolve().parents[1]
APP_ENTRYPOINT = Path(components.__file__).resolve().parents[3] / "app.py"


def _raw_html_calls(source: str, filename: str) -> list[str]:
    """Call sites that actually pass a truthy ``unsafe_allow_html`` keyword."""
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "unsafe_allow_html":
                continue
            disabled = isinstance(kw.value, ast.Constant) and kw.value.value in (False, None)
            if not disabled:
                offenders.append(f"{filename}:{node.lineno}")
    return offenders


def test_entity_decoding_really_does_produce_raw_markup():
    """Guards the premise of this module.

    If this ever stopped being true the escaping requirement below could be
    relaxed, so the premise is asserted rather than assumed.
    """
    raw = (
        b"<html><body><p>ITEM 1. BUSINESS</p>"
        b"<p>We process &lt;img src=x onerror=alert(1)&gt; payloads where margin "
        b"&lt; 30 percent.</p></body></html>"
    )
    text = html_to_text(raw)
    assert "<img src=x onerror=alert(1)>" in text
    assert "< 30 percent" in text


def test_ast_check_would_catch_a_regression():
    """Negative control — the checker must fail on the pattern it exists to ban."""
    bad = "import streamlit as st\nst.markdown(text, unsafe_allow_html=True)\n"
    assert _raw_html_calls(bad, "x.py") == ["x.py:2"]
    ok = "import streamlit as st\nst.markdown(t)\nst.markdown(t, unsafe_allow_html=False)\n"
    assert _raw_html_calls(ok, "x.py") == []


CHOKEPOINT_MODULE = "ui/theme.py"
CHOKEPOINT_FUNC = "render"


def test_raw_html_rendering_is_confined_to_one_chokepoint():
    """Chrome needs markup; filing text must never be inside it.

    The metric grid's diverging bars, the emphasis chart and the risk
    composition bar have no Streamlit primitive, so the UI does render some of
    its own HTML. Rather than let that spread across the UI as a judgement call
    at every call site, every such call goes through ``theme.render`` and this
    test pins it there — so auditing the raw-HTML path means reading one
    function, and a stray ``unsafe_allow_html`` anywhere else fails the build.
    """
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        rel = str(path.relative_to(PACKAGE_DIR))
        calls = _raw_html_calls(path.read_text(), rel)
        if rel != CHOKEPOINT_MODULE:
            assert calls == [], f"raw-HTML rendering outside the chokepoint at {calls}"

    source = (PACKAGE_DIR / CHOKEPOINT_MODULE).read_text()
    calls = _raw_html_calls(source, CHOKEPOINT_MODULE)
    assert calls, "the chokepoint should still be the one place using the raw-HTML path"

    func = next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == CHOKEPOINT_FUNC
    )
    for call in calls:
        lineno = int(call.split(":")[1])
        assert func.lineno <= lineno <= (func.end_lineno or func.lineno), (
            f"raw-HTML call at {call} is outside {CHOKEPOINT_FUNC}()"
        )


def test_app_entrypoint_enables_no_raw_html_rendering():
    assert APP_ENTRYPOINT.exists(), APP_ENTRYPOINT
    assert _raw_html_calls(APP_ENTRYPOINT.read_text(), "app.py") == []


def test_chrome_builders_escape_third_party_strings(monkeypatch, fy2024):
    """Hostile EDGAR metadata must reach the chokepoint already inert.

    ``company_name``, ``form`` and ``accession`` come from EDGAR's submissions
    JSON, not from this repository, so they are third-party strings that end up
    inside markup. This drives them through the real rendering path and asserts
    that what arrives at ``theme.render`` carries no live markup.
    """
    from filing_change_analyst.models import AnalysisResult, FilingPair

    captured: list[str] = []
    monkeypatch.setattr(components.theme, "render", captured.append)

    hostile = '<img src=x onerror=alert(1)>"'
    poisoned = fy2024.model_copy(
        update={
            "company_name": hostile,
            "ticker": hostile,
            "form": hostile,
            "accession": hostile,
        }
    )
    result = AnalysisResult(pair=FilingPair(earlier=poisoned, later=poisoned))

    components.company_header(result)
    components.filing_context_bar(result)
    components.section_heading(hostile, hostile)

    assert captured, "the builders should have produced markup"
    for markup in captured:
        # `onerror=` may appear as literal text and is inert there; an unescaped
        # `<img` is not, and neither is the payload reaching the page verbatim.
        assert "<img" not in markup
        assert hostile not in markup
    assert any("&lt;img src=x onerror=alert(1)&gt;&quot;" in m for m in captured), (
        "the payload should have reached the markup in escaped form, "
        "otherwise this test is not exercising the path it claims to"
    )


def test_evidence_card_splits_excerpt_from_provenance():
    """Excerpt and metadata are separate calls, so the metadata can carry Markdown
    links without the filing text being trusted."""
    src = inspect.getsource(components.evidence_card)
    assert "st.caption(" in src, "provenance line should use the caption path"
    assert src.count("st.markdown(") == 1, "only the excerpt should go through markdown"


def test_extracted_text_never_contains_script_or_style_bodies():
    raw = (
        b"<html><head><style>p{color:red}</style></head><body>"
        b"<script>alert('x')</script><p>ITEM 1. BUSINESS</p><p>Real body text.</p>"
        b"</body></html>"
    )
    text = html_to_text(raw)
    assert "alert" not in text
    assert "color:red" not in text
    assert "Real body text." in text


def test_a_hostile_excerpt_survives_the_pipeline_as_inert_text(fy2024):
    """End to end: entity-encoded markup must reach the chunk verbatim.

    Verbatim matters both ways — it must not be rendered, and it must not be
    silently stripped either, or a quoted excerpt would misrepresent the filing.
    """
    from filing_change_analyst.retrieval.chunking import chunk_filing
    from filing_change_analyst.sec.sections import extract_sections

    hostile = "We process &lt;img src=x onerror=alert(1)&gt; payloads. " * 40
    raw = (
        f"<html><body><p>ITEM 1. BUSINESS</p><p>{hostile}</p>"
        f"<p>ITEM 1A. RISK FACTORS</p><p>{'Risk body text. ' * 200}</p>"
        f"<p>ITEM 7. MD&amp;A</p><p>{'MD and A body. ' * 200}</p></body></html>"
    ).encode()
    sections, _, _ = extract_sections(raw)
    chunks = chunk_filing(sections, fy2024, "earlier")
    business = [c for c in chunks if c.section_id == "item_1_business"]
    assert business, "the hostile section should still be chunked"
    assert "onerror=alert(1)" in business[0].text
