"""Domain schemas.

These types are the contract between the deterministic core, the retrieval
layer, the (optional) LLM layer and the UI. Anything the user sees as a number
originates in :class:`MetricComparison`; anything the user sees as a quote
originates in :class:`EvidenceChunk`.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Filings
# --------------------------------------------------------------------------- #

PeriodType = Literal["duration", "instant"]
DurationClass = Literal["annual", "three_quarters", "half_year", "quarterly", "other", "instant"]


class Filing(BaseModel):
    """One SEC filing selected for comparison."""

    model_config = ConfigDict(frozen=True)

    cik: str
    ticker: str
    company_name: str
    form: str
    accession: str
    filing_date: date
    report_date: date
    primary_document: str = ""
    fiscal_year_end: str = ""  # e.g. "0630"
    is_amendment: bool = False

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def filing_index_url(self) -> str:
        return (
            f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/"
            f"{self.accession_nodash}/{self.accession}-index.htm"
        )

    @property
    def primary_document_url(self) -> str:
        if not self.primary_document:
            return self.filing_index_url
        return (
            f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/"
            f"{self.accession_nodash}/{self.primary_document}"
        )

    @property
    def label(self) -> str:
        return f"{self.form} FY-end {self.report_date.isoformat()} (filed {self.filing_date.isoformat()})"


class FilingPair(BaseModel):
    """The later ("latest") filing and the earlier comparable filing."""

    earlier: Filing
    later: Filing
    comparability_ok: bool = True
    comparability_notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# XBRL facts and metrics
# --------------------------------------------------------------------------- #


class XbrlFact(BaseModel):
    """A single reported XBRL fact, with the provenance needed to audit it."""

    model_config = ConfigDict(frozen=True)

    concept: str
    taxonomy: str = "us-gaap"
    unit: str
    value: float
    start: date | None = None
    end: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str | None = None
    accession: str | None = None
    filed: date | None = None
    frame: str | None = None

    @property
    def period_type(self) -> PeriodType:
        return "duration" if self.start is not None else "instant"

    @property
    def duration_days(self) -> int | None:
        if self.start is None:
            return None
        return (self.end - self.start).days

    @property
    def sec_url(self) -> str | None:
        if not self.accession:
            return None
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={self.accession}"


class FactProvenance(BaseModel):
    """Human-inspectable provenance for one selected fact."""

    concept: str
    taxonomy: str
    unit: str
    period_type: PeriodType
    start: date | None
    end: date
    duration_days: int | None
    duration_class: DurationClass
    form: str | None
    accession: str | None
    filed: date | None
    fiscal_year: int | None
    fiscal_period: str | None
    source_url: str | None = None
    selection_rule: str = ""


class MetricValue(BaseModel):
    """One metric for one period. ``value`` is always computed in Python."""

    metric_id: str
    value: float | None
    unit: str
    period_type: PeriodType
    start: date | None = None
    end: date | None = None
    duration_class: DurationClass = "other"
    provenance: list[FactProvenance] = Field(default_factory=list)
    derivation: str = ""
    missing_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.value is not None


ComparisonStatus = Literal[
    "ok",
    "missing_earlier",
    "missing_later",
    "missing_both",
    "incompatible_periods",
]


class MetricComparison(BaseModel):
    """Period-over-period comparison for one metric. All arithmetic is Python."""

    metric_id: str
    label: str
    kind: Literal["currency", "ratio", "count"]
    earlier: MetricValue
    later: MetricValue
    absolute_change: float | None = None
    percent_change: float | None = None
    point_change: float | None = None
    status: ComparisonStatus = "ok"
    period_note: str = ""
    warnings: list[str] = Field(default_factory=list)
    definition: str = ""

    @property
    def usable(self) -> bool:
        return self.status == "ok"


class RestatementFlag(BaseModel):
    """Prior-period value as re-reported in the later filing vs as originally filed."""

    metric_id: str
    label: str
    as_originally_reported: float
    as_restated_in_later_filing: float
    difference: float
    relative_difference: float
    note: str


# --------------------------------------------------------------------------- #
# Sections, chunks and evidence
# --------------------------------------------------------------------------- #

SectionId = Literal[
    "item_1_business",
    "item_1a_risk_factors",
    "item_7_mdna",
    "item_7a_market_risk",
    "item_8_financial_statements",
    "unclassified",
]

SECTION_LABELS: dict[str, str] = {
    "item_1_business": "Item 1 — Business",
    "item_1a_risk_factors": "Item 1A — Risk Factors",
    "item_7_mdna": "Item 7 — Management's Discussion and Analysis",
    "item_7a_market_risk": "Item 7A — Quantitative and Qualitative Disclosures About Market Risk",
    "item_8_financial_statements": "Item 8 — Financial Statements",
    "unclassified": "Unclassified",
}


class FilingSection(BaseModel):
    """One extracted section of a filing (plain text)."""

    section_id: str
    label: str
    text: str
    char_count: int = 0
    extraction_note: str = ""

    @field_validator("char_count", mode="before")
    @classmethod
    def _default_count(cls, v, info):  # type: ignore[no-untyped-def]
        return v


class EvidenceChunk(BaseModel):
    """A retrievable, citable passage with full SEC provenance."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    period: Literal["earlier", "later"]
    ticker: str
    company_name: str
    cik: str
    form: str
    accession: str
    filing_date: date
    report_date: date
    section_id: str
    section_label: str
    heading: str = ""
    text: str
    ordinal: int = 0
    source_url: str = ""

    @property
    def citation_label(self) -> str:
        return (
            f"{self.form} FY{self.report_date.year} · {self.section_label} · "
            f"acc {self.accession}"
        )


class RetrievedEvidence(BaseModel):
    chunk: EvidenceChunk
    score: float
    matched_terms: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Change detection
# --------------------------------------------------------------------------- #

ClaimType = Literal[
    "verified_fact",
    "calculated_change",
    "management_statement",
    "interpretation",
    "caveat",
    "open_question",
]

EvidenceStrength = Literal["high", "moderate", "low"]

ChangeClassification = Literal[
    "new_disclosure",
    "removed_disclosure",
    "expanded_emphasis",
    "reduced_emphasis",
    "reworded",
    "quantitative_shift",
]


class TopicEvidencePair(BaseModel):
    """Deterministically retrieved earlier/later evidence for one research topic."""

    topic_id: str
    topic_label: str
    query_terms: list[str]
    earlier: list[RetrievedEvidence] = Field(default_factory=list)
    later: list[RetrievedEvidence] = Field(default_factory=list)
    earlier_hit_count: int = 0
    later_hit_count: int = 0
    earlier_phrase_counts: dict[str, int] = Field(default_factory=dict)
    later_phrase_counts: dict[str, int] = Field(default_factory=dict)
    earlier_rate: float = 0.0
    later_rate: float = 0.0
    emphasis_delta: float = 0.0
    related_metric_ids: list[str] = Field(default_factory=list)
    signal_note: str = ""

    @property
    def has_both_sides(self) -> bool:
        return bool(self.earlier) and bool(self.later)


class MaterialChange(BaseModel):
    """A claimed material change, always backed by both-period evidence."""

    change_id: str
    topic_id: str
    topic_label: str
    claim: str
    claim_type: ClaimType = "interpretation"
    classification: ChangeClassification = "expanded_emphasis"
    why_it_matters: str = ""
    earlier_source_ids: list[str] = Field(default_factory=list)
    later_source_ids: list[str] = Field(default_factory=list)
    related_metric_ids: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength = "moderate"
    caveat: str = ""
    generated_by: Literal["deterministic", "llm"] = "deterministic"


class RiskFactorDelta(BaseModel):
    """Risk-factor heading level diff between the two filings."""

    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    retained: list[str] = Field(default_factory=list)
    earlier_heading_count: int = 0
    later_heading_count: int = 0
    earlier_char_count: int = 0
    later_char_count: int = 0
    extraction_confidence: Literal["high", "moderate", "low"] = "moderate"
    note: str = ""


# --------------------------------------------------------------------------- #
# LLM structured output (validated before anything is displayed)
# --------------------------------------------------------------------------- #


class LlmChange(BaseModel):
    """Schema the model must emit. Deliberately contains no free-form numbers."""

    model_config = ConfigDict(extra="ignore")

    claim: str
    claim_type: ClaimType
    classification: ChangeClassification = "expanded_emphasis"
    why_it_matters: str = ""
    earlier_source_ids: list[str] = Field(default_factory=list)
    later_source_ids: list[str] = Field(default_factory=list)
    related_metric_ids: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength = "moderate"
    caveat: str = ""


class LlmChangeSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    changes: list[LlmChange] = Field(default_factory=list)
    insufficient_evidence: bool = False
    notes: str = ""


class LlmAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: str
    answer_type: Literal["answered", "insufficient_evidence"] = "answered"
    source_ids: list[str] = Field(default_factory=list)
    related_metric_ids: list[str] = Field(default_factory=list)
    caveat: str = ""


class LlmBriefSections(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: list[str] = Field(default_factory=list)
    bull_considerations: list[str] = Field(default_factory=list)
    bear_considerations: list[str] = Field(default_factory=list)
    questions_for_management: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class LlmRunLog(BaseModel):
    """Auditable record of one model call. Never contains the API key."""

    model: str
    prompt_version: str
    purpose: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    ok: bool = True
    error: str = ""
    dropped_citations: list[str] = Field(default_factory=list)
    dropped_changes: int = 0


# --------------------------------------------------------------------------- #
# The assembled analysis
# --------------------------------------------------------------------------- #


class QaResult(BaseModel):
    question: str
    answer: str
    answer_type: Literal["answered", "insufficient_evidence", "llm_unavailable"]
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    related_metric_ids: list[str] = Field(default_factory=list)
    caveat: str = ""
    generated_by: Literal["deterministic", "llm"] = "deterministic"


class AnalysisResult(BaseModel):
    """Everything the UI and the brief render."""

    pair: FilingPair
    comparisons: list[MetricComparison] = Field(default_factory=list)
    restatements: list[RestatementFlag] = Field(default_factory=list)
    sections: dict[str, dict[str, FilingSection]] = Field(default_factory=dict)
    chunks: list[EvidenceChunk] = Field(default_factory=list)
    topics: list[TopicEvidencePair] = Field(default_factory=list)
    changes: list[MaterialChange] = Field(default_factory=list)
    risk_delta: RiskFactorDelta | None = None
    # Which heading convention located each period's sections; surfaced so an
    # analyst can see how the text was found rather than having to trust it.
    section_strategy: dict[str, str] = Field(default_factory=dict)
    brief_extras: LlmBriefSections | None = None
    llm_logs: list[LlmRunLog] = Field(default_factory=list)
    llm_used: bool = False
    warnings: list[str] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)

    def chunk_by_id(self, chunk_id: str) -> EvidenceChunk | None:
        for c in self.chunks:
            if c.chunk_id == chunk_id:
                return c
        return None

    def comparison_by_id(self, metric_id: str) -> MetricComparison | None:
        for m in self.comparisons:
            if m.metric_id == metric_id:
                return m
        return None
