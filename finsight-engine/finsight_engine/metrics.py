"""Pure, deterministic financial metrics. Every function returns a MetricResult carrying value, status,
formula, inputs, period, basis and sources. Invalid maths is reported via status, never as a number."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional
from .models import Basis, PeriodFinancials, PeriodType, SectorType

D = Decimal
HUNDRED = D(100)


class Status(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    MISSING_DATA = "missing_data"
    ZERO_DENOMINATOR = "zero_denominator"
    NOT_MEANINGFUL = "not_meaningful"
    NOT_APPLICABLE = "not_applicable"


class ComparabilityError(ValueError):
    """Raised when two statements must not be compared."""


@dataclass(frozen=True)
class Calc:
    value: Optional[Decimal]
    status: Status
    note: str = ""


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: Optional[Decimal]
    unit: str
    status: Status
    period: object
    basis: Basis
    formula: str
    inputs: dict
    note: str
    sources: tuple

    @property
    def ok(self) -> bool:
        return self.status in (Status.OK, Status.PARTIAL)


def safe_ratio(num, den) -> Calc:
    if num is None or den is None:
        return Calc(None, Status.MISSING_DATA, "required input missing")
    if den == 0:
        return Calc(None, Status.ZERO_DENOMINATOR, "denominator is zero")
    if den < 0:
        return Calc(None, Status.NOT_MEANINGFUL, "denominator is negative")
    return Calc(num / den, Status.OK)


def pct_growth(cur, prev) -> Calc:
    if cur is None or prev is None:
        return Calc(None, Status.MISSING_DATA, "current or previous value missing")
    if prev == 0:
        return Calc(None, Status.ZERO_DENOMINATOR, "previous value is zero")
    if prev < 0:
        return Calc(None, Status.NOT_MEANINGFUL, "previous value is negative; percentage growth is undefined")
    return Calc((cur - prev) / prev * HUNDRED, Status.OK)


def cagr(first, last, years: int) -> Calc:
    if first is None or last is None or years <= 0:
        return Calc(None, Status.MISSING_DATA, "needs two values and a positive span")
    if first <= 0 or last <= 0:
        return Calc(None, Status.NOT_MEANINGFUL, "CAGR needs positive start and end values")
    try:
        return Calc(((last / first) ** (D(1) / D(years)) - 1) * HUNDRED, Status.OK)
    except InvalidOperation:
        return Calc(None, Status.NOT_MEANINGFUL, "CAGR not computable")


def _avg_positive(opening, closing, label: str) -> Calc:
    if closing is None:
        return Calc(None, Status.MISSING_DATA, f"closing {label} missing")
    if closing <= 0 or (opening is not None and opening <= 0):
        return Calc(None, Status.NOT_MEANINGFUL, f"{label} is zero or negative")
    if opening is None:
        return Calc(closing, Status.PARTIAL, f"opening {label} unavailable; closing balance used instead of average")
    return Calc((opening + closing) / 2, Status.OK)


FINANCIAL_NA = {"ebitda", "ebitda_margin", "ebitda_growth_yoy", "ebitda_growth_qoq", "roce", "debt_to_equity",
                "current_ratio", "quick_ratio", "interest_coverage", "free_cash_flow", "cash_conversion", "net_debt"}


def _comparable(cur: PeriodFinancials, prev: PeriodFinancials):
    if cur.company != prev.company:
        raise ComparabilityError("different companies")
    if cur.basis != prev.basis:
        raise ComparabilityError(f"cannot compare {cur.basis.value} with {prev.basis.value} statements")
    if cur.period.period_type != prev.period.period_type:
        raise ComparabilityError("cannot compare annual with quarterly periods")
    if cur.currency != prev.currency:
        raise ComparabilityError("different currencies")


def _mk(name, unit, formula, fin, calc, inputs, others=(), note="") -> MetricResult:
    if fin.sector_type == SectorType.FINANCIAL and name in FINANCIAL_NA:
        calc = Calc(None, Status.NOT_APPLICABLE, "convention does not apply to banks/financial companies")
    srcs = tuple(dict.fromkeys([fin.source.source_id, *(o.source.source_id for o in others if o)]))
    value = calc.value if calc.status in (Status.OK, Status.PARTIAL) else None
    return MetricResult(name, value, unit, calc.status, fin.period, fin.basis, formula,
                        {k: None if v is None else str(v) for k, v in inputs.items()},
                        "; ".join(x for x in (calc.note, note) if x), srcs)


def _pct(c: Calc) -> Calc:
    return Calc(None if c.value is None else c.value * HUNDRED, c.status, c.note)


def get_ebit(fin):
    v = fin.get("ebit")
    if v is not None:
        return v, ""
    pbt, fc = fin.get("profit_before_tax"), fin.get("finance_costs")
    if pbt is not None and fc is not None:
        return pbt + fc, "EBIT derived as PBT + finance costs"
    return None, ""


def get_ebitda(fin):
    v = fin.get("ebitda")
    if v is not None:
        return v, ""
    ebit, _ = get_ebit(fin)
    dep = fin.get("depreciation")
    if ebit is not None and dep is not None:
        return ebit + dep, "EBITDA derived as EBIT + depreciation"
    return None, ""


def get_total_debt(fin):
    v = fin.get("total_debt")
    if v is not None:
        return v
    st, lt = fin.get("short_term_debt"), fin.get("long_term_debt")
    return st + lt if st is not None and lt is not None else None


def _capital_employed(fin):
    ta, cl = fin.get("total_assets"), fin.get("current_liabilities")
    return ta - cl if ta is not None and cl is not None else None


def ebit(fin):
    v, n = get_ebit(fin)
    return _mk("ebit", "INR", "reported EBIT, else PBT + finance costs", fin,
               Calc(v, Status.OK if v is not None else Status.MISSING_DATA), {"ebit": v}, note=n)


def ebitda(fin):
    v, n = get_ebitda(fin)
    return _mk("ebitda", "INR", "reported EBITDA, else EBIT + depreciation", fin,
               Calc(v, Status.OK if v is not None else Status.MISSING_DATA), {"ebitda": v}, note=n)


def _growth(stem, label, cur, prev, cur_v, prev_v, comparison):
    f = f"({label}_current - {label}_previous) / {label}_previous x 100"
    name = f"{stem}_growth_{comparison}"
    if prev is None:
        return _mk(name, "%", f, cur, Calc(None, Status.MISSING_DATA, "no comparable prior period on the same basis"),
                   {f"{label}_current": cur_v})
    _comparable(cur, prev)
    return _mk(name, "%", f, cur, pct_growth(cur_v, prev_v), {f"{label}_current": cur_v, f"{label}_previous": prev_v}, [prev])


def revenue_growth(cur, prev, comparison="yoy"):
    return _growth("revenue", "revenue", cur, prev, cur.get("revenue"), prev.get("revenue") if prev else None, comparison)


def ebitda_growth(cur, prev, comparison="yoy"):
    return _growth("ebitda", "ebitda", cur, prev, get_ebitda(cur)[0], get_ebitda(prev)[0] if prev else None, comparison)


def net_profit_growth(cur, prev, comparison="yoy"):
    return _growth("net_profit", "net_profit", cur, prev, cur.get("net_profit"), prev.get("net_profit") if prev else None, comparison)


def _margin(name, label, fin, numerator, note=""):
    c = safe_ratio(numerator, fin.get("revenue"))
    if c.status == Status.NOT_MEANINGFUL:
        c = Calc(None, c.status, "revenue is negative")
    return _mk(name, "%", f"{label} / revenue x 100", fin, _pct(c), {label: numerator, "revenue": fin.get("revenue")}, note=note)


def gross_margin(fin):
    return _margin("gross_margin", "gross_profit", fin, fin.get("gross_profit"))


def ebitda_margin(fin):
    v, n = get_ebitda(fin)
    return _margin("ebitda_margin", "ebitda", fin, v, n)


def ebit_margin(fin):
    v, n = get_ebit(fin)
    return _margin("ebit_margin", "ebit", fin, v, n)


def net_profit_margin(fin):
    return _margin("net_profit_margin", "net_profit", fin, fin.get("net_profit"))


def _opening(cur, prev):
    if prev is None:
        return None
    _comparable(cur, prev)
    return prev if prev.period == cur.period.prior_year() else None


def _return(name, formula, cur, prev, numerator, balance_fn, label, num_label):
    inputs = {num_label: numerator}
    if cur.period.period_type != PeriodType.ANNUAL:
        return _mk(name, "%", formula, cur, Calc(None, Status.NOT_MEANINGFUL,
                   "returns on capital are computed on annual statements only (quarterly figures are not annualised)"), inputs)
    op = _opening(cur, prev)
    closing, opening = balance_fn(cur), balance_fn(op) if op else None
    inputs.update({f"{label}_opening": opening, f"{label}_closing": closing})
    avg = _avg_positive(opening, closing, label)
    c = Calc(None, avg.status, avg.note) if avg.value is None or numerator is None else Calc(numerator / avg.value * HUNDRED, avg.status, avg.note)
    if numerator is None:
        c = Calc(None, Status.MISSING_DATA, f"{num_label} missing")
    return _mk(name, "%", formula, cur, c, inputs, [op])


def roe(cur, prev=None):
    return _return("roe", "net_profit / average(total_equity) x 100", cur, prev, cur.get("net_profit"),
                   lambda f: f.get("total_equity"), "total_equity", "net_profit")


def roa(cur, prev=None):
    return _return("roa", "net_profit / average(total_assets) x 100", cur, prev, cur.get("net_profit"),
                   lambda f: f.get("total_assets"), "total_assets", "net_profit")


def roce(cur, prev=None):
    return _return("roce", "EBIT / average(total_assets - current_liabilities) x 100", cur, prev, get_ebit(cur)[0],
                   _capital_employed, "capital_employed", "ebit")


def debt_to_equity(fin):
    debt, eq = get_total_debt(fin), fin.get("total_equity")
    c = safe_ratio(debt, eq)
    if c.status == Status.NOT_MEANINGFUL:
        c = Calc(None, c.status, "shareholders' equity is negative")
    return _mk("debt_to_equity", "x", "total_debt / total_equity", fin, c, {"total_debt": debt, "total_equity": eq},
               note="total_debt excludes lease liabilities unless the source includes them")


def net_debt(fin):
    debt, cash = get_total_debt(fin), fin.get("cash")
    c = Calc(debt - cash, Status.OK, "negative value means net cash") if debt is not None and cash is not None \
        else Calc(None, Status.MISSING_DATA, "debt or cash missing")
    return _mk("net_debt", "INR", "total_debt - cash", fin, c, {"total_debt": debt, "cash": cash})


def current_ratio(fin):
    ca, cl = fin.get("current_assets"), fin.get("current_liabilities")
    return _mk("current_ratio", "x", "current_assets / current_liabilities", fin, safe_ratio(ca, cl),
               {"current_assets": ca, "current_liabilities": cl})


def quick_ratio(fin):
    ca, inv, cl = fin.get("current_assets"), fin.get("inventory"), fin.get("current_liabilities")
    num = ca - inv if ca is not None and inv is not None else None
    return _mk("quick_ratio", "x", "(current_assets - inventory) / current_liabilities", fin, safe_ratio(num, cl),
               {"current_assets": ca, "inventory": inv, "current_liabilities": cl})


def interest_coverage(fin):
    e, fc = get_ebit(fin)[0], fin.get("finance_costs")
    c = safe_ratio(e, fc)
    if c.status == Status.ZERO_DENOMINATOR:
        c = Calc(None, c.status, "no finance costs reported; coverage is undefined, not infinite")
    return _mk("interest_coverage", "x", "EBIT / finance_costs", fin, c, {"ebit": e, "finance_costs": fc},
               note="negative coverage means EBIT does not cover interest" if c.value is not None and c.value < 0 else get_ebit(fin)[1])


def free_cash_flow(fin):
    cfo, capex = fin.get("cfo"), fin.get("capex")
    if cfo is None or capex is None:
        c = Calc(None, Status.MISSING_DATA, "operating cash flow or capex missing")
    elif capex < 0:
        c = Calc(None, Status.NOT_MEANINGFUL, "capex must be stored as a positive outflow")
    else:
        c = Calc(cfo - capex, Status.OK)
    return _mk("free_cash_flow", "INR", "cfo - capex", fin, c, {"cfo": cfo, "capex": capex})


def cash_conversion(fin):
    cfo, np_ = fin.get("cfo"), fin.get("net_profit")
    c = safe_ratio(cfo, np_)
    if c.status == Status.NOT_MEANINGFUL:
        c = Calc(None, c.status, "net profit is negative; cash conversion is not meaningful")
    return _mk("cash_conversion", "x", "cfo / net_profit", fin, c, {"cfo": cfo, "net_profit": np_})


def cagr_metric(stem, first, last):
    _comparable(first, last)
    years = last.period.fiscal_year - first.period.fiscal_year
    return _mk(f"{stem}_cagr", "%", f"(last/first)^(1/years) - 1, years={years}", last,
               cagr(first.get(stem), last.get(stem), years), {f"{stem}_first": first.get(stem), f"{stem}_last": last.get(stem)}, [first])
