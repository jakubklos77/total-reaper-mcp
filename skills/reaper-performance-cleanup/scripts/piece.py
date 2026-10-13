"""
piece.py - whole-piece analysis and safe note cleanup for a freely played piano MIDI take.

DAW-independent: works on a raw event list [[pos, flags, hex, ...], ...] plus a time in seconds
for every event, and returns new event lists. Used by cleanup.py (live REAPER via MCP).

1. piece_map()   - key, sections (free/rubato vs. pulsed), main pulse and tempo per section.
                   Everything else is judged against this map, never against a few seconds of
                   context: a slow prelude chord is not a "pause", a leading tone is not a
                   "wrong note".
2. find_fixes()  - accidents that are safe to fix because the result sounds like what was meant:
     ghost  - near-silent key press (velocity <= ghost_vel): deleted. A held ghost that fits the
              chord, or sits evenly in a repeated-note pattern, can be raised instead (--raise).
     slip   - very short note grazed together with a chord: an adjacent key, or a pitch that is
              in neither the key nor the chord. Grace notes (before the main note) are kept.
     double - the same key struck twice within double_sec: merged into one note.
     split  - a chord struck as two hits 30-70 ms apart (one hand late): the minority is moved
              onto the main hit. Only in pulsed sections; rolled chords are left alone.
     wrong  - possible wrong note: outside the key and the harmony, not resolving by step.
              Never applied automatically - only listed with a suggestion.
"""
import math, statistics

NAMES = "C C# D D# E F F# G G# A A# B".split()
GROUP_SEC = 0.05        # notes starting this close form one onset (chord)


def pname(p):
    return f"{NAMES[p % 12]}{p // 12 - 1}"


# ---------------------------------------------------------------- events -> notes, pedal

def parse(events, sec):
    """Notes (dicts with on/off event index, start, end, pitch, vel, chan, muted) and sustain
    pedal down-intervals [(start, end)] in seconds."""
    open_, notes, pedal, down = {}, [], [], None
    for i, e in enumerate(events):
        h = e[2]
        if len(h) != 6: continue
        st, ch, a, b = int(h[0], 16) << 4, int(h[1], 16), int(h[2:4], 16), int(h[4:6], 16)
        if st == 0xB0 and a == 64:
            if b >= 64 and down is None: down = sec[i]
            elif b < 64 and down is not None: pedal.append((down, sec[i])); down = None
        elif st == 0x90 and b > 0:
            open_.setdefault((ch, a), []).append(len(notes))
            notes.append({"on": i, "off": None, "start": sec[i], "end": sec[i], "pitch": a, "vel": b,
                          "chan": ch, "muted": bool(e[1] & 2)})
        elif st in (0x80, 0x90) and open_.get((ch, a)):
            n = notes[open_[(ch, a)].pop(0)]
            n["off"], n["end"] = i, sec[i]
    if down is not None: pedal.append((down, math.inf))
    notes = sorted((n for n in notes if n["off"] is not None), key=lambda n: (n["start"], n["pitch"]))
    for n in notes:                        # how long it actually sounds (sustain pedal holds it)
        n["ring"] = n["end"]
        for a, b in pedal:
            if a <= n["end"] < b: n["ring"] = max(n["end"], min(b, n["end"] + 4.0)); break
    return notes, pedal


def onsets(notes, ghost_vel=8):
    """Onset groups (chords) of audible notes: [[note, ...], ...] in time order."""
    out = []
    for n in notes:
        if n["muted"] or n["vel"] <= ghost_vel: continue
        if out and n["start"] - out[-1][0]["start"] < GROUP_SEC: out[-1].append(n)
        else: out.append([n])
    return out


# ---------------------------------------------------------------- key

KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
# scale degrees counted as "in key": diatonic major; natural + harmonic + melodic minor
IN_MAJOR = {0, 2, 4, 5, 7, 9, 11}
IN_MINOR = {0, 2, 3, 5, 7, 8, 9, 10, 11}


def _corr(x, y):
    mx, my = sum(x) / 12, sum(y) / 12
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) or 1
    return num / den


def estimate_key(notes):
    """Krumhansl-Kessler key finding, notes weighted by how long they sound (capped at 2 s)."""
    w = [0.0] * 12
    for n in notes:
        if not n["muted"]: w[n["pitch"] % 12] += min(n["ring"] - n["start"], 2.0)
    best = max(((_corr(w, prof[-t:] + prof[:-t] if t else prof), t, mode)
                for t in range(12) for prof, mode in ((KK_MAJOR, "major"), (KK_MINOR, "minor"))))
    r, tonic, mode = best
    scale = {(tonic + d) % 12 for d in (IN_MAJOR if mode == "major" else IN_MINOR)}
    return {"tonic": tonic, "mode": mode, "name": f"{NAMES[tonic]} {mode}", "confidence": round(r, 2),
            "scale": sorted(scale)}


# ---------------------------------------------------------------- sections and pulse

def _pulse(iois):
    """Most common inter-onset interval in 0.12..0.7 s (the played subdivision), by a log histogram."""
    cand = [g for g in iois if 0.12 <= g <= 0.7]
    if len(cand) < 8: return None
    best, score = None, -1
    for c in (0.12 * 1.02 ** k for k in range(90)):
        if c > 0.7: break
        s = sum(math.exp(-(math.log(g / c) / 0.07) ** 2) for g in cand)
        if s > score: best, score = c, s
    near = [g for g in cand if abs(math.log(g / best)) < 0.2]
    return statistics.median(near)


def piece_map(notes, ghost_vel=8, win=12.0, hop=2.0, min_section=15.0, free_ioi=0.8):
    """Key + sections. A window is 'free' (rubato, long chords: no steady pulse to measure) when
    its median onset gap is >= free_ioi s, otherwise 'pulsed'. Sections shorter than min_section
    are absorbed. Returns {"key", "pulse_sec", "sections": [{start, end, kind, pulse_sec, ...}]}."""
    on = onsets(notes, ghost_vel)
    t = [g[0]["start"] for g in on]
    if len(t) < 4:
        return {"key": estimate_key(notes), "pulse_sec": None, "sections": []}
    start, end = t[0], max(n["end"] for n in notes)
    labels = []
    x = start
    while x < end:
        w = [b - a for a, b in zip(t, t[1:]) if x - win / 2 <= a < x + win / 2]
        labels.append((x, "free" if not w or statistics.median(w) >= free_ioi else "pulsed"))
        x += hop
    # runs of equal labels -> sections
    secs = []
    for x, k in labels:
        if secs and secs[-1]["kind"] == k: secs[-1]["end"] = x + hop
        else: secs.append({"start": x, "end": x + hop, "kind": k})
    changed = True
    while changed and len(secs) > 1:       # absorb short sections into their neighbours
        changed = False
        i = min(range(len(secs)), key=lambda i: secs[i]["end"] - secs[i]["start"])
        if secs[i]["end"] - secs[i]["start"] < min_section:
            j = i - 1 if i == len(secs) - 1 or (i > 0 and secs[i - 1]["end"] - secs[i - 1]["start"]
                                                  >= secs[i + 1]["end"] - secs[i + 1]["start"]) else i + 1
            a, b = sorted((i, j))
            secs[a:b + 1] = [{"start": secs[a]["start"], "end": secs[b]["end"], "kind": secs[j]["kind"]}]
            k = 0                          # re-merge equal neighbours
            while k < len(secs) - 1:
                if secs[k]["kind"] == secs[k + 1]["kind"]:
                    secs[k:k + 2] = [{"start": secs[k]["start"], "end": secs[k + 1]["end"], "kind": secs[k]["kind"]}]
                else: k += 1
            changed = True
    secs[0]["start"], secs[-1]["end"] = start, end
    gaps = [b - a for a, b in zip(t, t[1:])]
    for s, nx in zip(secs, secs[1:]):      # snap each boundary to the onset where the playing changes
        b = s["end"]
        for i, x in enumerate(t):
            if x < b - win or i + 4 > len(gaps): continue
            if x > b + win: break
            ahead = statistics.median(gaps[i:i + 6])
            if (nx["kind"] == "pulsed") == (ahead < free_ioi) == (gaps[i] < free_ioi):
                s["end"] = nx["start"] = x - 0.01; break
    all_iois = [b - a for a, b in zip(t, t[1:])]
    pulse = _pulse([g for (a, g) in zip(t, all_iois)
                    if any(s["kind"] == "pulsed" and s["start"] <= a < s["end"] for s in secs)]) or _pulse(all_iois)
    for s in secs:
        st = [x for x in t if s["start"] <= x < s["end"]]
        gaps = [b - a for a, b in zip(st, st[1:])]
        s["onsets"] = len(st)
        s["median_gap_sec"] = round(statistics.median(gaps), 3) if gaps else None
        s["pulse_sec"] = None
        if s["kind"] == "pulsed" and pulse:
            near = [g for g in gaps if abs(math.log(g / pulse)) < 0.25]
            if near: s["pulse_sec"] = round(statistics.median(near), 3)
        s["start"], s["end"] = round(s["start"], 2), round(s["end"], 2)
    return {"key": estimate_key(notes), "pulse_sec": round(pulse, 3) if pulse else None, "sections": secs}


def section_at(pmap, x):
    for s in pmap["sections"]:
        if s["start"] <= x < s["end"]: return s
    return pmap["sections"][-1] if pmap["sections"] else {"kind": "pulsed"}


# ---------------------------------------------------------------- harmony

def harmony(notes, x, skip=(), span=0.35):
    """Pitch-class weights of what sounds around time x: notes ringing at x or struck within
    +-span s (velocity x capped duration), excluding the notes in skip."""
    w = [0.0] * 12
    sk = {id(n) for n in skip}
    for n in notes:
        if id(n) in sk or n["muted"] or n["vel"] <= 8: continue
        if n["start"] - span <= x <= n["ring"] or abs(n["start"] - x) <= span:
            w[n["pitch"] % 12] += n["vel"] * min(n["ring"] - n["start"], 1.0)
    return w


def pc_share(w, pc):
    return w[pc] / (sum(w) or 1)


# ---------------------------------------------------------------- fix finders

def find_fixes(notes, pmap, ghost_vel=8, slip_sec=0.07, double_sec=0.09, split_min=0.035, split_max=0.07):
    live = [n for n in notes if not n["muted"]]
    scale = set(pmap["key"]["scale"])
    fixes, taken = [], set()

    def add(n, kind, action, auto, why, **kw):
        taken.add(id(n))
        fixes.append({"kind": kind, "action": action, "auto": auto, "why": why, "note": n,
                      "time": round(n["start"], 3), "pitch": pname(n["pitch"]), "vel": n["vel"],
                      "dur_ms": round((n["end"] - n["start"]) * 1000), **kw})

    def group(n, before=0.08, after=0.08):
        return [m for m in live if m is not n and id(m) not in taken and m["vel"] > ghost_vel
                and -before <= m["start"] - n["start"] <= after]

    # ghost: inaudible. Delete (keeps what was heard); suggest raising when it looks intended.
    for n in live:
        if n["vel"] > ghost_vel: continue
        raise_to, why = None, "near-silent key press (inaudible)"
        g = group(n, 0.06, 0.06)
        w = harmony(live, n["start"] + 0.05, skip=[n])
        same = sorted((m for m in live if m["pitch"] == n["pitch"] and m["vel"] > ghost_vel), key=lambda m: m["start"])
        prev = [m for m in same if m["start"] < n["start"]][-1:]
        nxt = [m for m in same if m["start"] > n["start"]][:1]
        if prev and nxt and nxt[0]["start"] - prev[0]["start"] < 2.5 and \
                0.6 <= (n["start"] - prev[0]["start"]) / max(nxt[0]["start"] - n["start"], 1e-6) <= 1.6:
            raise_to = round((prev[0]["vel"] + nxt[0]["vel"]) / 2)
            why = f"inaudible - sits evenly in a repeated {pname(n['pitch'])} pattern: maybe a missed key"
        elif g and n["end"] - n["start"] >= 0.5 and pc_share(w, n["pitch"] % 12) >= 0.05:
            raise_to = round(0.8 * statistics.median(m["vel"] for m in g))
            why = f"inaudible - held {round(n['end'] - n['start'], 1)} s in a chord it fits: maybe meant to sound"
        add(n, "ghost", "delete", True, why, raise_to=raise_to)

    # double strike: same key twice within double_sec -> one note
    for p in sorted({n["pitch"] for n in live}):
        same = [n for n in live if n["pitch"] == p and id(n) not in taken]
        for a, b in zip(same, same[1:]):
            if b["start"] - a["start"] <= double_sec and id(a) not in taken:
                add(b, "double", "merge", True,
                    f"{pname(p)} struck twice {round((b['start'] - a['start']) * 1000)} ms apart", into=a)

    # slip: very short note grazed together with a chord
    for n in live:
        if id(n) in taken or n["end"] - n["start"] > slip_sec: continue
        g = group(n)
        held = [m for m in g if m["end"] - m["start"] >= 3 * (n["end"] - n["start"])]
        if not held: continue
        # a grace note comes clearly before a main note a step away: keep it
        if any(1 <= abs(m["pitch"] - n["pitch"]) <= 2 and m["start"] - n["start"] >= 0.025 for m in g): continue
        # in a fast line short notes are normal
        line = [m for m in live if id(m) not in taken and 0.06 <= abs(m["start"] - n["start"]) <= 0.3
                and m["end"] - m["start"] <= 0.15 and abs(m["pitch"] - n["pitch"]) <= 4]
        if len(line) >= 2: continue
        adj = [m for m in g if 1 <= abs(m["pitch"] - n["pitch"]) <= 2 and m["vel"] >= 0.8 * n["vel"]]
        w = harmony(live, n["start"] + 0.05, skip=[n])
        pc = n["pitch"] % 12
        clash = max(pc_share(w, (pc + 1) % 12), pc_share(w, (pc - 1) % 12)) >= 0.2   # a semitone against the chord
        foreign = pc_share(w, pc) < 0.04 and (pc not in scale or clash)
        if adj:
            add(n, "slip", "delete", True,
                f"{round((n['end'] - n['start']) * 1000)} ms graze next to "
                f"{pname(adj[0]['pitch'])} (vel {adj[0]['vel']})")
        elif foreign:
            quiet = n["vel"] <= statistics.median(m["vel"] for m in g)
            add(n, "slip", "delete", quiet,
                f"{round((n['end'] - n['start']) * 1000)} ms note "
                + ("outside the key" if pc not in scale else "a semitone against the chord")
                + ("" if quiet else " (as loud as the chord - review)"))

    # split chord: two hits 30-70 ms apart in a pulsed section -> minority onto the main hit
    groups = onsets([n for n in live if id(n) not in taken], ghost_vel)
    merged = []                            # regroup with the wider split window
    for g in groups:
        if merged and g[0]["start"] - merged[-1][0]["start"] <= split_max: merged[-1].extend(g)
        else: merged.append(list(g))
    for g in merged:
        if section_at(pmap, g[0]["start"])["kind"] != "pulsed": continue
        hits = []
        for n in sorted(g, key=lambda n: n["start"]):
            if hits and n["start"] - hits[-1][-1]["start"] < 0.015: hits[-1].append(n)
            else: hits.append([n])
        if len(hits) != 2: continue        # 3+ hits = a roll: deliberate
        a, b = hits
        gap = b[0]["start"] - a[-1]["start"]
        if not split_min <= gap <= split_max: continue
        if len(a) == 1 and len(b) >= 1 and a[0]["end"] - a[0]["start"] < 0.1 and \
                any(1 <= abs(a[0]["pitch"] - m["pitch"]) <= 2 for m in b): continue   # grace note
        main, minor = (a, b) if sum(n["vel"] for n in a) >= sum(n["vel"] for n in b) else (b, a)
        to = statistics.median(n["start"] for n in main)
        for n in minor:
            add(n, "split", "move", True,
                f"chord struck in two hits {round(gap * 1000)} ms apart - joined to "
                f"{'/'.join(pname(m['pitch']) for m in main)}", to=to, shift_ms=round((to - n["start"]) * 1000))

    # possible wrong note: never automatic
    for n in live:
        if id(n) in taken or n["vel"] <= ghost_vel or n["pitch"] % 12 in scale: continue
        w = harmony(live, n["start"] + 0.05, skip=[n])
        if pc_share(w, n["pitch"] % 12) >= 0.05: continue      # the harmony uses it (e.g. a secondary dominant)
        after = [m for m in live if 0 < m["start"] - n["start"] <= 0.6 and 1 <= abs(m["pitch"] - n["pitch"]) <= 2]
        before = [m for m in live if 0 < n["start"] - m["start"] <= 0.6 and 1 <= abs(m["pitch"] - n["pitch"]) <= 2]
        if after and before: continue                          # chromatic passing / neighbour tone
        cands = [(pc_share(w, (n["pitch"] + d) % 12), d) for d in (-1, 1, -2, 2) if (n["pitch"] + d) % 12 in scale]
        share, d = max(cands) if cands else (0, 0)
        if share < 0.1: continue
        together = [m for m in group(n, 0.04, 0.04) if m["pitch"] == n["pitch"] + d]
        add(n, "wrong", "delete" if together else "transpose", False,
            f"{NAMES[n['pitch'] % 12]} is outside {pmap['key']['name']} and the chord; "
            f"{NAMES[(n['pitch'] + d) % 12]} is {round(share * 100)}% of the sound"
            + (" and is pressed with it" if together else ""), to=pname(n["pitch"] + d), semitones=d)

    fixes.sort(key=lambda f: (f["time"], f["pitch"]))
    for k, f in enumerate(fixes, 1): f["id"] = f"N{k}"
    return fixes


# ---------------------------------------------------------------- apply (on the event list)

def apply_fixes(events, sec, fixes, raise_ids=()):
    """Return a new event list [[sec, flags, hex], ...] in seconds with the fixes applied.
    raise_ids: ghost ids to make audible (velocity raise_to) instead of deleting."""
    drop, newhex, move = set(), {}, {}
    raise_ids = set(raise_ids)
    for f in fixes:
        n = f["note"]
        if f["kind"] == "ghost" and f["id"] in raise_ids and f.get("raise_to"):
            h = events[n["on"]][2]; newhex[n["on"]] = h[:4] + f"{f['raise_to']:02x}"
        elif f["action"] == "delete":
            drop |= {n["on"], n["off"]}
        elif f["action"] == "merge":       # one note: first onset, louder velocity, later release
            a = f["into"]
            first_off = min(a["off"], n["off"], key=lambda i: sec[i])
            drop |= {n["on"], first_off}
            v = max(a["vel"], n["vel"])
            h = events[a["on"]][2]; newhex[a["on"]] = h[:4] + f"{v:02x}"
        elif f["action"] == "transpose":
            p = n["pitch"] + f["semitones"]
            for i in (n["on"], n["off"]):
                h = events[i][2]; newhex[i] = h[:2] + f"{p:02x}" + h[4:]
        elif f["action"] == "move":        # keep the note's length
            d = f["to"] - n["start"]
            move[n["on"]] = sec[n["on"]] + d
            move[n["off"]] = sec[n["off"]] + d
    out = [[move.get(i, sec[i]), e[1], newhex.get(i, e[2])] for i, e in enumerate(events) if i not in drop]
    return sorted(out, key=lambda e: e[0])   # stable: same-time events keep their order
