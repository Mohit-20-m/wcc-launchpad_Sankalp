"""
This route is the entire content of Step 1.

Its only job: prove that the backend container is alive AND can
actually reach the database — not just that the process started.
That's the real risk we're de-risking before writing any feature.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter()


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    # A trivial query that only succeeds if the DB connection is real.
    await db.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    }
