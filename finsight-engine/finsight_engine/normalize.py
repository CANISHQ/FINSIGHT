"""Raw provider record -> PeriodFinancials. Raw input is kept separate; this layer never guesses units."""
from __future__ import annotations
from datetime import date
from typing import Iterable
from .models import (BALANCE_ITEMS, CASHFLOW_ITEMS, INCOME_ITEMS, Basis, Period, PeriodFinancials,
                     PeriodType, SectorType, Source)
from .units import parse_unit, to_decimal, to_rupees

_ALIASES = {
    "revenue": ["revenue", "total revenue", "revenue from operations", "net sales", "sales"],
    "gross_profit": ["gross profit"], "ebitda": ["ebitda"], "ebit": ["ebit"],
    "depreciation": ["depreciation", "depreciation and amortisation", "depreciation and amortization", "d&a"],
    "finance_costs": ["finance costs", "finance cost", "interest expense", "interest"],
    "profit_before_tax": ["profit before tax", "pbt"],
    "net_profit": ["net profit", "profit after tax", "pat", "net income"],
    "eps": ["eps", "earnings per share"],
    "total_assets": ["total assets"], "current_assets": ["current assets", "total current assets"],
    "current_liabilities": ["current liabilities", "total current liabilities"],
    "total_liabilities": ["total liabilities"],
    "total_equity": ["total equity", "shareholders equity", "shareholders' equity", "net worth"],
    "short_term_debt": ["short term debt", "short-term borrowings", "short term borrowings"],
    "long_term_debt": ["long term debt", "long-term borrowings", "long term borrowings"],
    "total_debt": ["total debt", "total borrowings"],
    "cash": ["cash", "cash and cash equivalents"], "inventory": ["inventory", "inventories"],
    "receivables": ["receivables", "trade receivables", "debtors"],
    "cfo": ["cfo", "cash flow from operations", "net cash from operating activities"],
    "capex": ["capex", "capital expenditure", "purchase of fixed assets"],
    "cfi": ["cfi", "cash flow from investing", "net cash from investing activities"],
    "cff": ["cff", "cash flow from financing", "net cash from financing activities"],
}
_LOOKUP = {a: c for c, al in _ALIASES.items() for a in al}
_POSITIVE_EXPENSE = {"capex", "finance_costs", "depreciation"}


def _as_date(v):
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(v)


def normalize_record(raw: dict, source: Source) -> PeriodFinancials:
    """raw: {company, fiscal_year, period_type, quarter?, basis, unit, sector_type?, published_on?, restated?, items:{label: value}}.
    unit and basis are mandatory: we refuse to assume them."""
    for key in ("company", "fiscal_year", "period_type", "basis", "unit", "items"):
        if key not in raw:
            raise ValueError(f"raw record missing required field {key!r}")
    unit = parse_unit(raw["unit"])
    period = Period(int(raw["fiscal_year"]), PeriodType(raw["period_type"]), raw.get("quarter"))
    fin = PeriodFinancials(company=raw["company"], period=period, basis=Basis(raw["basis"]),
                           sector_type=SectorType(raw.get("sector_type", "general")), source=source,
                           published_on=_as_date(raw.get("published_on")), restated=bool(raw.get("restated", False)))
    blocks = {**{i: fin.income for i in INCOME_ITEMS}, **{i: fin.balance for i in BALANCE_ITEMS},
              **{i: fin.cashflow for i in CASHFLOW_ITEMS}}
    for label, value in raw["items"].items():
        canon = _LOOKUP.get(label.strip().lower().replace("_", " "))
        if canon is None:
            fin.unmapped.append(label)
            continue
        d = to_decimal(value)
        if d is not None:
            d = abs(d) if canon in _POSITIVE_EXPENSE else d
            if canon != "eps":
                d = to_rupees(d, unit)
        if canon in blocks[canon] and blocks[canon][canon] != d:
            raise ValueError(f"conflicting values for {canon!r} in {fin.company} {period.label}")
        blocks[canon][canon] = d
    return fin


def _diff(old: PeriodFinancials, new: PeriodFinancials) -> dict:
    out = {}
    for name in (*INCOME_ITEMS, *BALANCE_ITEMS, *CASHFLOW_ITEMS):
        a, b = old.get(name), new.get(name)
        if a != b:
            out[name] = {"old": None if a is None else str(a), "new": None if b is None else str(b)}
    return out


def resolve_restatements(records: Iterable[PeriodFinancials]) -> list:
    """Keep the latest-published version per (company, basis, period); record what it replaced."""
    groups: dict = {}
    for r in records:
        groups.setdefault((r.company, r.basis, r.period), []).append(r)
    out = []
    for versions in groups.values():
        versions.sort(key=lambda r: r.published_on or date.min)
        latest = versions[-1]
        latest.supersedes = [{"published_on": str(v.published_on), "source_id": v.source.source_id,
                              "changes": _diff(v, latest)} for v in versions[:-1]]
        if latest.supersedes:
            latest.restated = True
        out.append(latest)
    return out
