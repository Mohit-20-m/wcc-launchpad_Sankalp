from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.projects import ProjectOut


class TeamCreate(BaseModel):
    event_id: str
    name: str = Field(min_length=1, max_length=255)


class TeamJoin(BaseModel):
    invite_code: str


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    name: str
    # NOTE (documented simplification): invite_code is returned to anyone
    # who can view the team by id, not gated to members only. The new
    # /teams/mine endpoint below is the members-only view the consoles use.
    invite_code: str


class TeamMemberOut(BaseModel):
    user_id: str
    name: str
    is_leader: bool


class TeamRoundStatus(BaseModel):
    """One round as THIS team experiences it (deadline includes any
    extension granted to the team; state is team-specific)."""

    round_id: str
    number: int
    name: str
    instructions: Optional[str] = None
    allow_idea: bool
    allow_repo: bool
    allow_video: bool
    allow_files: bool
    file_types: list[str]
    max_file_mb: int
    closes_at: datetime
    state: str  # not_open | open | closed
    eligible: bool  # False: the team hasn't advanced into this round
    submission: Optional[ProjectOut] = None


class TeamMineOut(BaseModel):
    id: str
    name: str
    invite_code: str
    event_id: str
    event_name: str
    submissions_close: datetime
    members: list[TeamMemberOut]
    project: Optional[ProjectOut] = None
    # Per round: the team's submission for it (None = nothing submitted yet).
    rounds: list[TeamRoundStatus] = []
    current_round_id: Optional[str] = None
