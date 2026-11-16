"""Rule-based red-flag research alerts. These are NOT fraud allegations: every flag carries limitations.
Severity = materiality (size of the change) + persistence (also true in the previous year) + rule-specific boosts."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal as D
from enum import Enum
from typing import Callable, Optional
from . import metrics as M
from .models import PeriodFinancials, SectorType

DISCLAIMER = "Research alert based on reported figures. It is not an allegation or a conclusion about the company."


class Severity(str, Enum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_LADDER = [Severity.INFORMATIONAL, Severity.LOW, Severity.MEDIUM, Severity.HIGH]
NO_DATA = object()


@dataclass
class Hit:
    magnitude: D
    current: Optional[D]
    previous: Optional[D]
    extra: int = 0


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    metric: str
    cond: Callable
    min_fire: D
    mid: D
    high: D
    explain: Callable
    limitations: str
    persist: bool = True


@dataclass
class RedFlag:
    flag_id: str
    name: str
    severity: Severity
    metric: str
    current_value: Optional[D]
    previous_value: Optional[D]
    period: object
    comparison_period: object
    basis: object
    persistent: bool
    sources: tuple
    explanation: str
    limitations: str
    disclaimer: str = DISCLAIMER


def _cr(v):
    return "n/a" if v is None else f"₹{(v / D(10**7)):,.2f} crore"


def _f(v, p=2):
    return "n/a" if v is None else f"{v:.{p}f}"


def _pair(s, i):
    if i < 1 or s[i].period.fiscal_year - s[i - 1].period.fiscal_year != 1:
        return None
    return s[i], s[i - 1]


def _prior(s, i):
    return s[i - 1] if i >= 1 and s[i].period.fiscal_year - s[i - 1].period.fiscal_year == 1 else None


def _chg(a, b):
    return (b - a) / b * 100


def c_rev_up_cfo_down(s, i):
    pr = _pair(s, i)
    if not pr:
        return NO_DATA
    c, p = pr
    g, cf, pf = M.revenue_growth(c, p), c.get("cfo"), p.get("cfo")
    if not g.ok or cf is None or pf is None or pf <= 0:
        return NO_DATA
    return Hit(_chg(cf, pf), cf, pf) if g.value > 0 and cf < pf else None


def c_np_up_fcf_down(s, i):
    pr = _pair(s, i)
    if not pr:
        return NO_DATA
    c, p = pr
    g, fc, fp = M.net_profit_growth(c, p), M.free_cash_flow(c), M.free_cash_flow(p)
    if not (g.ok and fc.ok and fp.ok) or fp.value == 0:
        return NO_DATA
    return Hit((fp.value - fc.value) / abs(fp.value) * 100, fc.value, fp.value) if g.value > 0 and fc.value < fp.value else None


def c_rising_debt(s, i):
    pr = _pair(s, i)
    if not pr:
        return NO_DATA
    c, p = pr
    dc, dp = M.get_total_debt(c), M.get_total_debt(p)
    if dc is None or dp is None or dp <= 0:
        return NO_DATA
    dec, dep = M.debt_to_equity(c), M.debt_to_equity(p)
    if dc > dp and dec.ok and dep.ok and dec.value > dep.value:
        return Hit((dc - dp) / dp * 100, dc, dp)
    return None


def c_falling_cov(s, i):
    pr = _pair(s, i)
    if not pr:
        return NO_DATA
    c, p = pr
    a, b = M.interest_coverage(c), M.interest_coverage(p)
    if not (a.ok and b.ok) or b.value <= 0:
        return NO_DATA
    if a.value < b.value:
        return Hit(_chg(a.value, b.value), a.value, b.value, extra=1 if a.value < D("1.5") else 0)
    return None


def _outpacing(item):
    def cond(s, i):
        pr = _pair(s, i)
        if not pr:
            return NO_DATA
        c, p = pr
        r, g = M.pct_growth(c.get(item), p.get(item)), M.revenue_growth(c, p)
        if r.status != M.Status.OK or not g.ok:
            return NO_DATA
        gap = r.value - g.value
        return Hit(gap, c.get(item), p.get(item)) if r.value > 0 and gap > 0 else None
    return cond


def c_margin_decline(s, i):
    pr = _pair(s, i)
    if not pr:
        return NO_DATA
    a, b = M.ebit_margin(pr[0]), M.ebit_margin(pr[1])
    if not (a.ok and b.ok):
        return NO_DATA
    return Hit(b.value - a.value, a.value, b.value) if a.value < b.value else None


def c_roce_decline(s, i):
    pr = _pair(s, i)
    if not pr:
        return NO_DATA
    a, b = M.roce(pr[0], pr[1]), M.roce(pr[1], _prior(s, i - 1) if i >= 1 else None)
    if not (a.ok and b.ok):
        return NO_DATA
    return Hit(b.value - a.value, a.value, b.value) if a.value < b.value else None


def c_neg_fcf(s, i):
    n, j = 0, i
    while j >= 0:
        f = M.free_cash_flow(s[j])
        if not f.ok:
            return NO_DATA if n == 0 else (Hit(D(n), M.free_cash_flow(s[i]).value, None, 1) if n >= 2 else None)
        if f.value >= 0 or (j < i and s[j + 1].period.fiscal_year - s[j].period.fiscal_year != 1):
            break
        n += 1
        j -= 1
    return Hit(D(n), M.free_cash_flow(s[i]).value, None, 1) if n >= 2 else None


def c_cash_gap(s, i):
    c = s[i]
    cc, np_ = M.cash_conversion(c), c.get("net_profit")
    if not cc.ok:
        return NO_DATA if cc.status == M.Status.MISSING_DATA else None
    p = _prior(s, i)
    pcc = M.cash_conversion(p).value if p is not None and M.cash_conversion(p).ok else None
    return Hit(D("0.6") - cc.value, cc.value, pcc) if cc.value < D("0.6") and np_ > 0 else None


RULES = [
    Rule("rev_up_cfo_down", "Revenue growing while operating cash flow declines", "cfo", c_rev_up_cfo_down, D(2), D(10), D(25),
         lambda h, c, p: f"Revenue grew {_f(M.revenue_growth(c, p).value)}% but operating cash flow fell {_f(h.magnitude)}% to {_cr(h.current)} from {_cr(h.previous)}.",
         "Working-capital timing, one-off tax payments or large contracts can depress cash flow temporarily."),
    Rule("np_up_fcf_down", "Net profit rising while free cash flow deteriorates", "free_cash_flow", c_np_up_fcf_down, D(2), D(10), D(25),
         lambda h, c, p: f"Net profit grew {_f(M.net_profit_growth(c, p).value)}% while free cash flow fell to {_cr(h.current)} from {_cr(h.previous)}.",
         "Growth capex raises capex and lowers FCF without indicating weak earnings quality."),
    Rule("rising_debt", "Rising debt", "total_debt", c_rising_debt, D(2), D(10), D(25),
         lambda h, c, p: f"Total debt rose {_f(h.magnitude)}% to {_cr(h.current)} and debt-to-equity increased ({_f(M.debt_to_equity(p).value)}x to {_f(M.debt_to_equity(c).value)}x).",
         "Debt may fund productive expansion; compare with returns and cash generation."),
    Rule("falling_interest_coverage", "Falling interest coverage", "interest_coverage", c_falling_cov, D(2), D(20), D(40),
         lambda h, c, p: f"Interest coverage fell from {_f(h.previous)}x to {_f(h.current)}x." + (" Coverage is below 1.5x." if h.extra else ""),
         "EBIT here may include other income; coverage uses reported finance costs only."),
    Rule("receivables_outpacing_revenue", "Receivables growing faster than revenue", "receivables", _outpacing("receivables"), D(5), D(20), D(40),
         lambda h, c, p: f"Receivables grew {_f(h.magnitude)} percentage points faster than revenue (to {_cr(h.current)}).",
         "Sector credit terms, year-end billing timing and acquisitions can shift receivables."),
    Rule("declining_operating_margin", "Declining operating margin", "ebit_margin", c_margin_decline, D("0.5"), D("1.5"), D(3),
         lambda h, c, p: f"EBIT margin fell {_f(h.magnitude)} percentage points to {_f(h.current)}% from {_f(h.previous)}%.",
         "Input-cost cycles or mix shifts may be temporary; EBIT includes other income when derived from PBT."),
    Rule("inventory_outpacing_revenue", "Inventory growing faster than revenue", "inventory", _outpacing("inventory"), D(5), D(20), D(40),
         lambda h, c, p: f"Inventory grew {_f(h.magnitude)} percentage points faster than revenue (to {_cr(h.current)}).",
         "Planned stock build ahead of launches or seasonality can explain this."),
    Rule("declining_roce", "Declining ROCE", "roce", c_roce_decline, D("0.5"), D(2), D(5),
         lambda h, c, p: f"ROCE fell {_f(h.magnitude)} percentage points to {_f(h.current)}% from {_f(h.previous)}%.",
         "Large recent capex has not yet earned returns; ROCE uses average capital employed."),
    Rule("repeated_negative_fcf", "Repeated negative free cash flow", "free_cash_flow", c_neg_fcf, D(2), D(3), D(4),
         lambda h, c, p: f"Free cash flow has been negative for {int(h.magnitude)} consecutive years (latest {_cr(h.current)}).",
         "Companies in heavy investment phases often run negative FCF by design.", persist=False),
    Rule("profit_cash_gap", "Large gap between reported profit and cash generation", "cash_conversion", c_cash_gap, D("0.1"), D("0.2"), D("0.4"),
         lambda h, c, p: f"Operating cash flow was {_f(h.current)}x net profit (below the 0.6x reference).",
         "The 0.6x reference is a screening convention; lumpy working capital distorts single years."),
]


def detect_red_flags(annual: list) -> tuple:
    """annual: PeriodFinancials of ONE company and ONE basis. Returns (flags, not_evaluated_notes)."""
    s = sorted(annual, key=lambda f: f.period)
    if not s:
        return [], ["no annual statements supplied"]
    if s[0].sector_type == SectorType.FINANCIAL:
        return [], ["red flag rules for banks and financial companies are not implemented; generic rules would mislead"]
    flags, notes, i = [], [], len(s) - 1
    for r in RULES:
        hit = r.cond(s, i)
        if hit is NO_DATA:
            notes.append(f"{r.rule_id}: not evaluated (insufficient or non-comparable data)")
            continue
        if hit is None or hit.magnitude < r.min_fire:
            continue
        prev_hit = r.cond(s, i - 1) if i >= 1 else None
        persistent = r.persist and isinstance(prev_hit, Hit) and prev_hit.magnitude >= r.min_fire
        lvl = min(3, hit.extra + (hit.magnitude >= r.mid) + (hit.magnitude >= r.high) + (1 if persistent else 0))
        cur, prev = s[i], _prior(s, i)
        flags.append(RedFlag(r.rule_id, r.name, _LADDER[lvl], r.metric, hit.current, hit.previous, cur.period,
                             prev.period if prev else None, cur.basis, persistent,
                             tuple(dict.fromkeys([cur.source.source_id] + ([prev.source.source_id] if prev else []))),
                             r.explain(hit, cur, prev), r.limitations))
    flags.sort(key=lambda f: -_LADDER.index(f.severity))
    return flags, notes
