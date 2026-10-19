"""Offline tests for skills/reaper-piano-to-strings/scripts/arrange.py (synthetic takes, times in qn)."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "reaper-piano-to-strings", "scripts"))
from arrange import load, arrange, to_events, CB, VC, VA, V2, V1  # noqa: E402

# PDF-like sketch: G Bm A/C# D Em D/F# Asus4 A, one chord per 2 beats (bass, 3 chord tones)
CHORDS = [(43, 55, 59, 62), (47, 54, 59, 62), (49, 57, 61, 64), (50, 57, 62, 66),
          (40, 55, 59, 64), (42, 57, 62, 66), (45, 57, 62, 64), (45, 57, 61, 64)]
MELODY = [71, 74, 76, 74, 73, 74, 76, 78, 79, 78, 76, 74, 76, 74, 73, 69]   # quarters


def note(t, d, p, v=80):
    return [[t, 0, f"90{p:02x}{v:02x}"], [t + d, 0, f"80{p:02x}00"]]


def take(*notes):
    return sorted((e for n in notes for e in n), key=lambda e: e[0])


def run(ev, **kw):
    return arrange(load(ev, [e[0] for e in ev]), **kw)


def pitches(part, role=None):
    return [n["pitch"] for n in sorted(part, key=lambda n: n["start"]) if role is None or n["role"] == role]


def sounding(part, q):
    return [n["pitch"] for n in part if n["start"] <= q < n["end"]]


def sketch():
    return take(*[note(2 * k, 2, p, 70) for k, c in enumerate(CHORDS) for p in c],
                *[note(k, 1, p, 90) for k, p in enumerate(MELODY)])


def test_melody_goes_to_violins_1_bass_to_basses():
    r = run(sketch())
    assert pitches(r["parts"][V1], "melody") == MELODY
    for k, c in enumerate(CHORDS):              # Basses play the bass note of every chord (inversions kept)
        cb = sounding(r["parts"][CB], 2 * k + 1)
        assert cb and cb[0] % 12 == c[0] % 12, (k, cb)


def test_voices_do_not_cross_and_low_end_is_open():
    r = run(sketch(), legato=False)
    for k in range(len(CHORDS)):
        q = 2 * k + 1.5
        line = [sounding(r["parts"][i], q) for i in (CB, VC, VA, V2)]
        assert all(line), (k, line)
        lo = [min(x) for x in line]
        assert lo == sorted(lo), (k, line)
        d = lo[1] - lo[0]
        assert d == 0 or d >= 7, f"cellos {d} semitones above basses at chord {k}"
        assert max(max(x) for x in line) <= MELODY[int(q)], "harmony above the melody"


def test_chord_tones_covered_and_inner_voices_move_little():
    r = run(sketch(), legato=False)
    for k, c in enumerate(CHORDS):
        q = 2 * k + 1.5
        pcs = {p % 12 for i in range(5) for p in sounding(r["parts"][i], q)}
        assert {p % 12 for p in c} <= pcs, (k, c, pcs)
    for i in (VA, V2):
        ps = pitches(r["parts"][i])
        assert max(abs(b - a) for a, b in zip(ps, ps[1:])) <= 7, (i, ps)


def test_left_hand_arpeggio_kept_as_figure_bass_sustains_root():
    arp = [38, 45, 50, 53, 57, 53, 50, 45]      # D2 A2 D3 F3 A3 F3 D3 A2 in eighths
    ev = take(*[note(4 * b + 0.5 * k, 0.5, p, 65) for b in range(4) for k, p in enumerate(arp)],
              *[note(2 * k, 2, p, 95) for k, p in enumerate([74, 76, 77, 76, 74, 72, 74, 74])],
              [[0, 0, "b04040"], [15.9, 0, "b04000"]])          # sustain pedal through
    r = run(ev)
    figs = [i for i in range(5) if any(n["role"] == "figure" for n in r["parts"][i])]
    assert figs and figs[0] in (VC, VA), figs
    fig = pitches(r["parts"][figs[0]], "figure")
    assert len(fig) == 32 and len({p - a for p, a in zip(fig, arp * 4)}) == 1   # as played (maybe octave)
    assert pitches(r["parts"][V1], "melody") == [74, 76, 77, 76, 74, 72, 74, 74]
    cb = r["parts"][CB]
    assert cb and {n["pitch"] % 12 for n in cb} == {2} and len(cb) <= 2         # held D, not the arpeggio


def test_left_hand_melody_detected_and_flagged():
    chords = [(64, 67, 72), (65, 69, 72), (64, 67, 72), (62, 67, 71)]
    lh = [48, 50, 52, 55, 53, 52, 50, 47, 48, 52, 55, 57, 55, 53, 52, 50]    # tune in quarters, loud
    ev = take(*[note(4 * b + 0.5 * k, 0.45, p, 45) for b, c in enumerate(chords) for k in range(8) for p in c],
              *[note(k, 1, p, 100) for k, p in enumerate(lh)])
    r = run(ev)
    mel = [(i, n["pitch"]) for i in range(5) for n in r["parts"][i] if n["role"] == "melody"]
    assert {p for _, p in mel} >= set(lh) and {i for i, _ in mel} == {VC}
    assert any(f["kind"] == "melody" for f in r["flags"])


def test_pedal_point_over_descending_bass():
    # Em D C G/B A under a held top G (as at the end of the PDF piece)
    ch = [(40, 55, 59, 67), (38, 54, 57, 66), (36, 52, 55, 64), (35, 50, 55, 67), (33, 52, 57, 64)]
    ev = take(*[note(2 * k, 2, p, 70) for k, c in enumerate(ch) for p in c],
              *[note(2 * k, 2, p, 90) for k, p in enumerate([79, 78, 76, 74, 76])])
    r = run(ev)
    assert any(f["kind"] == "pedal" for f in r["flags"]), r["flags"]
    ped = [n for i in range(5) for n in r["parts"][i] if n["role"] == "pedal"]
    assert ped and ped[0]["end"] - ped[0]["start"] >= 4


def test_bass_rests_when_bass_lies_high():
    ev = take(*[note(4 * k, 4, p, 70) for k in range(3) for p in (55, 59, 64, 67)],
              *[note(k, 1, 76 + (k % 3), 90) for k in range(12)])
    r = run(ev)
    assert not r["parts"][CB] and any(f["kind"] == "bass-rest" for f in r["flags"])


def test_events_are_valid_midi_and_ranges_respected():
    from arrange import INSTR
    r = run(sketch())
    for i, (part, cc) in enumerate(zip(r["parts"], r["cc"])):
        assert all(INSTR[i][2][0] <= n["pitch"] <= INSTR[i][2][1] for n in part), i
        ev = to_events(part, cc)
        assert all(len(e[2]) == 6 for e in ev)
        assert {e[2][2:4] for e in ev if e[2][0] == "b"} <= {"01", "0b"}
        on = sum(e[2][0] == "9" for e in ev)
        assert on == sum(e[2][0] == "8" for e in ev) == len(part)


def test_rubato_early_notes_and_figure_stays_on_one_instrument():
    """Arpeggio + tune over 40 bars, every onset up to 50 ms early/late: the arpeggio stays complete
    and on one instrument, the tune stays in Violins 1, held upper notes are not absorbed."""
    import random
    random.seed(1)
    roots = [50, 46, 45, 50, 43, 45, 41, 45]
    ev = []
    for b in range(40):
        r = roots[b % 8]
        tri = [r, r + 7, r + 12, r + 15 if b % 2 else r + 16]
        for k, p in enumerate(tri + tri[2:0:-1] + [r + 7, r + 12]):
            ev += note(4 * b + 0.5 * k + random.uniform(-.1, .1), 0.5, p, 60 + random.randint(-8, 8))
        for k in range(4): ev += note(4 * b + k + random.uniform(-.1, .1), 1, 84 + random.choice([0, 2, 3, 5, 7]), 85)
    ev.sort(key=lambda e: e[0])
    r = run(ev)
    figs = {i for i in range(5) for n in r["parts"][i] if n["role"] == "figure"}
    assert figs == {VC}, figs
    assert sum(n["role"] == "figure" for n in r["parts"][VC]) == 40 * 8
    assert sum(n["role"] == "melody" for n in r["parts"][V1]) == 40 * 4
