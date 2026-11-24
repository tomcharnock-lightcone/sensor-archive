"""Daily per-sensor battery-voltage summaries, to locate battery swaps.

Usage:
    python src/daily_battery.py RAW_CSV OUT_CSV

RAW_CSV  the raw dump: columns time (ISO 8601, UTC), sensor, temp_c, battery_v
OUT_CSV  one row per sensor per UTC day that has readings:
           date, sensor, n_readings, mean_v, min_v, max_v, first_v, last_v,
           rise_v
         first_v and last_v are the day's first and last readings;
         rise_v is the largest rise from the sensor's previous reading to one
         of the day's readings, so a rise across midnight or across a gap in
         the record counts on the day of the later reading. It is 0 when the
         voltage did not rise. Between swaps the voltage only falls, so the
         rows with rise_v > 0 are where batteries were swapped.
"""

from __future__ import annotations

import sys

import polars as pl


def load(path: str) -> pl.DataFrame:
    """Read the dump's voltages, one row per reading, ordered by sensor then time."""
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
            "battery_v",
        )
        .sort(["sensor", "time"], maintain_order=True)
        .collect()
    )


def summarise(df: pl.DataFrame) -> pl.DataFrame:
    """One row per sensor per UTC day."""
    rise = pl.col("battery_v").diff().over("sensor").fill_null(0).clip(lower_bound=0)
    v = pl.col("battery_v")
    return (
        df.with_columns(rise=rise)
        .group_by(pl.col("time").dt.date().alias("date"), "sensor")
        .agg(
            n_readings=pl.len(),
            mean_v=v.mean(),
            min_v=v.min(),
            max_v=v.max(),
            first_v=v.first(),
            last_v=v.last(),
            rise_v=pl.col("rise").max(),
        )
        .with_columns(pl.col("sensor").cast(pl.String))
        .sort(["date", "sensor"])
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    raw, out = argv
    # Six decimals, as in daily_summary.py: far below the 0.01 V the sensors
    # report, and fixed, so a rerun writes the same bytes.
    summarise(load(raw)).write_csv(out, float_precision=6)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
