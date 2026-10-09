"""Transport and edit cursor."""
from typing import Annotated

from pydantic import Field

from ..core import rcall, read, write


@read
async def transport_state() -> dict:
    """Playing/paused/recording, play position, edit cursor and repeat state."""
    return await rcall("transport_state")


@write
async def transport_play() -> dict:
    """Start playback from the edit cursor."""
    return await rcall("transport_play")


@write
async def transport_stop() -> dict:
    """Stop playback or recording."""
    return await rcall("transport_stop")


@write
async def transport_pause() -> dict:
    """Toggle pause."""
    return await rcall("transport_pause")


@write
async def transport_record() -> dict:
    """Start recording on armed tracks."""
    return await rcall("transport_record")


@write
async def transport_set_cursor(
    position: Annotated[float, Field(description="Edit cursor position in seconds")],
    move_view: Annotated[bool, Field(description="Scroll the arrange view to the cursor")] = True,
    seek_play: Annotated[bool, Field(description="If playing, jump playback to the cursor")] = True,
) -> dict:
    """Move the edit cursor."""
    return await rcall("transport_set_cursor", position=position, move_view=move_view, seek_play=seek_play)


@write
async def transport_set_repeat(
    enabled: Annotated[bool, Field(description="Loop playback over the loop range")],
) -> dict:
    """Turn repeat (loop playback) on or off."""
    return await rcall("transport_set_repeat", enabled=enabled)
