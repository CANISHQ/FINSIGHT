"""Core data model: periods, sources and normalised statements."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional


class PeriodType(str, Enum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"


class Basis(str, Enum):
    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"


class SectorType(str, Enum):
    GENERAL = "general"      # non-financial companies
    FINANCIAL = "financial"  # banks / NBFCs: debt, EBITDA and FCF conventions do not apply


@dataclass(frozen=True, order=True)
class Period:
    """Indian fiscal period: fiscal_year 2026 means FY26 (Apr 2025 - Mar 2026)."""
    fiscal_year: int
    period_type: PeriodType
    quarter: Optional[int] = None

    def __post_init__(self):
        if self.period_type == PeriodType.ANNUAL and self.quarter is not None:
            raise ValueError("annual period cannot have a quarter")
        if self.period_type == PeriodType.QUARTERLY and self.quarter not in (1, 2, 3, 4):
            raise ValueError("quarterly period needs quarter 1-4")

    @property
    def label(self) -> str:
        fy = f"FY{self.fiscal_year % 100:02d}"
        return fy if self.quarter is None else f"Q{self.quarter} {fy}"

    def prior_year(self) -> "Period":
        return Period(self.fiscal_year - 1, self.period_type, self.quarter)

    def prior_quarter(self) -> "Period":
        if self.period_type != PeriodType.QUARTERLY:
            raise ValueError("prior_quarter needs a quarterly period")
        if self.quarter == 1:
            return Period(self.fiscal_year - 1, self.period_type, 4)
        return Period(self.fiscal_year, self.period_type, self.quarter - 1)


@dataclass(frozen=True)
class Source:
    source_id: str
    name: str
    url: Optional[str] = None
    document_type: Optional[str] = None
    publication_date: Optional[date] = None
    retrieval_date: Optional[date] = None
    verification_status: str = "unverified"


INCOME_ITEMS = ("revenue", "gross_profit", "ebitda", "ebit", "depreciation", "finance_costs",
                "profit_before_tax", "net_profit", "eps")
BALANCE_ITEMS = ("total_assets", "current_assets", "current_liabilities", "total_liabilities",
                 "total_equity", "short_term_debt", "long_term_debt", "total_debt", "cash",
                 "inventory", "receivables")
CASHFLOW_ITEMS = ("cfo", "capex", "cfi", "cff")


@dataclass
class PeriodFinancials:
    """One company, one period, one basis. All money values are Decimal RUPEES (eps in rupees/share).
    Expenses (finance_costs, depreciation, capex) are stored as positive numbers."""
    company: str
    period: Period
    basis: Basis
    sector_type: SectorType
    source: Source
    income: dict = field(default_factory=dict)
    balance: dict = field(default_factory=dict)
    cashflow: dict = field(default_factory=dict)
    published_on: Optional[date] = None
    restated: bool = False
    currency: str = "INR"
    supersedes: list = field(default_factory=list)  # prior versions replaced by this restatement
    unmapped: list = field(default_factory=list)    # input labels we could not map (never silently dropped)

    def get(self, name: str) -> Optional[Decimal]:
        for block in (self.income, self.balance, self.cashflow):
            if name in block:
                return block[name]
        return None
