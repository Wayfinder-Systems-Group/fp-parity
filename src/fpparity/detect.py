"""Find the compilers on this machine and write a starter fpparity.toml."""

from __future__ import annotations

import platform
import shutil
from typing import Dict, List

# (target name, compiler, cflags, ldflags or None, runner candidates)
_NATIVE = [
    ("native-gcc", "gcc", ["-O2"], None, []),
    ("native-clang", "clang", ["-O2"], None, []),
]
_CROSS = [
    ("aarch64-gcc", "aarch64-linux-gnu-gcc", ["-O2", "-static"], None, ["qemu-aarch64-static", "qemu-aarch64"]),
    ("armhf-gcc", "arm-linux-gnueabihf-gcc", ["-O2", "-static"], None, ["qemu-arm-static", "qemu-arm"]),
    ("riscv64-gcc", "riscv64-linux-gnu-gcc", ["-O2", "-static"], None, ["qemu-riscv64-static", "qemu-riscv64"]),
]


def detect() -> List[Dict[str, object]]:
    """Targets this machine can build and run. A cross compiler counts only
    when an emulator to run its output is also present."""
    found: List[Dict[str, object]] = []
    for name, cc, cflags, ldflags, _ in _NATIVE:
        if shutil.which(cc):
            found.append({"name": name, "cc": cc, "cflags": cflags, "ldflags": ldflags, "runner": []})
    for name, cc, cflags, ldflags, runners in _CROSS:
        if not shutil.which(cc):
            continue
        runner = next((r for r in runners if shutil.which(r)), None)
        if runner:
            found.append({"name": name, "cc": cc, "cflags": cflags, "ldflags": ldflags, "runner": [runner]})
    # The native compiler with FMA allowed: on x86-64 the default build has no
    # FMA, so this second target shows what contraction alone changes.
    if platform.machine().lower() in ("x86_64", "amd64") and shutil.which("gcc"):
        found.append({"name": "native-gcc-fma", "cc": "gcc", "cflags": ["-O2", "-mfma"], "ldflags": None, "runner": []})
    return found


def _toml_list(items: List[str]) -> str:
    return "[" + ", ".join('"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"' for s in items) + "]"


def starter_config(targets: List[Dict[str, object]], sources: List[str]) -> str:
    lines = [
        "# fp-parity configuration. Every target builds the same sources; each",
        "# value the harness emits is compared bit for bit against the baseline.",
        'baseline = "{}"'.format(targets[0]["name"]) if targets else '# baseline = "<first target>"',
        "sources = {}".format(_toml_list(sources)),
        'ldflags = ["-lm"]',
        "",
    ]
    for t in targets:
        lines += [
            "[[target]]",
            'name = "{}"'.format(t["name"]),
            'cc = "{}"'.format(t["cc"]),
            "cflags = {}".format(_toml_list(t["cflags"])),  # type: ignore[arg-type]
        ]
        if t["runner"]:
            lines.append("runner = {}".format(_toml_list(t["runner"])))  # type: ignore[arg-type]
        lines.append("")
    lines += [
        "# QNX example: build with qcc and run on a target over ssh.",
        "# [[target]]",
        '# name = "qnx-aarch64"',
        '# cc = "qcc"',
        '# cflags = ["-Vgcc_ntoaarch64le", "-O2"]',
        '# runner = ["ssh", "qnx-target", "--"]',
        "",
    ]
    return "\n".join(lines)
