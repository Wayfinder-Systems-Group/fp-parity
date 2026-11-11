"""The line protocol a harness prints, and exact bit-level views of the values.

A harness prints ``name TAB kind TAB hexbits`` per value (see fpparity.h).
Lines in any other shape are ignored, so a harness can log freely.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Dict, List, Tuple

# kind -> number of hex digits in the bit pattern
KINDS = {"f64": 16, "f32": 8}
_HEX = set("0123456789abcdefABCDEF")


@dataclass(frozen=True)
class Value:
    name: str
    kind: str
    bits: int

    @property
    def width(self) -> int:
        return 64 if self.kind == "f64" else 32

    def as_float(self) -> float:
        if self.kind == "f64":
            return struct.unpack("<d", self.bits.to_bytes(8, "little"))[0]
        return struct.unpack("<f", self.bits.to_bytes(4, "little"))[0]

    def hex(self) -> str:
        return format(self.bits, "0{}x".format(KINDS[self.kind]))


def parse_output(text: str) -> Tuple[Dict[str, Value], List[str]]:
    """Return the values a harness emitted, and any problems with lines that
    claimed to be protocol lines but were malformed.

    A name emitted twice keeps its first value and is reported: a harness that
    prints the same name from two code paths would otherwise compare whichever
    one happened to run last.
    """
    values: Dict[str, Value] = {}
    problems: List[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        parts = raw.rstrip("\r").split("\t")
        if len(parts) != 3 or parts[1] not in KINDS:
            continue
        name, kind, hexbits = parts
        if not name:
            problems.append("line {}: empty name".format(lineno))
            continue
        if len(hexbits) != KINDS[kind] or not set(hexbits) <= _HEX:
            problems.append("line {}: malformed bits for {!r}".format(lineno, name))
            continue
        if name in values:
            problems.append("line {}: {!r} emitted twice; the first value is kept".format(lineno, name))
            continue
        values[name] = Value(name, kind, int(hexbits, 16))
    return values, problems


def is_nan(v: Value) -> bool:
    return math.isnan(v.as_float())


def is_inf(v: Value) -> bool:
    return math.isinf(v.as_float())


def ordered(v: Value) -> int:
    """Map the bit pattern onto an integer line where adjacent floats are
    adjacent integers, so the distance between two values counts the
    representable floats between them. Both zeros map to 0."""
    sign = 1 << (v.width - 1)
    magnitude = v.bits & (sign - 1)
    return -magnitude if v.bits & sign else magnitude


def ulp_distance(a: Value, b: Value) -> int:
    return abs(ordered(a) - ordered(b))
