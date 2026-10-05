# Every model module must be imported here so SQLAlchemy's declarative
# registry knows about all tables before Base.metadata.create_all runs
# on startup, and so string-based relationship() targets can resolve.

from app.models.user import User, UserRole  # noqa: F401
from app.models.event import Event, Track, Prize  # noqa: F401
from app.models.team import Team, TeamMember  # noqa: F401
from app.models.project import Project, SubmissionStatus  # noqa: F401
from app.models.judging import JudgingCriterion, JudgeAssignment, Score, PairwiseComparison  # noqa: F401
from app.models.announcement import Announcement  # noqa: F401
from app.models.round import *  # noqa: F401,F403
from app.models.voting import *  # noqa: F401,F403
from app.models.audit import *  # noqa: F401,F403
from app.models.invite import *  # noqa: F401,F403
from app.models.platform_layer import *  # noqa: F401,F403
from app.models.engage import *  # noqa: F401,F403
