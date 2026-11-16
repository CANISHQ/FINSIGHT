"""Assemble per-period metrics, history and red flags into one JSON-ready CompanyAnalysis."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional
from . import metrics as M
from .models import Basis, PeriodFinancials, PeriodType
from .redflags import RedFlag, detect_red_flags

SCHEMA_VERSION = "1.0"
CONTRACT = ("All values below are computed by the Python engine. Consumers (including LLMs) must quote them verbatim "
            "and must not recompute, round differently, or infer values whose status is not 'ok' or 'partial'.")


@dataclass
class PeriodAnalysis:
    period: object
    restated: bool
    metrics: dict = field(default_factory=dict)


@dataclass
class CompanyAnalysis:
    company: str
    basis: Basis
    sector_type: str
    annual: list
    quarterly: list
    history: dict
    red_flags: list
    data_quality: list
    as_of: Optional[date] = None

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "contract": CONTRACT, "company": self.company,
                "basis": self.basis.value, "sector_type": self.sector_type, "as_of": str(self.as_of) if self.as_of else None,
                "annual": [_pa(p) for p in self.annual], "quarterly": [_pa(p) for p in self.quarterly],
                "history": {k: _mr(v) for k, v in self.history.items()},
                "red_flags": [_rf(f) for f in self.red_flags], "data_quality": self.data_quality,
                "facts": self.facts()}

    def facts(self) -> list:
        """Flat, citable list for the AI layer. Each fact has a stable id; the LLM cites ids, never computes."""
        out = []
        for pa in [*self.annual, *self.quarterly]:
            for m in pa.metrics.values():
                out.append({"id": f"{self.company}|{self.basis.value}|{pa.period.label}|{m.name}", **_mr(m)})
        return out


def _q(v, unit):
    if v is None:
        return None
    return str(v.quantize(Decimal("0.01") if unit == "INR" else Decimal("0.0001")))


def _per(p):
    return None if p is None else {"label": p.label, "fiscal_year": p.fiscal_year, "period_type": p.period_type.value, "quarter": p.quarter}


def _mr(m: M.MetricResult) -> dict:
    return {"metric": m.name, "value": _q(m.value, m.unit), "unit": m.unit, "status": m.status.value,
            "period": _per(m.period), "basis": m.basis.value, "formula": m.formula, "inputs": m.inputs,
            "note": m.note, "sources": list(m.sources)}


def _pa(p: PeriodAnalysis) -> dict:
    return {"period": _per(p.period), "restated": p.restated, "metrics": {k: _mr(v) for k, v in p.metrics.items()}}


def _rf(f: RedFlag) -> dict:
    return {"flag_id": f.flag_id, "name": f.name, "severity": f.severity.value, "metric": f.metric,
            "current_value": None if f.current_value is None else str(f.current_value.quantize(Decimal("0.0001"))),
            "previous_value": None if f.previous_value is None else str(f.previous_value.quantize(Decimal("0.0001"))),
            "period": _per(f.period), "comparison_period": _per(f.comparison_period), "basis": f.basis.value,
            "persistent": f.persistent, "sources": list(f.sources), "explanation": f.explanation,
            "limitations": f.limitations, "disclaimer": f.disclaimer}


def _metrics_for(cur, yoy, qoq=None) -> dict:
    ms = [M.ebit(cur), M.ebitda(cur), M.gross_margin(cur), M.ebitda_margin(cur), M.ebit_margin(cur),
          M.net_profit_margin(cur), M.free_cash_flow(cur), M.cash_conversion(cur), M.net_debt(cur),
          M.debt_to_equity(cur), M.current_ratio(cur), M.quick_ratio(cur), M.interest_coverage(cur)]
    if cur.period.period_type == PeriodType.ANNUAL:
        ms += [M.roe(cur, yoy), M.roce(cur, yoy), M.roa(cur, yoy)]
    ms += [M.revenue_growth(cur, yoy), M.ebitda_growth(cur, yoy), M.net_profit_growth(cur, yoy)]
    if qoq is not None or cur.period.period_type == PeriodType.QUARTERLY:
        ms += [M.revenue_growth(cur, qoq, "qoq"), M.ebitda_growth(cur, qoq, "qoq"), M.net_profit_growth(cur, qoq, "qoq")]
    return {m.name: m for m in ms}


def analyse_company(records: list, company: str, basis: Basis, as_of: Optional[date] = None) -> CompanyAnalysis:
    """Analyse ONE company on ONE basis. Records of the other basis are ignored, never blended.
    Call resolve_restatements() first; duplicate periods are an error."""
    fins = [r for r in records if r.company == company and r.basis == basis]
    idx: dict = {}
    for f in fins:
        if f.period in idx:
            raise ValueError(f"duplicate {f.period.label} for {company} ({basis.value}); resolve restatements first")
        idx[f.period] = f
    dq = []
    if not fins:
        dq.append(f"no {basis.value} statements available for {company}")
        return CompanyAnalysis(company, basis, "general", [], [], {}, [], dq, as_of)
    sector = fins[0].sector_type
    if any(f.sector_type != sector for f in fins):
        raise ValueError("mixed sector types for one company")
    annual = sorted((f for f in fins if f.period.period_type == PeriodType.ANNUAL), key=lambda f: f.period)
    quarterly = sorted((f for f in fins if f.period.period_type == PeriodType.QUARTERLY), key=lambda f: f.period)
    a_out = [PeriodAnalysis(f.period, f.restated, _metrics_for(f, idx.get(f.period.prior_year()))) for f in annual]
    q_out = [PeriodAnalysis(f.period, f.restated, _metrics_for(f, idx.get(f.period.prior_year()), idx.get(f.period.prior_quarter()))) for f in quarterly]
    history = {}
    if len(annual) >= 2:
        first, last = annual[0], annual[-1]
        for stem in ("revenue", "net_profit"):
            history[f"{stem}_cagr"] = M.cagr_metric(stem, first, last)
    for f in fins:
        if f.restated:
            dq.append(f"{f.period.label} is restated; earlier published versions are superseded")
        if f.unmapped:
            dq.append(f"{f.period.label}: unmapped source labels ignored: {', '.join(f.unmapped)}")
        if f.source.verification_status != "verified":
            dq.append(f"{f.period.label}: source {f.source.source_id} is {f.source.verification_status}")
    flags, notes = detect_red_flags(annual)
    return CompanyAnalysis(company, basis, sector.value, a_out, q_out, history, flags, dq + notes, as_of)
