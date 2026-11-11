import struct

from fpparity.compare import compare
from fpparity.protocol import Value, parse_output, ulp_distance


def f64(name, x):
    return Value(name, "f64", struct.unpack("<Q", struct.pack("<d", x))[0])


def test_parse_reads_protocol_lines_and_ignores_the_rest():
    text = "hello\nx\tf64\t3ff0000000000000\ny\tf32\t3f800000\nnot\tf16\tabcd\n"
    values, problems = parse_output(text)
    assert set(values) == {"x", "y"}
    assert values["x"].as_float() == 1.0
    assert values["y"].as_float() == 1.0
    assert problems == []


def test_parse_reports_malformed_and_duplicate_lines():
    text = "a\tf64\t123\nb\tf64\t3ff0000000000000\nb\tf64\t4000000000000000\n"
    values, problems = parse_output(text)
    assert "a" not in values
    assert values["b"].as_float() == 1.0  # the first value is kept
    assert len(problems) == 2


def test_ulp_distance_counts_representable_floats():
    one = f64("x", 1.0)
    next_up = Value("x", "f64", one.bits + 1)
    assert ulp_distance(one, next_up) == 1
    # across zero: the smallest positive and smallest negative subnormal are 2 apart
    tiny_pos = Value("x", "f64", 1)
    tiny_neg = Value("x", "f64", (1 << 63) | 1)
    assert ulp_distance(tiny_pos, tiny_neg) == 2


def test_identical_runs_have_no_differences():
    a = {"x": f64("x", 0.1), "y": f64("y", 2.0)}
    assert compare(a, dict(a)) == []


def test_bit_difference_is_reported_with_ulps():
    base = {"x": f64("x", 1.0)}
    other = {"x": Value("x", "f64", base["x"].bits + 3)}
    (d,) = compare(base, other)
    assert d.reason == "bits" and d.ulps == 3


def test_signed_zero_is_always_reported():
    (d,) = compare({"z": f64("z", 0.0)}, {"z": f64("z", -0.0)})
    assert d.reason == "zero-sign"


def test_nan_payloads_equal_unless_strict():
    quiet = Value("n", "f64", 0x7FF8000000000000)
    payload = Value("n", "f64", 0x7FF8000000000001)
    assert compare({"n": quiet}, {"n": payload}) == []
    (d,) = compare({"n": quiet}, {"n": payload}, strict_nan=True)
    assert d.reason == "nan-payload"


def test_missing_extra_and_kind_mismatch():
    base = {"a": f64("a", 1.0), "b": f64("b", 1.0)}
    other = {"b": Value("b", "f32", 0x3F800000), "c": f64("c", 1.0)}
    reasons = {d.name: d.reason for d in compare(base, other)}
    assert reasons == {"a": "missing", "b": "kind", "c": "extra"}


def test_non_finite_difference_has_no_ulp_count():
    (d,) = compare({"x": f64("x", 1.0)}, {"x": f64("x", float("inf"))})
    assert d.reason == "bits" and d.ulps is None
