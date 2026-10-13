"""
tempo_analysis.py - find the played beats and bars of a freely played (rubato) performance and
build a tempo map that puts DAW beats on the played beats.

Input is DAW-agnostic: notes in seconds plus sustain-pedal (CC64) events.
Used by tempo_sync.py (live REAPER via MCP).

How: a bar-pointer model (as in probabilistic beat/downbeat trackers) decoded with Viterbi over
the whole piece at once. State = (subdivision period, position in the bar). Between two onsets
the model picks how many subdivisions passed and how the tempo drifted; costs:
  - timing fit of the gap to a whole number of subdivisions,
  - tempo drift (smooth rubato is cheap, jumps are expensive),
  - distance to the piece's main pulse (stops the classic double/half tempo errors and carries
    the tempo through slow passages with few notes, e.g. a prelude of long chords),
  - downbeat evidence (new bass note, sustain pedal re-press, full chord) wants beat 1,
  - bars of another length (2..6 beats) are allowed but expensive.
"""
import math, statistics

ORNAMENT = 0.42          # onsets closer than this many main-pulse periods after the previous one are not on the grid
SIG, TAU = 0.09, 0.035   # timing noise (log ratio), tempo drift per subdivision (log)
W_PRIOR, W_K = 0.6, 0.6  # pull to the main pulse (per pulse of time), cost per subdivision
W_DOWN, W_STRONG, W_OFF, W_PICKUP = 2.0, 0.6, 1.2, 3.0
BEAM = 600


def main_pulse(times):
    """Most common gap between onsets in 0.12..0.7 s (log histogram mode)."""
    g = [b - a for a, b in zip(times, times[1:]) if 0.12 <= b - a <= 0.7]
    if len(g) < 8: raise ValueError("not enough notes to detect a pulse")
    cands = [0.12 * 1.02 ** k for k in range(90) if 0.12 * 1.02 ** k <= 0.7]
    best = max(cands, key=lambda c: sum(math.exp(-(math.log(x / c) / 0.07) ** 2) for x in g))
    return statistics.median([x for x in g if abs(math.log(x / best)) < 0.2])


def onset_groups(notes, pedal, cluster_sec):
    """Onsets (chords) with downbeat evidence D and relative strength S."""
    ons = []
    for s, e, p, v in notes:
        if ons and s - ons[-1]["t"] < cluster_sec: ons[-1]["notes"].append((p, v, e - s))
        else: ons.append({"t": s, "notes": [(p, v, e - s)]})
    presses = [t for (t0, v0), (t, v) in zip([(-1, 0)] + pedal, pedal) if v0 < 64 <= v]
    vs = [sum(v for _, v, _ in o["notes"]) for o in ons]
    med = statistics.median(vs) if vs else 1
    prev_bass = None
    for o, v in zip(ons, vs):
        p, _, d = min(o["notes"])
        D = 0.0
        if p <= 55 and d >= 0.5:                       # a held bass note (G3 or lower)
            D += 1.0 + (0.5 if p != prev_bass else 0.0)
            prev_bass = p
        if any(-0.1 <= r - o["t"] <= 0.35 for r in presses): D += 0.8
        if len(o["notes"]) >= 3: D += 0.3
        o["D"], o["S"] = D, min(v / med, 3.0)
    return ons


def track(ons, anchor, SPB, BPB):
    """Viterbi bar-pointer decoding. Returns (kept onsets with "slot", bar start slots)."""
    L0 = SPB * BPB
    alt = {b * SPB: (0.0 if b == BPB else 8.0 + 2.0 * abs(b - BPB)) for b in range(2, 7)}
    alt.setdefault(L0, 0.0)
    pmax = max(alt)
    kept = [ons[0]]
    for o in ons[1:]:
        if o["t"] - kept[-1]["t"] < ORNAMENT * anchor:
            if len(kept) > 1 and o["D"] + o["S"] > kept[-1]["D"] + kept[-1]["S"] + 1.5: kept[-1] = o
            continue
        kept.append(o)
    P = [0.08 * 1.03 ** k for k in range(300) if 0.08 * 1.03 ** k <= 1.2]
    P = [p for p in P if 0.45 * anchor <= p <= 2.2 * anchor]
    lp = [math.log(p) for p in P]
    prior = [((x - math.log(anchor)) / 0.35) ** 2 for x in lp]

    def emit(o, pos):
        if pos == 0: return -W_DOWN * o["D"] - W_STRONG * o["S"]
        if pos % SPB == 0:
            half = pos * 2 == L0
            return -W_STRONG * o["S"] * (0.6 if half else 0.4) - (0.5 * o["D"] if half else 0.0)
        return W_OFF * o["D"]

    cost = {(i, pos): prior[i] + (0.0 if pos == 0 else W_PICKUP) + emit(kept[0], pos)
            for i in range(len(P)) for pos in range(L0)}
    back = []
    for j in range(1, len(kept)):
        ioi = kept[j]["t"] - kept[j - 1]["t"]
        new, bp = {}, {}
        for (i, pos), c in sorted(cost.items(), key=lambda kv: kv[1])[:BEAM]:
            for i2 in range(max(0, i - 2), min(len(P), i + 3)):
                x = ioi / P[i2]
                for k in {max(1, math.floor(x)), max(1, math.ceil(x))}:
                    base = (c + (math.log(x / k) / SIG) ** 2 + ((lp[i2] - lp[i]) / (TAU * math.sqrt(k))) ** 2
                            + W_K * k + W_PRIOR * prior[i2] * ioi / anchor)
                    end = pos + k
                    opts = [((end - L) % L0, lc, L) for L, lc in alt.items() if pos < L <= end]
                    if end < pmax: opts.append((end, 0.0, None))
                    for npos, lc, L in opts:
                        if npos >= pmax: continue
                        tot = base + lc + emit(kept[j], npos)
                        if tot < new.get((i2, npos), 1e300):
                            new[(i2, npos)] = tot; bp[(i2, npos)] = ((i, pos), k, L)
        if not new: raise ValueError(f"no consistent pulse around {kept[j]['t']:.2f}s")
        cost = new; back.append(bp)
    s = min(cost, key=cost.get)
    path, steps = [s], []
    for bp in reversed(back):
        prev, k, L = bp[s]; steps.append((k, L)); s = prev; path.append(s)
    path.reverse(); steps.reverse()
    # absolute slots + every bar line (also those between two onsets)
    slot = path[0][1]
    kept[0]["slot"] = slot
    starts = [0]
    for j, ((k, L), (i, pos)) in enumerate(zip(steps, path[:-1]), 1):
        if L is not None:
            b = slot - pos + L
            while b <= slot + k:
                starts.append(b); b += L0
        slot += k
        kept[j]["slot"] = slot
    return kept, starts


def analyze(notes, pedal=(), slots_per_beat=2, beats_per_bar=4, per_bar=False, cluster_sec=0.05, pulse_sec=None):
    """
    notes: [(start_sec, end_sec, pitch, velocity)]
    pedal: [(time_sec, value)] CC64 events
    pulse_sec: main subdivision period; detected from the whole piece when None
    Returns dict: tempo_points [[time, bpm, num, den, linear]], grid [(qn, sec)],
                  bar_beats, bar_start_qn, sec_to_qn(fn), report(dict)
    """
    SPB, BPB = slots_per_beat, beats_per_bar
    SPBAR = SPB * BPB
    notes = sorted(notes)
    all_ons = onset_groups(notes, sorted(pedal), cluster_sec)
    if len(all_ons) < 8:
        raise ValueError("not enough notes to detect a pulse")
    anchor = pulse_sec or main_pulse([o["t"] for o in all_ons])
    ons, starts = track(all_ons, anchor, SPB, BPB)
    pickup = ons[0]["slot"]
    last_slot = ons[-1]["slot"]
    while starts[-1] + SPBAR <= last_slot: starts.append(starts[-1] + SPBAR)
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
        if not pickup:                     # starts on a downbeat: lead-in of whole bars
            lead_beats = BPB * max(1, round(lead_beats / BPB))
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
        "notes": len(notes), "onsets": len(all_ons), "grid_onsets": len(ons),
        "main_pulse_sec": round(anchor, 4), "main_bpm": round(60.0 / anchor / SPB, 1),
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
