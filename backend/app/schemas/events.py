from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.schemas.rounds import RoundCreate, RoundOut


class TrackCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class PrizeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    amount: Optional[float] = None


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    # Optional when `rounds` are given (the event's deadline is then the
    # last round's). Required for a single-round event.
    submissions_close: Optional[datetime] = None
    rounds: list[RoundCreate] = []
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    capacity: Optional[int] = Field(default=None, ge=1)
    tracks: list[TrackCreate] = []
    prizes: list[PrizeCreate] = []

    @model_validator(mode="after")
    def validate_dates(self):
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValueError("ends_at must not be before starts_at.")
        if not self.rounds and self.submissions_close is None:
            raise ValueError("Set a submission deadline (submissions_close), or define rounds.")
        closes = [r.closes_at for r in self.rounds]
        if closes != sorted(closes):
            raise ValueError("Round deadlines must be in order: each round closes after the one before it.")
        return self


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str


class PrizeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    amount: Optional[float] = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: Optional[str] = None
    submissions_close: datetime
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    capacity: Optional[int] = None
    results_published_at: Optional[datetime] = None
    voting_mode: str = "off"
    tracks: list[TrackOut] = []
    prizes: list[PrizeOut] = []
    rounds: list[RoundOut] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> str:
        """Derived from the real dates and round states, never stored:
        upcoming -> submissions_open -> judging."""
        now = datetime.now(timezone.utc)
        if self.starts_at and now < _aware(self.starts_at):
            return "upcoming"
        states = [r.state for r in self.rounds]
        if states:
            if "open" in states:
                return "submissions_open"
            if all(st == "not_open" for st in states):
                return "upcoming"
            return "judging"
        return "submissions_open" if now < _aware(self.submissions_close) else "judging"


class EventStats(BaseModel):
    teams: int
    participants: int
    submissions: int
    judges_assigned: int
    reviews_assigned: int
    reviews_done: int


class SubmissionRow(BaseModel):
    project_id: str
    title: str
    team_name: str
    track_name: Optional[str] = None
    submitted_at: Optional[datetime] = None
    round_id: Optional[str] = None
    round_number: Optional[int] = None
    round_name: Optional[str] = None
    assigned: int
    reviewed: int


class TeamRow(BaseModel):
    """A team as the organizer sees it (for pickers and rosters)."""

    id: str
    name: str
    members: int
    submitted_rounds: int
