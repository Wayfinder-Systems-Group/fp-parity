from pathlib import Path

import pytest

from fpparity.config import ConfigError, load


def write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "h.c").write_text("int main(void){return 0;}\n")
    p = tmp_path / "fpparity.toml"
    p.write_text(text)
    return p


TWO_TARGETS = """
sources = ["h.c"]
[[target]]
name = "a"
cc = "gcc"
[[target]]
name = "b"
cc = "clang"
cflags = ["-O1"]
ldflags = []
runner = ["env"]
"""


def test_loads_two_targets_and_defaults(tmp_path):
    cfg = load(write(tmp_path, TWO_TARGETS))
    assert cfg.baseline == "a"
    assert cfg.ldflags == ["-lm"]
    assert cfg.ldflags_for(cfg.target("a")) == ["-lm"]
    assert cfg.ldflags_for(cfg.target("b")) == []
    assert cfg.target("b").runner == ["env"]


@pytest.mark.parametrize(
    "text, message",
    [
        ('sources=["h.c"]\n[[target]]\nname="a"\ncc="gcc"\n', "at least two"),
        (TWO_TARGETS.replace('name = "b"', 'name = "a"'), "unique"),
        ('baseline = "zzz"\n' + TWO_TARGETS, "baseline"),
        (TWO_TARGETS.replace('"h.c"', '"nope.c"'), "source not found"),
        (TWO_TARGETS.replace('cflags = ["-O1"]', 'cflags = "-O1"'), "list of strings"),
    ],
)
def test_rejects_bad_configs(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load(write(tmp_path, text))


def test_missing_file_points_at_init(tmp_path):
    with pytest.raises(ConfigError, match="fp-parity init"):
        load(tmp_path / "fpparity.toml")
