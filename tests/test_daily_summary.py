"""Tests for the despike options of src/daily_summary.py."""

import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import daily_summary as ds  # noqa: E402

#: One sensor's unbroken run of 41 readings at 15.00 degC, but for one
#: reading 1.50 degC off its median and one 4.00 degC off.
TEMPS = [15.0] * 41
TEMPS[10] = 16.5
TEMPS[30] = 19.0


def flags(despike: str) -> list[int]:
    df = pl.DataFrame(
        {
            "time": [10_000 * i for i in range(len(TEMPS))],
            "sensor": ["s01"] * len(TEMPS),
            "temp_c": TEMPS,
        }
    ).with_columns(pl.col("time").cast(pl.Datetime("ms", "UTC")), pl.col("sensor").cast(pl.Categorical))
    spike = ds.flag_spikes(df, despike)["spike"]
    return [i for i, s in enumerate(spike) if s]


@pytest.mark.parametrize(
    ("despike", "dropped"),
    [("none", []), ("median3c", [30]), ("median1c", [10, 30])],
)
def test_each_option_drops_the_readings_beyond_its_threshold(despike, dropped):
    assert flags(despike) == dropped


def test_every_option_is_accepted_on_the_command_line():
    assert ds.DESPIKE == ("none", "median3c", "median1c")
