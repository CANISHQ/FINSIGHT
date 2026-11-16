import unittest
from decimal import Decimal
from finsight_engine import Period, PeriodType, Source, normalize_record, resolve_restatements
from finsight_engine.units import Unit, convert, parse_unit, to_decimal
from .helpers import CR, FY25, make


class UnitsAndParsing(unittest.TestCase):
    def test_parenthesised_negative(self):
        self.assertEqual(to_decimal("(1,234.5)"), Decimal("-1234.5"))

    def test_commas_and_rupee_symbol(self):
        self.assertEqual(to_decimal("₹ 12,00,000"), Decimal("1200000"))

    def test_missing_markers_are_none(self):
        for v in ("-", "", "NA", "n/a", "—", None):
            self.assertIsNone(to_decimal(v))

    def test_garbage_and_bool_rejected(self):
        with self.assertRaises(ValueError):
            to_decimal("abc")
        with self.assertRaises(TypeError):
            to_decimal(True)
        with self.assertRaises(ValueError):
            to_decimal(float("nan"))

    def test_float_goes_through_str(self):
        self.assertEqual(to_decimal(0.1), Decimal("0.1"))

    def test_unit_conversion(self):
        self.assertEqual(convert(Decimal(1), Unit.CRORE, Unit.LAKH), Decimal(100))
        self.assertEqual(convert(Decimal(1), Unit.CRORE, Unit.RUPEES), Decimal(10**7))
        self.assertEqual(convert(Decimal(5000), Unit.THOUSAND, Unit.LAKH), Decimal(50))
        self.assertIsNone(convert(None, Unit.CRORE, Unit.LAKH))

    def test_unit_aliases_and_unknown(self):
        self.assertEqual(parse_unit("Crores"), Unit.CRORE)
        self.assertEqual(parse_unit("Rs."), Unit.RUPEES)
        with self.assertRaises(ValueError):
            parse_unit("billions")


class PeriodTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(Period(2026, PeriodType.ANNUAL).label, "FY26")
        self.assertEqual(Period(2026, PeriodType.QUARTERLY, 1).label, "Q1 FY26")

    def test_prior_quarter_wraps_fiscal_year(self):
        self.assertEqual(Period(2026, PeriodType.QUARTERLY, 1).prior_quarter(), Period(2025, PeriodType.QUARTERLY, 4))
        self.assertEqual(Period(2026, PeriodType.QUARTERLY, 3).prior_quarter(), Period(2026, PeriodType.QUARTERLY, 2))

    def test_invalid_periods(self):
        with self.assertRaises(ValueError):
            Period(2026, PeriodType.QUARTERLY, 5)
        with self.assertRaises(ValueError):
            Period(2026, PeriodType.ANNUAL, 1)
        with self.assertRaises(ValueError):
            Period(2026, PeriodType.ANNUAL).prior_quarter()


class Normalisation(unittest.TestCase):
    def test_values_converted_to_rupees(self):
        f = make(2025, FY25)
        self.assertEqual(f.get("revenue"), Decimal(1000) * CR)

    def test_aliases_and_unmapped_reported(self):
        f = make(2025, {"Revenue from operations": "1,000", "PAT": "100", "Mystery line": "5"})
        self.assertEqual(f.get("revenue"), Decimal(1000) * CR)
        self.assertEqual(f.get("net_profit"), Decimal(100) * CR)
        self.assertEqual(f.unmapped, ["Mystery line"])

    def test_capex_and_expenses_stored_positive(self):
        f = make(2025, {"capex": "(60)", "finance_costs": "-30"})
        self.assertEqual(f.get("capex"), Decimal(60) * CR)
        self.assertEqual(f.get("finance_costs"), Decimal(30) * CR)

    def test_missing_value_stays_none_not_zero(self):
        f = make(2025, {"revenue": "-"})
        self.assertIsNone(f.get("revenue"))

    def test_eps_not_scaled(self):
        self.assertEqual(make(2025, {"eps": "12.5"}).get("eps"), Decimal("12.5"))

    def test_unit_and_basis_are_mandatory(self):
        src = Source("s", "s")
        base = {"company": "X", "fiscal_year": 2025, "period_type": "annual", "basis": "consolidated", "unit": "crore", "items": {}}
        for missing in ("unit", "basis"):
            raw = {k: v for k, v in base.items() if k != missing}
            with self.assertRaises(ValueError):
                normalize_record(raw, src)

    def test_conflicting_duplicate_labels_rejected(self):
        with self.assertRaises(ValueError):
            make(2025, {"Revenue": 100, "Net Sales": 200})

    def test_same_value_duplicate_labels_allowed(self):
        self.assertEqual(make(2025, {"Revenue": 100, "Net Sales": 100}).get("revenue"), Decimal(100) * CR)

    def test_different_units_standardise_to_same_value(self):
        a = make(2025, {"revenue": 1}, unit="crore")
        b = make(2025, {"revenue": 100}, unit="lakh")
        self.assertEqual(a.get("revenue"), b.get("revenue"))


class Restatements(unittest.TestCase):
    def test_latest_published_wins_and_changes_recorded(self):
        old = make(2025, {"revenue": 1000}, pub="2025-05-01", sid="orig")
        new = make(2025, {"revenue": 1010}, pub="2025-11-01", sid="restated")
        other = make(2024, {"revenue": 900}, pub="2024-05-01")
        out = resolve_restatements([new, old, other])
        self.assertEqual(len(out), 2)
        fy25 = next(f for f in out if f.period.fiscal_year == 2025)
        self.assertEqual(fy25.get("revenue"), Decimal(1010) * CR)
        self.assertTrue(fy25.restated)
        self.assertEqual(fy25.supersedes[0]["source_id"], "orig")
        self.assertEqual(fy25.supersedes[0]["changes"]["revenue"]["old"], str(Decimal(1000) * CR))

    def test_bases_are_never_merged(self):
        a = make(2025, {"revenue": 1000}, basis="consolidated")
        b = make(2025, {"revenue": 700}, basis="standalone")
        self.assertEqual(len(resolve_restatements([a, b])), 2)


if __name__ == "__main__":
    unittest.main()
