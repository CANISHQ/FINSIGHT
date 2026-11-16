import unittest
from decimal import Decimal
from finsight_engine import ComparabilityError, Status
from finsight_engine import metrics as M
from .helpers import CR, FY25, FY26, make, val


class Base(unittest.TestCase):
    def setUp(self):
        self.p, self.c = make(2025, FY25), make(2026, FY26)

    def assertVal(self, m, expected, places=4):
        self.assertEqual(m.status, Status.OK, m.note)
        self.assertAlmostEqual(val(m), expected, places=places)


class Growth(Base):
    def test_revenue_growth(self):
        self.assertVal(M.revenue_growth(self.c, self.p), 20.0)

    def test_ebitda_growth_uses_derived_ebitda(self):  # 280 vs 220
        self.assertVal(M.ebitda_growth(self.c, self.p), 27.272727)

    def test_net_profit_growth(self):
        self.assertVal(M.net_profit_growth(self.c, self.p), 30.0)

    def test_decline_is_negative(self):
        c = make(2026, {**FY26, "revenue": 800})
        self.assertVal(M.revenue_growth(c, self.p), -20.0)

    def test_profit_to_loss_is_valid_negative_growth(self):
        c, p = make(2026, {"net_profit": -50}), make(2025, {"net_profit": 100})
        self.assertVal(M.net_profit_growth(c, p), -150.0)

    def test_negative_base_not_meaningful(self):
        c, p = make(2026, {"net_profit": 50}), make(2025, {"net_profit": -100})
        m = M.net_profit_growth(c, p)
        self.assertEqual(m.status, Status.NOT_MEANINGFUL)
        self.assertIsNone(m.value)

    def test_zero_base(self):
        m = M.revenue_growth(make(2026, {"revenue": 10}), make(2025, {"revenue": 0}))
        self.assertEqual(m.status, Status.ZERO_DENOMINATOR)

    def test_missing_current_or_previous(self):
        self.assertEqual(M.revenue_growth(make(2026, {}), self.p).status, Status.MISSING_DATA)
        self.assertEqual(M.revenue_growth(self.c, None).status, Status.MISSING_DATA)

    def test_cagr(self):
        self.assertAlmostEqual(float(M.cagr(Decimal(1000), Decimal(1210), 2).value), 10.0, places=6)
        self.assertEqual(M.cagr(Decimal(-1), Decimal(10), 2).status, Status.NOT_MEANINGFUL)
        self.assertEqual(M.cagr(None, Decimal(10), 2).status, Status.MISSING_DATA)


class Comparability(Base):
    def test_basis_mismatch_raises(self):
        with self.assertRaises(ComparabilityError):
            M.revenue_growth(self.c, make(2025, FY25, basis="standalone"))

    def test_annual_vs_quarterly_raises(self):
        with self.assertRaises(ComparabilityError):
            M.revenue_growth(self.c, make(2025, FY25, pt="quarterly", q=4))

    def test_company_mismatch_raises(self):
        with self.assertRaises(ComparabilityError):
            M.revenue_growth(self.c, make(2025, FY25, company="OTHER"))


class Margins(Base):
    def test_margins(self):
        self.assertVal(M.ebitda_margin(self.c), 23.333333)
        self.assertVal(M.ebit_margin(self.c), 19.166667)
        self.assertVal(M.net_profit_margin(self.c), 10.833333)
        self.assertVal(M.gross_margin(self.c), 40.0)

    def test_reported_ebitda_preferred_over_derivation(self):
        f = make(2026, {**FY26, "ebitda": 300})
        self.assertVal(M.ebitda_margin(f), 25.0)

    def test_derivation_is_disclosed(self):
        self.assertIn("derived", M.ebitda(self.c).note)

    def test_negative_profit_gives_negative_margin(self):
        self.assertVal(M.net_profit_margin(make(2026, {"revenue": 500, "net_profit": -50})), -10.0)

    def test_zero_and_negative_revenue(self):
        self.assertEqual(M.net_profit_margin(make(2026, {"revenue": 0, "net_profit": 5})).status, Status.ZERO_DENOMINATOR)
        self.assertEqual(M.net_profit_margin(make(2026, {"revenue": -5, "net_profit": 5})).status, Status.NOT_MEANINGFUL)

    def test_missing_inputs(self):
        self.assertEqual(M.ebitda_margin(make(2026, {"revenue": 100})).status, Status.MISSING_DATA)


class Returns(Base):
    def test_roe_average_equity(self):  # 130 / avg(1000,1200)
        self.assertVal(M.roe(self.c, self.p), 11.818182)

    def test_roa_average_assets(self):  # 130 / avg(2000,2400)
        self.assertVal(M.roa(self.c, self.p), 5.909091)

    def test_roce_average_capital_employed(self):  # 230 / avg(1600,1900)
        self.assertVal(M.roce(self.c, self.p), 13.142857)

    def test_no_prior_year_falls_back_and_says_so(self):
        m = M.roe(self.c, None)
        self.assertEqual(m.status, Status.PARTIAL)
        self.assertAlmostEqual(val(m), 10.833333, places=4)
        self.assertIn("closing balance", m.note)

    def test_non_adjacent_prior_not_used_as_opening(self):
        m = M.roe(self.c, make(2024, FY25))
        self.assertEqual(m.status, Status.PARTIAL)

    def test_negative_equity_not_meaningful(self):
        c = make(2026, {**FY26, "total_equity": -100})
        self.assertEqual(M.roe(c, self.p).status, Status.NOT_MEANINGFUL)

    def test_negative_opening_equity_not_meaningful(self):
        p = make(2025, {**FY25, "total_equity": -100})
        self.assertEqual(M.roe(self.c, p).status, Status.NOT_MEANINGFUL)

    def test_loss_gives_negative_roe(self):
        c = make(2026, {**FY26, "net_profit": -120})
        self.assertVal(M.roe(c, self.p), -10.909091)

    def test_quarterly_not_computed(self):
        q = make(2026, FY26, pt="quarterly", q=1)
        self.assertEqual(M.roe(q, None).status, Status.NOT_MEANINGFUL)
        self.assertEqual(M.roce(q, None).status, Status.NOT_MEANINGFUL)

    def test_missing_numerator(self):
        self.assertEqual(M.roe(make(2026, {"total_equity": 100}), None).status, Status.MISSING_DATA)


class LeverageLiquidity(Base):
    def test_debt_to_equity(self):
        self.assertVal(M.debt_to_equity(self.c), 0.416667)

    def test_reported_total_debt_preferred(self):
        self.assertVal(M.debt_to_equity(make(2026, {**FY26, "total_debt": 600})), 0.5)

    def test_one_debt_component_missing_is_missing(self):
        self.assertEqual(M.debt_to_equity(make(2026, {"short_term_debt": 10, "total_equity": 100})).status, Status.MISSING_DATA)

    def test_negative_equity_and_zero_equity(self):
        self.assertEqual(M.debt_to_equity(make(2026, {**FY26, "total_equity": -1})).status, Status.NOT_MEANINGFUL)
        self.assertEqual(M.debt_to_equity(make(2026, {**FY26, "total_equity": 0})).status, Status.ZERO_DENOMINATOR)

    def test_zero_debt_is_valid_zero(self):
        self.assertVal(M.debt_to_equity(make(2026, {"short_term_debt": 0, "long_term_debt": 0, "total_equity": 100})), 0.0)

    def test_net_debt_and_net_cash(self):
        self.assertEqual(M.net_debt(self.c).value, Decimal(320) * CR)
        m = M.net_debt(make(2026, {"total_debt": 100, "cash": 160}))
        self.assertEqual(m.value, Decimal(-60) * CR)
        self.assertIn("net cash", m.note)

    def test_current_and_quick_ratio(self):
        self.assertVal(M.current_ratio(self.c), 2.0)
        self.assertVal(M.quick_ratio(self.c), 1.4)

    def test_zero_current_liabilities(self):
        self.assertEqual(M.current_ratio(make(2026, {"current_assets": 10, "current_liabilities": 0})).status, Status.ZERO_DENOMINATOR)

    def test_quick_ratio_does_not_assume_missing_inventory_is_zero(self):
        m = M.quick_ratio(make(2026, {"current_assets": 10, "current_liabilities": 5}))
        self.assertEqual(m.status, Status.MISSING_DATA)


class CashFlow(Base):
    def test_interest_coverage(self):
        self.assertVal(M.interest_coverage(self.c), 6.571429)

    def test_no_interest_is_undefined_not_infinite(self):
        m = M.interest_coverage(make(2026, {"profit_before_tax": 100, "finance_costs": 0}))
        self.assertEqual(m.status, Status.ZERO_DENOMINATOR)
        self.assertIn("undefined", m.note)

    def test_negative_ebit_gives_negative_coverage(self):
        m = M.interest_coverage(make(2026, {"profit_before_tax": -50, "finance_costs": 10}))
        self.assertVal(m, -4.0)
        self.assertIn("does not cover", m.note)

    def test_free_cash_flow(self):
        self.assertEqual(M.free_cash_flow(self.c).value, Decimal(10) * CR)

    def test_negative_fcf(self):
        self.assertEqual(M.free_cash_flow(make(2026, {"cfo": 40, "capex": 90})).value, Decimal(-50) * CR)

    def test_missing_capex_not_treated_as_zero(self):
        self.assertEqual(M.free_cash_flow(make(2026, {"cfo": 40})).status, Status.MISSING_DATA)

    def test_negative_capex_rejected(self):
        f = make(2026, {"cfo": 40, "capex": 10})
        f.cashflow["capex"] = Decimal(-10)
        self.assertEqual(M.free_cash_flow(f).status, Status.NOT_MEANINGFUL)

    def test_cash_conversion(self):
        self.assertVal(M.cash_conversion(self.c), 0.769231)

    def test_cash_conversion_loss_making_not_meaningful(self):
        self.assertEqual(M.cash_conversion(make(2026, {"cfo": 50, "net_profit": -10})).status, Status.NOT_MEANINGFUL)
        self.assertEqual(M.cash_conversion(make(2026, {"cfo": 50, "net_profit": 0})).status, Status.ZERO_DENOMINATOR)

    def test_negative_cfo_with_profit_is_negative_ratio(self):
        self.assertVal(M.cash_conversion(make(2026, {"cfo": -20, "net_profit": 100})), -0.2)


class BankConventions(Base):
    def test_debt_based_metrics_not_applicable(self):
        b = make(2026, FY26, sector="financial")
        for fn in (M.debt_to_equity, M.current_ratio, M.quick_ratio, M.interest_coverage, M.free_cash_flow,
                   M.cash_conversion, M.net_debt, M.ebitda_margin):
            self.assertEqual(fn(b).status, Status.NOT_APPLICABLE, fn.__name__)

    def test_roe_still_computed_for_banks(self):
        b, p = make(2026, FY26, sector="financial"), make(2025, FY25, sector="financial")
        self.assertVal(M.roe(b, p), 11.818182)


class Provenance(Base):
    def test_result_carries_formula_inputs_period_basis_sources(self):
        m = M.revenue_growth(self.c, self.p)
        self.assertEqual(m.period.label, "FY26")
        self.assertEqual(m.basis.value, "consolidated")
        self.assertIn("revenue_previous", m.inputs)
        self.assertEqual(set(m.sources), {self.c.source.source_id, self.p.source.source_id})
        self.assertTrue(m.formula)


if __name__ == "__main__":
    unittest.main()
