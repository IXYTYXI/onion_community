from datetime import datetime
from pydantic import BaseModel, Field


class ActivityLink(BaseModel):
    title: str
    url: str


class ActivityPhoto(BaseModel):
    id: str
    name: str = ""
    url: str


class ActivityItem(BaseModel):
    id: str
    title: str
    summary: str = ""
    speaker: str = ""
    organizer: str = ""
    audience: str = ""
    location: str = ""
    date_label: str = ""
    time_label: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    signup_url: str | None = None
    calendar_url: str | None = None
    documents: list[ActivityLink] = Field(default_factory=list)
    replays: list[ActivityLink] = Field(default_factory=list)
    cover_image: str | None = None
    photos: list[ActivityPhoto] = Field(default_factory=list)


class ActivityDirectory(BaseModel):
    items: list[ActivityItem]
    updated_at: datetime
    stale: bool = False
