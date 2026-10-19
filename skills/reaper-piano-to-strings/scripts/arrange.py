"""
arrange.py - turn a piano take into a five-part string arrangement (DAW-independent).

Works on a raw event list [[pos, flags, hex], ...] plus a time in quarter notes (project qn) for
every event, and returns notes and CCs per instrument. Used by strings.py (live REAPER via MCP).

The orchestration is not invented, it is read out of the piano part:

1. streams()      - split the take into monophonic lines by pitch proximity (an arpeggio or an
                    Alberti bass stays one line, a held chord becomes one line per note).
2. melody         - per bar the line that sounds most like a tune: the top line by default, but
                    a louder, non-repeating lower line wins (a left-hand theme under right-hand
                    chords). Smoothed over the piece; every hand-off away from the top is flagged.
                    Melody -> Violins 1, or Cellos/Violas when it lies below the violin.
3. figures        - other lines that keep moving (arpeggios, Alberti bass, inner runs) are kept as
                    played on the free instrument whose range fits best (Violas preferred, then
                    Cellos / Violins 2), shifted by whole octaves only when needed.
4. harmony        - per beat, everything that sounds (sustain pedal included) is voiced onto the
                    remaining instruments by a beam search over the whole piece: Basses take the
                    bass note (inversions kept; they rest while the bass lies high), the others
                    take chord tones as played, moving as little as possible, never crossing,
                    Cellos-Basses at least a 5th apart (or unison/octave). Too few notes ->
                    doubling; chord tones left over -> divisi in Violins 2 / Violas.
5. polish         - pedal points over stepwise bass lines, legato overlap, CC1 (dynamics, from the
                    played velocities) and CC11 (phrase swells).
"""
import bisect, math, os, statistics, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..",
                                "reaper-performance-cleanup", "scripts"))
from piece import parse, estimate_key, pname  # noqa: E402

GROUP_QN = 0.1          # notes starting this close (in quarter notes) form one onset
EARLY_QN = 0.25        # a note this much ahead of a barline (rubato) belongs to the next bar
# (name, colour, playable range, comfortable range) as sounding MIDI pitches, low to high
INSTR = [
    ("Basses",    "#e39a6b", (28, 67),  (28, 55)),
    ("Cellos",    "#e05a5a", (36, 81),  (36, 67)),
    ("Violas",    "#7f9de0", (48, 88),  (48, 76)),
    ("Violins 2", "#b38be0", (55, 100), (55, 84)),
    ("Violins 1", "#3fcf6a", (55, 103), (55, 91)),
]
CB, VC, VA, V2, V1 = range(5)
NAME = [i[0] for i in INSTR]


def load(events, times, ghost_vel=8):
    """Audible notes (sustain pedal folded into 'ring') from a raw event list."""
    notes, _ = parse(events, times)
    return [n for n in notes if not n["muted"] and n["vel"] > ghost_vel]


def _comf(i, p): return INSTR[i][3][0] <= p <= INSTR[i][3][1]
def _play(i, p): return INSTR[i][2][0] <= p <= INSTR[i][2][1]


# ---------------------------------------------------------------- 1. streams

def streams(notes, new_cost=10.0, held_cost=1.5, idle_qn=4.0):
    """Assign every note a stream id (n['stream']) by order-preserving matching of each onset
    group to the existing lines. Returns the number of streams."""
    groups = []
    for n in notes:
        if groups and n["start"] - groups[-1][0]["start"] < GROUP_QN: groups[-1].append(n)
        else: groups.append([n])
    last = []                               # last note of every stream
    for g in groups:
        g.sort(key=lambda n: n["pitch"])
        t = g[0]["start"]
        cand = sorted((s for s in range(len(last)) if t - last[s]["start"] < 4 * idle_qn),
                      key=lambda s: last[s]["pitch"])

        def cost(s, n):
            ln = last[s]
            d = abs(n["pitch"] - ln["pitch"])
            c = d if d <= 7 else 7 + (d - 7) * 0.5
            if ln["end"] > t + 0.05: c += held_cost
            if t - ln["start"] > idle_qn: c += 3
            return c
        N, M = len(g), len(cand)
        dp = [[math.inf] * (M + 1) for _ in range(N + 1)]
        dp[0] = [0.0] * (M + 1)
        for i in range(1, N + 1):
            dp[i][0] = dp[i - 1][0] + new_cost
            for j in range(1, M + 1):
                dp[i][j] = min(dp[i][j - 1], dp[i - 1][j] + new_cost,
                               dp[i - 1][j - 1] + cost(cand[j - 1], g[i - 1]))
        i, j = N, M
        while i > 0:
            if j > 0 and dp[i][j] == dp[i][j - 1]: j -= 1
            elif j > 0 and dp[i][j] == dp[i - 1][j - 1] + cost(cand[j - 1], g[i - 1]):
                g[i - 1]["stream"] = cand[j - 1]; i -= 1; j -= 1
            else:
                g[i - 1]["stream"] = None; i -= 1
        for n in g:
            if n["stream"] is None:
                n["stream"] = len(last); last.append(n)
            else: last[n["stream"]] = n
    return len(last)


# ---------------------------------------------------------------- 2. melody

def _repetition(ps):
    """How much a pitch sequence repeats itself with a period of 2-4 notes (0..1): ostinato."""
    if len(ps) < 4: return 0.0
    return max(sum(ps[i] == ps[i - k] for i in range(k, len(ps))) / (len(ps) - k) for k in (2, 3, 4) if len(ps) > k)


def melody(notes, q0, nbars, bar=4.0, switch=2.5):
    """Melody stream per bar (None = no melody) and the bars where it is not the top line."""
    rows = []
    for k in range(nbars):
        a, b = q0 + k * bar - EARLY_QN, q0 + (k + 1) * bar - EARLY_QN
        by = {}
        for n in notes:
            if a <= n["start"] < b or (n["start"] < a and n["end"] - a >= bar / 2):
                by.setdefault(n["stream"], []).append(n)
        if not by: rows.append({}); continue
        allv = statistics.mean(n["vel"] for ns in by.values() for n in ns)
        tops = sorted(by, key=lambda s: -statistics.mean(n["pitch"] for n in by[s]))
        sc = {}
        for r, s in enumerate(tops):
            ns = by[s]
            sc[s] = ((1.5 if r == 0 else -0.4 * r)
                     + max(-2, min(2, (statistics.mean(n["vel"] for n in ns) - allv) / 8))
                     - 2 * _repetition([n["pitch"] for n in ns])
                     - (0.5 if all(n["start"] < a for n in ns) else 0))
        rows.append({"score": sc, "top": tops[0]})
    # Viterbi over bars
    prev, back = {None: 0.0}, []
    for row in rows:
        cur, bk = {}, {}
        for s, v in list(row.get("score", {}).items()) + [(None, -3.0 if row else 0.0)]:
            best = max(prev, key=lambda p: prev[p] - (0 if p == s or p is None or s is None else switch))
            cur[s] = prev[best] - (0 if best == s or best is None or s is None else switch) + v
            bk[s] = best
        prev = cur; back.append(bk)
    s = max(prev, key=prev.get)
    out = []
    for bk in reversed(back):
        out.append(s); s = bk[s]
    out.reverse()
    flags = [k for k, (s, row) in enumerate(zip(out, rows)) if s is not None and s != row.get("top")]
    return out, flags


# ---------------------------------------------------------------- 3. figures

def is_figure(ns):
    """True if a line moves like a figure within one bar: >= 3 onsets, median gap <= 3/4 beat,
    and not a single repeated note."""
    st = sorted(n["start"] for n in ns)
    if len(st) < 3: return False
    gaps = [b - a for a, b in zip(st, st[1:])]
    return statistics.median(gaps) <= 0.75 and len({n["pitch"] for n in ns}) >= 2


def _fit(i, pitches):
    """Best whole-octave shift to play these pitches on instrument i: (cost, shift)."""
    best = None
    for sh in (0, -12, 12, -24, 24):
        ps = [p + sh for p in pitches]
        if not all(_play(i, p) for p in ps): continue
        c = 3 * abs(sh) / 12 + 5 * sum(not _comf(i, p) for p in ps) / len(ps)
        if best is None or c < best[0]: best = (c, sh)
    return best


PREF = {VA: 0.0, VC: 0.5, V2: 0.5, V1: 1.0}


# ---------------------------------------------------------------- 4. harmony

def _sounding(notes, a, b, skip):
    """Pitch -> weight (velocity x overlap) of what sounds in [a, b), pedal included."""
    w = {}
    for n in notes:
        if id(n) in skip: continue
        ov = min(b, n["ring"]) - max(a, n["start"])
        if ov >= 0.2 * (b - a) or a <= n["start"] < b:
            w[n["pitch"]] = w.get(n["pitch"], 0) + n["vel"] * max(ov, 0.1)
    return w


def _voicings(insts, pitch_w, strong, covered, mel, bass_opts):
    """All non-crossing voicings (tuple of pitch per instrument in `insts`, low to high, Basses
    first if present) with their static cost, best first."""
    played = set(pitch_w)
    cands = []
    for i in insts:
        if i == CB:
            cands.append(bass_opts); continue
        cs = [p for p in range(INSTR[i][3][0], INSTR[i][3][1] + 1)
              if p % 12 in {q % 12 for q in played} and min(abs(p - q) for q in played) <= 12]
        cands.append(cs or [None])
    out = []

    def static(v):
        c = 0.0
        pcs = set(covered)
        ps = [p for p in v if p is not None]
        for i, p in zip(insts, v):
            if p is None: continue
            pcs.add(p % 12)
            if p not in played: c += 1.2
            if p % 12 not in strong: c += 0.8
            if mel is not None and p > mel and i != CB: c += 3
        c += 3 * len(strong - pcs)
        c += 1.5 * (len(ps) - len(set(ps)))
        c += 0.3 * (len(ps) - len({p % 12 for p in ps}) - (len(ps) - len(set(ps))))
        if CB in insts and VC in insts:
            cb, vc = v[insts.index(CB)], v[insts.index(VC)]
            if cb is not None and vc is not None and 0 < vc - cb < 7: c += 4
        up = [p for i, p in zip(insts, v) if i != CB and p is not None]
        c += 0.5 * sum(b - a > 12 for a, b in zip(up, up[1:]))
        return c

    def rec(k, lo, acc):
        if k == len(insts):
            out.append((static(tuple(acc)), tuple(acc))); return
        for p in cands[k]:
            if p is not None and p < lo: continue
            rec(k + 1, lo if p is None else p, acc + [p])
    rec(0, 0, [])
    out.sort()
    return out[:40]


def _trans(ia, va, ib, vb):
    c = 0.0
    for i, p in zip(ib, vb):
        if i not in ia: continue
        q = va[ia.index(i)]
        if (p is None) != (q is None): c += 0.5
        elif p is not None:
            d = abs(p - q)
            c += -0.2 if d == 0 else 0.15 * d + (1.5 if d > 7 else 0)
    return c


# ---------------------------------------------------------------- main entry

def arrange(notes, bar=4.0, max_figures=2, bass_rest_from=52, pedal=True, legato=True, ccs=True):
    """Returns {"parts": [[note dicts] per instrument], "cc": [[(qn, cc, val)] per instrument],
    "flags": [...], "key": ..., "stats": ...}. Note dicts: start, end, pitch, vel, role."""
    flags = []
    if not notes: return {"parts": [[] for _ in INSTR], "cc": [[] for _ in INSTR], "flags": [], "key": None}
    nstreams = streams(notes)
    q0 = math.floor((min(n["start"] for n in notes) + EARLY_QN) / bar) * bar
    q1 = max(n["ring"] for n in notes)
    nbars = int(math.ceil((q1 - q0) / bar))
    key = estimate_key(notes)

    # --- melody: stream per bar, instrument per run of bars ---
    mel, mflags = melody(notes, q0, nbars, bar)
    for k in mflags:
        flags.append({"qn": q0 + k * bar, "kind": "melody",
                      "msg": "melody taken from a lower line (louder / less repetitive than the top) - check"})
    mel_notes, mel_inst = set(), [None] * nbars
    k = 0
    while k < nbars:
        s = mel[k]
        j = k
        while j < nbars and mel[j] == s: j += 1
        if s is not None:
            ns = [n for n in notes if n["stream"] == s and q0 + k * bar - EARLY_QN <= n["start"] < q0 + j * bar - EARLY_QN]
            if ns:
                med = statistics.median(n["pitch"] for n in ns)
                i = V1 if med >= 55 else VC if med >= 40 else CB
                fit = _fit(i, [n["pitch"] for n in ns]) or _fit(V1, [n["pitch"] for n in ns]) or (0, 0)
                if fit[1]: flags.append({"qn": ns[0]["start"], "kind": "octave",
                                         "msg": f"melody moved {fit[1]:+d} semitones to fit {NAME[i]}"})
                for n in ns:
                    n["role"], n["inst"], n["shift"] = "melody", i, fit[1]
                    mel_notes.add(id(n))
                if i != V1: flags.append({"qn": ns[0]["start"], "kind": "melody",
                                          "msg": f"melody lies low -> {NAME[i]} for {j - k} bar(s)"})
                for b in range(k, j): mel_inst[b] = i
        k = j

    # --- figures: per bar, up to max_figures moving lines, kept as played ---
    fig_insts = [set() for _ in range(nbars)]
    prev_figs = []                           # (low, high, instrument) of the previous bar's figures
    for k in range(nbars):
        a, b = q0 + k * bar - EARLY_QN, q0 + (k + 1) * bar - EARLY_QN
        by = {}
        for n in notes:
            if a <= n["start"] < b and id(n) not in mel_notes: by.setdefault(n["stream"], []).append(n)
        # short notes that only fill the gaps of a busy line, next to it in register, belong to it:
        # one broken-chord figure the stream split cut in two, or an arpeggio's top note picked up
        # by an idle chord line (two real voices share onsets on the beats and stay apart)
        for s in sorted(by, key=lambda s: -len(by.get(s, []))):
            if s not in by or len(by[s]) < 3: continue
            lo, hi = min(n["pitch"] for n in by[s]) - 12, max(n["pitch"] for n in by[s]) + 12
            for o in [o for o in by if o != s and len(by[o]) <= len(by[s])]:
                if all(lo <= n["pitch"] <= hi and n["end"] - n["start"] <= 1.0 and all(abs(n["start"] - x["start"]) > GROUP_QN for x in by[s])
                       for n in by[o]):
                    by[s] = sorted(by[s] + by.pop(o), key=lambda n: n["start"])
        figs = sorted((s for s, ns in by.items() if is_figure(ns)), key=lambda s: -len(by[s]))
        if len(figs) > max_figures:
            flags.append({"qn": a, "kind": "figure", "msg": f"{len(figs)} moving lines, kept {max_figures}, "
                          "the rest is sustained as harmony"})
        free = [i for i in (VA, VC, V2, V1) if i != mel_inst[k]]
        bottom = min((n["pitch"] for ns in by.values() for n in ns), default=0)
        cur_figs = []
        for s in figs[:max_figures]:
            ps = [n["pitch"] for n in by[s]]
            # stay on the instrument that played a figure in the same register in the previous bar
            same = {i for lo, hi, i in prev_figs if lo <= max(ps) and min(ps) <= hi}
            # a figure that carries the bass line is a cello figure, an inner one a viola figure
            pref = {**PREF, **({VC: 0.0, VA: 0.5} if min(ps) <= bottom else {})}
            opts = []
            for i in free:
                f = _fit(i, ps)
                if f: opts.append((f[0] + pref[i] - (2 if i in same else 0), i, f[1]))
            if not opts: continue
            _, i, sh = min(opts)
            free.remove(i); fig_insts[k].add(i); cur_figs.append((min(ps), max(ps), i))
            for n in by[s]: n["role"], n["inst"], n["shift"] = "figure", i, sh
            if sh: flags.append({"qn": a, "kind": "octave", "msg": f"figure moved {sh:+d} semitones for {NAME[i]}"})
        prev_figs = cur_figs

    # --- harmony: beam search over beats ---
    melodic = {id(n) for n in notes if n.get("role") == "melody"}
    beats = []
    q = q0
    while q < q1 - 1e-6:
        k = min(int((q - q0 + EARLY_QN) // bar), nbars - 1)
        w = _sounding(notes, q, q + 1, melodic)
        insts = [i for i in range(5) if i != mel_inst[k] and i not in fig_insts[k]]
        cov = {n["pitch"] % 12 for n in notes if id(n) in melodic or n.get("role") == "figure"
               if n["start"] < q + 1 and n["end"] > q}
        mp = [n["pitch"] + n["shift"] for n in notes if id(n) in melodic and n["start"] < q + 1 and n["end"] > q]
        tot = sum(w.values()) or 1
        pcw = {}
        for p, x in w.items(): pcw[p % 12] = pcw.get(p % 12, 0) + x
        lows = [p for p in sorted(w) if w[p] / tot >= 0.06] or sorted(w)
        on = [n["start"] for n in notes if q <= n["start"] < q + 0.5 and id(n) not in melodic]
        beats.append({"q": q, "w": w, "insts": insts, "strong": {c for c, x in pcw.items() if x / tot >= 0.12},
                      "covered": cov, "mel": max(mp) if mp else None, "bass": lows[0] if lows else None,
                      "onset": min(on) if on else q,
                      "vel": round(statistics.mean(n["vel"] for n in notes if q <= n["start"] < q + 1))
                      if any(q <= n["start"] < q + 1 for n in notes) else None})
        q += 1.0
    # Basses rest while the bass lies high for a while (>= two bars)
    high = [b["bass"] is not None and b["bass"] >= bass_rest_from for b in beats]
    k = 0
    while k < len(beats):
        j = k
        while j < len(beats) and high[j] == high[k]: j += 1
        if high[k] and j - k >= 2 * bar:
            for b in beats[k:j]:
                if CB in b["insts"]: b["insts"].remove(CB)
            flags.append({"qn": beats[k]["q"], "kind": "bass-rest",
                          "msg": f"bass above {pname(bass_rest_from)} for {j - k} beats -> Basses rest"})
        k = j
    memo, layers = {}, []
    for b in beats:
        if not b["w"] or not b["insts"]:
            layers.append([(0.0, tuple(None for _ in b["insts"]))]); continue
        bo = [p for p in (b["bass"], b["bass"] - 12, b["bass"] + 12, b["bass"] - 24)
              if _comf(CB, p)] or [None]
        mk = (tuple(sorted(b["w"])), frozenset(b["strong"]), frozenset(b["covered"]), tuple(b["insts"]),
              b["mel"], tuple(bo))
        if mk not in memo:
            memo[mk] = _voicings(b["insts"], b["w"], b["strong"], b["covered"], b["mel"], bo)
        layers.append(memo[mk])
    beam = [(0.0, 0, None)]                 # (cost, voicing index, back pointer)
    hist = []
    for t, layer in enumerate(layers):
        nb = []
        for vi, (sc, v) in enumerate(layer):
            best = None
            for bi, (c, pvi, _) in enumerate(beam):
                tc = c + sc
                if t > 0:
                    tc += _trans(beats[t - 1]["insts"], layers[t - 1][pvi][1], beats[t]["insts"], v)
                if best is None or tc < best[0]: best = (tc, vi, bi)
            nb.append(best)
        nb.sort()
        beam = nb[:12]
        hist.append(beam)
    voicing = [None] * len(beats)
    bi = 0
    for t in range(len(beats) - 1, -1, -1):
        c, vi, back = hist[t][bi]
        voicing[t] = layers[t][vi][1]
        bi = back if back is not None else 0
    lines = [[] for _ in INSTR]             # per instrument: per beat list of (pitch, role)
    for t, b in enumerate(beats):
        per = {i: [] for i in range(5)}
        for i, p in zip(b["insts"], voicing[t]):
            if p is not None: per[i].append((p, "harmony"))
        # divisi for chord tones nobody plays
        have = {p % 12 for ps in per.values() for p, _ in ps} | b["covered"]
        for pc in sorted(b["strong"] - have):
            for i in (V2, VA):
                if not per[i]: continue
                main = per[i][0][0]
                opts = [p for p in range(main - 9, main + 10) if p % 12 == pc and 2 <= abs(p - main) <= 9
                        and _comf(i, p) and (b["mel"] is None or p <= b["mel"])]
                if opts and len(per[i]) == 1:
                    per[i].append((min(opts, key=lambda p: abs(p - main)), "divisi")); break
        for i in range(5): lines[i].append(per[i])

    # --- pedal points over stepwise bass lines ---
    if pedal:
        bass = [(t, b["bass"]) for t, b in enumerate(beats) if b["bass"] is not None]
        ch = [(t, p) for k_, (t, p) in enumerate(bass) if k_ == 0 or p != bass[k_ - 1][1]]
        k = 0
        while k < len(ch) - 3:
            j, d = k + 1, ch[k + 1][1] - ch[k][1]
            while j < len(ch) and 1 <= abs(ch[j][1] - ch[j - 1][1]) <= 2 and (ch[j][1] - ch[j - 1][1]) * d > 0:
                j += 1
            if j - k >= 4:
                t0 = ch[k][0]
                top = beats[t0]["mel"]
                owner = mel_inst[min(int((beats[t0]["q"] - q0 + EARLY_QN) // bar), nbars - 1)]
                if top is None:
                    ups = [(p, i) for i in (V1, V2, VA) for p, r in lines[i][t0] if r == "harmony"]
                    if ups: top, owner = max(ups)
                if top is not None and owner is not None:
                    end = t0
                    for t in range(t0, ch[j][0] if j < len(ch) else len(beats)):
                        if top % 12 in {p % 12 for p in beats[t]["w"]} | beats[t]["covered"]: end = t
                    if end - t0 >= 4:
                        for t in range(t0, end + 1):
                            if all(p != top for p, _ in lines[owner][t]): lines[owner][t].append((top, "pedal"))
                        flags.append({"qn": beats[t0]["q"], "kind": "pedal",
                                      "msg": f"{pname(top)} held as a pedal point in {NAME[owner]} (divisi) over "
                                             f"the stepwise bass, {end - t0 + 1} beats"})
                k = j - 1
            else: k += 1

    # --- assemble notes ---
    parts = [[] for _ in INSTR]
    for n in notes:
        if n.get("role") in ("melody", "figure"):
            parts[n["inst"]].append({"start": n["start"], "end": n["end"], "pitch": n["pitch"] + n["shift"],
                                     "vel": n["vel"], "role": n["role"]})
    for i in range(5):
        cur = {}
        for t, b in enumerate(beats):
            now = {p: r for p, r in lines[i][t]}
            for p in list(cur):
                if p not in now: parts[i].append(cur.pop(p))
            for p, r in now.items():
                if p in cur: cur[p]["end"] = b["q"] + 1
                else:
                    cur[p] = {"start": b["onset"] if t == 0 or p not in {x for x, _ in lines[i][t - 1]} else b["q"],
                              "end": b["q"] + 1, "pitch": p, "vel": b["vel"] or 70, "role": r}
        parts[i].extend(cur.values())
    for ps in parts:
        # a pedal point that continues a melody / figure note simply holds that note on
        for pd in [n for n in ps if n["role"] == "pedal"]:
            src = [n for n in ps if n["role"] in ("melody", "figure") and n["pitch"] == pd["pitch"]
                   and n["start"] <= pd["start"] + 0.5 and n["end"] >= pd["start"] - 0.1]
            if src:
                src[0]["end"], src[0]["role"] = max(src[0]["end"], pd["end"]), "pedal"
                ps.remove(pd)
        ps.sort(key=lambda n: (n["start"], n["pitch"]))
    # no overlapping same pitch inside a part
    for ps in parts:
        last = {}
        for n in ps:
            o = last.get(n["pitch"])
            if o and o["end"] > n["start"]: o["end"] = n["start"]
            last[n["pitch"]] = n
        ps[:] = [n for n in ps if n["end"] - n["start"] > 0.02]

    # Cellos-Basses spacing left after voicing (figures/melody can cause it)
    for t, b in enumerate(beats):
        cb = [p for p, _ in lines[CB][t]]
        vc = [p for p, _ in lines[VC][t]]
        if cb and vc and 0 < min(vc) - max(cb) < 7:
            flags.append({"qn": b["q"], "kind": "spacing",
                          "msg": f"Cellos {pname(min(vc))} only {min(vc) - max(cb)} semitones above Basses {pname(max(cb))}"})

    if legato: _legato(parts)
    cc = [_ccs(ps, notes) for ps in parts] if ccs else [[] for _ in INSTR]
    flags.sort(key=lambda f: f["qn"])
    roles = {}
    for i, ps in enumerate(parts):
        for n in ps: roles.setdefault(NAME[i], {}).setdefault(n["role"], 0); roles[NAME[i]][n["role"]] += 1
    return {"parts": parts, "cc": cc, "flags": flags, "key": key,
            "stats": {"streams": nstreams, "bars": nbars, "beats": len(beats), "roles": roles,
                      "melody_bars": sum(m is not None for m in mel)}}


def _legato(parts, gap=0.25, overlap=0.06):
    """Lines that move on within a short gap overlap slightly (legato transitions in sample
    libraries, like bowing a real line). Divisi / pedal notes are left as they are."""
    for ps in parts:
        main = sorted((n for n in ps if n["role"] in ("melody", "figure", "harmony")),
                      key=lambda n: (n["start"], -n["pitch"]))
        j = 0
        for a in main:
            while j < len(main) and main[j]["start"] <= a["start"] + 1e-6: j += 1
            if j == len(main): break
            b = main[j]
            if b["pitch"] != a["pitch"] and 0 <= b["start"] - a["end"] <= gap or a["end"] > b["start"]:
                a["end"] = b["start"] + (overlap if b["pitch"] != a["pitch"] else 0)


def _ccs(ps, notes, step=0.25):
    """CC1 (dynamics) from the played velocities, CC11 (expression) as a swell over each phrase
    (notes separated by less than a beat), several swells in long phrases."""
    if not ps: return []
    out = []
    phrases = []
    for n in sorted(ps, key=lambda n: n["start"]):
        if phrases and n["start"] - phrases[-1][1] < 1.0: phrases[-1][1] = max(phrases[-1][1], n["end"])
        else: phrases.append([n["start"], n["end"]])
    ons = sorted((n["start"], n["vel"]) for n in notes)
    ts = [s for s, _ in ons]

    def dyn(q):
        w = [(v, math.exp(-((s - q) / 1.5) ** 2)) for s, v in ons[bisect.bisect_left(ts, q - 4):
                                                                 bisect.bisect_right(ts, q + 4)]]
        return sum(v * x for v, x in w) / sum(x for _, x in w) if w else 64
    for a, b in phrases:
        L = b - a
        nsw = max(1, round(L / 8))
        q = a
        while q <= b + 1e-6:
            x = ((q - a) / L * nsw) % 1 if L > 0 else 0.5
            out.append((round(q, 4), 1, max(1, min(127, round(25 + 0.8 * dyn(q))))))
            out.append((round(q, 4), 11, max(1, min(127, round(72 + 30 * math.sin(math.pi * x))))))
            q += step
        out.append((round(b + 0.25, 4), 11, 60))
    return out


def to_events(part, cc, chan=0):
    """[qn, flags, hex] events for one instrument."""
    ev = []
    for q, num, val in cc: ev.append([q, 0, f"{0xB0 | chan:02x}{num:02x}{val:02x}"])
    for n in part:
        ev.append([round(n["start"], 5), 0, f"{0x90 | chan:02x}{n['pitch']:02x}{max(1, min(127, n['vel'])):02x}"])
        ev.append([round(n["end"], 5), 0, f"{0x80 | chan:02x}{n['pitch']:02x}00"])
    ev.sort(key=lambda e: (e[0], e[2][0] != "8", e[2][0] == "9"))   # note-offs first at equal times
    return ev
