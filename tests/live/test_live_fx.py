"""Live: FX (uses REAPER's stock ReaEQ / ReaComp / ReaDelay)."""
import pytest
from conftest import ToolError


def test_installed_and_add_list_delete(r):
    found = r("fx_installed", filter="reaeq")["plugins"]
    assert any("ReaEQ" in p["name"] for p in found)
    r("track_create", name="FX")
    eq = r("fx_add", track=0, name="ReaEQ")
    comp = r("fx_add", track=0, name="ReaComp")
    first = r("fx_add", track=0, name="ReaDelay", position=0)
    assert first["index"] == 0 and "ReaDelay" in first["name"]
    names = [f["name"] for f in r("fx_list", track=0)["fx"]]
    assert "ReaDelay" in names[0] and "ReaEQ" in names[1] and "ReaComp" in names[2]
    with pytest.raises(ToolError, match="plugin not found"):
        r("fx_add", track=0, name="NoSuchPlugin XYZ")
    r("fx_delete", track=0, fx=0)
    assert len(r("fx_list", track=0)["fx"]) == 2
    with pytest.raises(ToolError, match="no FX 5"):
        r("fx_delete", track=0, fx=5)
    with pytest.raises(ToolError, match="either track"):
        r("fx_list")


def test_move_set_params(r):
    r("track_create", name="A"); r("track_create", name="B")
    r("fx_add", track="A", name="ReaEQ"); r("fx_add", track="A", name="ReaComp")
    moved = r("fx_move", track="A", fx=1, to_index=0)
    assert "ReaComp" in moved["name"] and moved["index"] == 0
    s = r("fx_set", track="A", fx=0, enabled=False, wet=0.5)
    assert s["enabled"] is False
    pr = r("fx_params", track="A", fx=0, filter="thresh")["params"]
    assert len(pr) >= 1 and "Thresh" in pr[0]["name"]
    out = r("fx_param_set", track="A", fx=0, params=[{"param": pr[0]["index"], "normalized": 0.25},
                                                    {"param": "Ratio", "normalized": 0.5}])["params"]
    assert out[0]["normalized"] == pytest.approx(0.25, abs=1e-3) and out[1]["formatted"]
    with pytest.raises(ToolError, match="no parameter named"):
        r("fx_param_set", track="A", fx=0, params=[{"param": "Nope", "normalized": 0.1}])
    r("fx_move", track="A", fx=1, to_track="B")
    assert len(r("fx_list", track="A")["fx"]) == 1 and "ReaEQ" in r("fx_list", track="B")["fx"][0]["name"]


def test_input_fx_and_take_fx_and_presets(r):
    r("track_create", name="Rec")
    r("fx_add", track=0, input_fx=True, name="ReaEQ")
    assert len(r("fx_list", track=0, input_fx=True)["fx"]) == 1 and r("fx_list", track=0)["fx"] == []
    it = r("item_create_midi", track=0, start=0, length=1)["guid"]
    tfx = r("fx_add", item=it, name="ReaEQ")
    assert tfx["index"] == 0 and len(r("fx_list", item=it)["fx"]) == 1
    pr = r("fx_presets", item=it, fx=0)
    assert "count" in pr
    r("fx_delete", item=it, fx=0)
    assert r("fx_list", item=it)["fx"] == []
    shown = r("fx_show", track=0, input_fx=True, fx=0, mode="floating")
    assert shown["open"] is True
    assert r("fx_show", track=0, input_fx=True, fx=0, mode="close_floating")["open"] is False
