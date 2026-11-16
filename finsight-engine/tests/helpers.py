from datetime import date
from decimal import Decimal
from finsight_engine import Source, normalize_record

FY25 = dict(revenue=1000, gross_profit=400, depreciation=40, finance_costs=30, profit_before_tax=150, net_profit=100,
            total_assets=2000, current_assets=800, current_liabilities=400, total_equity=1000, short_term_debt=100,
            long_term_debt=300, cash=150, inventory=200, receivables=250, cfo=120, capex=60)
FY26 = dict(revenue=1200, gross_profit=480, depreciation=50, finance_costs=35, profit_before_tax=195, net_profit=130,
            total_assets=2400, current_assets=1000, current_liabilities=500, total_equity=1200, short_term_debt=120,
            long_term_debt=380, cash=180, inventory=300, receivables=400, cfo=100, capex=90)
CR = Decimal(10**7)


def make(fy, items, basis="consolidated", pt="annual", q=None, unit="crore", sector="general", pub=None,
         sid=None, company="DEMO", status="verified"):
    src = Source(sid or f"src-{fy}-{q or 'A'}-{basis}", "Test filing", verification_status=status)
    return normalize_record({"company": company, "fiscal_year": fy, "period_type": pt, "quarter": q, "basis": basis,
                             "unit": unit, "sector_type": sector, "published_on": pub, "items": items}, src)


def val(m):
    return None if m.value is None else float(m.value)


def series(overrides, start=2023, **kw):
    """Annual series: overrides[i] is merged over FY25 defaults for year start+i."""
    return [make(start + i, {**FY25, **o}, **kw) for i, o in enumerate(overrides)]
