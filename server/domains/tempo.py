"""Tempo map and time signatures."""
from typing import Annotated, Any, List, Optional

from pydantic import Field

from ..core import destructive, rcall, read, write


@read
async def tempo_map_get() -> dict:
    """Get all tempo/time-signature markers (index, time, measure/beat 1-based, bpm,
    time_signature if it changes there, linear ramp, qn) plus the project tempo."""
    return await rcall("tempo_map_get")


@destructive
async def tempo_map_set(
    points: Annotated[List[Any], Field(description="Markers in ascending time: [time_sec, bpm, num, den, linear] or {time, bpm, num, den, linear}; num/den 0 = no signature change (put signatures only on bar starts)")],
    clear: Annotated[bool, Field(description="Delete existing markers first")] = True,
    base_bpm: Annotated[Optional[float], Field(description="Project tempo to set after clearing (e.g. points=[] + base_bpm=120 returns to a constant 120 BPM)")] = None,
) -> dict:
    """Write a whole tempo map in one undo step.

    Note: MIDI items that follow project tempo move with the tempo map. To keep a performance at the
    same absolute time, read it with midi_get first and write it back with midi_set(position_mode='time')."""
    return await rcall("tempo_map_set", points=points, clear=clear, base_bpm=base_bpm)


@write
async def tempo_marker_add(
    time: Annotated[float, Field(description="Position in seconds")],
    bpm: Annotated[float, Field(description="Tempo from this marker on")],
    num: Annotated[int, Field(description="Time signature numerator, 0 = no change")] = 0,
    den: Annotated[int, Field(description="Time signature denominator, 0 = no change")] = 0,
    linear: Annotated[bool, Field(description="Ramp linearly to the next marker")] = False,
) -> dict:
    """Add a tempo (and optionally time signature) marker. Adding the first marker after 0 s also
    makes REAPER create one at 0 s with the previous tempo."""
    return await rcall("tempo_marker_add", time=time, bpm=bpm, num=num, den=den, linear=linear)


@write
async def tempo_marker_set(
    index: Annotated[int, Field(description="Marker index from tempo_map_get")],
    time: Annotated[Optional[float], Field(description="New position in seconds")] = None,
    bpm: Annotated[Optional[float], Field(description="New tempo")] = None,
    num: Annotated[Optional[int], Field(description="Time signature numerator (0 = none)")] = None,
    den: Annotated[Optional[int], Field(description="Time signature denominator (0 = none)")] = None,
    linear: Annotated[Optional[bool], Field(description="Linear ramp to the next marker")] = None,
) -> dict:
    """Edit a tempo marker (only the given fields)."""
    return await rcall("tempo_marker_set", index=index, time=time, bpm=bpm, num=num, den=den, linear=linear)


@destructive
async def tempo_marker_delete(
    index: Annotated[int, Field(description="Marker index from tempo_map_get")],
) -> dict:
    """Delete a tempo/time-signature marker."""
    return await rcall("tempo_marker_delete", index=index)


@write
async def tempo_set(
    bpm: Annotated[float, Field(description="Project tempo in BPM")],
) -> dict:
    """Set the project tempo of a project without tempo markers (otherwise edit the markers)."""
    return await rcall("tempo_set", bpm=bpm)
