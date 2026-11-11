"""Bit-level comparison of two runs of the same harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .protocol import Value, is_inf, is_nan, ulp_distance

# Why two runs disagree on one name.
REASONS = {
    "bits": "different bits",
    "zero-sign": "+0.0 on one side, -0.0 on the other",
    "nan-payload": "both NaN, with different payload bits",
    "kind": "emitted as f64 on one side and f32 on the other",
    "missing": "not emitted by this target",
    "extra": "emitted only by this target",
}


@dataclass(frozen=True)
class Difference:
    name: str
    base: Optional[Value]
    other: Optional[Value]
    reason: str
    ulps: Optional[int]

    def describe(self) -> str:
        return REASONS[self.reason]


def compare(base: Dict[str, Value], other: Dict[str, Value], strict_nan: bool = False) -> List[Difference]:
    """Every name on which ``other`` disagrees with ``base``, in base order.

    Two NaNs with different payloads count as equal unless ``strict_nan``:
    payload bits are rarely meaningful and differ between CPUs for the same
    operation, so flagging them by default would bury the differences that
    matter. Signed zeros are always reported, because 1/x tells them apart.
    """
    diffs: List[Difference] = []
    for name, b in base.items():
        o = other.get(name)
        if o is None:
            diffs.append(Difference(name, b, None, "missing", None))
            continue
        if o.kind != b.kind:
            diffs.append(Difference(name, b, o, "kind", None))
            continue
        if o.bits == b.bits:
            continue
        if is_nan(b) and is_nan(o):
            if strict_nan:
                diffs.append(Difference(name, b, o, "nan-payload", None))
            continue
        if b.as_float() == 0.0 and o.as_float() == 0.0:
            diffs.append(Difference(name, b, o, "zero-sign", None))
            continue
        finite = not (is_nan(b) or is_nan(o) or is_inf(b) or is_inf(o))
        diffs.append(Difference(name, b, o, "bits", ulp_distance(b, o) if finite else None))
    for name, o in other.items():
        if name not in base:
            diffs.append(Difference(name, None, o, "extra", None))
    return diffs
