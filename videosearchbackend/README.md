# VideoSearch backend

Production-ready **FastAPI** template, managed with **uv**. Serves the video
search API on **port 3006**.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.12 is pinned via `.python-version`)

## Quick start

```bash
uv sync                 # create .venv + install deps (generates uv.lock)
uv run videosearch-api --reload   # run on HOST/PORT from .env (default :3006)
```

Or run uvicorn directly:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 3006 --reload
```

Open:

- API docs (Swagger UI): http://127.0.0.1:3006/docs
- Health check: http://127.0.0.1:3006/api/v1/health
- Search: http://127.0.0.1:3006/api/v1/search?q=typescript

## Scripts

```bash
uv run pytest                # run the test suite
uv run ruff check .          # lint
uv run ruff format .         # format
uv lock --check              # verify uv.lock is up to date
```

## Configuration

Settings are loaded from `.env` (see `.env.example`) via pydantic-settings in
`app/core/config.py`:

| Variable        | Default                                     | Purpose                       |
| --------------- | ------------------------------------------- | ----------------------------- |
| `APP_NAME`      | `VideoSearch API`                           | Shown in docs / responses     |
| `APP_ENV`       | `development`                               | `development` / `test` / `production` |
| `APP_DEBUG`     | `false`                                     | Debug mode                    |
| `HOST`          | `127.0.0.1`                                 | Bind address (used by `videosearch-api`) |
| `PORT`          | `3006`                                      | Bind port (used by `videosearch-api`)    |
| `CORS_ORIGINS`  | `["http://localhost:5174","http://127.0.0.1:5174"]` | Browser origins allowed to call the API |
| `LOG_LEVEL`     | `INFO`                                      | Root log level                |
| `DATABASE_URL`  | `postgresql://videosearch:videosearch@localhost:5432/videosearch` | Postgres connection string |
| `POSTGRES_HOST` | `localhost`                                 | Postgres host (set to `db` inside docker-compose) |
| `POSTGRES_PORT` | `5432`                                      | Postgres port                |
| `POSTGRES_DB`   | `videosearch`                               | Postgres database name       |
| `POSTGRES_USER` | `videosearch`                               | Postgres user                |
| `POSTGRES_PASSWORD` | `videosearch`                          | Postgres password (override in `.env`!) |

> `CORS_ORIGINS` already allows the Vite frontend (port 5174) — no extra setup
> needed to call this API from the browser.

## Project structure

```
app/
├── main.py              # FastAPI app: lifespan, CORS, routers
├── core/
│   ├── config.py        # pydantic-settings Settings
│   └── logging.py       # structured logging setup
├── api/
│   └── routes/
│       ├── health.py    # GET /api/v1/health
│       └── search.py    # GET /api/v1/search (demo catalog)
└── schemas/
    └── video.py         # VideoItem / SearchResponse models
tests/
└── test_api.py          # pytest + TestClient coverage
```

## Docker

### Full stack (API + Postgres with pgvector) via docker compose

```bash
docker compose up --build    # starts Postgres + the API on :3006
```

The DB uses the official **pgvector** image (`pgvector/pgvector:pg16`) — plain
Postgres 16 plus the `vector` extension for semantic search. The extension is
enabled automatically on first boot by `db/init/01-vector.sql`
(`CREATE EXTENSION IF NOT EXISTS vector;`).

Credentials come from `.env` (`POSTGRES_*` vars); the DB data is persisted in
the `postgres_data` volume. Stop with `docker compose down` (add `-v` to also
wipe the database).

> ℹ️ This project maps the DB to host port **5433** (`POSTGRES_PORT` in `.env`)
> to avoid clashing with another Postgres already running on 5432.

> ⚠️ Init scripts only run when the data volume is empty. If you previously
> started the old plain-Postgres image, run `docker compose down -v` once so the
> pgvector image can initialize a fresh volume with the extension enabled.

> ⚠️ Init scripts only run when the data volume is empty. If you previously
> started the old plain-Postgres image, run `docker compose down -v` once so the
> pgvector image can initialize a fresh volume with the extension enabled.

### API image only

```bash
docker build -t videosearchbackend .
docker run -p 3006:3006 videosearchbackend
```

The image installs with `uv sync --frozen --no-dev` and runs uvicorn on port
3006 with a container health check.

## Next steps to production

- Replace the demo catalog in `app/api/routes/search.py` with a real video
  search integration (e.g. YouTube Data API) using `VITE_YOUTUBE_API_KEY`-style
  secrets via env vars.
- Add a database (e.g. SQLModel/SQLAlchemy + Postgres) for persisted data.
- Add auth (e.g. JWT) if the API needs protected endpoints.
