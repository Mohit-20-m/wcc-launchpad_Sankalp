from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import UserRole


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A comment can't be blank.")
        return v


class CommentOut(BaseModel):
    id: str
    project_id: str
    author_name: str
    body: str
    created_at: datetime
    hidden: bool = False


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: Optional[str] = None
    actor_label: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail: Optional[str] = None
    created_at: datetime


class InviteCreate(BaseModel):
    role: UserRole
    label: Optional[str] = Field(default=None, max_length=255)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_in_days: Optional[int] = Field(default=14, ge=1, le=365)
    event_id: Optional[str] = None


class InviteOut(BaseModel):
    id: str
    code: str
    role: UserRole
    label: Optional[str] = None
    event_id: Optional[str] = None
    max_uses: int
    used_count: int
    expires_at: Optional[datetime] = None
    revoked: bool
    created_at: datetime


class PublicResultRow(BaseModel):
    rank: int
    project_id: str
    project_title: str
    team_name: str
    normalized_score: float
    raw_average: float


class WinnerOut(BaseModel):
    prize_name: str
    amount: Optional[float] = None
    rank: int
    project_id: str
    project_title: str
    team_name: str


class PublicResultsOut(BaseModel):
    event_id: str
    event_name: str
    published_at: datetime
    round_name: str
    judges_ranking: list[PublicResultRow]
    winners: list[WinnerOut]
    community: list["CommunityRow"] = []
    audit_anchor: Optional[dict] = None


class CommunityRow(BaseModel):
    rank: int
    project_id: str
    project_title: str
    team_name: str
    votes: int


PublicResultsOut.model_rebuild()


class PublishRequest(BaseModel):
    round_id: Optional[str] = None  # which round's judging to publish (default: last with scores)
