from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import SubmissionStatus


class ProjectCreate(BaseModel):
    team_id: str
    # Which round this is for; defaults to the team's current round.
    round_id: Optional[str] = None
    track_id: Optional[str] = None
    title: str = Field(min_length=1, max_length=255)
    summary: Optional[str] = None
    repo_url: Optional[str] = None
    tech_stack: Optional[str] = None
    video_url: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    summary: Optional[str] = None
    repo_url: Optional[str] = None
    tech_stack: Optional[str] = None
    video_url: Optional[str] = None
    track_id: Optional[str] = None


class ProjectFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    team_id: str
    round_id: Optional[str] = None
    files: list[ProjectFileOut] = []
    track_id: Optional[str] = None
    title: str
    summary: Optional[str] = None
    repo_url: Optional[str] = None
    tech_stack: Optional[str] = None
    video_url: Optional[str] = None
    status: SubmissionStatus
    submitted_at: Optional[datetime] = None


class ProjectPublic(ProjectOut):
    """What the public gallery shows: the project plus its team and
    track names, so a card doesn't need extra lookups."""

    team_name: str = ""
    track_name: Optional[str] = None
    event_id: str = ""
    event_name: str = ""
    round_number: Optional[int] = None
