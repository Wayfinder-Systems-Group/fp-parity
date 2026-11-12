/*
 * Bundled probe for fp-parity.
 *
 * One value per known source of cross-platform floating-point difference.
 * Every input is read from a volatile, so the compiler cannot fold the
 * arithmetic at build time: each result is computed at run time, on the
 * target, by the code the target's compiler generated. A value folded at
 * build time would be computed by the host compiler and would hide exactly
 * the differences this probe exists to show.
 *
 * Name prefixes group the values by cause:
 *   contract.   a multiply and an add fused into one rounding (FMA)
 *   eval.       intermediates kept wider than their declared type
 *   sum.        an arithmetic chain reordered
 *   libm.       math library functions that IEEE 754 does not pin down
 *   ieee.       operations IEEE 754 requires to be correctly rounded
 *   subnormal.  values below the normal range (flush-to-zero)
 *   convert.    narrowing and rounding conversions
 *   text.       the C library's conversion between decimal text and double
 *               (strtod, printf %f/%e/%g); the C standard does not require
 *               either to round correctly, and QNX 8.0's libc measurably
 *               differs from glibc on both
 */
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "fpparity.h"

static volatile double in_a = 0.1;
static volatile double in_b = 10.0;
static volatile double in_c = -1.0;
static volatile double in_x = 0.7;
static volatile double in_big = 1e22;
static volatile double in_max = DBL_MAX;
static volatile double in_dmin = DBL_MIN;
static volatile float in_fmin = FLT_MIN;
static volatile double in_half_scale = 0.5;
static volatile double in_two_and_half = 2.5;
static volatile float in_fa = 0.1f;
static volatile float in_fb = 10.0f;
static volatile float in_fc = -1.0f;
static volatile double terms[8] = {1e16, 1.0, -1e16, 1.0, 3.0e-17, 0.5, 1e-3, -0.25};
static volatile int n_terms = 8;

/* text.: decimal tokens that sit at or near a rounding boundary, so a parser
   that is not correctly rounded lands one ulp off. Read through volatile
   storage so the compiler cannot evaluate strtod at build time. */
static volatile const char *const tokens[] = {
    "2.2250738585072011e-308",   /* the classic hard case near DBL_MIN */
    "2.4703282292062328e-324",   /* just above half the smallest subnormal */
    "9007199254740993",          /* 2^53 + 1: an exact tie, rounds to even */
    "1.00000000000000011102230246251565404236316680908203125", /* tie above 1 */
    "7.038531e-26",
    "864834083.165500044823",    /* long expansions in the 7.9e7..8.7e8 band */
    "87402596.513749986887",
};
#define N_TOKENS ((int)(sizeof tokens / sizeof tokens[0]))

/* Large values whose %.12f expansion is long: the band where one C library
   was measured printing the last digit one low. */
static volatile double fmt_values[] = {
    864834083.165500044823, 87402596.513749986887, 79475591.683449998498,
    739731050.611500024796, 406308110.065500020981, 686311477.133499979973,
};
#define N_FMT ((int)(sizeof fmt_values / sizeof fmt_values[0]))

static double parse_token(int i)
{
    char buf[96];
    const volatile char *src = tokens[i];
    size_t k = 0;
    while (src[k] != '\0' && k + 1 < sizeof buf) {
        buf[k] = src[k];
        k++;
    }
    buf[k] = '\0';
    return strtod(buf, NULL);
}

/* An exact digest of the printed text: every character folded into an
   integer below 2^32, so the double holding it is exact and any changed
   character changes the bits. */
static double text_digest(const char *fmt)
{
    unsigned long h = 5381u;
    char buf[128];
    for (int i = 0; i < N_FMT; i++) {
        snprintf(buf, sizeof buf, fmt, fmt_values[i]);
        for (const char *p = buf; *p; p++) {
            h = (h * 33u + (unsigned char)*p) & 0xffffffffu;
        }
        h = (h * 33u + '\n') & 0xffffffffu;
    }
    return (double)h;
}

int main(void)
{
    double a = in_a, x = in_x;

    /* contract.: with FMA, a*b - a*b becomes fma(a, b, -(a*b)), which returns
       the rounding error of a*b instead of zero. Each expression reads the
       volatiles itself: if a*b were computed once into a local and reused,
       the compiler would share the product and there would be nothing left
       to fuse, hiding the very difference this probe looks for. */
    fpp_emit_d("contract.mul_add", in_a * in_b + in_c);
    fpp_emit_d("contract.residual", in_a * in_b - in_a * in_b);
    fpp_emit_f("contract.f32_mul_add", in_fa * in_fb + in_fc);
    fpp_emit_f("contract.f32_residual", in_fa * in_fb - in_fa * in_fb);

    /* eval.: FLT_EVAL_METHOD reports how the compiler evaluates intermediates.
       DBL_MAX * 2 / 2 overflows to infinity in double, and survives as DBL_MAX
       when the intermediate is held in a wider register. */
    fpp_emit_d("eval.flt_eval_method", (double)FLT_EVAL_METHOD);
    fpp_emit_d("eval.overflow_roundtrip", in_max * 2.0 / 2.0);

    /* sum.: source order is fixed; a compiler allowed to reassociate (for
       example to vectorize) can add these in another order. */
    {
        double s = 0.0;
        for (int i = 0; i < n_terms; i++) {
            s += terms[i];
        }
        fpp_emit_d("sum.forward", s);
    }

    /* libm.: IEEE 754 does not require these to be correctly rounded, and
       math libraries differ in their last bit. */
    fpp_emit_d("libm.sin_large", sin(in_big));
    fpp_emit_d("libm.cos", cos(x));
    fpp_emit_d("libm.exp", exp(x));
    fpp_emit_d("libm.log", log(x));
    fpp_emit_d("libm.pow", pow(1.0 + x, 37.25));
    fpp_emit_d("libm.tanh", tanh(x));
    fpp_emit_d("libm.atan2", atan2(x, -a));
    fpp_emit_d("libm.cbrt", cbrt(x));
    fpp_emit_d("libm.expm1", expm1(x * 1e-8));
    fpp_emit_d("libm.lgamma", lgamma(x + 10.0));

    /* ieee.: these must match bit for bit everywhere; a difference here
       points at the hardware or at a non-conforming build. */
    fpp_emit_d("ieee.sqrt", sqrt(x));
    fpp_emit_d("ieee.div", a / x);

    /* subnormal.: half of the smallest normal is subnormal; a target that
       flushes subnormals to zero returns 0. */
    fpp_emit_d("subnormal.half_min", in_dmin * in_half_scale);
    fpp_emit_f("subnormal.f32_half_min", in_fmin * (float)in_half_scale);

    /* convert.: narrowing to float, and round-half-to-even in the current
       rounding mode. */
    fpp_emit_d("convert.f32_round", (double)(float)x);
    fpp_emit_d("convert.nearbyint_half", nearbyint(in_two_and_half));

    /* text.: parse each token with strtod, and digest the printf output for
       three float formats over the long-expansion values. */
    {
        static const char *const names[] = {
            "text.strtod_dbl_min", "text.strtod_half_subnormal", "text.strtod_tie_2p53",
            "text.strtod_tie_above_1", "text.strtod_short", "text.strtod_long_1", "text.strtod_long_2",
        };
        for (int i = 0; i < N_TOKENS; i++) {
            fpp_emit_d(names[i], parse_token(i));
        }
    }
    fpp_emit_d("text.printf_f12", text_digest("%.12f"));
    fpp_emit_d("text.printf_e17", text_digest("%.17e"));
    fpp_emit_d("text.printf_g17", text_digest("%.17g"));

    return 0;
}
