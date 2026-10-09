"""
tempo_analysis.py - find the played pulse/bars of a freely played (rubato) performance and
build a tempo map that puts DAW beats on the played beats.

Input is DAW-agnostic: note onsets in seconds plus sustain-pedal (CC64) events.
Used by tempo_sync.py (live REAPER via MCP).
"""
import math, statistics

W_SMOOTH, W_REF, W_ANCHOR, W_RESTART, W_ZERO, W_PICKUP = 4.0, 2.0, 3.0, 2.5, 6.0, 1.0


def analyze(notes, pedal=(), slots_per_beat=2, beats_per_bar=4, per_bar=False, cluster_sec=0.035):
    """
    notes: [(start_sec, end_sec, pitch, velocity)]
    pedal: [(time_sec, value)] CC64 events
    Returns dict: tempo_points [[time, bpm, num, den, linear]], grid [(qn, sec)],
                  bars [(start_slot, beats)], sec_to_qn(fn), report(dict)
    """
    SPB, BPB = slots_per_beat, beats_per_bar
    SPBAR = SPB * BPB
    notes = sorted(notes)

    # ---------- onset clusters (chords / rolled notes) ----------
    ons = []
    for s, e, p, v in notes:
        if ons and s - ons[-1]["t"] < cluster_sec: ons[-1]["notes"].append((p, v, e - s))
        else: ons.append({"t": s, "notes": [(p, v, e - s)]})
    if len(ons) < 4:
        raise ValueError("not enough notes to detect a pulse")
    gaps = [b["t"] - a["t"] for a, b in zip(ons, ons[1:])]
    g_med = statistics.median(gaps)

    # ---------- downbeat evidence: sustained notes + pedal re-press ----------
    lens = sorted(l for o in ons for _, _, l in o["notes"])
    long_thr = 0.6 * lens[int(len(lens) * 0.97)]
    pedal = sorted(pedal)
    repress = [t for (t0, v0), (t, v) in zip(pedal, pedal[1:]) if v0 < 64 <= v and t - t0 < 0.6]
    for o in ons:
        ev = 0.0
        if any(l >= long_thr for _, _, l in o["notes"]): ev += 1.0
        if any(-0.15 <= r - o["t"] <= 0.5 for r in repress): ev += 0.6
        o["ev"] = ev

    # ---------- local reference pulse ----------
    for k, o in enumerate(ons):
        w = [g for g in gaps[max(0, k - 10):k + 10] if g > 0.5 * g_med]
        o["uref"] = statistics.median(w) if w else g_med

    # ---------- DP: assign every onset to a subdivision slot ----------
    NMAX = 4 * SPB + 1
    INF = float("inf")
    # (phase, n_slots_from_prev) -> (cost, backptr, bar_restart). The first onset may sit on
    # any phase (pickup / anacrusis); starting on the downbeat is preferred.
    layer = {(ph, 1): (0.0 if ph == 0 else W_PICKUP + W_ANCHOR * ons[0]["ev"], None, False)
             for ph in range(SPBAR)}
    hist = [layer]
    for k in range(1, len(ons)):
        g = ons[k]["t"] - ons[k - 1]["t"]; ur = ons[k]["uref"]
        nl = {}
        for (ph, n0), (c0, _, _) in layer.items():
            u_prev = (ons[k - 1]["t"] - ons[k - 2]["t"]) / n0 if (k >= 2 and n0 > 0) else ons[k - 1]["uref"]
            for n in range(0, NMAX + 1):
                if n == 0:
                    if g > 0.4 * ur: continue
                    c = W_ZERO * (g / ur)
                else:
                    u = g / n
                    c = W_SMOOTH * math.log(u / u_prev) ** 2 + W_REF * math.log(u / ur) ** 2
                raw = ph + n
                opts = [(raw % SPBAR, False, 0.0)]
                if raw % SPB == 0 and SPBAR // 2 <= raw < SPBAR:      # shortened bar ends here
                    opts.append((0, True, W_RESTART))
                for nph, rs, rc in opts:
                    cc = c0 + c + rc + (W_ANCHOR * ons[k]["ev"] if nph != 0 else 0.0)
                    key = (nph, n)
                    if cc < nl.get(key, (INF,))[0]: nl[key] = (cc, (ph, n0), rs)
        layer = nl; hist.append(layer)
    state = min(layer, key=lambda s_: layer[s_][0])
    path = []
    for k in range(len(ons) - 1, -1, -1):
        c, bp, rs = hist[k][state]
        path.append((state, rs)); state = bp if bp else state
    path.reverse()
    pickup = path[0][0][0]                 # phase of the first onset (0 = starts on a downbeat)
    slot = pickup; marks = [0]
    ons[0]["slot"] = pickup
    for k in range(1, len(ons)):
        (ph, n), rs = path[k]
        slot += n; ons[k]["slot"] = slot
        if rs: marks.append(slot)

    # ---------- bars: regular bars between restarts ----------
    last_slot = ons[-1]["slot"]
    starts = []
    for j, m in enumerate(marks):
        nxt = marks[j + 1] if j + 1 < len(marks) else None
        s_ = m
        while True:
            starts.append(s_)
            if nxt is None:
                if s_ + SPBAR > last_slot: break
            elif s_ + SPBAR >= nxt: break
            s_ += SPBAR
    bars = [(s_, ((starts[j + 1] if j + 1 < len(starts) else s_ + SPBAR) - s_) // SPB)
            for j, s_ in enumerate(starts)]

    # ---------- slot -> time ----------
    slot_time = {}
    for o in ons: slot_time.setdefault(o["slot"], o["t"])
    known = sorted(slot_time)
    end_slot = max(bars[-1][0] + bars[-1][1] * SPB, last_slot + SPB)

    def time_of_slot(s):
        if s in slot_time: return slot_time[s]
        lo = max((k for k in known if k < s), default=None)
        hi = min((k for k in known if k > s), default=None)
        if lo is not None and hi is not None:
            return slot_time[lo] + (slot_time[hi] - slot_time[lo]) * (s - lo) / (hi - lo)
        if lo is None:   # before the first note (pickup bar): early median pulse
            us = [(slot_time[b] - slot_time[a]) / (b - a) for a, b in zip(known[:16], known[1:17])]
            return slot_time[known[0]] - (known[0] - s) * statistics.median(us)
        # past the last note: recent median pulse (not the final ritardando gap)
        us = [(slot_time[b] - slot_time[a]) / (b - a) for a, b in zip(known[-17:-1], known[-16:])]
        return slot_time[known[-1]] + (s - known[-1]) * statistics.median(us)

    # ---------- pickup: the first bar becomes a short bar starting on the first played beat ----------
    if pickup:
        s0 = (pickup // SPB) * SPB
        bars[0] = (s0, BPB - s0 // SPB)
    if time_of_slot(bars[0][0]) < -1e-6:
        raise ValueError(f"the first beat would start at {time_of_slot(bars[0][0]):.3f}s, before the project "
                         f"start - move the item right by at least {-time_of_slot(bars[0][0]):.3f}s and run again")

    # ---------- beat times + bar lengths (in beats), lead-in first ----------
    music_beats = [s_ + k * SPB for s_, b in bars for k in range(b)] + [bars[-1][0] + bars[-1][1] * SPB]
    while music_beats[-1] < end_slot: music_beats.append(music_beats[-1] + SPB)
    beat_times = [time_of_slot(x) for x in music_beats]
    bar_beats = [b for _, b in bars]
    t0 = beat_times[0]
    lead_beats = 0
    if t0 > 1e-3:
        # music starts after 0s: lead-in of whole beats at the opening tempo, as a short bar
        # (remainder) plus full bars, so the first played downbeat is a bar line
        lead_beats = max(1, round(t0 / (beat_times[1] - beat_times[0])))
        beat_times = [t0 * k / lead_beats for k in range(lead_beats)] + beat_times
        rem, full = lead_beats % BPB, lead_beats // BPB
        bar_beats = ([rem] if rem else []) + [BPB] * full + bar_beats
    lead_bar_count = len(bar_beats) - len(bars)

    bar_start_q = [0]
    for b in bar_beats: bar_start_q.append(bar_start_q[-1] + b)
    grid_q = bar_start_q + list(range(bar_start_q[-1] + 1, len(beat_times))) if per_bar \
        else list(range(len(beat_times)))
    grid = [(float(q), beat_times[q]) for q in sorted(set(grid_q)) if q < len(beat_times)]

    def sec_to_qn(t):
        if t <= grid[0][1]:
            (q0, t0_), (q1, t1) = grid[0], grid[1]
        else:
            for (q0, t0_), (q1, t1) in zip(grid, grid[1:]):
                if t < t1: break
        return q0 + (t - t0_) * (q1 - q0) / (t1 - t0_)

    # ---------- tempo points (time signature only where the bar length changes) ----------
    sig_at = {}
    prev = None
    for q, b in zip(bar_start_q, bar_beats):
        if b != prev: sig_at[q] = b
        prev = b
    tempo_points, bpms = [], []
    for (q0, t0_), (q1, t1) in zip(grid, grid[1:]):
        bpm = 60.0 * (q1 - q0) / (t1 - t0_)
        bpms.append(bpm)
        num = sig_at.get(int(q0), 0)
        tempo_points.append([t0_, bpm, num, 4 if num else 0, False])

    # ---------- report ----------
    first_slot = bars[0][0]
    devms = []
    for o in ons:
        ideal_q = lead_beats + (o["slot"] - first_slot) / SPB; ti = o["t"]
        for (q0, t0_), (q1, t1) in zip(grid, grid[1:]):
            if q0 <= ideal_q <= q1:
                ti = t0_ + (ideal_q - q0) * (t1 - t0_) / (q1 - q0); break
        devms.append((o["t"] - ti) * 1000)
    report = {
        "notes": len(notes), "onsets": len(ons),
        "bars": len(bar_beats), "lead_in_bars": lead_bar_count, "lead_in_beats": lead_beats,
        "pickup_beats": bar_beats[lead_bar_count] if pickup else 0,
        "first_note_sec": round(ons[0]["t"], 4),
        "irregular_bars": [[k + 1, b] for k, b in enumerate(bar_beats) if b != BPB],
        "tempo_points": len(tempo_points),
        "bpm_min": round(min(bpms), 1), "bpm_max": round(max(bpms), 1),
        "bpm_median": round(statistics.median(bpms), 1),
        "per_bar_bpm": [round(60.0 * b / (time_of_slot(s_ + b * SPB) - time_of_slot(s_)), 1) for s_, b in bars],
        "bar_starts_sec": [round(beat_times[q], 3) for q in bar_start_q[:-1]],
        "onset_grid_dev_ms_median": round(statistics.median(abs(x) for x in devms), 1),
        "onset_grid_dev_ms_max": round(max(abs(x) for x in devms), 1),
    }
    return {"tempo_points": tempo_points, "grid": grid, "bar_beats": bar_beats, "bar_start_qn": bar_start_q[:-1],
            "sec_to_qn": sec_to_qn, "report": report}
