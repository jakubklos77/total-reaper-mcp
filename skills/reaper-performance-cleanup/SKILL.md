---
name: reaper-performance-cleanup
description: Analyse a whole freely played (improvised, no metronome) piano MIDI take in REAPER - key, free/rubato vs. pulsed sections, main pulse - and fix its accidents safely - inaudible ghost presses, keys grazed together with a chord, double strikes, chords struck in two hits - while only flagging possible wrong notes. Use when the user wants to "clean up mistakes", "fix slips / wrong notes", "polish my performance", "analyse my piece" or similar for a MIDI take in a running REAPER connected through the reaper-daw MCP server. Run it before the reaper-tempo-sync skill.
---

# Reaper performance cleanup

Polishes a played take **without changing the music**: only accidents that sound like nothing
or like a mistake are fixed, everything is judged against the whole piece, every change is
listed first, backed up and verifiable.

## Principles (why it works this way)

- **Analyse the whole piece first.** A slow prelude chord is not a "pause" and the leading tone
  of the key is not a "wrong note". The piece map (key, sections, pulse) is the context for
  every decision. Never judge from a few seconds around a note.
- **Only fix what is unambiguous.** Mechanical accidents (ghosts, grazes, doubles, split chords)
  have physical signatures and are fixed automatically. Pitch mistakes in an improvisation have
  no reference score, so they are only flagged with a suggestion; the user decides.
- **Default = what was heard.** An inaudible note is deleted (it was not heard). Making it
  sound (`--raise`) changes the music and is the user's choice.
- **Free/rubato sections are left alone in time.** Split-chord alignment only runs in pulsed
  sections; in a free prelude a spread chord is a roll.

## Requirements

- REAPER running with the MCP bridge and the `reaper-daw` MCP server. The script uses
  `midi_get` and `midi_set` and starts its own server through `$REAPER_MCP_LAUNCHER`
  (default `/home/jakub/Music/AI/reaper-mcp.sh`), because a whole take is too much data to
  pass through tool calls by hand.
- Run from this skill's `scripts/` directory. Item index = project-wide, 0-based (`item_list`).
- Works on the raw take (before tempo sync) and also after it - it never moves anything by more
  than a split-chord gap (≤ 70 ms) and never changes the item length.

## Workflow

1. **Dry run** (changes nothing):
   ```bash
   cd .claude/skills/reaper-performance-cleanup/scripts && python3 cleanup.py --item 0
   ```
   It prints the piece map, then every finding with an id, then `RESULT {json}`.

2. **Show the user the piece map** and ask them to confirm or correct it:
   - key (e.g. "D minor, fit 0.93") and which pitch classes count as in key,
   - main pulse and its tempo readings (eighths / sixteenths / quarters - the user knows which),
   - sections: `free` (rubato, long chords, no measurable pulse) and `pulsed`, with times.
   If a boundary is wrong (e.g. "the prelude ends at 48 s"), adjust `--free-gap` (median onset
   gap in s that makes a passage free, default 0.8) and run again.

3. **Show the findings** as a short summary per kind, plus every REVIEW item:

   | kind | signature | default |
   |---|---|---|
   | ghost | velocity ≤ 8: inaudible key press | delete (auto). If it is held in a chord it fits, or sits evenly in a repeated-note pattern, it may have been meant to sound: offered as `--raise N…` |
   | slip | ≤ 70 ms note struck with a chord (held notes ≥ 3× longer), not part of a fast line, and either an adjacent key (1–2 semitones) or a clash (outside the key / a semitone against the chord). Grace notes before a main note are kept | delete (auto); a slip as loud as its chord is REVIEW |
   | double | same key struck twice within 90 ms | merge into one note (auto) |
   | split | chord struck as two hits 35–70 ms apart, pulsed sections only, not a roll (3+ hits) or grace note | move the minority hit onto the main one, lengths kept (auto) |
   | wrong | outside the key and the harmony, not a chromatic passing/neighbour tone | REVIEW only: suggests delete (if the right key was pressed with it) or transpose |

   `[x]` marks what `--apply` will do. Ids are only valid for the current state of the take:
   after applying anything, run the dry run again before using ids.

4. **Apply** what the user agreed to:
   ```bash
   python3 cleanup.py --item 0 --apply [--include N35] [--exclude N8,split] [--raise N4,N48]
   ```
   - `--include`: REVIEW findings to apply as suggested.
   - `--exclude`: ids or whole kinds (`ghost,slip,double,split,wrong`) to skip.
   - `--raise`: ghosts to make audible (velocity shown in the dry run) instead of deleting.
   Require `"ok": true` and `events_as_planned: true`. Report notes before → after and the
   `backup` path. The project is not saved; the user listens and saves when happy.

5. **Undo.** `project_undo` in REAPER (one step), or
   `python3 cleanup.py --restore ~/.cache/reaper-performance-cleanup/<file>.json` (exact ticks).

## What this skill does NOT do (yet)

These steps were removed because they broke on whole pieces (e.g. the pause cutter shortened
the slow prelude chords). They will be rebuilt on top of the piece map, one at a time:

- **Tempo map** - use the reaper-tempo-sync skill after this one (it tracks the whole piece and
  keeps a free prelude in the main tempo).
- **Hesitation / thinking-pause removal** - planned: only inside pulsed sections, only single
  beats stretched against the smooth local tempo; never in free sections.
- **Timing tightening** - planned: after a good tempo map.

## Files

- `scripts/cleanup.py`: CLI for dry run, apply and restore against live REAPER.
- `scripts/piece.py`: DAW-independent analysis (`parse`, `piece_map`, `find_fixes`,
  `apply_fixes`). Offline tests in the repo's `tests/skills/test_cleanup_piece.py`.
- `scripts/mcp_client.py`: a minimal stdio MCP client.
