"""Offline tests for skills/reaper-performance-cleanup/scripts/cleanup_analysis.py (synthetic takes)."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "reaper-performance-cleanup", "scripts"))
from cleanup_analysis import (parse_notes, find_note_fixes, apply_note_fixes, find_pauses, pause_cuts,
                              cut_warp, timing_plan, anchor_warp)

E = 0.25   # eighth note at 120 BPM


def note(t, d, p, v=64):
    return [[t, 0, f"90{p:02x}{v:02x}"], [t + d, 0, f"80{p:02x}00"]]


def take(*notes, extra=()):
    ev = [e for n in notes for e in n] + list(extra)
    return sorted(ev, key=lambda e: e[0])


def run(ev):
    return parse_notes(ev, [e[0] for e in ev])


def melody(n, t0=0.0, pitches=(60, 62, 64, 65, 67, 65, 64, 62)):
    return [note(t0 + k * E, 0.2, pitches[k % len(pitches)]) for k in range(n)]


def test_ghost_in_repeated_pattern_gets_velocity_others_deleted():
    mel = melody(16)
    mel[8] = note(8 * E, 0.2, 63, 2)                    # stray near-silent press inside the melody
    bass = [note(k * 2 * E, 0.2, 48, 60) for k in range(8)]
    bass[3] = note(6 * E, 0.2, 48, 1)                  # missed key in a regular repeated bass note
    fixes = find_note_fixes(run(take(*(mel + bass))))
    kinds = {(f["kind"], f["action"], f["time"]) for f in fixes}
    assert ("ghost", "velocity", 6 * E) in kinds
    assert ("ghost", "delete", 8 * E) in kinds
    assert next(f for f in fixes if f["action"] == "velocity")["new_vel"] == 60


def test_slip_deleted_and_double_merged():
    ns = melody(16)
    slip = note(4 * E + 0.01, 0.06, 66, 20)            # F# grazed next to G (67) at 4*E
    double = note(10 * E + 0.05, 0.3, 64)               # E (melody[10]) struck again 50 ms later
    ev = take(*ns, slip, double)
    fixes = find_note_fixes(run(ev))
    by = {f["kind"]: f for f in fixes}
    assert by["slip"]["pitch"] == "F#4" and by["slip"]["auto"]
    assert by["double"]["action"] == "merge"
    out = apply_note_fixes(ev, fixes)
    notes = run(out)
    assert len(notes) == 16
    e64 = [n for n in notes if n["pitch"] == 64 and abs(n["start"] - 10 * E) < 1e-9][0]
    assert abs(e64["end"] - (10 * E + 0.35)) < 1e-9     # merged note lasts to the later release


def test_wrong_pitch_transposed_but_chromatic_passing_tone_kept():
    c_major = (60, 64, 67, 72, 67, 64)
    ns = [note(k * E, 0.2, c_major[k % 6]) for k in range(24)]
    ns[7] = note(7 * E, 0.2, 63)                        # Eb instead of E: wrong note
    ns[12], ns[13], ns[14] = note(12 * E, 0.2, 60), note(13 * E, 0.2, 61), note(14 * E, 0.2, 62)   # C C# D run
    fixes = [f for f in find_note_fixes(run(take(*ns))) if f["kind"] == "pitch"]
    assert [(f["time"], f["action"], f["to"]) for f in fixes] == [(7 * E, "transpose", "E4")]


def test_pause_cut_and_release_heuristic():
    a = melody(16)
    b = melody(16, 16 * E + 4.0)                       # 4 s thinking pause after the last note (released)
    ev = take(*(a + b), extra=[[16 * E + 3.98, 0, "b04040"]])    # pedal press just before the restart
    notes = run(ev)
    (p,) = find_pauses(notes)
    assert p["keep_beats"] == 0.5                      # released after 0.2 s -> resume one eighth later
    w = cut_warp(pause_cuts([p]))
    out = [[w(e[0]), e[1], e[2]] for e in ev]
    assert all(x[0] <= y[0] for x, y in zip(out, out[1:]))
    starts = sorted(n["start"] for n in run(out))
    assert abs(starts[16] - starts[15] - E) < 1e-6    # gap is now exactly one eighth
    assert all(abs(o[0] - e[0]) < 1e-12 for o, e in zip(out, ev) if e[0] <= 15 * E + 0.2)   # before: untouched
    pedal = next(o for o in out if o[2] == "b04040")
    assert abs((starts[16] - pedal[0]) - 0.02) < 1e-6  # pick-up pedal keeps its distance to the restart


def test_pause_held_through_uses_keep_beats():
    ns = melody(16) + [note(15 * E, 4.2, 48)] + melody(8, 16 * E + 4.0)
    (p,) = find_pauses(run(take(*ns)), keep_beats=1.0)
    assert p["keep_beats"] == 1.0 and abs(p["new_gap_sec"] - 2 * E) < 1e-6


def test_timing_pulls_toward_grid_and_keeps_order():
    q = [k * 0.5 for k in range(16)]
    q[3] += 0.1; q[6] -= 0.12; q[9] += 0.3            # 0.3 is outside the window: left alone
    ev = take(*[note(t, 0.3, 60 + k % 5) for k, t in enumerate(q)])
    moves, anchors = timing_plan(run(ev), grid=0.5, strength=0.5, window=0.35)
    assert {round(m["qn"], 2): m["shift_qn"] for m in moves} == {1.6: -0.05, 2.88: 0.06}
    w = anchor_warp(anchors)
    out = [[w(e[0]), e[1], e[2]] for e in ev]
    assert all(x[0] <= y[0] for x, y in zip(out, out[1:]))
    assert abs(w(q[9]) - q[9]) < 1e-12
