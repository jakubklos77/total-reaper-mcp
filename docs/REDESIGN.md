# Curated rebuild

Goal: a small, correct, live-tested REAPER MCP server. Replaces ~740 thin, partly broken
wrappers (duplicates, non-existent API calls, placeholder tools) with ~130 domain tools
plus a generic passthrough for the long tail.

## Architecture

```
MCP client ──stdio──> server (Python, FastMCP) ──files──> lua/mcp_bridge.lua (inside REAPER)
```

- **One tool = one bridge call = one Lua handler.** Handlers resolve objects by index/GUID
  inside REAPER (no pointer round trips), do the whole operation, and return plain data.
  Every write handler is a single undo step (`Undo_BeginBlock2/EndBlock2`).
- **Named parameters.** A request is `{"id", "func": "track_set", "args": [{...params}]}`;
  handlers are `H.track_set = function(p) ... end`. Errors are raised with `error()` and come
  back as `{"ok": false, "error": ...}` → the tool call fails with that message.
- **Lua source** lives in `lua/src/*.lua` (core, one file per domain, main loop) and is bundled
  into the single file REAPER runs, `lua/mcp_bridge.lua`, by `scripts/build_bridge.py`
  (the bundle is committed; never edit it by hand).
- **Python** `server/` = `bridge.py` (file IPC) + `core.py` (`rcall`) + `tools/<domain>.py`
  (thin typed wrappers with good docstrings, returning dicts → structured MCP output).
- **No profiles / capability gates.** All tools are always registered (~130 is fine for MCP
  clients that defer tool schemas). `REAPER_MCP_DOMAINS` env can restrict domains.

## Conventions

- Names: `<domain>_<verb>` (`track_list`, `item_set`, `midi_insert_notes`, ...).
- Indices are 0-based. Tracks: index, `-1` = master, or GUID string, or exact name.
  Items: project-wide index or GUID. Takes: index on the item, `-1` = active take.
  FX: track (or item+take) + fx index. Times are seconds unless a parameter says `qn`.
- Volumes in dB, pan -1..1, colors `#rrggbb` (or null to clear).
- List tools return compact records; `*_get` returns full detail for one object.
- Setter tools take optional fields and change only what is given (`track_set`, `item_set`...).
- Batch where it matters (MIDI notes/CCs, envelope points, tempo map, markers).
- No fake/placeholder tools: if REAPER can't do it, the tool doesn't exist.

## Tool list

| Domain | Tools |
|---|---|
| project | `project_info`, `project_save`, `project_notes`, `project_undo`, `project_redo`, `project_tabs`, `project_new_tab`, `project_select_tab`, `project_close_tab` |
| transport | `transport_play`, `transport_stop`, `transport_pause`, `transport_record`, `transport_state`, `transport_set_cursor`, `transport_set_repeat` |
| time | `time_selection_get`, `time_selection_set`, `time_convert` (seconds ⇄ qn ⇄ bars.beats), `grid_get`, `grid_set` |
| tempo | `tempo_map_get`, `tempo_map_set`, `tempo_marker_add`, `tempo_marker_set`, `tempo_marker_delete`, `tempo_set` |
| track | `track_list`, `track_get`, `track_create`, `track_delete`, `track_set`, `track_move`, `track_duplicate`, `track_select`, `track_chunk_get`, `track_chunk_set` |
| item | `item_list`, `item_get`, `item_create_midi`, `item_insert_media`, `item_delete`, `item_set`, `item_split`, `item_duplicate`, `item_glue`, `item_select`, `item_chunk_get`, `item_chunk_set`, `take_set`, `take_add`, `take_delete` |
| midi | `midi_get`, `midi_set`, `midi_insert_notes`, `midi_edit_notes`, `midi_delete_notes`, `midi_insert_ccs`, `midi_delete_ccs`, `midi_quantize`, `midi_transpose` |
| fx | `fx_list`, `fx_installed`, `fx_add`, `fx_delete`, `fx_move`, `fx_set`, `fx_params`, `fx_param_set`, `fx_presets`, `fx_preset_set`, `fx_show` |
| envelope | `envelope_list`, `envelope_get`, `envelope_points_set`, `envelope_points_delete`, `envelope_set` |
| marker | `marker_list`, `marker_add`, `marker_set`, `marker_delete` |
| routing | `send_list`, `send_create`, `send_set`, `send_delete` |
| render | `render_project`, `track_freeze`, `track_unfreeze` |
| action | `action_run`, `action_find`, `action_state` |
| api | `reaper_api` (call any ReaScript function; pointers come back as handles and can be passed back), `ping` |

Every domain has live tests (tests/live). Rules learned while testing: never trigger a modal dialog
(close/overwrite/save-as prompts block the bridge), and report REAPER options that change behaviour
(loop linked to time selection, track auto-arm) instead of silently failing.

## Testing

- `tests/core/` — offline: JSON, handles, dispatch, IPC (Lua runs in `lupa` with a mock).
- `tests/live/` — against a running REAPER: each test session opens a **scratch project tab**,
  runs there, saves it to a temp file and closes the tab, so user projects are never touched.
  Run: `pytest tests/live --live` (needs `REAPER_MCP_LAUNCHER` or the bridge dir reachable).
