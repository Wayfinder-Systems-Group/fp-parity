"""End-to-end runs against real compilers. Each test skips when its toolchain
is not installed, so the suite passes on any machine and proves more on a
machine with more compilers."""

import json
import platform
import shutil
from pathlib import Path

import pytest

from fpparity.cli import main

X86 = platform.machine().lower() in ("x86_64", "amd64")


def config(tmp_path: Path, targets: str) -> Path:
    p = tmp_path / "fpparity.toml"
    p.write_text(targets)
    return p


GCC_PAIR = """
[[target]]
name = "plain"
cc = "gcc"
cflags = ["-O2"]
[[target]]
name = "{name}"
cc = "gcc"
cflags = {cflags}
"""


@pytest.mark.skipif(not shutil.which("gcc"), reason="gcc not installed")
def test_same_toolchain_twice_is_identical(tmp_path):
    cfg = config(tmp_path, GCC_PAIR.format(name="again", cflags='["-O2"]'))
    assert main(["probe", "-c", str(cfg)]) == 0


@pytest.mark.skipif(not (shutil.which("gcc") and X86), reason="needs gcc on x86-64")
def test_fma_contraction_is_found_and_named(tmp_path, capsys):
    cfg = config(tmp_path, GCC_PAIR.format(name="fma", cflags='["-O2", "-mfma"]'))
    out_json = tmp_path / "report.json"
    rc = main(["probe", "-c", str(cfg), "--explain", "--json", str(out_json)])
    assert rc == 1
    report = json.loads(out_json.read_text())
    entry = report["targets"]["fma"]
    names = {d["name"] for d in entry["differences"]}
    assert "contract.residual" in names
    findings = entry["explanation"]["findings"]
    contract = [f for f in findings if f["flag"] == "-ffp-contract=off"]
    assert contract and "contract.residual" in contract[0]["resolved"]
    assert "FMA contraction" in capsys.readouterr().out


@pytest.mark.skipif(
    not (shutil.which("gcc") and X86 and shutil.which("aarch64-linux-gnu-gcc") and shutil.which("qemu-aarch64-static")),
    reason="needs gcc, aarch64-linux-gnu-gcc and qemu-aarch64-static on x86-64",
)
def test_x86_against_aarch64(tmp_path):
    cfg = config(
        tmp_path,
        """
[[target]]
name = "x86_64"
cc = "gcc"
cflags = ["-O2"]
[[target]]
name = "aarch64"
cc = "aarch64-linux-gnu-gcc"
cflags = ["-O2", "-static"]
runner = ["qemu-aarch64-static"]
""",
    )
    out_json = tmp_path / "report.json"
    rc = main(["probe", "-c", str(cfg), "--explain", "--json", str(out_json)])
    assert rc == 1
    entry = json.loads(out_json.read_text())["targets"]["aarch64"]
    names = {d["name"] for d in entry["differences"]}
    # aarch64 GCC contracts a*b+c into fmadd by default; x86-64 without -mfma cannot.
    assert "contract.residual" in names
    # the IEEE-mandated operations must still agree
    assert "ieee.sqrt" not in names and "ieee.div" not in names
    flags = {f["flag"] for f in entry["explanation"]["findings"]}
    assert "-ffp-contract=off" in flags


def test_include_dir_points_at_the_header(capsys):
    assert main(["include-dir"]) == 0
    assert (Path(capsys.readouterr().out.strip()) / "fpparity.h").is_file()


def test_bad_config_is_a_usage_error(tmp_path):
    p = tmp_path / "fpparity.toml"
    p.write_text("[[target]]\nname='a'\ncc='gcc'\n")
    assert main(["check", "-c", str(p)]) == 2
