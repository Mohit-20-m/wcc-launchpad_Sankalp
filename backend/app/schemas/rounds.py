from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.models.round import DEFAULT_FILE_TYPES
from app.services.files import ALLOWED_EXTS
from app.services.rounds import round_state


def _clean_types(value):
    if isinstance(value, str):
        value = value.split(",")
    cleaned = []
    for v in value or []:
        v = str(v).strip().lower().lstrip(".")
        if v and v not in cleaned:
            cleaned.append(v)
    bad = [v for v in cleaned if v not in ALLOWED_EXTS]
    if bad:
        raise ValueError(f"Unsupported file type(s): {', '.join(bad)}. Allowed: {', '.join(sorted(ALLOWED_EXTS))}.")
    return cleaned


class RoundBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    instructions: Optional[str] = Field(default=None, max_length=5000)
    opens_at: Optional[datetime] = None
    closes_at: datetime
    allow_idea: bool = True
    allow_repo: bool = True
    allow_video: bool = True
    allow_files: bool = True
    file_types: list[str] = Field(default_factory=lambda: DEFAULT_FILE_TYPES.split(","))
    max_file_mb: int = Field(default=25, ge=1, le=50)
    open_to_all: bool = True

    @field_validator("file_types", mode="before")
    @classmethod
    def _types(cls, v):
        return _clean_types(v)

    @model_validator(mode="after")
    def _dates(self):
        if self.opens_at and self.closes_at <= self.opens_at:
            raise ValueError("A round must close after it opens.")
        return self


class RoundCreate(RoundBase):
    pass


class RoundUpdate(BaseModel):
    """Everything optional; the deadline is changed via /extend, not here."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    instructions: Optional[str] = Field(default=None, max_length=5000)
    opens_at: Optional[datetime] = None
    allow_idea: Optional[bool] = None
    allow_repo: Optional[bool] = None
    allow_video: Optional[bool] = None
    allow_files: Optional[bool] = None
    file_types: Optional[list[str]] = None
    max_file_mb: Optional[int] = Field(default=None, ge=1, le=50)
    open_to_all: Optional[bool] = None

    @field_validator("file_types", mode="before")
    @classmethod
    def _types(cls, v):
        return None if v is None else _clean_types(v)


class RoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    number: int
    name: str
    instructions: Optional[str] = None
    opens_at: Optional[datetime] = None
    closes_at: datetime
    closed_early_at: Optional[datetime] = None
    allow_idea: bool
    allow_repo: bool
    allow_video: bool
    allow_files: bool
    file_types: list[str]
    max_file_mb: int
    open_to_all: bool

    @field_validator("file_types", mode="before")
    @classmethod
    def _types(cls, v):
        return v.split(",") if isinstance(v, str) else v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def state(self) -> str:
        """Round-level state: not_open | open | closed. (A single team can
        still hold an extension that keeps it open for them.)"""

        class _R:  # round_state only reads these attributes
            pass

        r = _R()
        r.closed_early_at, r.opens_at, r.closes_at = self.closed_early_at, self.opens_at, self.closes_at
        return round_state(r)  # type: ignore[arg-type]


class ExtendRequest(BaseModel):
    closes_at: datetime
    reason: Optional[str] = Field(default=None, max_length=500)


class ExtendTeamRequest(ExtendRequest):
    team_id: str


class AdvanceRequest(BaseModel):
    team_ids: list[str] = Field(min_length=1, max_length=500)


class AdvanceTopRequest(BaseModel):
    top_n: int = Field(ge=1, le=500)
