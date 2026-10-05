from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AnnouncementCreate(BaseModel):
    event_id: Optional[str] = None
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, v: str) -> str:
        # min_length counts spaces, so "   " would otherwise pass and get
        # stored as an empty announcement.
        stripped = v.strip()
        if not stripped:
            raise ValueError("Announcement text can't be blank.")
        return stripped


class AnnouncementOut(BaseModel):
    id: str
    event_id: Optional[str] = None
    body: str
    author_name: str
    created_at: datetime
