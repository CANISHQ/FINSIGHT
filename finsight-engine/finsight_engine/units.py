"""Number parsing and unit standardisation. Internally every money value is Decimal rupees."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, Union

Number = Union[None, str, int, float, Decimal]


class Unit(str, Enum):
    RUPEES = "rupees"
    THOUSAND = "thousand"
    LAKH = "lakh"
    MILLION = "million"
    CRORE = "crore"


SCALE = {Unit.RUPEES: Decimal(1), Unit.THOUSAND: Decimal(10**3), Unit.LAKH: Decimal(10**5),
         Unit.MILLION: Decimal(10**6), Unit.CRORE: Decimal(10**7)}
_UNIT_ALIASES = {"rupees": Unit.RUPEES, "inr": Unit.RUPEES, "rs": Unit.RUPEES, "units": Unit.RUPEES,
                 "thousand": Unit.THOUSAND, "thousands": Unit.THOUSAND,
                 "lakh": Unit.LAKH, "lakhs": Unit.LAKH, "lac": Unit.LAKH, "lacs": Unit.LAKH,
                 "million": Unit.MILLION, "millions": Unit.MILLION, "mn": Unit.MILLION,
                 "crore": Unit.CRORE, "crores": Unit.CRORE, "cr": Unit.CRORE}
_MISSING = {"", "-", "–", "—", "na", "n/a", "nil", "null", "none"}


def parse_unit(value: Union[str, Unit]) -> Unit:
    if isinstance(value, Unit):
        return value
    key = str(value).strip().lower().rstrip(".")
    if key not in _UNIT_ALIASES:
        raise ValueError(f"unknown unit {value!r}")
    return _UNIT_ALIASES[key]


def to_decimal(value: Number) -> Optional[Decimal]:
    """Parse a reported number. '(1,234.5)' is negative; '-', 'NA', '' mean missing (None)."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        d = Decimal(str(value))
    elif isinstance(value, str):
        s = value.strip().replace(",", "").replace("₹", "").strip()
        if s.lower() in _MISSING:
            return None
        neg = s.startswith("(") and s.endswith(")")
        if neg:
            s = s[1:-1].strip()
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise ValueError(f"unparseable number {value!r}") from None
        d = -d if neg else d
    else:
        raise TypeError(f"unsupported type {type(value).__name__}")
    if not d.is_finite():
        raise ValueError(f"non-finite number {value!r}")
    return d


def convert(value: Optional[Decimal], src: Unit, dst: Unit) -> Optional[Decimal]:
    return None if value is None else value * SCALE[src] / SCALE[dst]


def to_rupees(value: Optional[Decimal], unit: Unit) -> Optional[Decimal]:
    return convert(value, unit, Unit.RUPEES)
