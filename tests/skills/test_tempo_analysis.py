"""Offline tests for skills/reaper-tempo-sync/scripts/tempo_analysis.py (synthetic performances)."""
import math, os, statistics, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "reaper-tempo-sync", "scripts"))
from tempo_analysis import analyze


def performance(bars, bpm=100.0, bpb=4, spb=2, t0=0.0, rubato=0.08, period_bars=8):
    """Eighth-note ostinato with a held bass note + pedal re-press on every downbeat; the tempo
    breathes sinusoidally by +-rubato. Returns notes, pedal, downbeat times."""
    notes, pedal, downs = [], [], []
    t, n = t0, bars * bpb * spb
    for k in range(n):
        beat = 60.0 / bpm * (1 + rubato * math.sin(2 * math.pi * k / (period_bars * bpb * spb)))
        step = beat / spb
        if k % (bpb * spb) == 0:
            downs.append(t)
            notes.append((t, t + bpb * beat * 0.95, 38 + (k // (bpb * spb)) % 5, 90))
            pedal += [(t - 0.05, 0), (t + 0.08, 127)]
        notes.append((t, t + step * 0.8, 62 + k % 3 * 3, 70 + (10 if k % spb == 0 else 0)))
        t += step
    return notes, pedal, downs


def bar_lines(res):
    """Downbeat times of the musical bars (lead-in removed)."""
    rep = res["report"]
    return rep["bar_starts_sec"][rep["lead_in_bars"]:]


def test_steady_rubato_4_4():
    notes, pedal, downs = performance(24, bpm=100)
    res = analyze(notes, pedal)
    rep = res["report"]
    assert rep["irregular_bars"] == []
    assert abs(rep["main_bpm"] - 100) < 6
    got = bar_lines(res)
    assert len(got) >= 24 and all(abs(a - b) < 0.01 for a, b in zip(got, downs))


def test_slow_prelude_keeps_main_tempo():
    # 8 long chords, one every 2.6 s, then the ostinato at 115 BPM: the prelude must not
    # become double/half tempo or extra bars of silence
    pre = [(k * 2.6, k * 2.6 + 2.5, p, 50) for k in range(8) for p in (50, 57, 62, 65)]
    ped = [(k * 2.6 + 0.1, 127) for k in range(8)] + [(k * 2.6 - 0.05, 0) for k in range(1, 8)]
    notes, pedal, downs = performance(20, bpm=115, t0=8 * 2.6, rubato=0.03)
    res = analyze(pre + notes, sorted(ped + pedal))
    rep = res["report"]
    bpms = rep["per_bar_bpm"]
    assert all(60 < b < 200 for b in bpms), bpms
    tail = bpms[-18:]
    assert abs(statistics.median(tail) - 115) < 6
    got = bar_lines(res)
    assert all(any(abs(g - d) < 0.01 for g in got) for d in downs[:-1])   # every ostinato downbeat is a bar line


def test_three_four():
    notes, pedal, downs = performance(24, bpm=90, bpb=3)
    res = analyze(notes, pedal, beats_per_bar=3)
    assert res["report"]["irregular_bars"] == []
    got = bar_lines(res)
    assert all(abs(a - b) < 0.01 for a, b in zip(got, downs))


def test_one_short_bar_is_found():
    a, pa, da = performance(8, bpm=100, rubato=0.0)
    end = da[-1] + 4 * 0.6
    # a 2/4 bar, then 8 more 4/4 bars
    short = [(end + k * 0.3, end + k * 0.3 + 0.24, 64, 75) for k in range(4)] + [(end, end + 1.1, 40, 90)]
    b, pb, db = performance(8, bpm=100, rubato=0.0, t0=end + 1.2)
    res = analyze(a + short + b, sorted(pa + pb + [(end + 0.08, 127), (end - 0.05, 0)]))
    irr = res["report"]["irregular_bars"]
    assert [x[1] for x in irr] == [2]


def test_tempo_points_are_monotonic_and_cover_the_notes():
    notes, pedal, _ = performance(16, bpm=120, t0=1.7)
    res = analyze(notes, pedal)
    times = [p[0] for p in res["tempo_points"]]
    assert times[0] == 0.0 and all(b > a for a, b in zip(times, times[1:]))
    assert times[-1] >= max(n[0] for n in notes) - 0.6
    assert res["report"]["lead_in_beats"] % 4 == 0         # silence before a downbeat start = whole bars
