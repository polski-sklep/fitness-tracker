# Fitness Tracker

Single-user fitness tracking system. Telegram bot ingests text and screenshots, Claude API parses them into structured data, FastAPI + Postgres store and score, HTMX webapp visualizes progress. Tailscale-only access. No public auth.

## Files in this scaffold

| File | Purpose |
|---|---|
| `CLAUDE_CODE_BRIEF.md` | Full build specification. Hand this to Claude Code as project context. |
| `seed_exercises.json` | 22 pre-classified exercises with peak e1RM seeds. |
| `scripts/backfill_xlsx.py` | Ingests historical xlsx into the DB. Run after seed. |
| `data/historical/TrainerGPT_26_.xlsx` | 29 historical sessions to backfill. |
| `.env.example` | Required environment variables. Copy to `.env` and fill in. |

## Build order

See section 14 of `CLAUDE_CODE_BRIEF.md` for the full hour-by-hour plan.

## Deploy targets

- **Local dev:** `~/code/fitness-tracker/` on Mac.
- **Production:** `/opt/fitness-tracker/` on Hetzner VPS, behind Tailscale.

## Status

Scaffold only. Run Claude Code against the brief to generate the application.
