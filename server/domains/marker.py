"""Project markers and regions (identified by the number REAPER displays + whether it is a region)."""
from typing import Annotated, Optional

from pydantic import Field

from ..core import destructive, rcall, read, write

NUMBER = Field(description="Marker/region number as displayed in REAPER")
REGION = Field(description="True for a region, False for a marker")


@read
async def marker_list() -> dict:
    """List markers and regions: number, name, position, end (regions), color."""
    return await rcall("marker_list")


@write
async def marker_add(
    position: Annotated[float, Field(description="Position in seconds")],
    name: Annotated[Optional[str], Field(description="Name")] = None,
    end: Annotated[Optional[float], Field(description="Give an end to create a region")] = None,
    number: Annotated[Optional[int], Field(description="Wanted number (default: next free)")] = None,
    color: Annotated[Optional[str], Field(description="Color '#rrggbb'")] = None,
) -> dict:
    """Add a marker, or a region when `end` is given."""
    return await rcall("marker_add", position=position, name=name, end=end, number=number, color=color)


@write
async def marker_set(
    number: Annotated[int, NUMBER],
    region: Annotated[bool, REGION] = False,
    position: Annotated[Optional[float], Field(description="New position (s)")] = None,
    end: Annotated[Optional[float], Field(description="New region end (s)")] = None,
    name: Annotated[Optional[str], Field(description="New name ('' clears it)")] = None,
    color: Annotated[Optional[str], Field(description="Color '#rrggbb'")] = None,
    clear_color: Annotated[Optional[bool], Field(description="Remove the custom color")] = None,
) -> dict:
    """Edit a marker or region (only the given fields)."""
    return await rcall("marker_set", number=number, region=region, position=position, end=end, name=name,
                       color=color, clear_color=clear_color)


@destructive
async def marker_delete(
    number: Annotated[int, NUMBER],
    region: Annotated[bool, REGION] = False,
) -> dict:
    """Delete a marker or region."""
    return await rcall("marker_delete", number=number, region=region)
