"""The source scan: every case it must flag, every case it must pass, and a
negative control on disk that proves the command can fail."""

from pathlib import Path

import pytest

from fpparity.cli import main
from fpparity.scan import format_has_float_conversion, scan_text

FLAGGED = [
    # direct calls
    ("double f(const char* s){ return std::strtod(s, nullptr); }", 1),
    ("double f(const char* s){ return strtod(s, NULL); }", 1),
    ("double f(const std::string& s){ return std::stod(s); }", 1),
    ("double f(const char* s){ return ::atof(s); }", 1),
    ('void f(const char* s, double* d){ std::sscanf(s, "%lf", d); }', 1),
    ('void f(const char* s, float* d){ sscanf(s, "%*d %f", d); }', 1),
    ('void f(char* b, double x){ std::snprintf(b, 8, "%.12f", x); }', 1),
    ('void f(char* b, double x){ snprintf(b, 8, "%.17e", x); }', 1),
    ('void f(char* b, double x){ std::snprintf(b, 8, "%+.4g", x); }', 1),
    ('void f(FILE* o, double x){ fprintf(o, "%s=%.17g\\n", "v", x); }', 1),
    ('void f(double x){ printf("%a\\n", x); }', 1),
    ('void f(char* b, double x){ snprintf(b, 8, "%" "10.3" "f", x); }', 1),
    # stream manipulators
    ("void f(std::ostream& o){ o << std::setprecision(12); }", 1),
    ("void f(std::ostream& o, double x){ o << std::fixed << std::setprecision(12) << x; }", 2),
    ("void f(std::ostream& o, double x){ o << std::scientific << x; }", 1),
    ("using namespace std; void f(ostream& o, double x){ o << fixed << x; }", 1),
    # bypass forms
    ("#define CVT std::strtod\n", 1),
    ("double (*cvt)(const char*, char**) = std::strtod;", 1),
    ("using std::stod;\ndouble p(const std::string& s){ return stod(s); }", 2),
    ("double (*g)(const char*, char**) = &strtod;", 1),
]

CLEAN = [
    'void f(char* b, int c){ std::snprintf(b, 8, "\\\\u%04x", c); }',
    'void f(char* b, long long m){ std::snprintf(b, 8, "%s.%03lld", "x", m); }',
    'void f(char* b, long long h){ std::snprintf(b, 8, "%016llx", h); }',
    'void f(char* b){ snprintf(b, 8, "100%%"); }',
    'void f(const char* s, int* n){ sscanf(s, "%d", n); }',
    "double f(const char* s){ return cc::strtod_c(s); }",
    "double f(std::string_view s){ return mylib::parse_double(s); }",
    "int f(char* b, double x){ auto r = std::to_chars(b, b+8, x, std::chars_format::fixed, 12); return (int)(r.ptr-b); }",
    "long long f(const std::string& s){ return std::stoll(s); }",
    "double f(O& o, O* p){ return o.stod() + p->strtod(); }",
    "double stod = 1.5; double f(){ return stod; }",
    "bool f(double fixed, double x){ return x == fixed || x <= fixed; }",
    "double f(double scientific){ double y = scientific; return y; }",
    "int f(int fixed){ int y = fixed; return y; }",
    '// std::strtod(x)\n/* snprintf(b, 8, "%.12f", x) */ int f(){ return 0; }',
    'const char* a = "std::strtod("; const char* b = "%.12f";',
    'const char* r = R"x(strtod(s, 0); printf("%f", v);)x";',
    "int n = 1'000'000; double f(const char* s){ return 0; }",
]


@pytest.mark.parametrize("src,want", FLAGGED)
def test_flagged(src, want):
    hits = scan_text("<case>", src)
    assert len(hits) == want, [str(h) for h in hits]


@pytest.mark.parametrize("src", CLEAN)
def test_clean(src):
    hits = scan_text("<case>", src)
    assert hits == [], [str(h) for h in hits]


def test_hit_reports_line_and_kind():
    hits = scan_text("a.cpp", "int x;\n\ndouble f(const char* s){ return std::stod(s); }\n")
    assert len(hits) == 1
    h = hits[0]
    assert (h.file, h.line, h.name, h.kind) == ("a.cpp", 3, "stod", "parse")


def test_format_parser():
    assert format_has_float_conversion("%.12f")
    assert format_has_float_conversion("x=%-+ #012.3Le")
    assert format_has_float_conversion("%*.*g")
    assert not format_has_float_conversion("%d %s %016llx %%f")


# Negative control: plant files on disk and run the real command. Each file
# maps to the number of hits it must produce.
PLANTED = {
    "q_strtod.cpp": (1, "#include <cstdlib>\ndouble p(const char* s){ return std::strtod(s, nullptr); }\n"),
    "bare_strtod.c": (1, "#include <stdlib.h>\ndouble p(const char* s){ return strtod(s, 0); }\n"),
    "stod.cpp": (1, "#include <string>\ndouble p(const std::string& s){ return std::stod(s); }\n"),
    "fmt_f.cpp": (1, '#include <cstdio>\nvoid p(char* b, double x){ std::snprintf(b, 32, "%.6f", x); }\n'),
    "scanf.c": (1, '#include <stdio.h>\nvoid p(const char* s, double* d){ sscanf(s, "%lf", d); }\n'),
    "macro.hpp": (1, "#include <cstdlib>\n#define CVT std::strtod\n"),
    "fnptr.cpp": (1, "#include <cstdlib>\ndouble (*cvt)(const char*, char**) = std::strtod;\n"),
    "usingdecl.cpp": (2, "#include <string>\nusing std::stod;\ndouble p(const std::string& s){ return stod(s); }\n"),
    "manip.cpp": (2, "#include <sstream>\n#include <iomanip>\nstd::string p(double x){ std::ostringstream o; "
                     "o << std::fixed << std::setprecision(12) << x; return o.str(); }\n"),
    "wrapper.cpp": (1, "#include <cstdlib>\ndouble w(const char* s){ return std::strtod(s, nullptr); }\n"
                       "double p(const char* s){ return w(s); }\n"),
    "clean.cpp": (0, "#include <charconv>\nint p(char* b, double x){ auto r = std::to_chars(b, b+8, x, "
                     "std::chars_format::fixed, 12); return (int)(r.ptr-b); }\n"),
    "int_fmt.c": (0, '#include <stdio.h>\nvoid p(char* b, long long h){ snprintf(b, 32, "%016llx", h); }\n'),
    "int_parse.cpp": (0, "#include <string>\nlong long p(const std::string& s){ return std::stoll(s); }\n"),
    "notes.txt": (0, "strtod everywhere, not a source file\n"),
}


def _plant(root: Path) -> None:
    for name, (_, body) in PLANTED.items():
        (root / name).write_text(body)


def test_negative_control_fails_the_command(tmp_path, capsys):
    _plant(tmp_path)
    json_path = tmp_path / "scan.json"
    assert main(["scan", str(tmp_path), "--json", str(json_path)]) == 1
    import json
    report = json.loads(json_path.read_text())
    per = {}
    for h in report["hits"]:
        per[Path(h["file"]).name] = per.get(Path(h["file"]).name, 0) + 1
    for name, (want, _) in PLANTED.items():
        assert per.get(name, 0) == want, name
    assert report["files"] == len(PLANTED) - 1  # notes.txt is not a source
    assert len(report["hits"]) == sum(w for w, _ in PLANTED.values())


def test_clean_tree_passes(tmp_path):
    for name in ("clean.cpp", "int_fmt.c", "int_parse.cpp"):
        (tmp_path / name).write_text(PLANTED[name][1])
    assert main(["scan", str(tmp_path)]) == 0


def test_allow_skips_the_sanctioned_file(tmp_path):
    (tmp_path / "convert.cpp").write_text(PLANTED["q_strtod.cpp"][1])
    (tmp_path / "clean.cpp").write_text(PLANTED["clean.cpp"][1])
    assert main(["scan", str(tmp_path)]) == 1
    assert main(["scan", str(tmp_path), "--allow", "convert.cpp"]) == 0


def test_missing_path_is_a_usage_error(tmp_path):
    assert main(["scan", str(tmp_path / "nope")]) == 2
