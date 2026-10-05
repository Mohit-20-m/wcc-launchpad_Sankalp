from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.services.voting import METHODS, MODES


class VotingConfigIn(BaseModel):
    mode: str
    method: str = "single"
    opens_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    max_votes: int = Field(default=3, ge=1, le=50)
    credits: int = Field(default=100, ge=1, le=10000)
    round_id: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of: {', '.join(MODES)}")
        if self.method not in METHODS:
            raise ValueError(f"method must be one of: {', '.join(METHODS)}")
        if self.mode != "off":
            if self.closes_at is None:
                raise ValueError("Set when voting closes.")
            if self.opens_at and self.closes_at <= self.opens_at:
                raise ValueError("Voting must close after it opens.")
        return self


class VotingConfigOut(BaseModel):
    mode: str
    method: str
    opens_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    max_votes: int
    credits: int
    round_id: Optional[str] = None
    state: str  # off | not_open | open | closed
    results_published: bool


class Allocation(BaseModel):
    project_id: str
    votes: int = Field(ge=1, le=20)


class BallotIn(BaseModel):
    allocations: list[Allocation] = Field(default_factory=list, max_length=200)
    email: Optional[str] = Field(default=None, max_length=255)      # email-gated
    voter_token: Optional[str] = Field(default=None, min_length=16, max_length=100)  # open link

    @model_validator(mode="after")
    def _unique(self):
        ids = [a.project_id for a in self.allocations]
        if len(ids) != len(set(ids)):
            raise ValueError("Each project can appear once on a ballot.")
        return self


class BallotProject(BaseModel):
    id: str
    title: str
    summary: Optional[str] = None
    team_name: str
    track_name: Optional[str] = None
    tech_stack: Optional[str] = None
    repo_url: Optional[str] = None
    video_url: Optional[str] = None
    my_votes: int = 0


class BallotOut(BaseModel):
    config: VotingConfigOut
    projects: list[BallotProject]
    credits_used: int = 0
    can_vote: bool
    reason: Optional[str] = None


class AllowlistIn(BaseModel):
    patterns: list[str] = Field(min_length=1, max_length=500)


class AllowlistOut(BaseModel):
    patterns: list[str]


class VoteResultRow(BaseModel):
    project_id: str
    project_title: str
    team_name: str
    votes: int
    voters: int
    rank: int


class BallotAdminRow(BaseModel):
    voter_ref: str
    kind: str
    votes: int
    credits: int
    projects: int
    ip_ref: Optional[str] = None
    shared_ip_voters: int = 0
    flagged: bool
    voided: bool
    updated_at: datetime
