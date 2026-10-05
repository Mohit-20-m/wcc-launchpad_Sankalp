from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    announcements, audit, auth, comments, events, health, invites, judging, live, pairwise,
    projects, publish, reports, rounds, teams, voting,
    api_keys,
    certificates,
    data_io,
    integrity,
    webhooks,
    engage,
)
from app.core.database import AsyncSessionLocal, Base, engine
from app.services.live import hub
from app.services.redis_client import close_redis
from app.services.webhooks import dispatcher
from app.services.seed import run_seed

# Importing app.models registers every table on Base.metadata before
# create_all runs below -- see app/models/__init__.py.
import app.models  # noqa: F401

# IMPORTANT CONVENTION -- read before adding a new router below:
# Nginx's /api/ location strips that prefix before forwarding to this
# backend (see nginx/nginx.conf). A browser calls /api/auth/register,
# but THIS app registers it as /auth/register, not /api/auth/register.
# Getting this wrong is a silent 404 that only shows up once the whole
# stack runs through Nginx -- it happened once already; don't repeat it.


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PRAGMATIC CHOICE for the 72-hour build: create tables directly from
    # the models on startup instead of maintaining hand-authored Alembic
    # migrations under time pressure. Documented in backend/alembic/README.md
    # and ARCHITECTURE.md -- including the schema-drift caveat this
    # tradeoff carries (wipe the Postgres volume after a model change).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await run_seed(session)

    dispatcher.start()  # outbound webhooks + round-deadline sweeper
    hub.start()  # Redis bridge for live updates across workers (no-op without Redis)
    yield
    await dispatcher.stop()
    await hub.stop()
    await close_redis()


app = FastAPI(
    title="WCC Launchpad API",
    version="0.4.0",
    lifespan=lifespan,
    # Nginx serves the API under /api and strips it; telling FastAPI keeps
    # the interactive docs (/api/docs) pointing at /api/openapi.json.
    root_path="/api",
)

# CORS is wide open here only because Nginx is the single entry point
# the browser ever talks to in production; during local dev without
# Nginx you may hit this directly from Vite's dev server on another
# port, so we keep it permissive rather than fighting it at this stage.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(teams.router, prefix="/teams", tags=["teams"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(judging.router, prefix="/judge", tags=["judging"])
app.include_router(pairwise.router, prefix="/judge/pairwise", tags=["pairwise"])
app.include_router(announcements.router, prefix="/announcements", tags=["announcements"])
app.include_router(rounds.router, prefix="/events/{event_id}/rounds", tags=["rounds"])
app.include_router(voting.router, prefix="/voting", tags=["voting"])
app.include_router(invites.router, prefix="/invites", tags=["invites"])
app.include_router(comments.router, tags=["comments"])   # /projects/{id}/comments, /comments/{id}/hide
app.include_router(audit.router, tags=["audit"])         # /events/{id}/audit, /audit.csv, /conflicts
app.include_router(publish.router, tags=["results"])     # /events/{id}/publish-results, /public-results
app.include_router(live.router, tags=["live"])           # WebSocket: /ws/live/{event_id}
app.include_router(api_keys.router, tags=["api-keys"])          # /events/{id}/api-keys
app.include_router(webhooks.router, tags=["webhooks"])          # /events/{id}/webhooks, /webhook-event-types
app.include_router(certificates.router, tags=["certificates"])  # issue / verify / pdf
app.include_router(data_io.router, tags=["import-export"])      # CSV import, exports
app.include_router(integrity.router, tags=["integrity"])        # audit verify/anchor, similarity
app.include_router(reports.router, tags=["reports"])  # no prefix -- exposes /export.csv directly
app.include_router(engage.router, tags=["launchpad"])
