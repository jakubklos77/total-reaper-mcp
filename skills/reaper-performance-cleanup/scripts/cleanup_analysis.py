"""
cleanup_analysis.py - find and fix performance slips in a freely played MIDI take.

DAW-independent: works on a raw event list [[pos, flags, hex], ...] (one position unit, e.g.
seconds or quarter notes) and returns a new event list. Used by cleanup.py (live REAPER via MCP).

Detectors (each finding gets a stable id, in time order):
  P<n>  pause      - thinking pause: a long gap with no new notes; cut down to a few beats
  N<n>  ghost      - near-silent key press: deleted, or (in a regular repeated-note pattern)
                     given the neighbours' velocity
        slip       - short quiet note grazed next to a louder neighbouring key: deleted
        double     - the same key struck twice within a few ms: merged into one note
        pitch      - out-of-context pitch next to a strongly used one: transposed (review)
Timing: onsets close to the grid of the (tempo-synced) project are pulled towards it.

Every time change is a monotonic warp of the whole timeline, so pedal/CC/sysex events move with
the notes around them and nothing changes order.
"""
import math, statistics

NAMES = "C C# D D# E F F# G G# A A# B".split()
CLUSTER_SEC = 0.035


def pname(p):
    return f"{NAMES[p % 12]}{p // 12 - 1}"


# ---------------------------------------------------------------- events <-> notes

def status(h):
    return int(h[0:2], 16) & 0xF0


def parse_notes(events, sec):
    """events: [[pos, flags, hex, ...], ...] in stream order; sec: a time for each event (any unit).
    Returns notes: dicts with on/off event indices, start/end (s), pitch, vel, chan, muted."""
    open_, notes = {}, []
    for i, e in enumerate(events):
        fl, h = e[1], e[2]
        if len(h) != 6: continue
        st, ch = status(h), int(h[1], 16)
        if st not in (0x80, 0x90): continue
        p, v = int(h[2:4], 16), int(h[4:6], 16)
        if st == 0x90 and v > 0:
            open_.setdefault((ch, p), []).append(len(notes))
            notes.append({"on": i, "off": None, "start": sec[i], "end": sec[i], "pitch": p, "vel": v,
                          "chan": ch, "muted": bool(fl & 2)})
        elif open_.get((ch, p)):
            n = notes[open_[(ch, p)].pop(0)]
            n["off"], n["end"] = i, sec[i]
    return [n for n in notes if n["off"] is not None]


def clusters(notes):
    """Onset clusters (chords / rolled notes) of sounding notes."""
    out = []
    for n in sorted((n for n in notes if not n["muted"]), key=lambda n: n["start"]):
        if out and n["start"] - out[-1][0]["start"] < CLUSTER_SEC: out[-1].append(n)
        else: out.append([n])
    return out


def local_beat(cl, k, slots_per_beat):
    """Local beat length (s) around cluster k, from the surrounding onset spacing."""
    gaps = [b[0]["start"] - a[0]["start"] for a, b in zip(cl, cl[1:])]
    if not gaps: return 0.5
    g_med = statistics.median(gaps)
    w = [g for j, g in enumerate(gaps[max(0, k - 12):k + 12], max(0, k - 12))
         if j != k and 0.5 * g_med < g < 3 * g_med]
    return (statistics.median(w) if w else g_med) * slots_per_beat


# ---------------------------------------------------------------- note detectors

def find_note_fixes(notes, ghost_vel=8, slip_sec=0.12, double_sec=0.09, pitch_window=4.0):
    live = [n for n in notes if not n["muted"]]
    fixes, taken = [], set()

    def near(n, sec):
        return [m for m in live if m is not n and abs(m["start"] - n["start"]) <= sec]

    def add(n, kind, action, auto, why, **kw):
        taken.add(id(n))
        fixes.append({"kind": kind, "action": action, "auto": auto, "why": why, "note": n,
                      "time": round(n["start"], 3), "pitch": pname(n["pitch"]), "vel": n["vel"],
                      "dur_ms": round((n["end"] - n["start"]) * 1000), **kw})

    # ghost: near-silent press
    for n in live:
        if n["vel"] > ghost_vel: continue
        same = sorted((m for m in live if m["pitch"] == n["pitch"] and m is not n and m["vel"] > ghost_vel),
                      key=lambda m: m["start"])
        prev = [m for m in same if m["start"] < n["start"]][-1:]
        nxt = [m for m in same if m["start"] > n["start"]][:1]
        if prev and nxt and nxt[0]["start"] - prev[0]["start"] < 2.5:
            a, b = n["start"] - prev[0]["start"], nxt[0]["start"] - n["start"]
            if 0.6 <= a / b <= 1.6:   # sits evenly inside a repeated-note pattern -> a missed note
                v = round((prev[0]["vel"] + nxt[0]["vel"]) / 2)
                add(n, "ghost", "velocity", False,
                    f"near-silent note evenly inside a repeated {pname(n['pitch'])} pattern - probably a missed key",
                    new_vel=v)
                continue
        add(n, "ghost", "delete", True, "near-silent key press (inaudible)")

    # slip: short, quiet, next to a louder neighbouring key struck at the same time
    for n in live:
        if id(n) in taken or n["end"] - n["start"] > slip_sec: continue
        ctx = [m["vel"] for m in live if m is not n and abs(m["start"] - n["start"]) <= 1.5]
        if not ctx or n["vel"] > 0.5 * statistics.median(ctx): continue
        nb = [m for m in near(n, 0.08) if abs(m["pitch"] - n["pitch"]) in (1, 2) and m["vel"] >= 1.5 * n["vel"]]
        if nb:
            add(n, "slip", "delete", True,
                f"short quiet note grazed next to {pname(nb[0]['pitch'])} (vel {nb[0]['vel']})")

    # double strike: same key twice within double_sec
    for p in {n["pitch"] for n in live}:
        same = sorted((n for n in live if n["pitch"] == p and id(n) not in taken), key=lambda n: n["start"])
        for a, b in zip(same, same[1:]):
            if b["start"] - a["start"] <= double_sec and id(a) not in taken:
                add(b, "double", "merge", True,
                    f"{pname(p)} struck twice {round((b['start'] - a['start']) * 1000)} ms apart", into=a)

    # pitch: a pitch class unused around it, a semitone from one that is used a lot
    durs = sorted(n["end"] - n["start"] for n in live)
    med_dur = durs[len(durs) // 2] if durs else 0
    for n in live:
        if id(n) in taken or n["end"] - n["start"] > med_dur: continue
        w = [0.0] * 12
        for m in live:
            if m is not n and id(m) not in taken and abs(m["start"] - n["start"]) <= pitch_window:
                w[m["pitch"] % 12] += (m["end"] - m["start"]) * m["vel"]
        tot = sum(w) or 1
        pc = n["pitch"] % 12
        if w[pc] / tot >= 0.02: continue
        cand = max((d for d in (-1, 1)), key=lambda d: w[(pc + d) % 12])
        if w[(pc + cand) % 12] / tot < 0.12: continue
        # chromatic passing / neighbour tone in a line: leave it
        line = sorted((m for m in live if m is not n and abs(m["pitch"] - n["pitch"]) <= 4
                       and abs(m["start"] - n["start"]) <= 1.0), key=lambda m: m["start"])
        pv = [m for m in line if m["start"] < n["start"] - CLUSTER_SEC][-1:]
        nx = [m for m in line if m["start"] > n["start"] + CLUSTER_SEC][:1]
        if pv and nx and abs(pv[0]["pitch"] - n["pitch"]) == 1 and abs(nx[0]["pitch"] - n["pitch"]) == 1:
            continue
        why = (f"{NAMES[pc]} is not played nearby (±{pitch_window:g}s) but {NAMES[(pc + cand) % 12]} is "
               f"({round(100 * w[(pc + cand) % 12] / tot)}% of the sound)")
        two_keys = [m for m in near(n, CLUSTER_SEC) if abs(m["pitch"] - n["pitch"]) in (1, 2)]
        if two_keys:      # struck together with the key next to it: an extra key, not a wrong one
            add(n, "pitch", "delete", False, why + f"; pressed together with {pname(two_keys[0]['pitch'])}")
        else:
            add(n, "pitch", "transpose", False, why, new_pitch=n["pitch"] + cand, to=pname(n["pitch"] + cand))

    fixes.sort(key=lambda f: (f["time"], f["pitch"]))
    for k, f in enumerate(fixes, 1): f["id"] = f"N{k}"
    return fixes


def apply_note_fixes(events, fixes):
    """Return a new event list with the given fixes applied (deletions, velocity, pitch, merges)."""
    ev = [list(e) for e in events]
    drop = set()
    for f in fixes:
        n = f["note"]
        if f["action"] == "delete":
            drop |= {n["on"], n["off"]}
        elif f["action"] == "velocity":
            h = ev[n["on"]][2]; ev[n["on"]][2] = h[:4] + f"{f['new_vel']:02x}"
        elif f["action"] == "transpose":
            for i in (n["on"], n["off"]):
                h = ev[i][2]; ev[i][2] = h[:2] + f"{f['new_pitch']:02x}" + h[4:]
        elif f["action"] == "merge":
            a = f["into"]
            drop |= {n["on"], a["off"]}          # one note from a's start to the later end
            if n["end"] < a["end"]:
                drop.discard(a["off"]); drop.add(n["off"])
    return [e for i, e in enumerate(ev) if i not in drop]


# ---------------------------------------------------------------- pauses

def find_pauses(notes, slots_per_beat=2, min_pause=1.5, pause_beats=3.0, keep_beats=1.0, keep=None):
    """Long gaps between onsets. keep: {id: beats} overrides keep_beats per pause."""
    cl = clusters(notes)
    out = []
    for k, (a, b) in enumerate(zip(cl, cl[1:])):
        t_prev, t_next = a[0]["start"], b[0]["start"]
        g = t_next - t_prev
        beat = local_beat(cl, k, slots_per_beat)
        if g < max(min_pause, pause_beats * beat): continue
        held = max(n["end"] for n in a) - t_prev
        out.append({"time": round(t_prev, 3), "next_onset": round(t_next, 3), "gap_sec": round(g, 3),
                    "gap_beats": round(g / beat, 1), "beat_sec": round(beat, 3), "held_sec": round(held, 3),
                    "_beat": beat, "_held": held, "_t_next": t_next, "_gap": g})
    for k, p in enumerate(out, 1):
        p["id"] = f"P{k}"
        slot = p["_beat"] / slots_per_beat
        if keep and p["id"] in keep:
            kb = keep[p["id"]]
        elif p["_held"] < p["gap_sec"] - slot:
            # the last notes were let go well before the pause ended: resume on the next
            # subdivision after the release (at most keep_beats)
            kb = min(keep_beats, max(1, math.ceil(p["_held"] / slot - 0.25)) / slots_per_beat)
        else:   # held through the pause
            kb = keep_beats
        new_gap = min(p["_gap"], kb * p["_beat"])
        p["_new_gap"] = new_gap
        p["keep_beats"] = round(kb, 3)
        p["new_gap_sec"] = round(new_gap, 3)
        p["removed_sec"] = round(p["gap_sec"] - new_gap, 3)
    return out


def pause_cuts(pauses, tiny=0.02):
    """Each pause -> a cut window [c, c+r] that collapses to `tiny` seconds. The window starts after the
    last notes are released (when they are) and ends a little before the next onset, so releases and
    pick-up pedal presses right before the restart keep their timing."""
    cuts = []
    for p in pauses:
        removed = p["_gap"] - p["_new_gap"]
        if removed <= tiny: continue
        lead = min(0.5 * p["_beat"], 0.3 * p["_new_gap"])
        if p["_held"] < p["_new_gap"] - tiny:          # keep the released tail of the last notes intact
            lead = min(lead, p["_new_gap"] - tiny - p["_held"])
        r = removed + tiny
        cuts.append((p["_t_next"] - lead - r, r))
    return sorted(cuts)


def cut_warp(cuts, tiny=0.02):
    def f(t):
        shift = 0.0
        for c, r in cuts:
            if t >= c + r: shift += r - tiny
            elif t > c: return t - shift - (t - c) + (t - c) * tiny / r
            else: break
        return t - shift
    return f


# ---------------------------------------------------------------- timing (needs the synced grid)

def timing_plan(notes_q, grid=0.5, strength=0.5, window=0.35, min_dev=0.01):
    """notes_q: parsed notes with start/end in quarter notes (project grid).
    Returns (moves, anchors): one move per onset cluster pulled toward the grid, and warp anchors."""
    cl = clusters(notes_q)
    span, target, shift = [], [], []
    for k, c in enumerate(cl):
        q0, q1 = c[0]["start"], max(n["start"] for n in c)
        t = round(q0 / grid) * grid
        dev = q0 - t
        nxt = cl[k + 1][0]["start"] if k + 1 < len(cl) else None
        ornament = all(n["end"] - n["start"] < 0.25 * grid for n in c) and nxt is not None and nxt - q0 < 0.3 * grid
        span.append((q0, q1)); target.append(t)
        shift.append(-strength * dev if (min_dev <= abs(dev) <= window * grid and not ornament) else 0.0)
    changed = True
    while changed:                       # never let two clusters touch or swap: leave both unmoved
        changed = False
        for k in range(1, len(cl)):
            if span[k][0] + shift[k] <= span[k - 1][1] + shift[k - 1] + 1e-4 and (shift[k] or shift[k - 1]):
                shift[k] = shift[k - 1] = 0.0; changed = True
    moves, anchors = [], []
    for k, c in enumerate(cl):
        (q0, q1), s = span[k], shift[k]
        if s:
            moves.append({"qn": round(q0, 4), "target_qn": round(target[k], 4), "dev_qn": round(q0 - target[k], 4),
                          "shift_qn": round(s, 4), "notes": len(c)})
        anchors += [(q0, q0 + s), (q1, q1 + s)] if q1 > q0 else [(q0, q0 + s)]
    return moves, anchors


def anchor_warp(anchors):
    """Piecewise-linear warp through (old, new) anchors; constant offset outside them."""
    a = sorted(set(anchors))
    def f(t):
        if not a: return t
        if t <= a[0][0]: return t + a[0][1] - a[0][0]
        if t >= a[-1][0]: return t + a[-1][1] - a[-1][0]
        lo, hi = 0, len(a) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if a[mid][0] <= t: lo = mid
            else: hi = mid
        (x0, y0), (x1, y1) = a[lo], a[hi]
        return y0 + (t - x0) * (y1 - y0) / (x1 - x0)
    return f


def onset_deviation(notes_q, grid):
    devs = [abs(c[0]["start"] - round(c[0]["start"] / grid) * grid) for c in clusters(notes_q)]
    return {"median_dev_qn": round(statistics.median(devs), 4) if devs else 0,
            "max_dev_qn": round(max(devs), 4) if devs else 0,
            "on_grid_pct": round(100 * sum(d < 0.02 for d in devs) / len(devs)) if devs else 100}
