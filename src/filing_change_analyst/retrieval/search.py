"""Topic probes and question routing.

A *topic probe* is a hand-written, versioned query used to pull comparable
evidence from both filings for the same research theme. Because the queries are
fixed, the retrieved evidence is identical on every run — which is what lets the
no-LLM mode still surface real, citable cross-period changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import RetrievedEvidence, TopicEvidencePair
from .index import Bm25Index, tokenize

# Occurrences per 10 000 tokens; keeps the signal comparable when one filing's
# section is materially longer than the other's.
NORMALISATION_BASE = 10_000

DEFAULT_SECTIONS = ("item_1_business", "item_1a_risk_factors", "item_7_mdna", "item_7a_market_risk")


@dataclass(frozen=True)
class Topic:
    topic_id: str
    label: str
    query: str
    # Terms counted for the emphasis delta (distinct from the retrieval query,
    # which is broader on purpose).
    emphasis_terms: tuple[str, ...]
    sections: tuple[str, ...] = DEFAULT_SECTIONS
    related_metric_ids: tuple[str, ...] = ()
    why_it_matters: str = ""


TOPICS: tuple[Topic, ...] = (
    Topic(
        topic_id="capex_infrastructure",
        label="Capital expenditure and infrastructure build-out",
        query=(
            "capital expenditures property and equipment datacenters data center infrastructure "
            "finance leases construction in progress server capacity"
        ),
        emphasis_terms=("capital expenditures", "datacenter", "data center", "finance leases", "infrastructure"),
        sections=("item_7_mdna", "item_1_business", "item_1a_risk_factors"),
        related_metric_ids=("capex", "capex_intensity", "free_cash_flow", "operating_cash_flow"),
        why_it_matters=(
            "Capital intensity changes the shape of free cash flow and future depreciation, "
            "which feeds directly into margin and valuation work."
        ),
    ),
    Topic(
        topic_id="ai_investment",
        label="AI investment and monetisation",
        query=(
            "artificial intelligence AI Copilot Azure AI models inference training OpenAI "
            "generative AI investment"
        ),
        emphasis_terms=("artificial intelligence", "ai", "copilot", "openai", "generative"),
        related_metric_ids=("rnd_expense", "rnd_intensity", "capex", "revenue"),
        why_it_matters=(
            "Shifts in how prominently AI is discussed indicate where management expects growth "
            "and where spending is being directed."
        ),
    ),
    Topic(
        topic_id="competition",
        label="Competitive positioning",
        query="competition competitors competitive pressure market share rivals alternative providers",
        emphasis_terms=("competition", "competitors", "competitive"),
        sections=("item_1_business", "item_1a_risk_factors", "item_7_mdna"),
        related_metric_ids=("gross_margin", "operating_margin", "revenue"),
        why_it_matters="Competitive language shifts often precede pricing and margin pressure.",
    ),
    Topic(
        topic_id="cloud_demand",
        label="Cloud demand and growth drivers",
        query=(
            "Azure cloud services demand growth consumption commercial bookings remaining "
            "performance obligation subscription seats"
        ),
        emphasis_terms=("azure", "cloud", "bookings", "consumption", "demand"),
        sections=("item_7_mdna", "item_1_business"),
        related_metric_ids=("revenue", "gross_margin"),
        why_it_matters="Demand commentary is the main qualitative check on the revenue trajectory.",
    ),
    Topic(
        topic_id="margin_drivers",
        label="Margin and cost drivers",
        query=(
            "gross margin operating expenses cost of revenue depreciation useful lives "
            "operating leverage cost of goods sold margin percentage"
        ),
        emphasis_terms=("gross margin", "depreciation", "useful lives", "cost of revenue", "operating expenses"),
        sections=("item_7_mdna",),
        related_metric_ids=("gross_margin", "operating_margin", "cost_of_revenue"),
        why_it_matters="Named margin drivers let an analyst separate mix effects from cost inflation.",
    ),
    Topic(
        topic_id="capacity_constraints",
        label="Capacity, supply and energy constraints",
        query=(
            "capacity constraints supply chain shortage power energy availability construction "
            "delays components lead times"
        ),
        emphasis_terms=("capacity", "constraints", "supply chain", "energy", "power"),
        related_metric_ids=("capex", "revenue"),
        why_it_matters="Physical constraints cap near-term revenue conversion regardless of demand.",
    ),
    Topic(
        topic_id="regulation",
        label="Regulatory and legal exposure",
        query=(
            "regulatory requirements regulation antitrust competition authorities Digital Markets "
            "Act privacy data protection investigations compliance"
        ),
        emphasis_terms=("regulation", "regulatory", "antitrust", "privacy", "investigation"),
        sections=("item_1a_risk_factors", "item_1_business", "item_7_mdna"),
        related_metric_ids=(),
        why_it_matters="Regulatory change alters the cost base and can restrict product bundling.",
    ),
    Topic(
        topic_id="workforce",
        label="Workforce and headcount",
        query="employees headcount talent workforce hiring severance restructuring attrition compensation",
        emphasis_terms=("employees", "headcount", "severance", "restructuring", "workforce"),
        related_metric_ids=("sgna_expense", "operating_margin"),
        why_it_matters="Headcount actions show up in operating expense with a lag.",
    ),
    Topic(
        topic_id="security_cyber",
        label="Cybersecurity exposure",
        query="cyberattack cybersecurity security incident vulnerability threat actor nation-state breach",
        emphasis_terms=("cyberattack", "cybersecurity", "vulnerability", "threat actor", "incident"),
        sections=("item_1a_risk_factors", "item_1_business"),
        related_metric_ids=(),
        why_it_matters="Security incidents carry direct remediation cost and indirect trust cost.",
    ),
    Topic(
        topic_id="shareholder_returns",
        label="Shareholder returns",
        query="dividends declared share repurchases buyback returned to shareholders repurchase program",
        emphasis_terms=("dividends", "repurchase", "buyback", "shareholders"),
        sections=("item_7_mdna",),
        related_metric_ids=("free_cash_flow",),
        why_it_matters="Return policy competes with capex for the same cash flow.",
    ),
)

TOPICS_BY_ID: dict[str, Topic] = {t.topic_id: t for t in TOPICS}


def probe_topic(index: Bm25Index, topic: Topic, *, top_k: int = 3) -> TopicEvidencePair:
    """Retrieve matched earlier/later evidence and compute a deterministic emphasis delta."""
    earlier = index.search(topic.query, period="earlier", section_ids=topic.sections, top_k=top_k)
    later = index.search(topic.query, period="later", section_ids=topic.sections, top_k=top_k)

    e_counts = index.phrase_frequency(
        list(topic.emphasis_terms), period="earlier", section_ids=topic.sections
    )
    l_counts = index.phrase_frequency(
        list(topic.emphasis_terms), period="later", section_ids=topic.sections
    )
    e_hits, l_hits = sum(e_counts.values()), sum(l_counts.values())
    e_tokens = index.token_count(period="earlier", section_ids=topic.sections) or 1
    l_tokens = index.token_count(period="later", section_ids=topic.sections) or 1

    e_rate = e_hits / e_tokens * NORMALISATION_BASE
    l_rate = l_hits / l_tokens * NORMALISATION_BASE
    delta = l_rate - e_rate

    signal = (
        f"Emphasis = non-overlapping occurrences of {list(topic.emphasis_terms)} per "
        f"{NORMALISATION_BASE:,} tokens across {', '.join(topic.sections)}. "
        f"Earlier: {e_hits} mentions / {e_tokens:,} tokens = {e_rate:.1f}. "
        f"Later: {l_hits} mentions / {l_tokens:,} tokens = {l_rate:.1f}. "
        f"Delta {delta:+.1f}."
    )

    return TopicEvidencePair(
        topic_id=topic.topic_id,
        topic_label=topic.label,
        query_terms=tokenize(topic.query),
        earlier=earlier,
        later=later,
        earlier_hit_count=e_hits,
        later_hit_count=l_hits,
        earlier_phrase_counts=e_counts,
        later_phrase_counts=l_counts,
        earlier_rate=round(e_rate, 3),
        later_rate=round(l_rate, 3),
        emphasis_delta=round(delta, 3),
        related_metric_ids=list(topic.related_metric_ids),
        signal_note=signal,
    )


def probe_all_topics(index: Bm25Index, *, top_k: int = 3) -> list[TopicEvidencePair]:
    return [probe_topic(index, t, top_k=top_k) for t in TOPICS]


# --------------------------------------------------------------------------- #
# Free-text question routing
# --------------------------------------------------------------------------- #

_SECTION_HINTS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\brisk", re.I), ("item_1a_risk_factors",)),
    (re.compile(r"\b(md&a|management.s discussion|margin|cash flow|revenue|expense|guidance)\b", re.I),
     ("item_7_mdna",)),
    (re.compile(r"\b(business|segment|product|strategy|competitor)\b", re.I),
     ("item_1_business", "item_7_mdna", "item_1a_risk_factors")),
)


def sections_for_question(question: str) -> tuple[str, ...]:
    """Metadata pre-filter for a free-text question."""
    for pattern, sections in _SECTION_HINTS:
        if pattern.search(question):
            return sections
    return DEFAULT_SECTIONS


def expand_query(question: str) -> str:
    """Add domain synonyms that BM25 cannot infer on its own."""
    q = question.lower()
    extra: list[str] = []
    if "capex" in q or "capital expenditure" in q:
        extra += ["property", "equipment", "datacenters", "finance leases"]
    if "buyback" in q or "repurchase" in q:
        extra += ["repurchase", "dividends", "shareholders"]
    if "margin" in q:
        extra += ["gross margin", "cost of revenue", "operating expenses"]
    if "ai" in tokenize(q):
        extra += ["artificial intelligence", "copilot", "models"]
    if "competition" in q or "competitor" in q:
        extra += ["competitive", "competitors", "market share"]
    return f"{question} {' '.join(extra)}".strip()


@dataclass
class QuestionRoute:
    question: str
    expanded_query: str
    sections: tuple[str, ...]
    evidence: list[RetrievedEvidence] = field(default_factory=list)


def retrieve_for_question(
    index: Bm25Index, question: str, *, top_k_per_period: int = 3
) -> QuestionRoute:
    """Retrieve balanced evidence from both periods for a free-text question."""
    sections = sections_for_question(question)
    expanded = expand_query(question)
    earlier = index.search(expanded, period="earlier", section_ids=sections, top_k=top_k_per_period)
    later = index.search(expanded, period="later", section_ids=sections, top_k=top_k_per_period)
    if not earlier and not later:  # widen the net before giving up
        earlier = index.search(expanded, period="earlier", top_k=top_k_per_period)
        later = index.search(expanded, period="later", top_k=top_k_per_period)
        sections = DEFAULT_SECTIONS
    merged = sorted(earlier + later, key=lambda r: -r.score)
    return QuestionRoute(
        question=question, expanded_query=expanded, sections=sections, evidence=merged
    )
