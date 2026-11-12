"""fp-parity command line.

Exit codes: 0 every target matched the baseline bit for bit (scan: no
conversion found), 1 at least one value differs (scan: a conversion found),
2 usage, configuration, or build error.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import __version__
from .build import DATA_DIR, PROBE_SOURCE, BuildError, build_and_run
from .compare import Difference, compare
from .config import DEFAULT_NAME, Config, ConfigError, from_dict, load
from .detect import detect, starter_config
from .explain import Explanation, explain
from .protocol import Value, parse_output
from .scan import scan_paths

EXIT_OK, EXIT_DIFF, EXIT_USAGE = 0, 1, 2


def _fmt(v: Optional[Value]) -> str:
    if v is None:
        return "-"
    return "0x{} ({!r})".format(v.hex(), v.as_float())


def _diff_line(d: Difference) -> str:
    extra = ""
    if d.reason == "bits":
        extra = ", {} ulp".format(d.ulps) if d.ulps is not None else ", non-finite"
    return "  {:<28} {}{}\n      baseline {}\n      target   {}".format(
        d.name, d.describe(), extra, _fmt(d.base), _fmt(d.other))


def _diff_json(d: Difference) -> dict:
    return {
        "name": d.name,
        "reason": d.reason,
        "ulps": d.ulps,
        "baseline": None if d.base is None else d.base.hex(),
        "target": None if d.other is None else d.other.hex(),
    }


def _probe_config(path: Path) -> Config:
    """The configured targets if a config exists, else the detected ones,
    building the bundled probe in place of the harness."""
    if path.is_file():
        cfg = load(path, require_sources=False)
    else:
        targets = detect()
        if len(targets) < 2:
            raise ConfigError("fewer than two usable compilers found; write {} with at least two targets".format(DEFAULT_NAME))
        data = {"target": [{k: v for k, v in t.items() if v is not None} for t in targets]}
        cfg = from_dict(data, Path.cwd(), require_sources=False)
    cfg.sources = [PROBE_SOURCE]
    return cfg


def run_comparison(cfg: Config, do_explain: bool, strict_nan: bool, json_path: Optional[Path]) -> int:
    base = cfg.target(cfg.baseline)
    report: dict = {"version": __version__, "baseline": base.name, "targets": {}}
    any_diff = False

    with tempfile.TemporaryDirectory(prefix="fpparity-") as tmp:
        work = Path(tmp)
        outputs: Dict[str, Dict[str, Value]] = {}
        for t in cfg.targets:
            values, problems = parse_output(build_and_run(cfg, t, cfg.sources, work))
            for p in problems:
                print("fp-parity: {}: {}".format(t.name, p), file=sys.stderr)
            if not values:
                raise BuildError("{}: the program printed no fp-parity lines (see fpparity.h)".format(t.name))
            outputs[t.name] = values

        base_values = outputs[base.name]
        print("fp-parity {}: baseline {}, {} values".format(__version__, base.name, len(base_values)))
        for t in cfg.targets:
            if t.name == base.name:
                continue
            diffs = compare(base_values, outputs[t.name], strict_nan=strict_nan)
            entry: dict = {"differences": [_diff_json(d) for d in diffs]}
            if not diffs:
                print("\n{}: identical".format(t.name))
            else:
                any_diff = True
                print("\n{}: {} of {} values differ".format(t.name, len(diffs), len(base_values)))
                for d in diffs:
                    print(_diff_line(d))
                if do_explain:
                    names = [d.name for d in diffs if d.reason in ("bits", "zero-sign", "nan-payload")]
                    ex = explain(cfg, base, base_values, t, outputs[t.name], names, cfg.sources, work, strict_nan)
                    _print_explanation(ex)
                    entry["explanation"] = {
                        "findings": [f.__dict__ for f in ex.findings],
                        "unexplained": ex.unexplained,
                        "skipped_flags": ex.skipped,
                    }
            report["targets"][t.name] = entry

    if json_path is not None:
        json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return EXIT_DIFF if any_diff else EXIT_OK


def _print_explanation(ex: Explanation) -> None:
    print("  cause:")
    for f in ex.findings:
        where = {"target": "on this target", "baseline": "on the baseline", "both": "on both"}[f.side]
        print("    {} {} removes {}: {}".format(f.flag, where, ", ".join(f.resolved), f.meaning))
    text = [n for n in ex.unexplained if n.startswith("text.")]
    other = [n for n in ex.unexplained if not n.startswith("text.")]
    if text:
        print("    no compiler flag removes {}: the C library converts between text and floating point "
              "differently (strtod and printf need not round correctly); run `fp-parity scan` on your "
              "sources to find these calls".format(", ".join(text)))
    if other:
        print("    no compiler flag removes {}: the math library or the hardware differ".format(", ".join(other)))
    if ex.skipped:
        print("    flags a compiler rejected, not tried: {}".format(", ".join(ex.skipped)))


def run_scan(paths: Sequence[Path], allow: Sequence[str], json_path: Optional[Path]) -> int:
    try:
        files, hits = scan_paths(paths, allow)
    except FileNotFoundError as exc:
        print("fp-parity: no such file or directory: {}".format(exc), file=sys.stderr)
        return EXIT_USAGE
    print("fp-parity {}: scanned {} source file(s), {} conversion(s) through the C library or a locale".format(
        __version__, len(files), len(hits)))
    for h in hits:
        print("  " + str(h))
    if hits:
        print("these round differently on different C libraries; use std::to_chars / std::from_chars, "
              "or your own correctly rounded routine (then --allow it)")
    if json_path is not None:
        json_path.write_text(json.dumps({
            "version": __version__,
            "files": len(files),
            "hits": [h.__dict__ for h in hits],
        }, indent=2) + "\n", encoding="utf-8")
    return EXIT_DIFF if hits else EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="fp-parity", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version="fp-parity " + __version__)
    sub = ap.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", type=Path, default=Path(DEFAULT_NAME), help="config file (default: %(default)s)")
    common.add_argument("--explain", action="store_true", help="rebuild with one flag changed at a time to name each difference's cause")
    common.add_argument("--strict-nan", action="store_true", help="treat NaNs with different payload bits as different")
    common.add_argument("--json", type=Path, help="also write the report as JSON to this path")

    sub.add_parser("check", parents=[common], help="build your harness for every target and compare the bits")
    sub.add_parser("probe", parents=[common], help="build the bundled probe for every target and compare the bits")
    init = sub.add_parser("init", help="write a starter config from the compilers found on this machine")
    init.add_argument("-c", "--config", type=Path, default=Path(DEFAULT_NAME))
    init.add_argument("--source", action="append", default=None, help="harness source file (repeatable)")
    init.add_argument("--force", action="store_true", help="overwrite an existing config")
    sub.add_parser("include-dir", help="print the directory that holds fpparity.h")
    scan = sub.add_parser("scan", help="find float <-> text conversions that go through the C library or a locale")
    scan.add_argument("paths", nargs="+", type=Path, help="source files or directories")
    scan.add_argument("--allow", action="append", default=[], metavar="PATTERN",
                      help="file name or glob to skip, such as your own conversion routine (repeatable)")
    scan.add_argument("--json", type=Path, help="also write the hits as JSON to this path")

    args = ap.parse_args(argv)
    try:
        if args.command == "scan":
            return run_scan(args.paths, args.allow, args.json)
        if args.command == "include-dir":
            print(DATA_DIR)
            return EXIT_OK
        if args.command == "init":
            if args.config.exists() and not args.force:
                print("fp-parity: {} exists; pass --force to overwrite".format(args.config), file=sys.stderr)
                return EXIT_USAGE
            targets = detect()
            args.config.write_text(starter_config(targets, args.source or ["harness.c"]), encoding="utf-8")
            print("wrote {} with {} target(s): {}".format(args.config, len(targets), ", ".join(t["name"] for t in targets)))
            if len(targets) < 2:
                print("fp-parity: fewer than two targets found; add another [[target]] by hand", file=sys.stderr)
            return EXIT_OK
        cfg = _probe_config(args.config) if args.command == "probe" else load(args.config)
        return run_comparison(cfg, args.explain, args.strict_nan, args.json)
    except (ConfigError, BuildError) as exc:
        print("fp-parity: {}".format(exc), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
