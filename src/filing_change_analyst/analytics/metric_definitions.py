"""The metric catalogue.

Each metric is either
  * ``reported`` — read straight from one or more XBRL concepts, or
  * ``derived``  — computed in Python from other metrics.

Concept lists are ordered fallbacks: the first concept that yields a usable
fact for the filing wins, and the concept actually used is recorded in the
metric's provenance so an analyst can see which tag was read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MetricKind = Literal["currency", "ratio", "count"]


@dataclass(frozen=True)
class MetricDef:
    metric_id: str
    label: str
    kind: MetricKind
    definition: str
    # reported metrics
    concepts: tuple[str, ...] = ()
    sum_concepts: tuple[tuple[str, ...], ...] = ()  # each inner tuple is one addend's fallbacks
    period_type: Literal["duration", "instant"] = "duration"
    sign: float = 1.0
    # derived metrics
    derived_from: tuple[str, ...] = ()
    formula: str = ""
    higher_is_better: bool | None = True
    tags: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# Reported metrics
# --------------------------------------------------------------------------- #

REPORTED_METRICS: tuple[MetricDef, ...] = (
    MetricDef(
        metric_id="revenue",
        label="Revenue",
        kind="currency",
        definition="Total revenue as reported on the income statement.",
        concepts=(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
        ),
        tags=("revenue", "growth"),
    ),
    MetricDef(
        metric_id="cost_of_revenue",
        label="Cost of revenue",
        kind="currency",
        definition="Cost of revenue / cost of sales as reported.",
        concepts=("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices"),
        higher_is_better=False,
        tags=("margin",),
    ),
    MetricDef(
        metric_id="gross_profit",
        label="Gross profit",
        kind="currency",
        definition="Gross profit as reported; if not tagged, revenue less cost of revenue.",
        concepts=("GrossProfit",),
        tags=("margin",),
    ),
    MetricDef(
        metric_id="operating_income",
        label="Operating income",
        kind="currency",
        definition="Operating income (loss) as reported.",
        concepts=("OperatingIncomeLoss",),
        tags=("margin", "profit"),
    ),
    MetricDef(
        metric_id="net_income",
        label="Net income",
        kind="currency",
        definition="Net income (loss) attributable to the company as reported.",
        concepts=("NetIncomeLoss", "ProfitLoss"),
        tags=("profit",),
    ),
    MetricDef(
        metric_id="rnd_expense",
        label="R&D expense",
        kind="currency",
        definition="Research and development expense as reported.",
        concepts=("ResearchAndDevelopmentExpense",),
        tags=("investment",),
    ),
    MetricDef(
        metric_id="sgna_expense",
        label="Sales, general & admin expense",
        kind="currency",
        definition="Selling, general and administrative expense (sum of tagged components).",
        concepts=(
            "SellingGeneralAndAdministrativeExpense",
            "GeneralAndAdministrativeExpense",
        ),
        higher_is_better=False,
        tags=("cost",),
    ),
    MetricDef(
        metric_id="operating_cash_flow",
        label="Operating cash flow",
        kind="currency",
        definition="Net cash provided by operating activities as reported in the cash-flow statement.",
        concepts=(
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
        tags=("cash",),
    ),
    MetricDef(
        metric_id="capex",
        label="Capital expenditure",
        kind="currency",
        definition=(
            "Cash paid to acquire property, plant and equipment, as reported in investing "
            "activities. Reported as a positive outflow."
        ),
        concepts=(
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ),
        higher_is_better=None,
        tags=("capex", "investment"),
    ),
    MetricDef(
        metric_id="cash_and_equivalents",
        label="Cash and equivalents",
        kind="currency",
        definition="Cash and cash equivalents at period end (balance-sheet instant).",
        concepts=(
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        period_type="instant",
        tags=("balance_sheet",),
    ),
    MetricDef(
        metric_id="short_term_investments",
        label="Short-term investments",
        kind="currency",
        definition="Short-term investments at period end (balance-sheet instant).",
        concepts=("ShortTermInvestments", "OtherShortTermInvestments"),
        period_type="instant",
        tags=("balance_sheet",),
    ),
    MetricDef(
        metric_id="total_debt",
        label="Total debt",
        kind="currency",
        definition=(
            "Current portion of long-term debt plus non-current long-term debt at period end. "
            "Falls back to the combined LongTermDebt tag when the split is not available."
        ),
        sum_concepts=(
            ("LongTermDebtCurrent", "LongTermDebtCurrentMaturities"),
            ("LongTermDebtNoncurrent",),
        ),
        concepts=("LongTermDebt",),
        period_type="instant",
        higher_is_better=False,
        tags=("balance_sheet", "leverage"),
    ),
    MetricDef(
        metric_id="stockholders_equity",
        label="Stockholders' equity",
        kind="currency",
        definition="Total stockholders' equity at period end (balance-sheet instant).",
        concepts=("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        period_type="instant",
        tags=("balance_sheet",),
    ),
    MetricDef(
        metric_id="diluted_eps",
        label="Diluted EPS",
        kind="count",
        definition="Diluted earnings per share as reported (USD per share).",
        concepts=("EarningsPerShareDiluted",),
        tags=("profit",),
    ),
)


# --------------------------------------------------------------------------- #
# Derived metrics — computed in Python, never by the model
# --------------------------------------------------------------------------- #

DERIVED_METRICS: tuple[MetricDef, ...] = (
    MetricDef(
        metric_id="gross_margin",
        label="Gross margin",
        kind="ratio",
        definition="Gross profit ÷ revenue. Reported as a percentage; change is in percentage points.",
        derived_from=("gross_profit", "revenue"),
        formula="gross_profit / revenue",
        tags=("margin",),
    ),
    MetricDef(
        metric_id="operating_margin",
        label="Operating margin",
        kind="ratio",
        definition="Operating income ÷ revenue. Change is in percentage points.",
        derived_from=("operating_income", "revenue"),
        formula="operating_income / revenue",
        tags=("margin",),
    ),
    MetricDef(
        metric_id="net_margin",
        label="Net margin",
        kind="ratio",
        definition="Net income ÷ revenue. Change is in percentage points.",
        derived_from=("net_income", "revenue"),
        formula="net_income / revenue",
        tags=("margin",),
    ),
    MetricDef(
        metric_id="free_cash_flow",
        label="Estimated free cash flow",
        kind="currency",
        definition=(
            "PROTOTYPE DEFINITION: operating cash flow minus capital expenditure "
            "(purchases of property, plant and equipment). It excludes acquisitions, "
            "finance-lease principal payments and capitalised software not tagged as PP&E, so "
            "it will not always equal a company's own 'free cash flow' disclosure."
        ),
        derived_from=("operating_cash_flow", "capex"),
        formula="operating_cash_flow - capex",
        tags=("cash", "capex"),
    ),
    MetricDef(
        metric_id="capex_intensity",
        label="Capex ÷ revenue",
        kind="ratio",
        definition="Capital expenditure ÷ revenue. Change is in percentage points.",
        derived_from=("capex", "revenue"),
        formula="capex / revenue",
        higher_is_better=None,
        tags=("capex", "investment"),
    ),
    MetricDef(
        metric_id="rnd_intensity",
        label="R&D ÷ revenue",
        kind="ratio",
        definition="R&D expense ÷ revenue. Change is in percentage points.",
        derived_from=("rnd_expense", "revenue"),
        formula="rnd_expense / revenue",
        tags=("investment",),
    ),
    MetricDef(
        metric_id="net_cash",
        label="Net cash (cash + ST investments − total debt)",
        kind="currency",
        definition=(
            "Cash and equivalents plus short-term investments minus total debt at period end. "
            "A simple liquidity indicator, not a formal net-debt definition."
        ),
        derived_from=("cash_and_equivalents", "short_term_investments", "total_debt"),
        formula="cash_and_equivalents + short_term_investments - total_debt",
        tags=("balance_sheet", "leverage"),
    ),
)

ALL_METRICS: tuple[MetricDef, ...] = REPORTED_METRICS + DERIVED_METRICS
METRICS_BY_ID: dict[str, MetricDef] = {m.metric_id: m for m in ALL_METRICS}

# The order shown in the snapshot table (View B).
DISPLAY_ORDER: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "gross_margin",
    "operating_income",
    "operating_margin",
    "net_income",
    "net_margin",
    "diluted_eps",
    "rnd_expense",
    "rnd_intensity",
    "operating_cash_flow",
    "capex",
    "capex_intensity",
    "free_cash_flow",
    "cash_and_equivalents",
    "short_term_investments",
    "total_debt",
    "net_cash",
    "stockholders_equity",
    "cost_of_revenue",
    "sgna_expense",
)

FREE_CASH_FLOW_DEFINITION = METRICS_BY_ID["free_cash_flow"].definition
