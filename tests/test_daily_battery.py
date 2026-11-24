"""Tests for src/daily_battery.py, run as the recipe runs it: a CSV in, a CSV out."""

import csv
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "src" / "daily_battery.py"

HEADER = "time,sensor,temp_c,battery_v"

#: Deliberately out of order. s01 is swapped across midnight (3.50 -> 3.95);
#: s02 is swapped during a six-hour gap in its record (3.85 -> 3.95).
ROWS = [
    "2023-01-02T00:00:00Z,s01,5.0,3.95",
    "2023-01-01T00:00:00Z,s01,5.0,3.52",
    "2023-01-01T00:00:10Z,s01,5.0,3.51",
    "2023-01-01T23:59:50Z,s01,5.0,3.50",
    "2023-01-01T00:00:00Z,s02,5.0,3.85",
    "2023-01-01T00:00:10Z,s02,5.0,3.85",
    "2023-01-01T06:00:00Z,s02,5.0,3.95",
    "2023-01-01T06:00:10Z,s02,5.0,3.94",
]

EXPECTED = """\
date,sensor,n_readings,mean_v,min_v,max_v,first_v,last_v,rise_v
2023-01-01,s01,3,3.510000,3.500000,3.520000,3.520000,3.500000,0.000000
2023-01-01,s02,4,3.897500,3.850000,3.950000,3.850000,3.940000,0.100000
2023-01-02,s01,1,3.950000,3.950000,3.950000,3.950000,3.950000,0.450000
"""


def run(tmp_path: Path, rows: list[str]) -> str:
    raw = tmp_path / "raw.csv"
    raw.write_text("\n".join([HEADER, *rows]) + "\n")
    out = tmp_path / "out.csv"
    subprocess.run([sys.executable, str(SCRIPT), str(raw), str(out)], check=True)
    return out.read_text()


def row(text: str, date: str, sensor: str) -> dict[str, str]:
    [found] = [r for r in csv.DictReader(text.splitlines()) if (r["date"], r["sensor"]) == (date, sensor)]
    return found


def test_output_text(tmp_path):
    assert run(tmp_path, ROWS) == EXPECTED


def test_swap_across_midnight(tmp_path):
    out = run(tmp_path, ROWS)
    assert float(row(out, "2023-01-02", "s01")["rise_v"]) == 0.45
    assert float(row(out, "2023-01-01", "s01")["rise_v"]) == 0.0


def test_swap_across_gap(tmp_path):
    out = run(tmp_path, ROWS)
    assert float(row(out, "2023-01-01", "s02")["rise_v"]) == 0.1


def test_unsorted_input(tmp_path):
    assert run(tmp_path, ROWS[::-1]) == run(tmp_path, ROWS)
