"""fpparity.toml: the harness sources and the targets to build them for.

    baseline = "x86_64-gcc"        # optional; defaults to the first target
    sources  = ["harness.c"]       # relative to this file
    include  = ["include"]         # optional extra -I directories
    ldflags  = ["-lm"]             # optional; default ["-lm"]

    [[target]]
    name   = "x86_64-gcc"
    cc     = "gcc"
    cflags = ["-O2"]

    [[target]]
    name   = "aarch64-gcc"
    cc     = "aarch64-linux-gnu-gcc"
    cflags = ["-O2", "-static"]
    runner = ["qemu-aarch64-static"]   # optional; how to run the binary
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.9 and 3.10
    import tomli as tomllib

DEFAULT_NAME = "fpparity.toml"


class ConfigError(ValueError):
    pass


@dataclass
class Target:
    name: str
    cc: str
    cflags: List[str] = field(default_factory=list)
    ldflags: Optional[List[str]] = None
    runner: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    root: Path
    sources: List[Path]
    include: List[Path]
    ldflags: List[str]
    baseline: str
    targets: List[Target]

    def target(self, name: str) -> Target:
        for t in self.targets:
            if t.name == name:
                return t
        raise ConfigError("no target named {!r}".format(name))

    def ldflags_for(self, target: Target) -> List[str]:
        return list(self.ldflags if target.ldflags is None else target.ldflags)


def _strings(table: Dict[str, Any], key: str, where: str, default: Optional[List[str]] = None) -> List[str]:
    value = table.get(key, default)
    if value is None:
        raise ConfigError("{}: '{}' is required".format(where, key))
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ConfigError("{}: '{}' must be a list of strings".format(where, key))
    return list(value)


def _target(raw: Any, index: int) -> Target:
    where = "target #{}".format(index + 1)
    if not isinstance(raw, dict):
        raise ConfigError("{}: must be a table".format(where))
    name = raw.get("name")
    cc = raw.get("cc")
    if not isinstance(name, str) or not name:
        raise ConfigError("{}: 'name' must be a non-empty string".format(where))
    if not isinstance(cc, str) or not cc:
        raise ConfigError("{} ({}): 'cc' must be a non-empty string".format(where, name))
    env = raw.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ConfigError("{} ({}): 'env' must be a table of strings".format(where, name))
    ldflags = raw.get("ldflags")
    return Target(
        name=name,
        cc=cc,
        cflags=_strings(raw, "cflags", where, []),
        ldflags=None if ldflags is None else _strings(raw, "ldflags", where),
        runner=_strings(raw, "runner", where, []),
        env=dict(env),
    )


def from_dict(data: Dict[str, Any], root: Path, require_sources: bool = True) -> Config:
    raw_targets = data.get("target")
    if not isinstance(raw_targets, list) or len(raw_targets) < 2:
        raise ConfigError("at least two [[target]] tables are needed to compare anything")
    targets = [_target(t, i) for i, t in enumerate(raw_targets)]
    names = [t.name for t in targets]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ConfigError("target names must be unique: {}".format(", ".join(duplicates)))

    baseline = data.get("baseline", targets[0].name)
    if baseline not in names:
        raise ConfigError("baseline {!r} is not one of the targets: {}".format(baseline, ", ".join(names)))

    sources = [root / s for s in _strings(data, "sources", "config", [] if not require_sources else None)]
    if require_sources:
        missing = [str(s) for s in sources if not s.is_file()]
        if missing:
            raise ConfigError("source not found: {}".format(", ".join(missing)))
    include = [root / p for p in _strings(data, "include", "config", [])]
    return Config(
        root=root,
        sources=sources,
        include=include,
        ldflags=_strings(data, "ldflags", "config", ["-lm"]),
        baseline=baseline,
        targets=targets,
    )


def load(path: Path, require_sources: bool = True) -> Config:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError("{} not found (run 'fp-parity init' to write one)".format(path))
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("{}: {}".format(path, exc))
    return from_dict(data, path.resolve().parent, require_sources=require_sources)
