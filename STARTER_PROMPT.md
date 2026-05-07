# Claude Code starter prompt

Paste the block below into a fresh Claude Code session in this repo. It is the only prompt you should need to begin.

---

```
Read CLAUDE_CODE_BRIEF.md in the repo root. That is the complete build specification.

Begin work at Section 14 build order, hour 0-1. Scaffold the repo structure exactly as specified in Section 4. Create:

- pyproject.toml with the pinned dependencies from Section 3
- Dockerfile.api and Dockerfile.bot
- docker-compose.yml per Section 13
- alembic.ini and alembic/ scaffold
- app/ module with __init__.py, main.py, config.py, db.py
- bot/ module skeleton
- Caddyfile per Section 13

Do not yet write models, services, routes or templates. Stop after the scaffold is in place and run `docker compose config` to validate the compose file. Report back with the file tree and the compose validation output.

Two important notes that override anything you might infer:

1. The project deliberately has NO authentication layer. Tailscale ACL is the only gate. Do not add HTTP basic auth, JWT, or session middleware.

2. seed_exercises.json and scripts/backfill_xlsx.py already exist. Do not regenerate them. They feed the seed and historical backfill steps in hours 1-3.

After hour 0-1 is complete and validated, await my confirmation before proceeding to hour 1-2 (SQLAlchemy models + initial migration).
```

---

After Claude Code completes hour 0-1, paste this for hour 1-2:

```
Proceed with Section 14 hour 1-2.

Implement app/models.py for all six tables in Section 6 using SQLAlchemy 2.0 declarative style with Mapped[] annotations. Use enum types via SQLAlchemy's Enum with native_enum=True on Postgres.

Generate the alembic baseline migration. Verify it applies cleanly against a fresh Postgres 16 by running `docker compose up db -d`, waiting for healthy, then `docker compose run --rm api alembic upgrade head`.

Then implement scripts/seed.py that reads seed_exercises.json and inserts the 22 exercises with peak_e1rm_seed populated. Run it. Verify with `docker compose run --rm api python -c "from app.db import SessionLocal; from app.models import Exercise; s = SessionLocal(); print(s.query(Exercise).count())"` — should print 22.

Stop and report. Await confirmation before hour 2-3.
```

Continue prompting hour-by-hour. Do not give Claude Code the entire build at once — incremental hand-off catches errors before they compound.
