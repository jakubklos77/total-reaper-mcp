"""Live: MIDI editing (120 BPM, 4/4 scratch project: 1 qn = 0.5 s)."""
import pytest
from conftest import ToolError


def _item(r):
    r("track_create", name="Keys")
    return r("item_create_midi", track=0, start=0, length=8)["guid"]


def _notes(r, it):
    m = r("midi_get", item=it, ccs=False)
    f = m["note_fields"]
    return [dict(zip(f, row)) for row in m["notes"]]


def test_insert_get_notes_units(r):
    it = _item(r)
    out = r("midi_insert_notes", item=it, notes=[
        {"pitch": 60, "start": 0, "length": 1, "velocity": 100},
        {"pitch": 64, "start": 1, "end": 1.5},
        {"pitch": 67, "start": 2.0, "length": 0.25, "channel": 2}])
    assert out == {"inserted": 3, "notes": 3}
    r("midi_insert_notes", item=it, unit="seconds", notes=[{"pitch": 72, "start": 2.0, "length": 0.5}])
    n = _notes(r, it)
    assert [x["pitch"] for x in n] == [60, 64, 67, 72]
    assert n[0]["velocity"] == 100 and n[1]["velocity"] == 96 and n[2]["channel"] == 2
    assert n[1]["start_qn"] == pytest.approx(1) and n[1]["end_sec"] == pytest.approx(0.75)
    assert n[3]["start_qn"] == pytest.approx(4) and n[3]["end_qn"] == pytest.approx(5)
    m = r("midi_get", item=it)
    assert m["ppq_per_qn"] == 960 and m["follows_project_tempo"] is True
    with pytest.raises(ToolError):
        r("midi_insert_notes", item=it, notes=[{"pitch": 200, "start": 0, "length": 1}])
    with pytest.raises(ToolError, match="end must be after start"):
        r("midi_insert_notes", item=it, notes=[{"pitch": 60, "start": 2, "end": 1}])


def test_edit_delete_transpose(r):
    it = _item(r)
    r("midi_insert_notes", item=it, notes=[{"pitch": p, "start": i, "length": 0.5} for i, p in enumerate([60, 62, 64, 65])])
    r("midi_edit_notes", item=it, edits=[{"index": 0, "pitch": 48, "velocity": 30},
                                         {"index": 1, "start": 1.5},          # move, keep length
                                         {"index": 2, "length": 2}])
    n = _notes(r, it)
    assert n[0]["pitch"] == 48 and n[0]["velocity"] == 30
    assert n[1]["start_qn"] == pytest.approx(1.5) and n[1]["end_qn"] == pytest.approx(2.0)
    assert n[2]["end_qn"] == pytest.approx(4)
    assert r("midi_transpose", item=it, semitones=12, pitch_min=60)["transposed"] == 3
    assert [x["pitch"] for x in _notes(r, it)] == [48, 74, 76, 77]
    with pytest.raises(ToolError, match="leave the MIDI range"):
        r("midi_transpose", item=it, semitones=60)
    assert r("midi_delete_notes", item=it, start=1, end=3)["deleted"] == 2
    assert [x["pitch"] for x in _notes(r, it)] == [48, 77]
    assert r("midi_delete_notes", item=it)["notes"] == 0


def test_ccs_pitchbend_program(r):
    it = _item(r)
    r("midi_insert_ccs", item=it, ccs=[
        {"position": 0, "cc": 64, "value": 127}, {"position": 2, "cc": 64, "value": 0},
        {"position": 1, "type": "pitchbend", "value": -8192}, {"position": 1.5, "type": "pitchbend", "value": 8191},
        {"position": 0, "type": "program", "value": 5}])
    m = r("midi_get", item=it, notes=False)
    rows = [dict(zip(m["cc_fields"], row)) for row in m["ccs"]]
    pb = [x["value"] for x in rows if x["type"] == "pitchbend"]
    assert pb == [-8192, 8191]
    assert [x["value"] for x in rows if x["type"] == "program"] == [5]
    assert [(x["cc"], x["value"]) for x in rows if x["type"] == "cc"] == [(64, 127), (64, 0)]
    assert r("midi_delete_ccs", item=it, type="pitchbend")["deleted"] == 2
    assert r("midi_delete_ccs", item=it, cc=64, start=1)["deleted"] == 1
    assert r("midi_get", item=it, notes=False)["counts"]["ccs"] == 2


def test_quantize(r):
    it = _item(r)
    r("midi_insert_notes", item=it, notes=[{"pitch": 60, "start": 0.1, "length": 0.4},
                                            {"pitch": 62, "start": 0.95, "length": 0.3},
                                            {"pitch": 64, "start": 1.6, "length": 0.3}])
    out = r("midi_quantize", item=it, grid=0.5, strength=1.0)
    assert out == {"notes": 3, "moved": 3}
    n = _notes(r, it)
    assert [round(x["start_qn"], 6) for x in n] == [0, 1, 1.5]
    assert n[0]["end_qn"] - n[0]["start_qn"] == pytest.approx(0.4, abs=1e-3)      # length kept
    r("midi_edit_notes", item=it, edits=[{"index": 0, "start": 0.2}])
    r("midi_quantize", item=it, grid=0.5, strength=0.5, indices=[0])
    assert _notes(r, it)[0]["start_qn"] == pytest.approx(0.1, abs=1e-3)


def test_quantize_follows_tempo_map(r):
    it = _item(r)
    r("tempo_map_set", points=[[0, 120, 4, 4, False], [1.0, 60, 0, 0, False]])   # qn 2 at 1.0 s, then slower
    r("midi_insert_notes", item=it, unit="seconds", notes=[{"pitch": 60, "start": 2.1, "length": 0.2}])
    r("midi_quantize", item=it, grid=1)
    n = _notes(r, it)[0]
    assert n["start_qn"] == pytest.approx(3) and n["start_sec"] == pytest.approx(2.0)   # qn 3 = 1.0 s + 1 beat at 60


def test_midi_set_lossless_roundtrip_and_time_mode(r):
    it = _item(r)
    r("midi_insert_notes", item=it, notes=[{"pitch": 60, "start": 0, "length": 1}, {"pitch": 64, "start": 2, "length": 1}])
    r("midi_insert_ccs", item=it, ccs=[{"position": 0.5, "cc": 64, "value": 127}])
    ev = r("midi_get", item=it, notes=False, ccs=False, events=True)["events"]
    r("midi_set", item=it, events=[[e[0], e[1], e[2]] for e in ev])
    ev2 = r("midi_get", item=it, notes=False, ccs=False, events=True)["events"]
    assert [e[:3] for e in ev2] == [e[:3] for e in ev]
    # keep absolute times while the tempo changes
    r("tempo_map_set", points=[[0, 90, 4, 4, False]])
    r("midi_set", item=it, unit="seconds", fit_item=True, events=[[e[3], e[1], e[2]] for e in ev])
    ev3 = r("midi_get", item=it, notes=False, ccs=False, events=True)["events"]
    assert all(abs(a[3] - b[3]) < 0.002 for a, b in zip(ev, ev3))
    with pytest.raises(ToolError, match="bad hex"):
        r("midi_set", item=it, events=[[0, 0, "zz"]])
    with pytest.raises(ToolError, match="no item at index 99"):
        r("midi_get", item=99)
