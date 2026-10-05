from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CriterionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    weight: float = Field(gt=0)
    description: Optional[str] = None


class CriterionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    weight: float
    description: Optional[str] = None


class AssignmentCreate(BaseModel):
    judge_email: str
    project_id: str


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    judge_user_id: str
    project_id: str


class ScoreSubmit(BaseModel):
    project_id: str
    criteria: dict[str, float]
    comment: Optional[str] = None

    @field_validator("criteria")
    @classmethod
    def validate_criteria_range(cls, v: dict[str, float]) -> dict[str, float]:
        # Matches the 1-5 scale fixtures.json's own scores use. Found
        # missing after a real submitted score showed up in a CSV export
        # with values like 7.6 and 8.0 -- silently accepted before this
        # validator existed, which would have quietly distorted
        # normalization for that judge and skewed that project's ranking.
        if not v:
            raise ValueError("At least one criterion score is required.")
        for key, value in v.items():
            if not (1 <= value <= 5):
                raise ValueError(f"'{key}' must be between 1 and 5, got {value}.")
        return v


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    judge_user_id: str
    project_id: str
    criteria: dict
    comment: Optional[str] = None


class ProgressOut(BaseModel):
    judge_user_id: str
    judge_email: str
    judge_name: str = ""
    assigned: int
    completed: int


class ResultRow(BaseModel):
    project_id: str
    project_title: str
    team_name: str = ""
    judge_count: int
    raw_average: float
    normalized_score: float


class QueueFile(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int


class QueueItem(BaseModel):
    """One assigned project as the judge console shows it."""

    project_id: str
    project_title: str
    project_summary: Optional[str] = None
    repo_url: Optional[str] = None
    tech_stack: Optional[str] = None
    video_url: Optional[str] = None
    team_name: str
    track_name: Optional[str] = None
    event_id: str
    event_name: str
    scored: bool
    round_id: Optional[str] = None
    round_name: Optional[str] = None
    round_number: Optional[int] = None
    # False until the round's submissions are closed (deadline passed or
    # the organizer stopped them): judges cannot score work that can still change.
    scorable: bool = False
    conflict: bool = False
    files: list[QueueFile] = []


class JudgeOut(BaseModel):
    id: str
    name: str
    email: str


class ConflictDeclare(BaseModel):
    project_id: str
    reason: Optional[str] = Field(default=None, max_length=500)


class ConflictOut(BaseModel):
    project_id: str
    judge_user_id: str
    project_title: str
    judge_name: str
    judge_email: str
    reason: Optional[str] = None
    created_at: datetime
