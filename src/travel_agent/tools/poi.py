from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PoiItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str
    distance_m: int = Field(ge=0)
    walking_minutes: int = Field(ge=1)
    supports: list[str] = Field(default_factory=list)
    source: str


class PoiSearchResult(BaseModel):
    """Provider-neutral output contract for the search_poi tool."""

    model_config = ConfigDict(extra="forbid")

    location: str
    latitude: float
    longitude: float
    radius_m: int
    provider: str
    attribution: str
    verified_preferences: list[str] = Field(default_factory=list)
    unverified_preferences: list[str] = Field(default_factory=list)
    results: list[PoiItem] = Field(default_factory=list)
