"""Daily per-sensor temperature summaries from the raw 10-second readings.

Usage:
    python src/daily_summary.py RAW_CSV DESPIKE OUT_CSV

RAW_CSV  the raw dump: columns time (ISO 8601, UTC), sensor, temp_c, battery_v
DESPIKE  an option of the `despike` decision in astra.yaml:
           none      keep every reading
           median3c  drop a reading more than 3 degC from the median of the
                     31 readings centred on it (5 minutes at 10 s), computed
                     per sensor within each unbroken run of readings
OUT_CSV  one row per sensor per UTC day that has readings:
           date, sensor, n_readings, mean_c, min_c, max_c, std_c, n_removed
         n_readings counts the readings summarised (after despiking);
         n_removed counts the readings despiking dropped (always 0 for none);
         std_c is the sample standard deviation (ddof = 1).
"""

from __future__ import annotations

import sys

import polars as pl

#: Readings are every 10 s; a longer step starts a new run, so the rolling
#: median never reaches across a gap in a sensor's record.
STEP_S = 10

#: The rolling median's window, in readings: 5 minutes, centred.
WINDOW = 31

#: How far, in degC, a reading may sit from its rolling median and be kept.
THRESHOLD_C = 3.0

DESPIKE = ("none", "median3c")


def load(path: str) -> pl.DataFrame:
    """Read the dump, one row per reading, ordered by sensor then time."""
    return (
        pl.scan_csv(
            path,
            schema={
                "time": pl.String,
                "sensor": pl.String,
                "temp_c": pl.Float64,
                "battery_v": pl.Float64,
            },
        )
        .select(
            pl.col("time").str.to_datetime("%Y-%m-%dT%H:%M:%SZ", time_unit="ms", time_zone="UTC"),
            pl.col("sensor").cast(pl.Categorical),
            "temp_c",
        )
        .sort(["sensor", "time"], maintain_order=True)
        .collect()
    )


def flag_spikes(df: pl.DataFrame, despike: str) -> pl.DataFrame:
    """Add a boolean `spike` column: the readings `despike` drops."""
    if despike == "none":
        return df.with_columns(spike=pl.lit(False))
    run = (
        (pl.col("time").diff().dt.total_seconds() != STEP_S)
        .fill_null(True)
        .cum_sum()
        .over("sensor")
    )
    median = (
        pl.col("temp_c")
        .rolling_median(WINDOW, center=True, min_samples=1)
        .over(["sensor", "run"])
    )
    return (
        df.with_columns(run=run)
        .with_columns(spike=(pl.col("temp_c") - median).abs() > THRESHOLD_C)
        .drop("run")
    )


def summarise(df: pl.DataFrame) -> pl.DataFrame:
    """One row per sensor per UTC day."""
    kept = pl.col("temp_c").filter(~pl.col("spike"))
    return (
        df.group_by(pl.col("time").dt.date().alias("date"), "sensor")
        .agg(
            n_readings=kept.len(),
            mean_c=kept.mean(),
            min_c=kept.min(),
            max_c=kept.max(),
            std_c=kept.std(ddof=1),
            n_removed=pl.col("spike").sum(),
        )
        .with_columns(pl.col("sensor").cast(pl.String))
        .sort(["date", "sensor"])
    )


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in DESPIKE:
        print(__doc__, file=sys.stderr)
        return 2
    raw, despike, out = argv
    summary = summarise(flag_spikes(load(raw), despike))
    # Six decimals: far below the 0.01 degC the sensors report, and fixed, so a
    # rerun writes the same bytes whatever order the threads summed in.
    summary.write_csv(out, float_precision=6)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
