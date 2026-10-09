"""Media items and takes."""
from typing import Annotated, List, Optional

from pydantic import Field

from ..core import ItemRef, TrackRef, destructive, rcall, read, write

ITEM = Field(description="Item: project-wide 0-based index (see item_list) or GUID")
TAKE = Field(description="Take index on the item, -1 = active take")
TRACK = Field(description="Track: 0-based index, GUID or exact name")


@read
async def item_list(
    track: Annotated[Optional[TrackRef], Field(description="Only items on this track")] = None,
    start: Annotated[Optional[float], Field(description="Only items ending after this time (s)")] = None,
    end: Annotated[Optional[float], Field(description="Only items starting before this time (s)")] = None,
    selected_only: Annotated[bool, Field(description="Only selected items")] = False,
) -> dict:
    """List items (index, guid, track, position, length, end, name, midi, mute, locked, selected,
    color, take count, active take), optionally filtered by track / time range / selection."""
    return await rcall("item_list", track=track, start=start, end=end, selected_only=selected_only)


@read
async def item_get(item: Annotated[ItemRef, ITEM]) -> dict:
    """Full detail for one item incl. volume, fades, snap offset, notes and all takes
    (name, source file/type, volume, pan, pitch, playrate, offset; note/CC counts for MIDI)."""
    return await rcall("item_get", item=item)


@write
async def item_create_midi(
    track: Annotated[TrackRef, TRACK],
    start: Annotated[float, Field(description="Start in seconds")],
    end: Annotated[Optional[float], Field(description="End in seconds (or give length)")] = None,
    length: Annotated[Optional[float], Field(description="Length in seconds (or give end)")] = None,
    name: Annotated[Optional[str], Field(description="Take name")] = None,
) -> dict:
    """Create an empty MIDI item. Fill it with midi_insert_notes / midi_set."""
    return await rcall("item_create_midi", track=track, start=start, end=end, length=length, name=name)


@write
async def item_insert_media(
    track: Annotated[TrackRef, TRACK],
    path: Annotated[str, Field(description="Audio/MIDI/video file path on the REAPER machine")],
    position: Annotated[float, Field(description="Start in seconds")] = 0.0,
    length: Annotated[Optional[float], Field(description="Item length in seconds (default: source length)")] = None,
) -> dict:
    """Insert a media file as a new item."""
    return await rcall("item_insert_media", track=track, path=path, position=position, length=length)


@destructive
async def item_delete(item: Annotated[ItemRef, ITEM]) -> dict:
    """Delete an item. Note: indices of later items shift down by one."""
    return await rcall("item_delete", item=item)


@write
async def item_set(
    item: Annotated[ItemRef, ITEM],
    position: Annotated[Optional[float], Field(description="Start in seconds")] = None,
    length: Annotated[Optional[float], Field(description="Length in seconds")] = None,
    track: Annotated[Optional[TrackRef], Field(description="Move to this track")] = None,
    mute: Annotated[Optional[bool], Field(description="Mute")] = None,
    locked: Annotated[Optional[bool], Field(description="Lock")] = None,
    selected: Annotated[Optional[bool], Field(description="Selected")] = None,
    name: Annotated[Optional[str], Field(description="Name of the active take")] = None,
    color: Annotated[Optional[str], Field(description="Color '#rrggbb'")] = None,
    clear_color: Annotated[Optional[bool], Field(description="Remove the custom color")] = None,
    volume_db: Annotated[Optional[float], Field(description="Item volume in dB")] = None,
    fade_in: Annotated[Optional[float], Field(description="Fade-in length (s)")] = None,
    fade_out: Annotated[Optional[float], Field(description="Fade-out length (s)")] = None,
    fade_in_shape: Annotated[Optional[int], Field(description="Fade-in shape 0-6")] = None,
    fade_out_shape: Annotated[Optional[int], Field(description="Fade-out shape 0-6")] = None,
    snap_offset: Annotated[Optional[float], Field(description="Snap offset (s)")] = None,
    loop_source: Annotated[Optional[bool], Field(description="Loop the source when the item is longer")] = None,
    active_take: Annotated[Optional[int], Field(description="Make this take index active")] = None,
    notes: Annotated[Optional[str], Field(description="Item notes")] = None,
) -> dict:
    """Change item properties - only the given fields, in one undo step. Returns the item."""
    return await rcall("item_set", item=item, position=position, length=length, track=track, mute=mute,
                       locked=locked, selected=selected, name=name, color=color, clear_color=clear_color,
                       volume_db=volume_db, fade_in=fade_in, fade_out=fade_out, fade_in_shape=fade_in_shape,
                       fade_out_shape=fade_out_shape, snap_offset=snap_offset, loop_source=loop_source,
                       active_take=active_take, notes=notes)


@write
async def item_split(
    item: Annotated[ItemRef, ITEM],
    position: Annotated[float, Field(description="Split point in seconds (inside the item)")],
) -> dict:
    """Split an item in two; returns the left and right items."""
    return await rcall("item_split", item=item, position=position)


@write
async def item_duplicate(
    item: Annotated[ItemRef, ITEM],
    position: Annotated[Optional[float], Field(description="Place the copy here (default: right after the item)")] = None,
    track: Annotated[Optional[TrackRef], Field(description="Place the copy on this track")] = None,
) -> dict:
    """Duplicate an item (with all takes)."""
    return await rcall("item_duplicate", item=item, position=position, track=track)


@write
async def item_glue(
    items: Annotated[List[ItemRef], Field(description="Items to glue (per track, adjacent items are joined)")],
) -> dict:
    """Glue items into one per track (renders audio items to a new file; MIDI is merged)."""
    return await rcall("item_glue", items=items)


@write
async def item_select(
    items: Annotated[List[ItemRef], Field(description="Items to select; [] clears the selection")],
    add: Annotated[bool, Field(description="Add to the current selection")] = False,
) -> dict:
    """Set the item selection (many REAPER actions work on selected items)."""
    return await rcall("item_select", items=items, add=add)


@read
async def item_chunk_get(item: Annotated[ItemRef, ITEM]) -> dict:
    """Get an item's complete state as RPP text (incl. inline MIDI)."""
    return await rcall("item_chunk_get", item=item)


@destructive
async def item_chunk_set(
    item: Annotated[ItemRef, ITEM],
    chunk: Annotated[str, Field(description="Full '<ITEM ...>' state text")],
) -> dict:
    """Replace an item's complete state with RPP text (one undo step)."""
    return await rcall("item_chunk_set", item=item, chunk=chunk)


@write
async def take_set(
    item: Annotated[ItemRef, ITEM],
    take: Annotated[int, TAKE] = -1,
    name: Annotated[Optional[str], Field(description="Take name")] = None,
    volume_db: Annotated[Optional[float], Field(description="Take volume in dB")] = None,
    pan: Annotated[Optional[float], Field(description="Pan -1..1")] = None,
    pitch: Annotated[Optional[float], Field(description="Pitch shift in semitones")] = None,
    playrate: Annotated[Optional[float], Field(description="Playback rate (1 = normal)")] = None,
    preserve_pitch: Annotated[Optional[bool], Field(description="Preserve pitch when changing rate")] = None,
    start_offset: Annotated[Optional[float], Field(description="Offset into the source (s)")] = None,
    color: Annotated[Optional[str], Field(description="Color '#rrggbb'")] = None,
    active: Annotated[Optional[bool], Field(description="Make this the active take")] = None,
) -> dict:
    """Change take properties - only the given fields. Returns the take."""
    return await rcall("take_set", item=item, take=take, name=name, volume_db=volume_db, pan=pan, pitch=pitch,
                       playrate=playrate, preserve_pitch=preserve_pitch, start_offset=start_offset,
                       color=color, active=active)


@write
async def take_add(
    item: Annotated[ItemRef, ITEM],
    path: Annotated[Optional[str], Field(description="Media file for the new take (default: empty take)")] = None,
    name: Annotated[Optional[str], Field(description="Take name")] = None,
    active: Annotated[bool, Field(description="Make the new take active")] = True,
) -> dict:
    """Add a take to an item (empty or from a media file)."""
    return await rcall("take_add", item=item, path=path, name=name, active=active)


@destructive
async def take_delete(
    item: Annotated[ItemRef, ITEM],
    take: Annotated[int, TAKE],
) -> dict:
    """Delete one take from an item (an item must keep at least one take)."""
    return await rcall("take_delete", item=item, take=take)
