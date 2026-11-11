"""Name the cause of a difference by rebuilding with one flag changed.

Each candidate flag turns off one known source of difference. A flag that,
added to one side or both, makes a differing value match the baseline is the
cause of that value's difference. A value no flag fixes is reported as such:
that is the signature of a math library or hardware difference, which no
compiler flag can remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Set

from .build import BuildError, build_and_run
from .compare import compare
from .config import Config, Target
from .protocol import Value, parse_output

# (flag, what it means when this flag removes the difference)
CANDIDATES = [
    ("-ffp-contract=off", "FMA contraction: a multiply and an add were fused into one rounding"),
    ("-fexcess-precision=standard", "excess precision: intermediates were kept wider than their declared type"),
    ("-ffloat-store", "excess precision: intermediates were held in wider registers"),
    ("-fno-fast-math", "fast-math: value-changing optimizations were enabled"),
    ("-fno-associative-math", "reassociation: an arithmetic chain was reordered"),
    ("-O0", "an optimization pass changed the arithmetic"),
]

SIDES = ("target", "baseline", "both")


@dataclass
class Finding:
    flag: str
    side: str
    meaning: str
    resolved: List[str]


@dataclass
class Explanation:
    target: str
    findings: List[Finding] = field(default_factory=list)
    unexplained: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def _run(cfg: Config, target: Target, sources: Sequence[Path], workdir: Path, flags: Sequence[str]) -> Dict[str, Value]:
    values, _ = parse_output(build_and_run(cfg, target, sources, workdir, extra_cflags=flags))
    return values


def explain(cfg: Config, base: Target, base_values: Dict[str, Value], other: Target,
            other_values: Dict[str, Value], names: Sequence[str], sources: Sequence[Path],
            workdir: Path, strict_nan: bool = False) -> Explanation:
    """Try each candidate flag on the target, the baseline, and both. A flag a
    compiler rejects is skipped and listed, not treated as a failure: clang,
    for example, has no -fexcess-precision=standard on every version."""
    pending: Set[str] = set(n for n in names if n in base_values and n in other_values)
    result = Explanation(target=other.name)
    explained: Set[str] = set()

    for flag, meaning in CANDIDATES:
        for side in SIDES:
            try:
                b = _run(cfg, base, sources, workdir, [flag]) if side in ("baseline", "both") else base_values
                o = _run(cfg, other, sources, workdir, [flag]) if side in ("target", "both") else other_values
            except BuildError:
                if flag not in result.skipped:
                    result.skipped.append(flag)
                continue
            still = {d.name for d in compare(b, o, strict_nan=strict_nan)}
            # Candidates run from most to least specific. A later, broader flag
            # (-O0 removes nearly everything) only claims what no earlier flag
            # explained, so each difference is attributed to its narrowest cause.
            fixed = sorted(n for n in pending if n not in still and n not in explained)
            if fixed:
                result.findings.append(Finding(flag, side, meaning, fixed))
                explained.update(fixed)
                break  # the first side that works is enough for this flag

    result.unexplained = sorted(pending - explained)
    return result
