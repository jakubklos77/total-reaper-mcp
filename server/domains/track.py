"""Tracks."""
from typing import Annotated, List, Optional

from pydantic import Field

from ..core import TrackRef, destructive, rcall, read, write

TRACK = Field(description="Track: 0-based index, -1 = master, GUID '{...}' or exact name")


@read
async def track_list() -> dict:
    """List all tracks (index, name, guid, folder depth, volume dB, pan, mute, solo, arm, auto_arm, selected,
    color, FX and item counts) and the master track's main settings."""
    return await rcall("track_list")


@read
async def track_get(track: Annotated[TrackRef, TRACK]) -> dict:
    """Full detail for one track: settings, input/monitoring/record mode, send counts, FX chain,
    items (index, position, length, name, midi) and envelopes."""
    return await rcall("track_get", track=track)


_PROPS = dict(
    name=(Optional[str], "Track name"),
    volume_db=(Optional[float], "Volume in dB (0 = unity)"),
    pan=(Optional[float], "Pan -1 (left) .. 1 (right)"),
    width=(Optional[float], "Stereo width -1..1"),
    mute=(Optional[bool], "Mute"),
    solo=(Optional[bool], "Solo"),
    arm=(Optional[bool], "Record arm (fails if auto_arm is on - then arming follows selection)"),
    auto_arm=(Optional[bool], "Automatic record-arm when the track is selected"),
    phase_inverted=(Optional[bool], "Invert polarity"),
    color=(Optional[str], "Color '#rrggbb'"),
    input=(Optional[int], "Record input: -1 none, n = mono input n, 1024+n stereo pair, 4096+(device<<5)+channel for MIDI (device 63 = all, channel 0 = all; all MIDI = 6112)"),
    monitor=(Optional[int], "Input monitoring: 0 off, 1 on, 2 auto"),
    record_mode=(Optional[int], "Record mode: 0 input, 1 output (stereo), 2 none, 7 MIDI overdub, 8 MIDI replace ..."),
    folder_depth=(Optional[int], "Folder: 1 = folder start, 0 = normal, -n = closes n folder levels"),
    main_send=(Optional[bool], "Send to master/parent"),
    selected=(Optional[bool], "Selected"),
    height=(Optional[int], "Track height in pixels (0 = default)"),
)


@write
async def track_create(
    index: Annotated[Optional[int], Field(description="Insert at this index (default: end)")] = None,
    name: Annotated[Optional[str], Field(description=_PROPS["name"][1])] = None,
    color: Annotated[Optional[str], Field(description=_PROPS["color"][1])] = None,
    volume_db: Annotated[Optional[float], Field(description=_PROPS["volume_db"][1])] = None,
    pan: Annotated[Optional[float], Field(description=_PROPS["pan"][1])] = None,
    input: Annotated[Optional[int], Field(description=_PROPS["input"][1])] = None,
    folder_depth: Annotated[Optional[int], Field(description=_PROPS["folder_depth"][1])] = None,
) -> dict:
    """Create a track (with REAPER's default track settings) and return it."""
    return await rcall("track_create", index=index, name=name, color=color, volume_db=volume_db, pan=pan,
                       input=input, folder_depth=folder_depth)


@write
async def track_set(
    track: Annotated[TrackRef, TRACK],
    name: Annotated[Optional[str], Field(description=_PROPS["name"][1])] = None,
    volume_db: Annotated[Optional[float], Field(description=_PROPS["volume_db"][1])] = None,
    pan: Annotated[Optional[float], Field(description=_PROPS["pan"][1])] = None,
    width: Annotated[Optional[float], Field(description=_PROPS["width"][1])] = None,
    mute: Annotated[Optional[bool], Field(description=_PROPS["mute"][1])] = None,
    solo: Annotated[Optional[bool], Field(description=_PROPS["solo"][1])] = None,
    arm: Annotated[Optional[bool], Field(description=_PROPS["arm"][1])] = None,
    auto_arm: Annotated[Optional[bool], Field(description=_PROPS["auto_arm"][1])] = None,
    phase_inverted: Annotated[Optional[bool], Field(description=_PROPS["phase_inverted"][1])] = None,
    color: Annotated[Optional[str], Field(description=_PROPS["color"][1])] = None,
    clear_color: Annotated[Optional[bool], Field(description="Remove the custom color")] = None,
    input: Annotated[Optional[int], Field(description=_PROPS["input"][1])] = None,
    monitor: Annotated[Optional[int], Field(description=_PROPS["monitor"][1])] = None,
    record_mode: Annotated[Optional[int], Field(description=_PROPS["record_mode"][1])] = None,
    folder_depth: Annotated[Optional[int], Field(description=_PROPS["folder_depth"][1])] = None,
    main_send: Annotated[Optional[bool], Field(description=_PROPS["main_send"][1])] = None,
    selected: Annotated[Optional[bool], Field(description=_PROPS["selected"][1])] = None,
    height: Annotated[Optional[int], Field(description=_PROPS["height"][1])] = None,
) -> dict:
    """Change track settings - only the given fields, in one undo step. Returns the track."""
    return await rcall("track_set", track=track, name=name, volume_db=volume_db, pan=pan, width=width,
                       mute=mute, solo=solo, arm=arm, auto_arm=auto_arm, phase_inverted=phase_inverted, color=color,
                       clear_color=clear_color, input=input, monitor=monitor, record_mode=record_mode,
                       folder_depth=folder_depth, main_send=main_send, selected=selected, height=height)


@destructive
async def track_delete(track: Annotated[TrackRef, TRACK]) -> dict:
    """Delete a track with its items, FX and envelopes."""
    return await rcall("track_delete", track=track)


@write
async def track_move(
    track: Annotated[TrackRef, TRACK],
    to_index: Annotated[int, Field(description="Final 0-based position of the track")],
) -> dict:
    """Move a track to another position in the track list."""
    return await rcall("track_move", track=track, to_index=to_index)


@write
async def track_duplicate(track: Annotated[TrackRef, TRACK]) -> dict:
    """Duplicate a track (items, FX, envelopes, routing); the copy is placed right after it."""
    return await rcall("track_duplicate", track=track)


@write
async def track_select(
    tracks: Annotated[List[TrackRef], Field(description="Tracks to select (index, GUID or name); [] clears the selection")],
    add: Annotated[bool, Field(description="Add to the current selection instead of replacing it")] = False,
) -> dict:
    """Set the track selection (many REAPER actions work on selected tracks)."""
    return await rcall("track_select", tracks=tracks, add=add)


@read
async def track_chunk_get(track: Annotated[TrackRef, TRACK]) -> dict:
    """Get a track's complete state as RPP text (for advanced edits; see track_chunk_set)."""
    return await rcall("track_chunk_get", track=track)


@destructive
async def track_chunk_set(
    track: Annotated[TrackRef, TRACK],
    chunk: Annotated[str, Field(description="Full '<TRACK ...>' state text")],
) -> dict:
    """Replace a track's complete state with RPP text (one undo step)."""
    return await rcall("track_chunk_set", track=track, chunk=chunk)
