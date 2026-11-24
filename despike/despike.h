/*
 * despike: the sensor network's despiking filter, for the gateways.
 *
 * A reading is a spike when it lies more than 3 degC from the median of the
 * 31 readings centred on it (15 before, itself, 15 after), taken within its
 * run: a sensor's unbroken sequence of readings 10 s apart. Any other step
 * between two readings (a gap, a repeat, a step back) ends the run, and the
 * window is cut at the run's ends, so near them it holds fewer readings.
 * The median of an even number of readings is lo + (hi - lo) * 0.5 of the
 * middle two.
 *
 * This is the `median3c` option of the archive's `despike` decision, and it
 * gives the archive's verdicts bit for bit: tests/test_despike_c.py checks it
 * against the archive's implementation (src/daily_summary.py).
 *
 * Use one despike_state per sensor and push its readings in the order they
 * were taken. A reading can only be judged once the 15 after it have
 * arrived, or once its run has ended, so verdicts come out up to 15 readings
 * (150 s) late, always in the order the readings went in. When a sensor's
 * stream ends, call despike_flush for the readings still waiting.
 *
 * C99, standard library only, no heap allocation. Readings must be finite.
 */
#ifndef DESPIKE_H
#define DESPIKE_H

#include <stddef.h>
#include <stdint.h>

#define DESPIKE_STEP_S 10      /* seconds between readings within a run */
#define DESPIKE_HALF 15        /* readings either side of the one judged */
#define DESPIKE_WINDOW 31      /* 2 * DESPIKE_HALF + 1 */
#define DESPIKE_THRESHOLD_C 3.0

/* Most verdicts one call to despike_push or despike_flush returns. */
#define DESPIKE_MAX_VERDICTS DESPIKE_HALF

typedef struct {
    int64_t time_s; /* the reading's time, in whole seconds */
    double temp_c;  /* the reading */
    int spike;      /* 1 if the filter drops it, 0 if it keeps it */
} despike_verdict;

/* One sensor's state. Treat as opaque; it is a plain struct so it can live
 * on the stack or in a static array. */
typedef struct {
    int64_t last_time_s;
    size_t run_len; /* readings of the current run pushed so far */
    size_t decided; /* readings of the current run already judged */
    int64_t time_s[DESPIKE_WINDOW]; /* reading k of the run at k % DESPIKE_WINDOW */
    double temp_c[DESPIKE_WINDOW];
} despike_state;

/* Start a sensor's state with no readings. */
void despike_init(despike_state *s);

/* Push the sensor's next reading. Writes the verdicts that became decidable
 * to out, which must hold DESPIKE_MAX_VERDICTS, and returns how many. */
size_t despike_push(despike_state *s, int64_t time_s, double temp_c, despike_verdict *out);

/* End the current run: judge every reading still waiting, write their
 * verdicts to out (room for DESPIKE_MAX_VERDICTS) and return how many. The
 * next push starts a new run, whatever its time, so call this only when the
 * run has really ended, such as at the end of the stream. */
size_t despike_flush(despike_state *s, despike_verdict *out);

/* Judge n readings of one sensor, in the order taken, in one call: sets
 * spike[i] to 1 if reading i is a spike, else 0. Returns n. */
size_t despike_batch(const int64_t *time_s, const double *temp_c, size_t n, unsigned char *spike);

/* sizeof(despike_state) and DESPIKE_MAX_VERDICTS, for callers through an FFI. */
size_t despike_state_size(void);
size_t despike_max_verdicts(void);

#endif
