---
name: reaper-performance-cleanup
description: Clean up a freely played (improvised, no metronome) MIDI take in REAPER - delete slips, ghost presses and double strikes, flag wrong notes, cut out long "thinking" pauses, and tighten small timing errors against a tempo-synced grid. Pedal/CC/sysex events move with the notes. Use when the user wants to "fix wrong notes", "clean up mistakes", "remove the pauses/gaps where I was thinking", "tighten the timing", "fix small timing errors" or similar for a MIDI take in a running REAPER connected through the reaper-daw MCP server. Works together with the reaper-tempo-sync skill.
---

# Reaper performance cleanup

Fixes the accidents in a played take while keeping the performance. Every change is reported
first, applied only on request, backed up, verified and restorable.

## Where it fits: run it around tempo sync

```
1. cleanup  --apply notes,pauses   (before sync: on the raw performance)
2. reaper-tempo-sync --apply       (beats/bars follow the cleaned playing)
3. cleanup  --apply timing         (after sync: pull onsets towards the synced grid)
```

- **Pauses before sync.** A thinking pause looks like a very slow beat or extra bars to the tempo
  detector. Pause removal refuses to run on a project that already has a tempo map. To undo a sync:
  `tempo_sync.py --restore <backup>`.
- **Notes before sync.** Slips and double strikes are extra onsets that the tempo detector would
  try to place on the beat. Note fixes don't move anything in time, so they also work later.
- **Timing after sync.** "Late" or "early" only means something against the beat, and the
  synced tempo map is that beat. Timing refuses to run without a tempo map.

If the user wants only one thing, run just that step. Timing still needs step 2 first.

## Requirements

- REAPER running with the MCP bridge and the `reaper-daw` MCP server. The scripts use `midi_get`,
  `midi_set`, `item_set` and `tempo_map_get`, and start their own server through
  `$REAPER_MCP_LAUNCHER` (default `/home/jakub/Music/AI/reaper-mcp.sh`).
- Run from this skill's `scripts/` directory. Item index = project-wide, 0-based (see `item_list`).

## Workflow

1. **Dry run** (changes nothing):
   ```bash
   cd .claude/skills/reaper-performance-cleanup/scripts && python3 cleanup.py --item 0
   ```
   It prints every finding with an id, then `RESULT {json}`. Show the user the table:

   | kind | what | default |
   |---|---|---|
   | ghost | velocity ≤ 8, inaudible. Deleted, or, if it sits evenly in a repeated-note pattern, a missed key: velocity → neighbours' | delete = auto, velocity = review |
   | slip | short (≤ 120 ms), quiet (≤ ½ of the local velocity) note struck with a louder key 1–2 semitones away | auto |
   | double | same key struck twice within 90 ms → merged | auto |
   | pitch | pitch class not used within ±4 s while a semitone neighbour is used a lot (chromatic runs are left alone). Played together with the key next to it → delete, else → transpose | review |
   | pause (P) | onset gap ≥ 1.5 s and ≥ 3 local beats → cut down | when `pauses` applied |
   | timing | onset groups within 35 % of a grid step from the synced grid → moved part of the way | when `timing` applied |

   `[x]` marks what `--apply notes` will do (the auto ones). Review findings are musical
   judgement calls. List them and let the user pick (`--include N2,N5`). Anything can be
   skipped with `--exclude N3,P2`. **Ids are only valid for the current state of the take**:
   after applying anything, run the dry run again before using ids.

2. **Pauses: how much to keep.** If the notes before a pause were released, the music resumes
   one subdivision after the release. If they were held through the pause, `--keep-beats` (default 1)
   beat is kept. Override per pause with `--keep P1=2,P2=0.5` (beats). The cut is placed
   after the releases and just before the restart, so a pedal press right before the next
   phrase keeps its timing. Only this take gets shorter: warn the user if other items or
   markers sit after a pause (check `item_list` / `marker_list`).

3. **Apply** what the user agreed to:
   ```bash
   python3 cleanup.py --item 0 --apply notes,pauses [--include …] [--exclude …] [--keep …]
   ```
   Then the reaper-tempo-sync skill. Then the timing step:
   ```bash
   python3 cleanup.py --item 0                      # timing preview: onsets that would move
   python3 cleanup.py --item 0 --apply timing [--strength 0.5] [--window 0.35] [--grid 0.5]
   ```
   - `--strength` is how far onsets move toward the grid (0..1). The default 0.5 keeps the feel.
   - `--window` leaves alone any onset further than that fraction of a grid step (deliberate
     syncopation, triplets, ornaments).
   - `--grid` is in quarter notes. The default is 1/`--slots-per-beat`, so eighths; use 0.25
     for sixteenth-based playing.
   - Beats already sit exactly on the notes after a per-beat tempo sync, so timing mostly evens
     out the subdivisions between beats.
   - Very short grace-note groups right before another onset are left alone.

   Require `"ok": true` and `events_same_payload: true`. Report what changed and the `backup` path.
   For timing, report `timing_before` → `timing_after` (`on_grid_pct`, `max_dev_qn`). The
   project is not saved. The user saves when happy.

4. **Undo.** Use `project_undo` in REAPER (one step per apply), or
   `python3 cleanup.py --restore ~/.cache/reaper-performance-cleanup/<file>.json`, which
   restores the exact ticks and the item length. Restore in reverse order of the steps
   (timing backup → tempo-sync backup → notes/pauses backup).

## How time changes are applied

Pause cuts and timing moves are one continuous, order-preserving warp of the whole take.
Note-offs, sustain pedal, other CCs and sysex between two onsets move proportionally with
them, so pedal changes stay in the same place relative to the notes.

## Files

- `scripts/cleanup.py`: CLI for dry run, apply (notes, pauses, timing) and restore against live REAPER.
- `scripts/cleanup_analysis.py`: DAW-independent detectors and warps. Offline tests are in the repo's
  `tests/skills/`.
- `scripts/mcp_client.py`: a minimal stdio MCP client.
