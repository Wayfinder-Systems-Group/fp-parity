"""Compile the harness for one target, run it, and return what it printed."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, List, Sequence

from .config import Config, Target

DATA_DIR = Path(__file__).resolve().parent / "data"
PROBE_SOURCE = DATA_DIR / "probe.c"


class BuildError(RuntimeError):
    pass


def _tail(text: str, lines: int = 20) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def compile_command(cfg: Config, target: Target, sources: Sequence[Path], output: Path,
                    extra_cflags: Iterable[str] = ()) -> List[str]:
    includes = ["-I" + str(p) for p in [*cfg.include, DATA_DIR]]
    return [
        target.cc,
        *target.cflags,
        *extra_cflags,
        *includes,
        *[str(s) for s in sources],
        "-o",
        str(output),
        *cfg.ldflags_for(target),
    ]


def build_and_run(cfg: Config, target: Target, sources: Sequence[Path], workdir: Path,
                  extra_cflags: Sequence[str] = (), timeout: float = 300.0) -> str:
    """Build ``sources`` with ``target``'s toolchain and return the program's
    stdout. Raises BuildError with the command and the tail of stderr when the
    compiler or the program fails, because a silent failure here would read as
    'no output, nothing differs'."""
    tag = _safe(target.name) + ("-" + _safe("_".join(extra_cflags)) if extra_cflags else "")
    output = workdir / tag
    env = dict(os.environ)
    env.update(target.env)

    cmd = compile_command(cfg, target, sources, output, extra_cflags)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise BuildError("{}: compiler {!r} not found on PATH".format(target.name, target.cc))
    except subprocess.TimeoutExpired:
        raise BuildError("{}: compile timed out after {:.0f}s".format(target.name, timeout))
    if proc.returncode != 0:
        raise BuildError("{}: compile failed (exit {})\n  {}\n{}".format(
            target.name, proc.returncode, " ".join(cmd), _tail(proc.stderr)))

    # MinGW appends .exe when the output name has no extension.
    exe = output if output.exists() else output.with_suffix(".exe")
    run = [*target.runner, str(exe)]
    try:
        proc = subprocess.run(run, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise BuildError("{}: runner {!r} not found".format(target.name, run[0]))
    except subprocess.TimeoutExpired:
        raise BuildError("{}: program timed out after {:.0f}s".format(target.name, timeout))
    if proc.returncode != 0:
        raise BuildError("{}: program exited {}\n  {}\n{}".format(
            target.name, proc.returncode, " ".join(run), _tail(proc.stderr)))
    return proc.stdout
