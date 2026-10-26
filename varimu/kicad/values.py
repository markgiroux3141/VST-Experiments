"""Engineering numbers, read and written exactly: "40u" is the float 40.0e-6 is.

A number is a decimal with an optional exponent and an optional SI prefix (p n u µ m
k M G), or the "4k7" form (R for no prefix: "4R7"), then an optional unit (ohm, Ω, F,
H, V, A, Hz), which is ignored. The decimal is scaled in decimal arithmetic and
rounded to a float once, so "40u", "40e-6" and "0.04m" are all float("40.0e-6"). A
plain integer ("470") reads as an int, as YAML would, so an int in a circuit file
survives the round trip through a schematic.
"""

from __future__ import annotations

import re
from decimal import Decimal

PREFIX = {"p": -12, "n": -9, "u": -6, "µ": -6, "m": -3, "": 0, "k": 3, "M": 6, "G": 9}
_UNIT = r"(?:ohms?|Ω|F|H|V|A|Hz)?"
_PLAIN = re.compile(r"([-+]?(?:\d+\.?\d*|\.\d+))(?:[eE]([-+]?\d+))?\s*([pnuµmkMG]?)\s*" + _UNIT)
_EMBEDDED = re.compile(r"(\d+)([pnuµmkMGR])(\d+)\s*" + _UNIT)


def parse_eng(text: str) -> int | float | None:
    """The number `text` writes, or None when it isn't one (then it is a key)."""
    s = text.strip()
    if m := _PLAIN.fullmatch(s):
        mant, exp, prefix = m.groups()
        if re.fullmatch(r"[-+]?\d+", mant) and exp is None and not prefix:
            return int(mant)
        return float(Decimal(mant).scaleb(int(exp or 0) + PREFIX[prefix]))
    if m := _EMBEDDED.fullmatch(s):
        whole, prefix, frac = m.groups()
        return float(Decimal(f"{whole}.{frac}").scaleb(PREFIX.get(prefix, 0)))
    return None


def format_eng(x: int | float) -> str:
    """`x` as an engineering number that parse_eng reads back as exactly `x` (an int
    as an int)."""
    if isinstance(x, bool) or not isinstance(x, int | float):
        raise TypeError(f"{x!r} is not a number")
    if isinstance(x, int):
        return str(x)
    if x == 0:
        return "0.0"
    d = Decimal(repr(x))
    k = (d.adjusted() // 3) * 3
    prefix = {v: p for p, v in PREFIX.items() if p != "µ"}.get(k)
    if prefix is None:
        return repr(x)
    mant = format(d.scaleb(-k).normalize(), "f")
    if not prefix and "." not in mant:
        mant += ".0"
    out = mant + prefix
    assert parse_eng(out) == x and isinstance(parse_eng(out), float), (x, out)
    return out
