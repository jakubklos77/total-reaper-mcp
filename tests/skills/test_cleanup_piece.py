"""Offline tests for skills/reaper-performance-cleanup/scripts/piece.py (synthetic takes, times in s)."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "reaper-performance-cleanup", "scripts"))
from piece import parse, piece_map, find_fixes, apply_fixes, estimate_key

E = 0.25   # eighth note at 120 BPM
D_MINOR_CHORDS = [(50, 57, 62, 65), (46, 53, 58, 62), (45, 52, 57, 61), (50, 57, 62, 65)]   # Dm Bb A Dm
PRELUDE = 8 * 2.6                          # where the ostinato starts


def note(t, d, p, v=80):
    return [[t, 0, f"90{p:02x}{v:02x}"], [t + d, 0, f"80{p:02x}00"]]


def take(*notes):
    return sorted((e for n in notes for e in n), key=lambda e: e[0])


def run(ev):
    notes, _ = parse(ev, [e[0] for e in ev])
    pm = piece_map(notes)
    return notes, pm, find_fixes(notes, pm)


def prelude(n=8, gap=2.6):
    """Slow long chords, one every `gap` s."""
    return [note(k * gap, gap - 0.1, p, 50) for k in range(n) for p in D_MINOR_CHORDS[k % 4]]


def ostinato(t0, bars):
    """Steady eighths: bass on each bar, chord tones on every eighth."""
    out = []
    for b in range(bars):
        ch = D_MINOR_CHORDS[b % 4]
        out.append(note(t0 + b * 8 * E, 8 * E - 0.05, ch[0] - 12, 85))
        out += [note(t0 + (b * 8 + k) * E, 0.2, ch[1 + k % 3], 75) for k in range(8)]
    return out


def song():
    return prelude() + ostinato(PRELUDE, 16)


def apply(ev, fixes, **kw):
    return apply_fixes(ev, [e[0] for e in ev], fixes, **kw)


def test_key_sections_and_pulse():
    _, pm, _ = run(take(*song()))
    assert pm["key"]["name"] == "D minor"
    assert [s["kind"] for s in pm["sections"]] == ["free", "pulsed"]
    assert abs(pm["sections"][1]["start"] - PRELUDE) < 0.5
    assert abs(pm["pulse_sec"] - E) < 0.01


def test_clean_song_has_no_findings():
    # slow prelude chords and the leading tone C# in the A chord are music, not mistakes
    assert run(take(*song()))[2] == []


def test_graze_next_to_chord_is_deleted():
    t = PRELUDE + 4 * 8 * E                                        # a Dm downbeat
    _, _, fx = run(take(*song(), note(t + 0.04, 0.035, 63, 50)))   # D#4 grazed 40 ms after it
    assert [(f["kind"], f["pitch"], f["auto"]) for f in fx] == [("slip", "D#4", True)]


def test_short_chord_tone_is_kept():
    t = PRELUDE + 4 * 8 * E
    assert run(take(*song(), note(t + 0.01, 0.05, 69, 50)))[2] == []   # A4: fifth of Dm, played short


def test_grace_note_before_main_note_is_kept():
    t = PRELUDE + 4 * 8 * E + 2 * E
    _, _, fx = run(take(*song(), note(t - 0.04, 0.035, 63, 60), note(t, 0.4, 64, 90)))   # D#4 -> E4
    assert all(f["pitch"] != "D#4" for f in fx)


def test_ghost_is_deleted_or_raised():
    ev = take(*song(), note(2.6, 2.0, 62, 4))      # D4 held at vel 4 inside the Bb chord: fits, inaudible
    _, _, fx = run(ev)
    assert [(f["kind"], f["action"], f["auto"]) for f in fx] == [("ghost", "delete", True)]
    assert fx[0]["raise_to"]
    assert len(apply(ev, fx)) == len(ev) - 2
    out = apply(ev, fx, raise_ids={fx[0]["id"]})
    assert len(out) == len(ev) and [t for t, _, h in out if h == f"903e{fx[0]['raise_to']:02x}"] == [2.6]


def test_double_strike_is_merged():
    t = PRELUDE + 3 * E                            # ostinato note A3 at t
    ev = take(*song(), note(t + 0.05, 0.15, 57, 90))
    _, _, fx = run(ev)
    assert [f["kind"] for f in fx] == ["double"]
    out = apply(ev, fx)
    assert len(out) == len(ev) - 2
    a3 = [(round(t2, 6), h) for t2, _, h in out if h[2:4] == "39" and t - 0.01 < t2 < t + 0.3]
    assert a3 == [(round(t, 6), "90395a"), (round(t + 0.2, 6), "803900")]   # one note, louder velocity


def test_split_chord_moves_only_in_pulsed_section():
    t = PRELUDE + 5 * 8 * E + 4 * E
    ost = ostinato(PRELUDE, 16)
    for n in ost:                                  # the left/inner hand lands 45 ms late
        if abs(n[0][0] - t) < 1e-9: n[0][0] += 0.045; n[1][0] += 0.045
    ev = take(*prelude(), *ost, note(t, 0.5, 74, 95), note(t, 0.5, 77, 95))
    _, _, fx = run(ev)
    assert [(f["kind"], f["auto"], round(f["shift_ms"])) for f in fx] == [("split", True, -45)]
    out = apply(ev, fx)
    assert sum(1 for t2, _, h in out if h.startswith("90") and abs(t2 - t) < 1e-6) == 3

    pre = prelude()                                # the same in the free prelude: left alone
    for n in pre[2:4]: n[0][0] += 0.045; n[1][0] += 0.045
    assert [f for f in run(take(*pre, *ostinato(PRELUDE, 16)))[2] if f["kind"] == "split"] == []


def test_wrong_note_is_only_flagged():
    t = PRELUDE + 6 * 8 * E + 3 * E
    _, _, fx = run(take(*song(), note(t, 0.3, 68, 70), note(t, 0.3, 81, 80)))   # G#4 in Dm, A5 with it
    assert [(f["kind"], f["auto"]) for f in fx] == [("wrong", False)]


def test_pedal_survives_apply():
    ev = take(*song(), note(PRELUDE + 0.04, 0.035, 63, 50)) + [[1.0, 0, "b0407f"], [3.0, 0, "b04000"]]
    ev.sort(key=lambda e: e[0])
    _, _, fx = run(ev)
    assert [h for _, _, h in apply(ev, fx) if h.startswith("b0")] == ["b0407f", "b04000"]


def test_estimate_key_major():
    ev = take(*[note(k * 0.5, 0.45, p) for k, p in enumerate([60, 64, 67, 72, 65, 69, 67, 71, 74, 72] * 3)])
    assert estimate_key(parse(ev, [e[0] for e in ev])[0])["name"] == "C major"
