/*
 * fpparity.h: emit floating-point results as exact bit patterns.
 *
 * Each call prints one line on stdout:
 *
 *     <name> TAB f64 TAB <16 hex digits>
 *     <name> TAB f32 TAB <8 hex digits>
 *
 * fp-parity reads only lines in this shape, so a harness can print anything
 * else alongside them. Bits are copied with memcpy, never through a union or a
 * pointer cast, so the value printed is the value the program computed and the
 * read is defined behavior in C and C++.
 */
#ifndef FPPARITY_H
#define FPPARITY_H

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static inline void fpp_emit_d(const char *name, double value)
{
    uint64_t bits;
    memcpy(&bits, &value, sizeof bits);
    printf("%s\tf64\t%016" PRIx64 "\n", name, bits);
}

static inline void fpp_emit_f(const char *name, float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof bits);
    printf("%s\tf32\t%08" PRIx32 "\n", name, bits);
}

#define FPP_EMIT_D(name, value) fpp_emit_d((name), (value))
#define FPP_EMIT_F(name, value) fpp_emit_f((name), (value))

#endif /* FPPARITY_H */
