Database migrations (Alembic) are not set up yet.

Tables are created from the SQLAlchemy models on startup
(`Base.metadata.create_all`). That creates new tables automatically, but it
never alters an existing one, so a change to an existing table's columns
needs `docker compose down -v` (which wipes local data). All features
added so far use new tables only, precisely so existing databases keep
working.

Adding Alembic is the natural next step before running real events with
data that must survive schema changes:
  1. `alembic init alembic` inside this folder
  2. point `env.py` at `app.core.database` and `app.models`
  3. `alembic revision --autogenerate` for the baseline
