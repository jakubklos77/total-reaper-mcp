"""MIDI editing. Positions are in `unit`: 'qn' (project quarter notes - follows the tempo map),
'seconds' (project time) or 'ppq' (take ticks)."""
from typing import Annotated, Any, List, Literal, Optional

from pydantic import BaseModel, Field

from ..core import ItemRef, destructive, rcall, read, write

ITEM = Field(description="MIDI item: project-wide 0-based index or GUID")
TAKE = Field(description="Take index on the item, -1 = active take")
Unit = Literal["qn", "seconds", "ppq"]
UNIT = Field(description="Unit of all positions/lengths: 'qn' (project quarter notes, follows the tempo map), 'seconds' (project time) or 'ppq' (take ticks)")


class Note(BaseModel):
    pitch: int = Field(ge=0, le=127, description="MIDI note number (60 = middle C)")
    start: float = Field(description="Start position in `unit`")
    length: Optional[float] = Field(None, gt=0, description="Length in `unit` (or give end)")
    end: Optional[float] = Field(None, description="End position in `unit`")
    velocity: int = Field(96, ge=1, le=127)
    channel: int = Field(0, ge=0, le=15)
    selected: bool = False
    muted: bool = False


class NoteEdit(BaseModel):
    index: int = Field(ge=0, description="Note index from midi_get")
    pitch: Optional[int] = Field(None, ge=0, le=127)
    velocity: Optional[int] = Field(None, ge=1, le=127)
    start: Optional[float] = Field(None, description="New start (moving keeps the length unless end/length given)")
    end: Optional[float] = None
    length: Optional[float] = Field(None, gt=0)
    channel: Optional[int] = Field(None, ge=0, le=15)
    selected: Optional[bool] = None
    muted: Optional[bool] = None


class CC(BaseModel):
    position: float = Field(description="Position in `unit`")
    type: Literal["cc", "pitchbend", "program", "channel_pressure", "poly_aftertouch"] = "cc"
    cc: Optional[int] = Field(None, ge=0, le=127, description="Controller number (type cc), e.g. 64 = sustain pedal, 1 = mod wheel")
    value: int = Field(description="0-127; pitchbend -8192..8191")
    channel: int = Field(0, ge=0, le=15)
    selected: bool = False
    muted: bool = False


def _dump(models):
    return [m.model_dump(exclude_none=True) for m in models]


def _filter(indices, pitch_min, pitch_max, start, end, channel, selected_only):
    return dict(indices=indices, pitch_min=pitch_min, pitch_max=pitch_max, start=start, end=end,
                channel=channel, selected_only=selected_only or None)


@read
async def midi_get(
    item: Annotated[ItemRef, ITEM],
    take: Annotated[int, TAKE] = -1,
    notes: Annotated[bool, Field(description="Include notes")] = True,
    ccs: Annotated[bool, Field(description="Include CC / pitch bend / program / pressure events")] = True,
    events: Annotated[bool, Field(description="Include the raw event stream (every event incl. sysex, as hex) - for lossless midi_set round trips")] = False,
) -> dict:
    """Read a MIDI take. Notes/CCs/events are compact rows; `note_fields` / `cc_fields` / `event_fields`
    name the columns (positions given in qn, seconds and ppq). Also returns counts, ppq_per_qn, item
    position/length and whether the take follows the project tempo."""
    return await rcall("midi_get", item=item, take=take, notes=notes, ccs=ccs, events=events)


@destructive
async def midi_set(
    item: Annotated[ItemRef, ITEM],
    events: Annotated[List[List[Any]], Field(description="ALL events as [position, flags(1=selected,2=muted), hex_message], e.g. [0, 0, '903c64']. Same-position events keep their order. Include the end-of-take event if there was one.")],
    take: Annotated[int, TAKE] = -1,
    unit: Annotated[Unit, UNIT] = "ppq",
    fit_item: Annotated[bool, Field(description="Set the item end to the last event")] = False,
) -> dict:
    """Replace ALL events of a take in one undo step (lossless rewrite; pair with midi_get events=true).
    unit='seconds' converts with the CURRENT tempo map - use it after tempo_map_set to keep a
    performance at the same absolute time."""
    return await rcall("midi_set", item=item, take=take, events=events, unit=unit, fit_item=fit_item)


@write
async def midi_insert_notes(
    item: Annotated[ItemRef, ITEM],
    notes: Annotated[List[Note], Field(description="Notes to insert")],
    take: Annotated[int, TAKE] = -1,
    unit: Annotated[Unit, UNIT] = "qn",
) -> dict:
    """Insert notes (batch, one undo step). Positions are project positions in `unit`, not relative
    to the item: with unit='qn', qn 0 is the project start."""
    return await rcall("midi_insert_notes", item=item, take=take, unit=unit, notes=_dump(notes))


@write
async def midi_edit_notes(
    item: Annotated[ItemRef, ITEM],
    edits: Annotated[List[NoteEdit], Field(description="Changes per note index (from midi_get); only given fields change")],
    take: Annotated[int, TAKE] = -1,
    unit: Annotated[Unit, UNIT] = "qn",
) -> dict:
    """Edit notes by index (batch, one undo step): pitch, velocity, start/end/length, channel, selection, mute."""
    return await rcall("midi_edit_notes", item=item, take=take, unit=unit, edits=_dump(edits))


@destructive
async def midi_delete_notes(
    item: Annotated[ItemRef, ITEM],
    take: Annotated[int, TAKE] = -1,
    indices: Annotated[Optional[List[int]], Field(description="Only these note indices")] = None,
    pitch_min: Annotated[Optional[int], Field(description="Only pitches >= this")] = None,
    pitch_max: Annotated[Optional[int], Field(description="Only pitches <= this")] = None,
    start: Annotated[Optional[float], Field(description="Only notes starting at/after this (unit)")] = None,
    end: Annotated[Optional[float], Field(description="Only notes starting before this (unit)")] = None,
    channel: Annotated[Optional[int], Field(description="Only this channel")] = None,
    selected_only: Annotated[bool, Field(description="Only selected notes")] = False,
    unit: Annotated[Unit, UNIT] = "qn",
) -> dict:
    """Delete notes matching ALL given filters (no filter = all notes)."""
    return await rcall("midi_delete_notes", item=item, take=take, unit=unit,
                       **_filter(indices, pitch_min, pitch_max, start, end, channel, selected_only))


@write
async def midi_insert_ccs(
    item: Annotated[ItemRef, ITEM],
    ccs: Annotated[List[CC], Field(description="CC / pitch bend / program / pressure events")],
    take: Annotated[int, TAKE] = -1,
    unit: Annotated[Unit, UNIT] = "qn",
) -> dict:
    """Insert controller events (batch, one undo step), e.g. sustain pedal = cc 64 (127 down, 0 up)."""
    return await rcall("midi_insert_ccs", item=item, take=take, unit=unit, ccs=_dump(ccs))


@destructive
async def midi_delete_ccs(
    item: Annotated[ItemRef, ITEM],
    take: Annotated[int, TAKE] = -1,
    indices: Annotated[Optional[List[int]], Field(description="Only these CC indices")] = None,
    type: Annotated[Optional[Literal["cc", "pitchbend", "program", "channel_pressure", "poly_aftertouch"]], Field(description="Only this event type")] = None,
    cc: Annotated[Optional[int], Field(description="Only this controller number")] = None,
    start: Annotated[Optional[float], Field(description="Only events at/after this (unit)")] = None,
    end: Annotated[Optional[float], Field(description="Only events before this (unit)")] = None,
    channel: Annotated[Optional[int], Field(description="Only this channel")] = None,
    selected_only: Annotated[bool, Field(description="Only selected events")] = False,
    unit: Annotated[Unit, UNIT] = "qn",
) -> dict:
    """Delete controller events matching ALL given filters (no filter = all)."""
    return await rcall("midi_delete_ccs", item=item, take=take, unit=unit, indices=indices, type=type, cc=cc,
                       start=start, end=end, channel=channel, selected_only=selected_only or None)


@write
async def midi_quantize(
    item: Annotated[ItemRef, ITEM],
    grid: Annotated[float, Field(gt=0, description="Grid in quarter notes: 1 = quarter, 0.5 = eighth, 0.25 = 16th, 1/3 = eighth triplet")],
    take: Annotated[int, TAKE] = -1,
    strength: Annotated[float, Field(ge=0, le=1, description="0 = unchanged .. 1 = exactly on the grid")] = 1.0,
    swing: Annotated[float, Field(ge=-1, le=1, description="Shift every second grid point by swing * grid/2")] = 0.0,
    ends: Annotated[bool, Field(description="Also quantize note ends (otherwise lengths are kept)")] = False,
    indices: Annotated[Optional[List[int]], Field(description="Only these note indices")] = None,
    pitch_min: Annotated[Optional[int], Field(description="Only pitches >= this")] = None,
    pitch_max: Annotated[Optional[int], Field(description="Only pitches <= this")] = None,
    start: Annotated[Optional[float], Field(description="Only notes starting at/after this (qn)")] = None,
    end: Annotated[Optional[float], Field(description="Only notes starting before this (qn)")] = None,
    selected_only: Annotated[bool, Field(description="Only selected notes")] = False,
) -> dict:
    """Quantize note starts to a grid of PROJECT quarter notes (follows the tempo map, so a tempo-synced
    performance snaps to the played beats). One undo step."""
    return await rcall("midi_quantize", item=item, take=take, grid=grid, strength=strength, swing=swing,
                       ends=ends, unit="qn", **_filter(indices, pitch_min, pitch_max, start, end, None, selected_only))


@write
async def midi_transpose(
    item: Annotated[ItemRef, ITEM],
    semitones: Annotated[int, Field(description="Semitones up (positive) or down (negative)")],
    take: Annotated[int, TAKE] = -1,
    indices: Annotated[Optional[List[int]], Field(description="Only these note indices")] = None,
    pitch_min: Annotated[Optional[int], Field(description="Only pitches >= this")] = None,
    pitch_max: Annotated[Optional[int], Field(description="Only pitches <= this")] = None,
    start: Annotated[Optional[float], Field(description="Only notes starting at/after this (unit)")] = None,
    end: Annotated[Optional[float], Field(description="Only notes starting before this (unit)")] = None,
    selected_only: Annotated[bool, Field(description="Only selected notes")] = False,
    unit: Annotated[Unit, UNIT] = "qn",
) -> dict:
    """Transpose notes (all, or those matching the filters). Fails if a note would leave 0-127."""
    return await rcall("midi_transpose", item=item, take=take, semitones=semitones, unit=unit,
                       **_filter(indices, pitch_min, pitch_max, start, end, None, selected_only))
