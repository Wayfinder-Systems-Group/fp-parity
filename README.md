# fp-parity

The same C or C++ numeric code can produce different bits on different
compilers, flags, and CPU architectures. A multiply and an add fused into one
rounding on one target and not the other, an intermediate held wider than its
type, a reordered sum, a math library that rounds its last bit differently.
Each one is a few ulps. Each one breaks a replay, a golden-file test, a
lockstep simulation, or a claim that two builds compute the same thing.

fp-parity builds your harness for every target you list, runs each one,
compares every value bit for bit against a baseline, and with `--explain`
names the cause of each difference by rebuilding with one flag changed at a
time.

```
$ fp-parity probe --explain
fp-parity 0.1.0: baseline native-gcc, 23 values

aarch64-gcc: 4 of 23 values differ
  contract.residual            different bits
      baseline 0x0000000000000000 (0.0)
      target   0x3c90000000000000 (5.551115123125783e-17)
  ...
  cause:
    -ffp-contract=off on this target removes contract.mul_add, contract.residual, ...:
    FMA contraction: a multiply and an add were fused into one rounding
```

That is GCC on x86-64 against GCC on aarch64, run under qemu: the aarch64
compiler fuses `a*b + c` into one `fmadd` by default, and the x86-64 build
without `-mfma` cannot.

## Install

```sh
pip install fp-parity
```

Python 3.9 or newer. The compilers are yours: fp-parity calls whatever `cc`
each target names, and runs the result directly or through a `runner` such as
`qemu-aarch64-static` or `ssh`.

## Two ways to use it

**Probe a toolchain.** `fp-parity probe` builds a bundled probe that emits one
value per known source of difference (FMA contraction, excess precision,
reassociation, math library functions, subnormals, conversions) for every
target. With no config file it uses the compilers it finds on the machine.

**Check your own code.** Write a small harness that calls your numeric code
and emits each result with `fpparity.h`, list your targets in
`fpparity.toml`, and run `fp-parity check`.

```c
#include "fpparity.h"   /* fp-parity include-dir prints its location */
#include "filter.h"

int main(void) {
    FPP_EMIT_D("filter.step_1", filter_step(1.0));
    FPP_EMIT_F("filter.gain", filter_gain());
    return 0;
}
```

Read inputs from `volatile` variables or from a file, not from constants. A
value the compiler folds at build time is computed by the host, not the
target, and hides the difference you are looking for.

## Configuration

`fp-parity init` writes a starter `fpparity.toml` from the compilers it finds.

```toml
baseline = "x86_64-gcc"      # optional; defaults to the first target
sources  = ["harness.c", "filter.c"]
include  = ["include"]       # optional extra -I directories
ldflags  = ["-lm"]           # optional; default ["-lm"]

[[target]]
name   = "x86_64-gcc"
cc     = "gcc"
cflags = ["-O2"]

[[target]]
name   = "aarch64-gcc"
cc     = "aarch64-linux-gnu-gcc"
cflags = ["-O2", "-static"]
runner = ["qemu-aarch64-static"]

[[target]]
name   = "qnx-aarch64"
cc     = "qcc"
cflags = ["-Vgcc_ntoaarch64le", "-O2"]
runner = ["ssh", "qnx-target", "--"]
```

A target may also set its own `ldflags` and an `env` table.

## What `--explain` tries

For each difference, fp-parity rebuilds with one flag added to the target,
the baseline, or both, and reports the first flag that makes the value match.
Flags run from most to least specific, so each difference is attributed to
its narrowest cause.

| Flag | Cause it identifies |
|---|---|
| `-ffp-contract=off` | FMA contraction |
| `-fexcess-precision=standard`, `-ffloat-store` | intermediates kept wider than their type |
| `-fno-fast-math` | value-changing optimizations |
| `-fno-associative-math` | a reordered arithmetic chain |
| `-O0` | an optimization pass changed the arithmetic |

A difference no flag removes is reported as a math library or hardware
difference. A flag a compiler rejects is skipped and listed.

## How values are compared

Every value is compared as a bit pattern. Signed zeros are always reported.
Two NaNs with different payload bits count as equal unless `--strict-nan` is
passed, because payloads differ between CPUs for the same operation and are
rarely meaningful. Finite differences are reported with their distance in
ulps.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | every target matched the baseline bit for bit |
| 1 | at least one value differs |
| 2 | usage, configuration, or build error |

`--json PATH` also writes the report as JSON, for CI.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The most useful contribution is a
probe for a source of difference the bundled probe does not yet cover.

## License

Apache License 2.0. Maintained by [Wayfinder Systems Group](https://wayfindersystemsgroup.com).
