"""The gateways' C despiking filter (despike/) gives the archive's verdicts, bit for bit.

The archive despikes in polars: `flag_spikes(df, "median3c")` in
src/daily_summary.py. The gateways run despike/despike.c. These tests compile
the C library with the system's C compiler, load it with ctypes, and check
that it flags exactly the readings the archive flags.

Run with `uv run --with pytest --with numpy pytest tests/`. To compare every
reading of the real 2023 dump as well (about a minute and some 16 GB of
memory), set DESPIKE_RAW_CSV to its path.
"""

import ctypes
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import daily_summary as ds  # noqa: E402

CC = shutil.which("cc") or shutil.which("gcc")
CFLAGS = ["-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared"]


class Verdict(ctypes.Structure):
    _fields_ = [("time_s", ctypes.c_int64), ("temp_c", ctypes.c_double), ("spike", ctypes.c_int)]


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler on PATH")
    so = tmp_path_factory.mktemp("despike") / "despike.so"
    extra = os.environ.get("DESPIKE_CFLAGS", "").split()
    subprocess.run([CC, *CFLAGS, *extra, "-o", str(so), str(ROOT / "despike" / "despike.c"), "-lm"], check=True)
    lib = ctypes.CDLL(str(so))
    lib.despike_state_size.restype = ctypes.c_size_t
    lib.despike_init.argtypes = [ctypes.c_void_p]
    lib.despike_push.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_double, ctypes.POINTER(Verdict)]
    lib.despike_push.restype = ctypes.c_size_t
    lib.despike_flush.argtypes = [ctypes.c_void_p, ctypes.POINTER(Verdict)]
    lib.despike_flush.restype = ctypes.c_size_t
    lib.despike_batch.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    lib.despike_batch.restype = ctypes.c_size_t
    lib.despike_max_verdicts.restype = ctypes.c_size_t
    return lib


def frame(rows: list[tuple[str, int, float]]) -> pl.DataFrame:
    """Readings (sensor, time in s, temp_c), shaped and ordered as `ds.load` returns them."""
    sensor, time_s, temp_c = zip(*rows)
    return (
        pl.DataFrame({"time": [t * 1000 for t in time_s], "sensor": sensor, "temp_c": temp_c})
        .with_columns(pl.col("time").cast(pl.Datetime("ms", "UTC")), pl.col("sensor").cast(pl.Categorical))
        .select("time", "sensor", "temp_c")
        .sort(["sensor", "time"], maintain_order=True)
    )


def archive_flags(df: pl.DataFrame) -> np.ndarray:
    return ds.flag_spikes(df, "median3c")["spike"].to_numpy()


def c_flags(lib, df: pl.DataFrame) -> np.ndarray:
    """Run each sensor's readings, in the frame's order, through despike_batch."""
    parts = []
    for one in df.partition_by("sensor", maintain_order=True):
        time_s = np.ascontiguousarray(one["time"].dt.epoch("s").to_numpy(), dtype=np.int64)
        temp_c = np.ascontiguousarray(one["temp_c"].to_numpy(), dtype=np.float64)
        spike = np.zeros(len(one), dtype=np.uint8)
        done = lib.despike_batch(time_s.ctypes.data, temp_c.ctypes.data, len(one), spike.ctypes.data)
        assert done == len(one)
        parts.append(spike.astype(bool))
    return np.concatenate(parts)


def assert_same(archive: np.ndarray, c: np.ndarray) -> None:
    differ = np.flatnonzero(archive != c)
    assert differ.size == 0, f"{differ.size} of {archive.size} verdicts differ, first at rows {differ[:10]}"


def test_two_reading_run_uses_the_archives_median(lib):
    # The archive takes a two-value median as lo + (hi - lo) * 0.5; (lo + hi) / 2
    # would give the opposite verdict on 1.02 here.
    df = frame([("s01", 0, -4.98), ("s01", 10, 1.02)])
    assert archive_flags(df).tolist() == [False, True]
    assert c_flags(lib, df).tolist() == [False, True]


def test_streaming_verdicts_come_in_order_once_decidable(lib):
    state = ctypes.create_string_buffer(lib.despike_state_size())
    out = (Verdict * lib.despike_max_verdicts())()
    lib.despike_init(state)
    counts = [lib.despike_push(state, 10 * i, 20.0, out) for i in range(15)]
    assert counts == [0] * 15  # reading 0 needs the 15 after it
    assert lib.despike_push(state, 150, 20.0, out) == 1
    assert out[0].time_s == 0
    # A gap ends the run: its 15 undecided readings are decided at once, in order.
    assert lib.despike_push(state, 1000, 20.0, out) == 15
    assert [out[i].time_s for i in range(15)] == [10 * i for i in range(1, 16)]
    assert lib.despike_flush(state, out) == 1
    assert out[0].time_s == 1000
    assert lib.despike_flush(state, out) == 0


def test_run_edges_and_gaps_match_the_archive(lib):
    rows = []
    t = 0
    for n_run in (1, 2, 3, 15, 16, 17, 30, 31, 32, 61):
        for i in range(n_run):
            # A spike at the start, the middle and the end of each run.
            spike = 8.0 if i in (0, n_run // 2, n_run - 1) else 0.0
            rows.append(("s01", t, round(15.0 + 0.01 * i + spike, 2)))
            t += 10
        t += 20  # a gap: the next run starts here
    rows.append(("s01", t - 30, 15.0))  # a repeated timestamp also starts a run
    rows.append(("s02", 0, 12.0))
    df = frame(rows)
    assert_same(archive_flags(df), c_flags(lib, df))


def test_random_readings_match_the_archive(lib):
    rng = random.Random(2023)
    rows = []
    for s in range(1, 41):
        t, temp = rng.randrange(0, 600, 10), rng.uniform(-10.0, 30.0)
        for _ in range(3000):
            r = rng.random()
            t += 10 if r > 0.004 else rng.choice([0, 20, 30, 600, 86400])
            temp += rng.gauss(0.0, 0.05)
            spike = rng.choice([-1, 1]) * rng.choice([2.99, 3.0, 3.01, 4.0, 12.0]) if rng.random() < 0.02 else 0.0
            rows.append((f"s{s:02d}", t, round(temp + spike, 2)))
    df = frame(rows)
    archive = archive_flags(df)
    assert archive.sum() > 1000  # the fixture really exercises the threshold
    assert_same(archive, c_flags(lib, df))


@pytest.mark.skipif(not os.environ.get("DESPIKE_RAW_CSV"), reason="set DESPIKE_RAW_CSV to the raw dump")
def test_real_dump_matches_the_archive(lib):
    df = ds.load(os.environ["DESPIKE_RAW_CSV"])
    archive = archive_flags(df)
    assert_same(archive, c_flags(lib, df))
    published = ROOT / "results" / "despiked" / "daily_summary.csv"
    if published.stat().st_size > 1000:  # the bytes, not an annex pointer
        assert int(archive.sum()) == pl.read_csv(published)["n_removed"].sum()
