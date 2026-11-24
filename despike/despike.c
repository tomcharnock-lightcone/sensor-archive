/* despike: see despike.h. */
#include "despike.h"

#include <float.h>
#include <math.h>

/* Bit-identical verdicts need every double operation rounded to double, as
 * on x86-64 and ARM. On 32-bit x86 compile with -msse2 -mfpmath=sse. */
#if defined(FLT_EVAL_METHOD) && FLT_EVAL_METHOD != 0
#error "despike needs FLT_EVAL_METHOD == 0 (on 32-bit x86: -msse2 -mfpmath=sse)"
#endif
/* -ffast-math may rewrite lo + (hi - lo) * 0.5 as (lo + hi) * 0.5, which
 * changes verdicts. */
#ifdef __FAST_MATH__
#error "despike must not be compiled with -ffast-math"
#endif

void despike_init(despike_state *s)
{
    s->last_time_s = 0;
    s->run_len = 0;
    s->decided = 0;
}

/* Median of the run's readings first..last (inclusive, at most
 * DESPIKE_WINDOW of them, all still in the ring). */
static double window_median(const despike_state *s, size_t first, size_t last)
{
    double v[DESPIKE_WINDOW];
    size_t n = 0;
    for (size_t k = first; k <= last; k++) {
        double x = s->temp_c[k % DESPIKE_WINDOW];
        size_t j = n++;
        while (j > 0 && v[j - 1] > x) {
            v[j] = v[j - 1];
            j--;
        }
        v[j] = x;
    }
    if (n % 2 == 1)
        return v[n / 2];
    double lo = v[n / 2 - 1], hi = v[n / 2];
    return lo + (hi - lo) * 0.5;
}

/* Judge the run's next waiting reading; last is the run's last reading the
 * window may reach. */
static despike_verdict judge_next(despike_state *s, size_t last)
{
    size_t i = s->decided++;
    size_t first = i > DESPIKE_HALF ? i - DESPIKE_HALF : 0;
    if (last > i + DESPIKE_HALF)
        last = i + DESPIKE_HALF;
    despike_verdict v;
    v.time_s = s->time_s[i % DESPIKE_WINDOW];
    v.temp_c = s->temp_c[i % DESPIKE_WINDOW];
    v.spike = fabs(v.temp_c - window_median(s, first, last)) > DESPIKE_THRESHOLD_C;
    return v;
}

size_t despike_flush(despike_state *s, despike_verdict *out)
{
    size_t n = 0;
    while (s->decided < s->run_len)
        out[n++] = judge_next(s, s->run_len - 1);
    s->run_len = 0;
    s->decided = 0;
    return n;
}

size_t despike_push(despike_state *s, int64_t time_s, double temp_c, despike_verdict *out)
{
    size_t n = 0;
    /* Unsigned, so a far-off time cannot overflow the subtraction. */
    if (s->run_len > 0 && (uint64_t)time_s - (uint64_t)s->last_time_s != DESPIKE_STEP_S)
        n = despike_flush(s, out);
    size_t k = s->run_len++;
    s->time_s[k % DESPIKE_WINDOW] = time_s;
    s->temp_c[k % DESPIKE_WINDOW] = temp_c;
    s->last_time_s = time_s;
    if (k >= DESPIKE_HALF)
        out[n++] = judge_next(s, k);
    return n;
}

size_t despike_batch(const int64_t *time_s, const double *temp_c, size_t n, unsigned char *spike)
{
    despike_state s;
    despike_verdict v[DESPIKE_MAX_VERDICTS];
    size_t done = 0;
    despike_init(&s);
    for (size_t i = 0; i < n; i++) {
        size_t got = despike_push(&s, time_s[i], temp_c[i], v);
        for (size_t j = 0; j < got; j++)
            spike[done++] = (unsigned char)v[j].spike;
    }
    size_t got = despike_flush(&s, v);
    for (size_t j = 0; j < got; j++)
        spike[done++] = (unsigned char)v[j].spike;
    return done;
}

size_t despike_state_size(void) { return sizeof(despike_state); }
size_t despike_max_verdicts(void) { return DESPIKE_MAX_VERDICTS; }
