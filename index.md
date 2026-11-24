# sensor-archive

Archive of the 2023 readings of the city's network of 40 low-cost temperature
sensors, and daily summaries made from them. The analysis is specified in
`astra.yaml` (ASTRA 0.1) and run with lightcone-cli (`lc`).

## Data

`data/sensor-dump-2023.csv` is the raw delivery: one row every 10 seconds per
sensor for all of 2023, with columns `time` (ISO 8601, UTC), `sensor`
(`s01` to `s40`), `temp_c` and `battery_v`. It is under version control with
git-annex: git holds a pointer whose key is the file's SHA-256, the checksum
the delivery's `SHA256SUMS` lists, so any copy can be checked against it.

The bytes themselves are neither in this repository nor on GitHub. They stay
where they were delivered (`lc-trial/incoming/`), which git-annex knows as a
`file://` URL, so on the machine that holds the delivery `lc fetch sensor_dump`
brings them in.

## Methods

`src/daily_summary.py` summarises each sensor's readings per UTC day: the
number of readings, their mean, minimum, maximum and sample standard deviation
(ddof = 1), plus how many readings despiking dropped.

The raw readings contain occasional spikes: isolated single readings far from
their neighbours. Whether to remove them is the `despike` decision, and
both answers are built, one per universe:

- `raw` (`despike: none`): every reading is summarised.
- `despiked` (`despike: median3c`): a reading more than 3 °C from the median
  of the 31 readings centred on it (5 minutes) is dropped. The median is
  taken per sensor within each unbroken run of readings, never across a gap.

A Hampel filter based on the median absolute deviation was considered and
excluded. Its reason is recorded in `astra.yaml`.

The network's gateways apply the same despiking to live readings with a C
library, `despike/`, which has no Python dependency. The archive itself keeps
despiking in polars. `tests/test_despike_c.py` checks that the C library
flags exactly the readings the archive flags. Run on every reading of the
2023 dump, the two agree on all of them.

`src/daily_battery.py` summarises each sensor's battery voltage per UTC day,
to locate battery swaps: the number of readings, their mean, minimum and
maximum, the day's first and last readings, and `rise_v`, the largest rise
from the sensor's previous reading to one of the day's readings. Between swaps
the voltage only falls, in 0.01 V steps, so a swap is a row with `rise_v`
above 0. A rise across midnight or across a gap in the record counts on the
day of the later reading. 3.35 V is the lowest value the sensors report, so a
reading of 3.35 V may stand for less. Despiking concerns temperature only, so
this summary is made once rather than per universe.

## Results

| File | Universe |
|---|---|
| `results/raw/daily_summary.csv` | not despiked |
| `results/despiked/daily_summary.csv` | despiked |
| `results/daily_battery.csv` | made once |

The two temperature summaries have the columns
`date, sensor, n_readings, mean_c, min_c, max_c, std_c, n_removed`; the
battery summary has `date, sensor, n_readings, mean_v, min_v, max_v, first_v,
last_v, rise_v`. All three have one row per sensor per UTC day with readings:
days a sensor recorded nothing are absent rather than empty.

The swaps are the battery summary's rows with `rise_v` above 0, for example:

```sh
awk -F, 'NR == 1 || $9 > 0' results/daily_battery.csv
```

## Maintaining the archive

`lc materialize` fetches the raw bytes into this clone to remake a summary.
Drop that copy again before publishing (`git annex drop
data/sensor-dump-2023.csv`): `lc publish` sends every annexed file whose
bytes this clone holds to the project's data store, and the raw dump is not
meant to go there.

The tests run with `uv run --with pytest --with numpy pytest tests/`. They
need a C compiler on `PATH` to test `despike/`. Setting `DESPIKE_RAW_CSV` to
the raw dump's path also compares the C library with the archive on every
reading. pytest and numpy are kept out of `pyproject.toml` on purpose: lc
takes `uv.lock` as the environment the results were made under, so adding a
dependency there marks every result as behind.
