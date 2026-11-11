# Contributing

## The bar

A change is welcome when it catches a real source of cross-platform
floating-point difference, names a cause more precisely, or removes noise
that would get this tool turned off in someone's CI.

The most useful contribution is a probe for a source of difference the
bundled probe does not yet cover: a compiler, a flag, an instruction set, or a
math library that changes bits in a way no current probe shows.

## Ground rules

1. **A new probe arrives with the targets that disagree on it.** Name the
   two toolchains and the flags, and show the two bit patterns. If you cannot
   reproduce it, open an issue and describe the code and the targets.
2. **Inputs come from volatiles.** A probe value the compiler can fold at
   build time is computed by the host and proves nothing about the target.
3. **No runtime dependencies beyond the standard library.** The tool runs
   inside other people's build systems.
4. **Exit codes are the interface.** 0 identical, 1 a value differs, 2 usage,
   configuration, or build error. Do not add a fourth meaning to an existing
   code.

## Running the tests

```sh
pip install -e ".[dev]"
pytest -q
```

Tests that need a toolchain skip when it is missing. The full suite runs on a
Linux x86-64 machine with `gcc`, `aarch64-linux-gnu-gcc`, and
`qemu-aarch64-static`, which is what CI installs.

## Reporting a wrong result

A difference reported where the bits match, or a match reported where they
differ, is the most serious bug this tool can have. Include the harness, the
config, both toolchain versions, and `fp-parity --version`.

## Security

Do not open a public issue for a security report. Email
JonathanLuethke@WayfinderSystemsGroup.com.
