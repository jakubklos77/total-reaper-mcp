"""Track routing: sends, receives and hardware outputs."""
from typing import Annotated, Literal, Optional

from pydantic import Field

from ..core import TrackRef, destructive, rcall, read, write

TRACK = Field(description="Track: index, GUID or name")
Category = Literal["send", "receive", "hardware"]
Mode = Literal["post_fader", "pre_fx", "post_fx"]


@read
async def send_list(track: Annotated[TrackRef, TRACK]) -> dict:
    """List a track's sends (with dest_track), receives (with source_track) and hardware outputs:
    index, volume dB, pan, mute, mode, channels, MIDI flags."""
    return await rcall("send_list", track=track)


@write
async def send_create(
    track: Annotated[TrackRef, Field(description="Source track")],
    dest_track: Annotated[Optional[TrackRef], Field(description="Destination track; omit for a hardware output")] = None,
    volume_db: Annotated[Optional[float], Field(description="Send volume in dB")] = None,
    pan: Annotated[Optional[float], Field(description="Pan -1..1")] = None,
    mode: Annotated[Optional[Mode], Field(description="Tap point (default post_fader)")] = None,
    mute: Annotated[Optional[bool], Field(description="Mute the send")] = None,
) -> dict:
    """Create a send to another track (e.g. a reverb bus) or a hardware output."""
    return await rcall("send_create", track=track, dest_track=dest_track, volume_db=volume_db, pan=pan,
                       mode=mode, mute=mute)


@write
async def send_set(
    track: Annotated[TrackRef, TRACK],
    index: Annotated[int, Field(description="Index within the category (see send_list)")],
    category: Annotated[Category, Field(description="send, receive or hardware")] = "send",
    volume_db: Annotated[Optional[float], Field(description="Volume in dB")] = None,
    pan: Annotated[Optional[float], Field(description="Pan -1..1")] = None,
    mute: Annotated[Optional[bool], Field(description="Mute")] = None,
    mode: Annotated[Optional[Mode], Field(description="Tap point")] = None,
    src_channel: Annotated[Optional[int], Field(description="Source channel (0 = 1/2, 1024+n = mono n, -1 = no audio)")] = None,
    dst_channel: Annotated[Optional[int], Field(description="Destination channel (0 = 1/2, 1024+n = mono n)")] = None,
    midi_flags: Annotated[Optional[int], Field(description="MIDI: low 5 bits source channel (0 = all, 31 = none), next 5 bits destination channel")] = None,
) -> dict:
    """Change a send/receive/hardware output (only the given fields)."""
    return await rcall("send_set", track=track, index=index, category=category, volume_db=volume_db, pan=pan,
                       mute=mute, mode=mode, src_channel=src_channel, dst_channel=dst_channel, midi_flags=midi_flags)


@destructive
async def send_delete(
    track: Annotated[TrackRef, TRACK],
    index: Annotated[int, Field(description="Index within the category")],
    category: Annotated[Category, Field(description="send, receive or hardware")] = "send",
) -> dict:
    """Remove a send, receive or hardware output."""
    return await rcall("send_delete", track=track, index=index, category=category)
