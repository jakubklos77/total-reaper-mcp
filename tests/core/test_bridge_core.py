"""Core bridge behaviour: dispatch, errors, JSON, handles, generic API passthrough."""


def test_ping_and_unknown_function(bridge):
    assert bridge("ping")["version"] == "7.80/win64"
    r = bridge("no_such_tool", {})
    assert r["ok"] is False and "Unknown function" in r["error"]


def test_handler_errors_are_reported_without_lua_location(bridge):
    r = bridge("track_chunk_get", {"track": 7})
    assert r == {"ok": False, "error": "no track at index 7 (project has 2 tracks)"}


def test_malformed_request(bridge):
    r = bridge(None, raw="{not json")
    assert r["ok"] is False


def test_track_refs_by_index_master_and_guid_errors(bridge):
    assert bridge("track_chunk_get", {"track": 0})["chunk"] == "<TRACK\nNAME Piano\n>"
    assert bridge("track_chunk_get", {"track": -1})["chunk"] == "<TRACK\nNAME MASTER\n>"
    r = bridge("track_chunk_get", {"track": "{0000}"})
    assert not r["ok"] and "GUID" in r["error"]


def test_json_strings_with_structural_and_unicode_chars(bridge):
    chunk = '<TRACK\nNAME "a, [b] {c}" \\ tab\there é ✓ \u0001\n>'
    assert bridge("track_chunk_set", {"track": 1, "chunk": chunk})["ok"]
    assert bridge("track_chunk_get", {"track": 1})["chunk"] == chunk


def test_reaper_api_passthrough_handles_and_multireturn(bridge):
    tr = bridge("reaper_api", {"func": "GetTrack", "args": [0, 1]})["ret"][0]
    assert "__ptr" in tr
    r = bridge("reaper_api", {"func": "GetTrackStateChunk", "args": [tr, "", False]})
    assert r["ret"] == [True, "<TRACK\nNAME Bass\n>"]
    assert bridge("reaper_api", {"func": "Multi"})["ret"] == [True, "a", None, 7]


def test_reaper_api_stale_unknown_handles_and_bad_function(bridge):
    tr = bridge("reaper_api", {"func": "GetTrack", "args": [0, 0]})["ret"][0]
    bridge.R.tracks[0].alive = False
    r = bridge("reaper_api", {"func": "GetTrackStateChunk", "args": [tr, "", False]})
    assert not r["ok"] and "Stale handle" in r["error"]
    r = bridge("reaper_api", {"func": "GetTrackStateChunk", "args": [{"__ptr": "x"}, "", False]})
    assert not r["ok"] and "Unknown handle" in r["error"]
    r = bridge("reaper_api", {"func": "rm_rf"})
    assert not r["ok"] and "unknown ReaScript function" in r["error"]
