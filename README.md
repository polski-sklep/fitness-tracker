# Fitness Tracker

Personal training log for Jacob Kowalewski. Send a strength session or a cycling ride to the Telegram bot as text or a screenshot. Claude parses it, the bot asks you to confirm, and Postgres stores the session. A small FastAPI site shows recent training, a Power Index, cycling calories, and a muscle-group heatmap.

The bot replies only when the Telegram user id matches `TELEGRAM_ALLOWED_USER_ID`. Compose publishes the site on `127.0.0.1`. The pages themselves have no login.

## Stack

- Python 3.11+ (`requires-python` in `pyproject.toml`; the Dockerfiles use `python:3.11-slim`)
- FastAPI, Jinja2, Uvicorn
- SQLAlchemy 2 and Alembic, against PostgreSQL 16
- python-telegram-bot, long polling
- Anthropic Python SDK (`claude_extractor` and `claude_summary`)
- Pydantic and pydantic-settings
- pandas and openpyxl, used by the spreadsheet backfill
- pytest (declared as the `dev` extra; see Tests for how to install it)
- Pages are server-rendered Jinja templates. `app/templates/base.html` loads Tailwind, Chart.js 4.4.7, and HTMX 1.9.12 from CDNs. The charts call the JSON routes with `fetch`.

## Layout

```
app/                 FastAPI app
  main.py            app entry, mounts page and API routers
  config.py          settings from the environment and .env
  db.py              engine and session
  models.py          exercises, sessions, strength sets, cycling efforts, raw inputs, summaries
  schemas.py         parsed-session and API models
  routes/pages.py    HTML: dashboard, session, exercise, profile, reference texts
  routes/api.py      JSON: health, ingest, chart data
  services/          Power Score, Claude extract/summary, PRs, persistence, exercise aliases
  templates/         Jinja pages
bot/                 Telegram polling bot, handlers, confirm keyboard
alembic/versions/    migrations 0001_baseline through 0005_add_cycling_max_rpm
scripts/             seed, xlsx backfill, cycling backfill, recompute, weekly summary
tests/               power-score and extractor JSON tests
data/historical/     TrainerGPT_26_.xlsx
profile/             Jacob's profile (txt/rtf) and profile.md
text/                about, glossary, workout template
seed_exercises.json  22 exercises, aliases, seed peaks
docker-compose.yml   db, api, bot
Dockerfile.api       migrations, then uvicorn
Dockerfile.bot       python -m bot.main
Caddyfile            host reverse-proxy template
.env.example         variable names
```

`CLAUDE_CODE_BRIEF.md` is the original build spec. `STARTER_PROMPT.md` is the kickoff prompt from that spec. The running Power Score is v1.1 in `app/services/power_score.py`.

## What gets stored

Strength sessions keep readiness, fatigue, sensitivity, quality, duration, sets (reps, weight, RIR, local sensitivity), an Epley estimated 1RM, and a per-exercise Power Score. A set is marked a PR when its estimated 1RM beats both the prior logged peak and the seed peak for that exercise.

Cycling sessions keep distance, kcal, duration, average heart rate, average and max watts, and average and max rpm. They are not given a Power Index. The dashboard cycling chart plots kcal.

Power Index is session power divided by `SESSION_MEDIAN_POWER`, times 100. Session power sums the exercise scores and applies quality, fatigue, sensitivity, and time against a benchmark (`lower_core` 94.5 min, `upper_pull` 77, `upper_push` 81, `other` 85). Exercise power (v1.1) uses volume, an exercise-class coefficient, average working weight relative to the lifetime peak working weight, RIR, local sensitivity, and readiness. The class coefficients live in `EC_LOOKUP` in `app/services/power_score.py`.

`seed_exercises.json` records 22 canonical exercises and says the seed came from 29 sessions and 113 strength entries in the spreadsheet. Unknown exercise names are inserted on first use. Aliases in that file are applied before lookup.

## Setup

You need Docker Compose, a Telegram bot token, your numeric Telegram user id, and an Anthropic API key. Python 3.11 or newer is enough for the tests.

```sh
cp .env.example .env
```

Fill `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, and `ANTHROPIC_API_KEY` in `.env`. Leave the other defaults unless you have a reason to change them. `.env` is gitignored.

```sh
docker compose up --build
```

The API container runs `alembic upgrade head` and then Uvicorn. The site is at http://127.0.0.1:8000 and http://127.0.0.1:8000/api/health returns `{"status":"ok"}`.

Postgres stays on the Compose network (host name `db`). The compose file does not publish port 5432. The default `DATABASE_URL` in `.env.example` uses that host. `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` are set on the `db` service in `docker-compose.yml`.

Load the seed and the spreadsheet from the API container. The historical file is mounted at `data/historical/` inside that container.

```sh
docker compose run --rm api python scripts/seed.py
docker compose run --rm api python scripts/backfill_xlsx.py data/historical/TrainerGPT_26_.xlsx
```

`scripts/backfill_cycling.py` inserts six rides that are hardcoded in that file, skipping a date that already has a cycling effort. `scripts/recompute_all.py` rebuilds estimated 1RMs, Power Scores, indexes, and PR flags.

A process started on the host (outside Compose) needs its own reachable `DATABASE_URL`.

## Configuration

Copy `.env.example` to `.env`. Names only:

| Variable | Where it is read | What it is for |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `app/config.py`, required by `bot/main.py` | Bot token from BotFather. The bot process exits if it is empty. |
| `TELEGRAM_ALLOWED_USER_ID` | `app/config.py`, checked in `bot/handlers.py` | Numeric Telegram user id. Every other sender is ignored. |
| `ANTHROPIC_API_KEY` | `app/config.py`; `app/services/claude_extractor.py`, `app/services/claude_summary.py` | Anthropic API key. |
| `CLAUDE_MODEL` | `app/config.py`; the extractor, the summary, and the `raw_inputs.claude_model` column | Model id. Default `claude-sonnet-4-5-20250929`. |
| `DATABASE_URL` | `app/config.py`; `app/db.py`, `alembic/env.py` | SQLAlchemy URL. Default host is the Compose service `db`. |
| `BODYWEIGHT_KG` | `app/config.py` (`Settings.bodyweight_kg`); passed into the Claude prompt in `claude_extractor.py` | Bodyweight in kg for bodyweight movements. Default 78. `scripts/backfill_xlsx.py` uses its own constant `78`. |
| `SESSION_MEDIAN_POWER` | `app/config.py`; `app/services/persistence.py`, `scripts/recompute_all.py` | Baseline for Power Index. Default 3161. |
| `TZ` | `app/config.py` (`Settings.tz`) | Default `Europe/Lisbon`. Loaded into settings; no other module reads it. |
| `WEB_BIND_HOST` | `app/config.py` (`Settings.web_bind_host`) | Default `127.0.0.1`. Loaded into settings. Compose and `Caddyfile` do not read it. |
| `WEB_BIND_PORT` | `app/config.py`; the host port in `docker-compose.yml`; the listen port in `Dockerfile.api` | Default 8000. Compose maps `127.0.0.1:${WEB_BIND_PORT:-8000}` to container port 8000, and the API process listens on `WEB_BIND_PORT`. Keep it at 8000. |

## Running locally

`docker compose up --build` starts the database, the site, and the bot.

Bot commands, from `bot/main.py`:

- `/start` and `/help` — short instructions
- a text message — parse one or more workouts, then Save / Edit / Discard
- a photo — same flow for a screenshot, saved under `data/uploads/`
- `/undo` — soft-delete the latest session (`deleted_at`)
- `/summary` — write a weekly review for the last seven days and send it back

Web routes:

- `/` — last 7 days, Power Index chart, cycling kcal chart, 12-week muscle heatmap, latest sessions, latest summary, profile and reference-text links
- `/sessions/{id}` — sets or the cycling effort
- `/exercises/{id}` — exercise power and estimated 1RM chart, last 20 sets
- `/profile`, `/profile/edit` — reads and writes `profile/jacobkowalewski.txt`
- `/text/{slug}` — files in `text/` (markdown, text, or RTF)

JSON routes, all under `/api`: `GET /health`, `POST /sessions`, `POST /sessions/from_raw`, `GET /chart/sessions`, `GET /chart/cycling`, `GET /chart/exercises/{id}`.

Weekly summary from the shell, with the app environment and database available:

```sh
python -m scripts.weekly_summary
```

`scripts/weekly_summary.sh` does the same from the repo root. The bot command `/summary` calls the same generator. Both save a row in `summaries`.

## Tests

`pip install .` and `pip install -e ".[dev]"` fail in a full checkout. Setuptools sees several top-level directories (`app`, `bot`, `alembic`, `data`, `profile`, `text`) and refuses the flat layout. The Dockerfiles avoid that by running `pip install .` before those directories are copied in. Tests import the tree via `pythonpath = ["."]` in `pyproject.toml`, so they do not need the project install.

From a virtualenv, no database and no API key:

```sh
python -m venv .venv
source .venv/bin/activate
pip install 'pytest>=8.3' 'pydantic>=2.10' 'pydantic-settings>=2.7'
pytest
```

`tests/test_claude_extractor.py` covers JSON fence stripping and parsing a session array. `test_epley_e1rm` passes. The other three tests in `tests/test_power_score.py` still call `exercise_power(..., peak_e1rm=...)`. The v1.1 function requires `peak_weight_kg`, so those three fail.

## Deployment

`docker-compose.yml` is the run file: Postgres 16, the API image, and the bot image. Uploads, the historical spreadsheet, `profile/`, and `text/` are mounted into the API container. Uploads are shared with the bot. Postgres data is stored in `data/pgdata/` (gitignored).

`Caddyfile` is a host-level reverse proxy, separate from Compose. The checked-in file uses the placeholders `fitness.YOUR-TAILNET.ts.net` and `bind 100.x.x.x`, and it proxies to `127.0.0.1:8000`.

There is no systemd unit, backup script, or GitHub Actions workflow in the repo. `CLAUDE_CODE_BRIEF.md` still marks a weekly cron and database backups as deferred. Summaries run when you ask for them (`/summary` or `scripts/weekly_summary.py`).
