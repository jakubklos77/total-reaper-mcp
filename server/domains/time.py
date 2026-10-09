"""Time selection, loop range, grid and position conversion."""
from typing import Annotated, Literal, Optional

from pydantic import Field

from ..core import rcall, read, write


@read
async def time_selection_get() -> dict:
    """Get the time selection and the loop range (seconds; start == end means none). `linked` tells
    whether REAPER's 'loop points linked to time selection' option is on (then they always match)."""
    return await rcall("time_selection_get")


@write
async def time_selection_set(
    start: Annotated[float, Field(description="Start in seconds")],
    end: Annotated[float, Field(description="End in seconds")],
    target: Annotated[Literal["time_selection", "loop", "both"], Field(description="What to set")] = "time_selection",
) -> dict:
    """Set the time selection and/or loop range. start == end clears it. With REAPER's 'loop points
    linked to time selection' option on (default), setting either one sets both."""
    return await rcall("time_selection_set", start=start, end=end, target=target)


@read
async def time_convert(
    seconds: Annotated[Optional[float], Field(description="Project time in seconds")] = None,
    qn: Annotated[Optional[float], Field(description="Quarter notes from project start")] = None,
    measure: Annotated[Optional[int], Field(description="Measure number as shown in REAPER (1 = first)")] = None,
    beat: Annotated[Optional[float], Field(description="Beat within the measure, 1-based (with measure)")] = None,
    text: Annotated[Optional[str], Field(description="A time string in the project's ruler format, e.g. '5.2.00' or '1:23.500'")] = None,
) -> dict:
    """Convert a position (give exactly one of seconds / qn / measure(+beat) / text) into all forms:
    seconds, quarter notes, measure & beat (1-based), time signature and tempo there, ruler texts.
    Uses the project's tempo map."""
    return await rcall("time_convert", seconds=seconds, qn=qn, measure=measure, beat=beat, text=text)


@read
async def grid_get() -> dict:
    """Get the grid: division (fraction of a whole note: 0.25 = 1/4), swing, snap on/off."""
    return await rcall("grid_get")


@write
async def grid_set(
    division: Annotated[Optional[float], Field(description="Fraction of a whole note: 0.25 = quarter, 0.125 = eighth, 1/12 = eighth triplet")] = None,
    swing: Annotated[Optional[bool], Field(description="Swing grid on/off")] = None,
    swing_amount: Annotated[Optional[float], Field(description="Swing amount -1..1")] = None,
    snap: Annotated[Optional[bool], Field(description="Snap to grid on/off")] = None,
) -> dict:
    """Change grid division, swing and snapping (only the given fields)."""
    return await rcall("grid_set", division=division, swing=swing, swing_amount=swing_amount, snap=snap)
