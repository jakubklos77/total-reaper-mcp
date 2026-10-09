"""Automation envelopes: track envelopes by name, FX parameter envelopes, take envelopes.

Target with `track` + `name` (e.g. 'Volume', 'Pan', 'Width', 'Mute'), `track` + `fx` + `param`,
or `item` (+ `take`) + `name`."""
from typing import Annotated, List, Optional

from pydantic import BaseModel, Field

from ..core import ItemRef, TrackRef, destructive, rcall, read, write

TRACK = Field(description="Track: index, -1 = master, GUID or name")
NAME = Field(description="Envelope name as shown in REAPER: 'Volume', 'Pan', 'Width', 'Mute', 'Volume (Pre-FX)', 'Trim Volume' (take: 'Volume', 'Pan', 'Mute', 'Pitch')")
FXI = Field(description="FX index (for an FX parameter envelope)")
PARAM = Field(description="FX parameter index (with fx)")
ITEM = Field(description="Item for a take envelope")
TAKE = Field(description="Take index, -1 = active")


class Point(BaseModel):
    time: float = Field(description="Position in seconds")
    value: Optional[float] = Field(None, description="Raw envelope value (pan -1..1, FX params 0..1, ...)")
    value_db: Optional[float] = Field(None, description="For volume envelopes: value in dB")
    shape: int = Field(0, ge=0, le=5, description="0 linear, 1 square, 2 slow start/end, 3 fast start, 4 fast end, 5 bezier")
    tension: float = Field(0, ge=-1, le=1, description="Bezier tension")


def _t(track, name, fx, param, item, take):
    return dict(track=track, name=name, fx=fx, param=param, item=item, take=take if item is not None else None)


@read
async def envelope_list(
    track: Annotated[Optional[TrackRef], TRACK] = None,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
) -> dict:
    """List the envelopes of a track (incl. FX parameter envelopes, with fx/param) or of a take."""
    return await rcall("envelope_list", track=track, item=item, take=take if item is not None else None)


@read
async def envelope_get(
    track: Annotated[Optional[TrackRef], TRACK] = None,
    name: Annotated[Optional[str], NAME] = None,
    fx: Annotated[Optional[int], FXI] = None,
    param: Annotated[Optional[int], PARAM] = None,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    start: Annotated[Optional[float], Field(description="Only points at/after this time (s)")] = None,
    end: Annotated[Optional[float], Field(description="Only points at/before this time (s)")] = None,
) -> dict:
    """Get an envelope's state (active/visible/armed) and points (time, value, value_db for volume,
    shape, tension)."""
    return await rcall("envelope_get", start=start, end=end, **_t(track, name, fx, param, item, take))


@write
async def envelope_points_set(
    points: Annotated[List[Point], Field(description="Points to write")],
    track: Annotated[Optional[TrackRef], TRACK] = None,
    name: Annotated[Optional[str], NAME] = None,
    fx: Annotated[Optional[int], FXI] = None,
    param: Annotated[Optional[int], PARAM] = None,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    replace: Annotated[bool, Field(description="Delete existing points between the first and last new point first")] = True,
    create: Annotated[bool, Field(description="Create/show the envelope if it doesn't exist (track built-ins and FX params)")] = True,
) -> dict:
    """Write automation points (batch, one undo step), e.g. a volume fade or a filter sweep."""
    return await rcall("envelope_points_set", points=[q.model_dump(exclude_none=True) for q in points],
                       replace=replace, create=create, **_t(track, name, fx, param, item, take))


@destructive
async def envelope_points_delete(
    track: Annotated[Optional[TrackRef], TRACK] = None,
    name: Annotated[Optional[str], NAME] = None,
    fx: Annotated[Optional[int], FXI] = None,
    param: Annotated[Optional[int], PARAM] = None,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    start: Annotated[Optional[float], Field(description="From this time (s); default: beginning")] = None,
    end: Annotated[Optional[float], Field(description="To this time (s); default: end")] = None,
) -> dict:
    """Delete envelope points in a time range (default: all)."""
    return await rcall("envelope_points_delete", start=start, end=end, **_t(track, name, fx, param, item, take))


@write
async def envelope_set(
    track: Annotated[Optional[TrackRef], TRACK] = None,
    name: Annotated[Optional[str], NAME] = None,
    fx: Annotated[Optional[int], FXI] = None,
    param: Annotated[Optional[int], PARAM] = None,
    item: Annotated[Optional[ItemRef], ITEM] = None,
    take: Annotated[int, TAKE] = -1,
    active: Annotated[Optional[bool], Field(description="Envelope affects playback")] = None,
    visible: Annotated[Optional[bool], Field(description="Show the envelope lane")] = None,
    armed: Annotated[Optional[bool], Field(description="Arm for automation recording")] = None,
    create: Annotated[bool, Field(description="Create the envelope if missing")] = True,
) -> dict:
    """Show/hide, activate/bypass or arm an envelope (creates track built-ins / FX envelopes if needed)."""
    return await rcall("envelope_set", active=active, visible=visible, armed=armed, create=create,
                       **_t(track, name, fx, param, item, take))
