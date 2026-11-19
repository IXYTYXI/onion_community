from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictBool

from app.schemas.common import InputModel


class CaseContact(BaseModel):
    name: str
    chat_url: str


class Case(BaseModel):
    id: str
    title: str
    summary: str = ''
    team: str = ''
    author: str = ''
    tags: list[str] = Field(default_factory=list)
    product_type: str = ''
    source: str = ''
    number: str = ''
    access: str
    url: str | None = None
    contact_url: str | None = None
    ai_officers: list[CaseContact] = Field(default_factory=list)
    image: str | None = None


class CaseDirectory(BaseModel):
    items: list[Case]
    updated_at: datetime
    stale: bool = False


EngagementAction = Literal['like', 'favorite']


class EngagementInput(InputModel):
    active: StrictBool


class CaseEngagement(BaseModel):
    liked: bool = False
    favorited: bool = False
    like_count: int = 0
    favorite_count: int = 0
    liked_at: int | None = None
    favorited_at: int | None = None


class EngagementDirectory(BaseModel):
    personal_lists: Literal['00', '01', '10', '11']
    items: dict[str, CaseEngagement]
