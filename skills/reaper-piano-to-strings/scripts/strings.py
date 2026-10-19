#!/usr/bin/env python3
"""
strings.py - arrange a piano MIDI take in the OPEN REAPER project for a string section
(Violins 1, Violins 2, Violas, Cellos, Basses) via the Reaper MCP server.

  dry run (default)        analysis + the arrangement per instrument + every flag, change nothing
  --apply                  create a 'Strings' folder with five MIDI tracks under the piano track,
                           write the parts (notes + CC1/CC11) and mute the piano track
  --restore BACKUP.json    delete the created tracks and unmute the piano again

Output: human-readable lines plus a final line "RESULT {json}".
"""
import argparse, json, os, sys, time
from mcp_client import MCPClient
from arrange import load, arrange, to_events, INSTR, NAME, pname, CB, VC, VA, V2, V1

BACKUP_DIR = os.path.expanduser("~/.cache/reaper-piano-to-strings")
SCORE_ORDER = (V1, V2, VA, VC, CB)
FOLDER = "Strings"

ap = argparse.ArgumentParser()
ap.add_argument("--item", type=int, default=0, help="project-wide media item index of the piano take")
mode = ap.add_mutually_exclusive_group()
mode.add_argument("--apply", action="store_true", help="create the string tracks (default: dry run)")
mode.add_argument("--restore", metavar="BACKUP", help="remove what --apply created")
ap.add_argument("--bar", type=float, default=4.0, help="quarter notes per analysis bar (melody / figure decisions)")
ap.add_argument("--max-figures", type=int, default=2, help="moving lines kept as played per bar")
ap.add_argument("--bass-rest-from", type=int, default=52,
                help="MIDI pitch from which a bass line held for 2+ bars leaves the Basses resting (52 = E3)")
ap.add_argument("--no-pedal", action="store_true", help="do not add pedal points")
ap.add_argument("--no-legato", action="store_true", help="no legato overlap")
ap.add_argument("--no-cc", action="store_true", help="no CC1/CC11")
ap.add_argument("--replace", action="store_true", help="delete an existing 'Strings' folder from an earlier run first")
ap.add_argument("--keep-piano", action="store_true", help="do not mute the piano track")
a = ap.parse_args()


def result(**kw):
    print("RESULT " + json.dumps(kw))


def existing(m):
    """Indices of an earlier run's folder + its five tracks (by name, consecutive)."""
    ts = m.call("track_list")["tracks"]
    for k, t in enumerate(ts):
        if t["name"] == FOLDER and t["folder_depth"] == 1 and \
                [x["name"] for x in ts[k + 1:k + 6]] == [NAME[i] for i in SCORE_ORDER]:
            return [x["guid"] for x in ts[k:k + 6]]
    return []


m = MCPClient()
try:
    if a.restore:
        b = json.load(open(a.restore))
        for g in b["created_tracks"]:
            try: m.call("track_delete", track=g)
            except RuntimeError as e: print(f"could not delete {g}: {e}")
        m.call("track_set", track=b["piano_track"], mute=b["piano_mute_before"])
        left = {t["guid"] for t in m.call("track_list")["tracks"]} & set(b["created_tracks"])
        print(f"removed {len(b['created_tracks']) - len(left)} tracks, piano mute -> {b['piano_mute_before']}")
        result(mode="restore", ok=not left)
        sys.exit(0 if not left else 1)

    item = m.call("item_get", item=a.item)
    take = m.call("midi_get", item=a.item, notes=False, ccs=False, events=True)
    events = take["events"]                  # [ppq, flags, hex, sec, qn]
    notes = load(events, [e[4] for e in events])
    if not notes:
        result(mode="error", error=f"item {a.item} has no audible notes"); sys.exit(2)
    r = arrange(notes, bar=a.bar, max_figures=a.max_figures, bass_rest_from=a.bass_rest_from,
                pedal=not a.no_pedal, legato=not a.no_legato, ccs=not a.no_cc)
    st = r["stats"]

    # ---------- report ----------
    print(f"piano take: item {a.item} on track {item['track']}, {len(notes)} notes, "
          f"{item['position']:.2f}-{item['end']:.2f} s")
    print(f"key: {r['key']['name']} (fit {r['key']['confidence']}); {st['streams']} lines found; "
          f"{st['bars']} bars of {a.bar:g} beats; melody in {st['melody_bars']} bars")
    for i in SCORE_ORDER:
        ps = r["parts"][i]
        if not ps:
            print(f"  {NAME[i]:10} rests"); continue
        roles = ", ".join(f"{k} {v}" for k, v in st["roles"].get(NAME[i], {}).items())
        print(f"  {NAME[i]:10} {len(ps):4} notes  {pname(min(n['pitch'] for n in ps)):>4}-"
              f"{pname(max(n['pitch'] for n in ps)):<4}  ({roles})")
    kinds = {}
    for f in r["flags"]: kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    print(f"{len(r['flags'])} notes for review " + (str(kinds) if kinds else ""))
    for f in r["flags"]:
        q = f["qn"]
        print(f"  qn {q:7.2f} (bar {int(q // 4) + 1:3}, 4/4)  {f['kind']:9} {f['msg']}")
    report = {"item": a.item, "key": r["key"]["name"], "stats": st, "flags": r["flags"]}
    if not a.apply:
        result(mode="dry-run", **report); sys.exit(0)

    # ---------- apply ----------
    old = existing(m)
    if old and not a.replace:
        result(mode="error", error="a 'Strings' folder from an earlier run exists - use --replace"); sys.exit(2)
    for g in reversed(old): m.call("track_delete", track=g)
    piano = m.call("track_get", track=item["track"])
    mute_before = piano["mute"]
    if old:                                  # the earlier run muted the piano: keep its original state
        for f in sorted(os.listdir(BACKUP_DIR) if os.path.isdir(BACKUP_DIR) else [], reverse=True):
            prev = json.load(open(os.path.join(BACKUP_DIR, f)))
            if set(prev.get("created_tracks", [])) == set(old):
                mute_before = prev["piano_mute_before"]; break
    idx = piano["index"] + 1
    created, items = [], {}
    created.append(m.call("track_create", index=idx, name=FOLDER, folder_depth=1)["guid"])
    for k, i in enumerate(SCORE_ORDER):
        t = m.call("track_create", index=idx + 1 + k, name=NAME[i], color=INSTR[i][1],
                   folder_depth=-1 if k == len(SCORE_ORDER) - 1 else 0)
        created.append(t["guid"])
        it = m.call("item_create_midi", track=t["guid"], start=item["position"], end=item["end"], name=NAME[i])
        items[i] = it["guid"]
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = os.path.join(BACKUP_DIR, time.strftime("%Y%m%d-%H%M%S") + f"-item{a.item}.json")
    json.dump({"item": a.item, "created_tracks": created, "piano_track": piano["guid"],
               "piano_mute_before": mute_before, "report": report}, open(backup, "w"))
    ok = True
    for i in SCORE_ORDER:
        ev = to_events(r["parts"][i], r["cc"][i])
        base = m.call("midi_get", item=items[i], notes=False, ccs=False, events=True)["events"]
        ev += [[e[4], e[1], e[2]] for e in base]            # keep what REAPER put in a new take
        m.call("midi_set", item=items[i], unit="qn", events=ev)
        got = m.call("midi_get", item=items[i], notes=True, ccs=False)["counts"]
        n_ok = got.get("notes") == len(r["parts"][i])
        ok &= n_ok
        print(f"  {NAME[i]:10} wrote {len(r['parts'][i])} notes, {len(r['cc'][i])} CCs; in REAPER: {got}"
              + ("" if n_ok else "  <-- MISMATCH"))
    if not a.keep_piano: m.call("track_set", track=piano["guid"], mute=True)
    report.update(backup=backup, created_tracks=created)
    print(f"backup: {backup}")
    result(mode="apply", ok=ok, **report)
    sys.exit(0 if ok else 1)
finally:
    m.close()
