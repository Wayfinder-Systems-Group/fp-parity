"""Find float <-> text conversions that go through the C library or a locale.

The C standard does not require strtod or printf("%.*f") to be correctly
rounded, and real C libraries are not: QNX 8.0's strtod rounds some decimal
tokens one unit in the last place away from glibc, and its printf("%.12f")
prints the last digit one low for some large values. The same double then
becomes different text on different platforms, and the same text becomes a
different double. Arithmetic can be bit-identical everywhere and the output
file still differs.

`fp-parity scan` reads C and C++ sources (comments and string literals
stripped) and reports every place a double is converted to or from text
through the C library or an iostream float manipulator:

  parse   strtod, strtof, strtold, atof, std::stod/stof/stold, and the scanf
          family with a float conversion (%f %lf %e %g %a)
  format  the printf family (printf, fprintf, snprintf, sprintf and the v and
          d variants) whose format string carries a float conversion
          (%f %e %g %a, any flags, width or precision)
  stream  std::fixed, std::scientific, std::hexfloat, std::defaultfloat,
          std::setprecision

Bypass forms are caught too: a macro body naming std::strtod, a function
pointer or address of strtod, and a using-declaration together with the call it
enables. Integer conversions (%d, %016llx, std::stoll) are exact and pass, as
do member functions and other namespaces' symbols (obj.stod(), my::parse()).
std::to_chars and std::from_chars pass: they are specified to round
correctly. Files named with --allow (the one place a project keeps its own
conversion routine, for example) are not scanned.

Known limit: a bare std::to_string(double) or `stream << double` with no
manipulator cannot be told from its integer use by a text scan, and is not
reported.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

SOURCE_SUFFIXES = {".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".inc", ".ipp"}

PARSE = {"strtod", "strtof", "strtold", "atof", "stod", "stof", "stold"}
MANIP = {"setprecision", "fixed", "scientific", "hexfloat", "defaultfloat"}
# Every printf-family function, including the ones that write to a stream:
# fprintf(f, "%.17g", x) is how most golden files and replay logs are written.
FORMAT = {"snprintf", "sprintf", "vsnprintf", "vsprintf",
          "printf", "fprintf", "vprintf", "vfprintf", "dprintf", "vdprintf"}
# The scanf family reads text into a double only through a float conversion
# (%f %lf %e %g %a); sscanf(s, "%d", &n) is an exact integer parse and passes.
SCANF = {"scanf", "sscanf", "fscanf", "vscanf", "vsscanf", "vfscanf"}

# A manipulator named without std:: is only a stream manipulator when it is
# streamed (`o << fixed` after `using namespace std`). Anywhere else a bare
# `fixed` or `scientific` is far more often a variable, so only setprecision,
# which no one names a variable, keeps the parse-function rules.
BARE_NAME_MANIP = {"fixed", "scientific", "hexfloat", "defaultfloat"}

_QUAL_KEYWORDS = {"return", "case", "else", "throw", "do", "new", "delete", "sizeof", "co_return", "using"}


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    name: str
    kind: str  # parse | format | stream
    text: str

    def __str__(self) -> str:
        return "{}:{}: {} ({}): {}".format(self.file, self.line, self.name, self.kind, self.text.strip())


def _ident(c: str) -> bool:
    return c.isalnum() or c == "_"


def strip_comments_and_literals(s: str) -> str:
    """Blank out comments, string and character literals (raw strings too),
    keeping every newline so line numbers survive."""
    out = [" "] * len(s)
    n = len(s)
    i = 0

    def keep_nl(k: int) -> None:
        if s[k] == "\n":
            out[k] = "\n"

    while i < n:
        c = s[i]
        if c == "/" and i + 1 < n and s[i + 1] == "/":
            while i < n and s[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and s[i + 1] == "*":
            i += 2
            while i < n and not (s[i] == "*" and i + 1 < n and s[i + 1] == "/"):
                keep_nl(i)
                i += 1
            i = i + 2 if i < n else n
            continue
        if c == "R" and i + 1 < n and s[i + 1] == '"' and (
                i == 0 or not _ident(s[i - 1]) or s[i - 1] in "8uUL"):
            j = i + 2
            delim = []
            while j < n and s[j] != "(":
                delim.append(s[j])
                j += 1
            close = ")" + "".join(delim) + '"'
            end = s.find(close, j)
            stop = n if end < 0 else end + len(close)
            for k in range(i, stop):
                keep_nl(k)
            i = stop
            continue
        if c in "\"'":
            # A digit separator (1'000'000) is not a character literal.
            if c == "'" and 0 < i < n - 1 and s[i - 1] in "0123456789abcdefABCDEF" and s[i + 1] in "0123456789abcdefABCDEF":
                i += 1
                continue
            i += 1
            while i < n and s[i] != c:
                if s[i] == "\\" and i + 1 < n:
                    i += 1
                keep_nl(i)
                i += 1
            i += 1
            continue
        out[i] = c
        i += 1
    return "".join(out)


def format_has_float_conversion(fmt: str) -> bool:
    """True if a printf format string holds a floating conversion (%% ignored)."""
    i, n = 0, len(fmt)
    while i < n:
        if fmt[i] != "%":
            i += 1
            continue
        j = i + 1
        if j < n and fmt[j] == "%":
            i = j + 1
            continue
        while j < n and fmt[j] in "-+ 0#'":
            j += 1
        while j < n and (fmt[j].isdigit() or fmt[j] == "*"):
            j += 1
        if j < n and fmt[j] == ".":
            j += 1
            while j < n and (fmt[j].isdigit() or fmt[j] == "*"):
                j += 1
        while j < n and fmt[j] in "lhLjzt":
            j += 1
        if j < n and fmt[j] in "fFeEgGaA":
            return True
        i = j
    return False


def _call_has_float_format(raw: str, name_end: int) -> bool:
    """Concatenate the string literals at the top level of the call's argument
    list and test them for a float conversion."""
    i, n = name_end, len(raw)
    while i < n and raw[i].isspace():
        i += 1
    if i >= n or raw[i] != "(":
        return False
    depth = 0
    fmt = []
    while i < n:
        c = raw[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        elif c == '"':
            i += 1
            lit = []
            while i < n and raw[i] != '"':
                if raw[i] == "\\" and i + 1 < n:
                    lit.append(raw[i:i + 2])
                    i += 2
                    continue
                lit.append(raw[i])
                i += 1
            if depth == 1:
                fmt.append("".join(lit))
        i += 1
    return format_has_float_conversion("".join(fmt))


def _skip_ws(s: str, pos: int) -> int:
    while pos < len(s) and s[pos].isspace():
        pos += 1
    return pos


def _skip_ws_back(s: str, pos: int) -> int:
    while pos > 0 and s[pos - 1].isspace():
        pos -= 1
    return pos


def scan_text(name: str, raw: str) -> List[Hit]:
    """Every C-library or locale-dependent float conversion in one source text."""
    s = strip_comments_and_literals(raw)
    n = len(s)
    hits: List[Hit] = []
    lines = raw.split("\n")

    i = 0
    while i < n:
        if not _ident(s[i]) or (i > 0 and _ident(s[i - 1])):
            i += 1
            continue
        j = i
        while j < n and _ident(s[j]):
            j += 1
        ident = s[i:j]
        start = i
        i = j
        if ident[0].isdigit():
            continue
        is_parse = ident in PARSE
        is_manip = ident in MANIP
        is_fmt = ident in FORMAT or ident in SCANF
        if not (is_parse or is_manip or is_fmt):
            continue

        b = _skip_ws_back(s, start)
        qual = "none"
        if b >= 1 and s[b - 1] == ".":
            qual = "member"
        elif b >= 2 and s[b - 2:b] == "->":
            qual = "member"
        elif b >= 2 and s[b - 2:b] == "::":
            q = _skip_ws_back(s, b - 2)
            qs = q
            while qs > 0 and _ident(s[qs - 1]):
                qs -= 1
            qname = s[qs:q]
            qual = "std" if (qname == "" or qname == "std" or qname in _QUAL_KEYWORDS) else "other"
        if qual in ("member", "other"):
            continue

        k = _skip_ws(s, j)
        is_call = k < n and s[k] == "("
        addr = b >= 1 and s[b - 1] == "&" and not (b >= 2 and s[b - 2] == "&")
        assign = b >= 1 and s[b - 1] == "=" and not (b >= 2 and s[b - 2] in "=!<>")
        ends = k < n and s[k] in ";,)"
        streamed = b >= 2 and s[b - 2:b] == "<<"

        if is_fmt:
            if is_call:
                flagged = _call_has_float_format(raw, j)
            elif qual == "std":
                flagged = True
            else:
                flagged = (addr or assign) and ends
            kind = "parse" if ident in SCANF else "format"
        elif is_manip and ident in BARE_NAME_MANIP:
            flagged = qual == "std" or streamed
            kind = "stream"
        else:
            if qual == "std":
                flagged = True
            elif is_call:
                flagged = True
            else:
                flagged = (addr or assign) and ends
            kind = "stream" if is_manip else "parse"

        if flagged:
            line = raw.count("\n", 0, start) + 1
            hits.append(Hit(name, line, ident, kind, lines[line - 1]))
    return hits


def _expand(paths: Sequence[Path]) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SOURCE_SUFFIXES))
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(str(p))
    return files


def _allowed(path: Path, allow: Iterable[str]) -> bool:
    posix = path.as_posix()
    return any(fnmatch.fnmatch(posix, pat) or fnmatch.fnmatch(path.name, pat) or posix.endswith("/" + pat.lstrip("./"))
               for pat in allow)


def scan_paths(paths: Sequence[Path], allow: Iterable[str] = ()) -> "tuple[List[Path], List[Hit]]":
    allow = list(allow)
    files = [f for f in _expand(paths) if not _allowed(f, allow)]
    hits: List[Hit] = []
    for f in files:
        hits.extend(scan_text(str(f), f.read_text(encoding="utf-8", errors="replace")))
    return files, hits
