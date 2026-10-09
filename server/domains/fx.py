"""FX chains: track FX, input (record) FX and take FX.

Target an FX chain with `track` (optionally input_fx=true) OR with `item` (+ `take`)."""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from ..core import ItemRef, TrackRef, destructive, rcall, read, write
from mcp.server.fastmcp.exceptions import ToolError

TRACK = Field(description="Track FX chain: 0-based index, -1 = master, GUID or name")
INPUT = Field(description="Use the track's input (record) FX chain")
ITEM = Field(description="Take FX chain: item index or GUID (instead of track)")
TAKE = Field(description="Take index on the item, -1 = active take")
FX = Field(description="FX index in the chain (see fx_list)")


def _target(track, input_fx, item, take):
    if (track is None) == (item is None):
        raise ToolError("give either track (track FX) or item (take FX)")
    return dict(track=track, input_fx=input_fx or None, item=item, take=take if item is not None else None)


class ParamValue(BaseModel):
    param: Union[int, str] = Field(description="Parameter index or name (exact, or a unique part of it)")
    value: Optional[float] = Field(None, description="Raw value in the parameter's own range (see fx_params min/max)")
    normalized: Optional[float] = Field(None, ge=0, le=1, description="Normalized 0..1 value")


@read
async def fx_list(
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
) -> dict:
    """List an FX chain: index, name, guid, enabled, offline, current preset, parameter count, UI open."""
    return await rcall("fx_list", **_target(track, input_fx, item, take))


@read
async def fx_installed(
    filter: Annotated[Optional[str], Field(description="Case-insensitive part of the plugin name, e.g. 'reverb', 'ReaEQ', 'Pianoteq'")] = None,
    limit: Annotated[int, Field(description="Maximum results")] = 200,
) -> dict:
    """Search installed plugins (VST/VST3/CLAP/AU/JS...). `name` is what fx_add accepts."""
    return await rcall("fx_installed", filter=filter, limit=limit)


@write
async def fx_add(
    name: Annotated[str, Field(description="Plugin name as listed by fx_installed (e.g. 'VST3: ReaEQ (Cockos)' or just 'ReaEQ')")],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    position: Annotated[Optional[int], Field(description="Insert at this chain index (default: end)")] = None,
) -> dict:
    """Add a plugin to an FX chain; returns the new FX."""
    return await rcall("fx_add", name=name, position=position, **_target(track, input_fx, item, take))


@destructive
async def fx_delete(
    fx: Annotated[int, FX],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
) -> dict:
    """Remove an FX from a chain."""
    return await rcall("fx_delete", fx=fx, **_target(track, input_fx, item, take))


@write
async def fx_move(
    fx: Annotated[int, FX],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    to_index: Annotated[Optional[int], Field(description="New position in the chain (or in to_track's chain)")] = None,
    to_track: Annotated[Optional[TrackRef], Field(description="Move to another track's FX chain")] = None,
) -> dict:
    """Reorder an FX within its chain, or move a track FX to another track."""
    return await rcall("fx_move", fx=fx, to_index=to_index, to_track=to_track, **_target(track, input_fx, item, take))


@write
async def fx_set(
    fx: Annotated[int, FX],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    enabled: Annotated[Optional[bool], Field(description="False = bypassed")] = None,
    offline: Annotated[Optional[bool], Field(description="Take the plugin offline (unloaded)")] = None,
    wet: Annotated[Optional[float], Field(ge=0, le=1, description="Wet/dry mix 0..1")] = None,
) -> dict:
    """Bypass/enable, set offline, or change the wet/dry mix of an FX."""
    return await rcall("fx_set", fx=fx, enabled=enabled, offline=offline, wet=wet, **_target(track, input_fx, item, take))


@read
async def fx_params(
    fx: Annotated[int, FX],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    filter: Annotated[Optional[str], Field(description="Only parameters whose name contains this (case-insensitive)")] = None,
) -> dict:
    """List an FX's parameters: index, name, value, min, max, normalized 0..1 and the plugin's display text."""
    return await rcall("fx_params", fx=fx, filter=filter, **_target(track, input_fx, item, take))


@write
async def fx_param_set(
    fx: Annotated[int, FX],
    params: Annotated[List[ParamValue], Field(description="Parameters to set (by index or name) with value or normalized")],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
) -> dict:
    """Set FX parameters (batch, one undo step). Returns each parameter with its new display text."""
    return await rcall("fx_param_set", fx=fx, params=[q.model_dump(exclude_none=True) for q in params],
                       **_target(track, input_fx, item, take))


@read
async def fx_presets(
    fx: Annotated[int, FX],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
) -> dict:
    """Current preset name/index and the number of presets of an FX."""
    return await rcall("fx_presets", fx=fx, **_target(track, input_fx, item, take))


@write
async def fx_preset_set(
    fx: Annotated[int, FX],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    name: Annotated[Optional[str], Field(description="Preset name")] = None,
    index: Annotated[Optional[int], Field(description="Preset index (0-based; -1 = default user, -2 = factory)")] = None,
    step: Annotated[Optional[int], Field(description="Move +n / -n presets from the current one")] = None,
) -> dict:
    """Load a preset by name, by index, or step to the next/previous one."""
    return await rcall("fx_preset_set", fx=fx, name=name, index=index, step=step, **_target(track, input_fx, item, take))


@write
async def fx_show(
    fx: Annotated[int, FX],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    input_fx: Annotated[bool, INPUT] = False,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    mode: Annotated[Literal["floating", "chain", "close_floating", "close_chain"], Field(description="Open the plugin window or the FX chain, or close them")] = "floating",
) -> dict:
    """Open or close an FX window in REAPER's UI."""
    return await rcall("fx_show", fx=fx, mode=mode, **_target(track, input_fx, item, take))
