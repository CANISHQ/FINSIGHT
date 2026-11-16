import json
import unittest
from decimal import Decimal
from finsight_engine import Basis, Severity, Status, analyse_company, detect_red_flags, resolve_restatements
from .helpers import CR, FY25, FY26, make, series

D = Decimal


def scaled(k):
    f = D("1.1") ** k
    return {key: D(v) * f for key, v in FY25.items()}


def flag(flags, rule_id):
    return next((f for f in flags if f.flag_id == rule_id), None)


class RedFlags(unittest.TestCase):
    def test_healthy_company_has_no_flags(self):
        flags, notes = detect_red_flags([make(2023 + k, scaled(k)) for k in range(4)])
        self.assertEqual(flags, [], [f.name for f in flags])
        self.assertEqual(notes, [])

    def test_revenue_up_cfo_down_persistent_and_large_is_high(self):
        s = series([dict(revenue=800, cfo=160), dict(revenue=900, cfo=150), dict(revenue=1000, cfo=130), dict(revenue=1100, cfo=90)])
        f = flag(detect_red_flags(s)[0], "rev_up_cfo_down")
        self.assertEqual(f.severity, Severity.HIGH)
        self.assertTrue(f.persistent)
        self.assertEqual(f.period.label, "FY26")
        self.assertEqual(f.comparison_period.label, "FY25")
        self.assertEqual(f.current_value, D(90) * CR)
        self.assertEqual(f.previous_value, D(130) * CR)
        self.assertTrue(f.limitations and f.disclaimer)

    def test_single_small_decline_is_informational_not_alarming(self):
        s = series([dict(revenue=800, cfo=120), dict(revenue=900, cfo=120), dict(revenue=1000, cfo=120), dict(revenue=1100, cfo=117)])
        f = flag(detect_red_flags(s)[0], "rev_up_cfo_down")
        self.assertEqual(f.severity, Severity.INFORMATIONAL)

    def test_noise_below_threshold_not_flagged(self):
        s = series([dict(revenue=800), dict(revenue=900), dict(revenue=1000, cfo=120), dict(revenue=1100, cfo=119)])
        self.assertIsNone(flag(detect_red_flags(s)[0], "rev_up_cfo_down"))

    def test_cfo_growing_with_revenue_not_flagged(self):
        s = series([dict(revenue=800), dict(revenue=900), dict(revenue=1000), dict(revenue=1100, cfo=150)])
        self.assertIsNone(flag(detect_red_flags(s)[0], "rev_up_cfo_down"))

    def test_profit_up_fcf_down(self):
        s = series([dict(), dict(), dict(net_profit=100, cfo=120, capex=60), dict(net_profit=120, cfo=100, capex=80)])
        f = flag(detect_red_flags(s)[0], "np_up_fcf_down")  # FCF 60 -> 20
        self.assertIsNotNone(f)
        self.assertEqual(f.current_value, D(20) * CR)

    def test_rising_debt(self):
        s = series([dict(), dict(), dict(), dict(short_term_debt=200, long_term_debt=450)])  # 400 -> 650, equity flat
        f = flag(detect_red_flags(s)[0], "rising_debt")
        self.assertEqual(f.current_value, D(650) * CR)
        self.assertIn(f.severity, (Severity.MEDIUM, Severity.HIGH))

    def test_falling_interest_coverage_below_floor_is_high(self):
        s = series([dict(), dict(), dict(), dict(profit_before_tax=10, finance_costs=30)])  # 6.0x -> 1.33x
        f = flag(detect_red_flags(s)[0], "falling_interest_coverage")
        self.assertEqual(f.severity, Severity.HIGH)
        self.assertIn("1.5x", f.explanation)

    def test_receivables_outpacing_revenue(self):
        s = series([dict(), dict(), dict(), dict(revenue=1100, receivables=400)])  # +60% vs +10%
        f = flag(detect_red_flags(s)[0], "receivables_outpacing_revenue")
        self.assertIsNotNone(f)
        self.assertEqual(f.current_value, D(400) * CR)

    def test_inventory_outpacing_revenue(self):
        s = series([dict(), dict(), dict(), dict(revenue=1100, inventory=320)])
        self.assertIsNotNone(flag(detect_red_flags(s)[0], "inventory_outpacing_revenue"))

    def test_declining_operating_margin(self):
        s = series([dict(), dict(), dict(), dict(profit_before_tax=100)])  # EBIT 180 -> 130 on revenue 1000
        f = flag(detect_red_flags(s)[0], "declining_operating_margin")
        self.assertIn("5.00 percentage points", f.explanation)

    def test_declining_roce(self):
        s = series([dict(), dict(), dict(), dict(profit_before_tax=100)])
        self.assertIsNotNone(flag(detect_red_flags(s)[0], "declining_roce"))

    def test_repeated_negative_fcf_scales_with_streak(self):
        neg = dict(cfo=50, capex=80)
        two = flag(detect_red_flags(series([dict(), dict(), neg, neg]))[0], "repeated_negative_fcf")
        three = flag(detect_red_flags(series([dict(), neg, neg, neg]))[0], "repeated_negative_fcf")
        four = flag(detect_red_flags(series([neg, neg, neg, neg]))[0], "repeated_negative_fcf")
        self.assertEqual((two.severity, three.severity, four.severity), (Severity.LOW, Severity.MEDIUM, Severity.HIGH))

    def test_single_negative_fcf_year_not_flagged(self):
        s = series([dict(), dict(), dict(), dict(cfo=50, capex=80)])
        self.assertIsNone(flag(detect_red_flags(s)[0], "repeated_negative_fcf"))

    def test_profit_cash_gap(self):
        s = series([dict(), dict(), dict(), dict(cfo=30)])  # 0.3x
        f = flag(detect_red_flags(s)[0], "profit_cash_gap")
        self.assertEqual(f.current_value, D("0.3"))

    def test_missing_data_means_not_evaluated_not_clear(self):
        no_recv = {k: v for k, v in FY25.items() if k != "receivables"}
        s = [make(2023 + i, no_recv) for i in range(4)]
        flags, notes = detect_red_flags(s)
        self.assertTrue(any("receivables_outpacing_revenue" in n for n in notes))

    def test_non_consecutive_years_not_compared(self):
        s = [make(2023, FY25), make(2026, FY26)]
        flags, notes = detect_red_flags(s)
        self.assertTrue(notes)

    def test_banks_skip_generic_rules(self):
        flags, notes = detect_red_flags(series([dict(), dict()], sector="financial"))
        self.assertEqual(flags, [])
        self.assertIn("banks", notes[0])

    def test_sorted_by_severity(self):
        s = series([dict(), dict(), dict(), dict(profit_before_tax=10, finance_costs=30, cfo=30)])
        flags = detect_red_flags(s)[0]
        order = [Severity.INFORMATIONAL, Severity.LOW, Severity.MEDIUM, Severity.HIGH]
        ranks = [order.index(f.severity) for f in flags]
        self.assertEqual(ranks, sorted(ranks, reverse=True))


class Analysis(unittest.TestCase):
    def setUp(self):
        self.recs = [make(2025, FY25), make(2026, FY26)]

    def test_annual_metrics_and_provenance(self):
        a = analyse_company(self.recs, "DEMO", Basis.CONSOLIDATED)
        m = a.annual[-1].metrics
        self.assertAlmostEqual(float(m["revenue_growth_yoy"].value), 20.0)
        self.assertAlmostEqual(float(m["roe"].value), 11.818182, places=4)
        self.assertEqual(m["free_cash_flow"].value, D(10) * CR)
        self.assertEqual(a.annual[0].metrics["revenue_growth_yoy"].status, Status.MISSING_DATA)

    def test_history_cagr(self):
        recs = [make(2024, {**FY25, "revenue": 1000}), make(2026, {**FY26, "revenue": 1210})]
        a = analyse_company(recs, "DEMO", Basis.CONSOLIDATED)
        self.assertAlmostEqual(float(a.history["revenue_cagr"].value), 10.0, places=4)

    def test_consolidated_and_standalone_never_mixed(self):
        recs = self.recs + [make(2025, {**FY25, "revenue": 700}, basis="standalone"), make(2026, {**FY26, "revenue": 840}, basis="standalone")]
        c = analyse_company(recs, "DEMO", Basis.CONSOLIDATED)
        s = analyse_company(recs, "DEMO", Basis.STANDALONE)
        self.assertAlmostEqual(float(c.annual[-1].metrics["revenue_growth_yoy"].value), 20.0)
        self.assertAlmostEqual(float(s.annual[-1].metrics["revenue_growth_yoy"].value), 20.0)
        self.assertEqual(c.annual[-1].metrics["net_profit_margin"].basis, Basis.CONSOLIDATED)
        self.assertEqual(s.annual[-1].metrics["net_profit_margin"].basis, Basis.STANDALONE)
        self.assertAlmostEqual(float(s.annual[-1].metrics["net_profit_margin"].value), 130 / 840 * 100, places=3)

    def test_standalone_never_substituted_when_consolidated_missing(self):
        a = analyse_company([make(2026, FY26, basis="standalone")], "DEMO", Basis.CONSOLIDATED)
        self.assertEqual(a.annual, [])
        self.assertIn("no consolidated statements", a.data_quality[0])

    def test_duplicate_period_requires_restatement_resolution(self):
        recs = self.recs + [make(2026, FY26, pub="2026-06-01", sid="dup")]
        with self.assertRaises(ValueError):
            analyse_company(recs, "DEMO", Basis.CONSOLIDATED)
        a = analyse_company(resolve_restatements(recs), "DEMO", Basis.CONSOLIDATED)
        self.assertEqual(len(a.annual), 2)

    def test_restatement_surfaces_in_data_quality(self):
        recs = resolve_restatements([make(2025, {"revenue": 1000}, pub="2025-05-01"), make(2025, {"revenue": 1010}, pub="2025-11-01")])
        a = analyse_company(recs, "DEMO", Basis.CONSOLIDATED)
        self.assertTrue(any("restated" in n for n in a.data_quality))
        self.assertTrue(a.annual[0].restated)

    def test_quarterly_yoy_and_qoq(self):
        q = lambda fy, n, rev: make(fy, {"revenue": rev}, pt="quarterly", q=n)
        recs = [q(2025, 1, 250), q(2025, 4, 280), q(2026, 1, 300)]
        a = analyse_company(recs, "DEMO", Basis.CONSOLIDATED)
        m = a.quarterly[-1].metrics
        self.assertEqual(a.quarterly[-1].period.label, "Q1 FY26")
        self.assertAlmostEqual(float(m["revenue_growth_yoy"].value), 20.0)
        self.assertAlmostEqual(float(m["revenue_growth_qoq"].value), 7.142857, places=4)

    def test_quarterly_and_annual_stay_separate(self):
        recs = self.recs + [make(2026, {"revenue": 300}, pt="quarterly", q=1)]
        a = analyse_company(recs, "DEMO", Basis.CONSOLIDATED)
        self.assertEqual(len(a.annual), 2)
        self.assertEqual(a.quarterly[0].metrics["revenue_growth_yoy"].status, Status.MISSING_DATA)
        self.assertNotIn("roe", a.quarterly[0].metrics)

    def test_output_is_json_serialisable_and_self_describing(self):
        a = analyse_company(self.recs, "DEMO", Basis.CONSOLIDATED)
        out = json.loads(json.dumps(a.to_dict()))
        self.assertIn("must quote them verbatim", out["contract"])
        self.assertEqual(out["basis"], "consolidated")
        m = out["annual"][-1]["metrics"]["roe"]
        self.assertEqual((m["unit"], m["status"], m["period"]["label"]), ("%", "ok", "FY26"))
        self.assertEqual(m["value"], "11.8182")
        self.assertTrue(m["formula"] and m["inputs"] and m["sources"])
        self.assertEqual(out["annual"][-1]["metrics"]["free_cash_flow"]["value"], "100000000.00")

    def test_facts_have_stable_ids_for_citation(self):
        out = analyse_company(self.recs, "DEMO", Basis.CONSOLIDATED).to_dict()
        ids = {f["id"] for f in out["facts"]}
        self.assertIn("DEMO|consolidated|FY26|revenue_growth_yoy", ids)
        self.assertEqual(len(ids), len(out["facts"]))

    def test_unverified_sources_noted(self):
        a = analyse_company([make(2026, FY26, status="unverified")], "DEMO", Basis.CONSOLIDATED)
        self.assertTrue(any("unverified" in n for n in a.data_quality))

    def test_missing_values_are_null_not_zero_in_output(self):
        out = analyse_company([make(2026, {"revenue": 100})], "DEMO", Basis.CONSOLIDATED).to_dict()
        m = out["annual"][0]["metrics"]["net_profit_margin"]
        self.assertIsNone(m["value"])
        self.assertEqual(m["status"], "missing_data")

    def test_red_flags_included_in_output(self):
        s = series([dict(revenue=800, cfo=160), dict(revenue=900, cfo=150), dict(revenue=1000, cfo=130), dict(revenue=1100, cfo=90)])
        out = analyse_company(s, "DEMO", Basis.CONSOLIDATED).to_dict()
        rf = next(f for f in out["red_flags"] if f["flag_id"] == "rev_up_cfo_down")
        self.assertEqual((rf["severity"], rf["period"]["label"]), ("high", "FY26"))
        self.assertTrue(rf["limitations"] and rf["sources"])

    def test_bank_analysis_marks_inapplicable_metrics(self):
        recs = [make(2025, FY25, sector="financial"), make(2026, FY26, sector="financial")]
        a = analyse_company(recs, "DEMO", Basis.CONSOLIDATED)
        self.assertEqual(a.annual[-1].metrics["debt_to_equity"].status, Status.NOT_APPLICABLE)
        self.assertTrue(any("banks" in n for n in a.data_quality))


if __name__ == "__main__":
    unittest.main()
