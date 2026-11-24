# despike

The network's despiking filter in C, for the gateways. It makes the same
decision as the archive's `despike: median3c` option, reading for reading.

## The rule

A reading is a spike when it lies more than 3 °C from the median of the 31
readings centred on it: 15 before, itself and 15 after. The window only spans
the reading's **run**, a sensor's unbroken sequence of readings 10 s apart.
Any other step between two readings (a gap, a repeated time, a step back)
ends the run, and near a run's ends the window is cut short. The median of
an even number of readings is `lo + (hi - lo) * 0.5` of the middle two.

## Same verdicts as the archive

The archive despikes in polars (`flag_spikes` in `src/daily_summary.py`).
`tests/test_despike_c.py` compiles this library and checks that it flags
exactly the readings the archive flags. It covers:

- hand-made runs of every awkward length
- gaps and repeated times
- readings right at the 3 °C line
- 120,000 random readings

With `DESPIKE_RAW_CSV` set, it also covers every reading of the 2023 dump:

```sh
uv run --with pytest --with numpy pytest tests/
DESPIKE_RAW_CSV=/path/to/sensor-dump-2023.csv uv run --with pytest --with numpy pytest tests/
```

## Building

`despike.c` and `despike.h` are C99 and use only the standard library, with
no heap allocation. Build them with any optimisation level, under three
conditions:

- **Don't use `-ffast-math`.** It can change verdicts, so the file refuses to
  compile with it.
- **Double arithmetic must round to double.** That is already the case on
  x86-64 and ARM. On 32-bit x86, add `-msse2 -mfpmath=sse`; the file refuses
  to compile otherwise.
- **Link with `-lm`.**

```sh
cc -std=c99 -O2 -c despike.c
```

## Use

Keep one `despike_state` per sensor and push its readings in the order they
were taken. Times are whole seconds and readings must be finite.

A reading can only be judged once the 15 readings after it have arrived, or
once its run has ended. So verdicts come out up to 150 s late, in the order
the readings went in. A reading that ends a run releases the verdicts of the
run before it.

```c
#include "despike.h"

despike_state s;
despike_verdict out[DESPIKE_MAX_VERDICTS];
despike_init(&s);

/* for each reading of the sensor, in order: */
size_t n = despike_push(&s, time_s, temp_c, out);
for (size_t i = 0; i < n; i++)
    handle(out[i].time_s, out[i].temp_c, out[i].spike);

/* when the sensor's stream ends: */
n = despike_flush(&s, out);
```

Only call `despike_flush` when the run has really ended. The next push
always starts a new run, so a reading that would have continued the run
would then get different verdicts from the archive. `despike_batch` judges a
whole array of one sensor's readings in one call.
