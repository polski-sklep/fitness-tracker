# Fitness Tracker — Claude Code Build Brief

**Owner:** Jacob Kowalewski
**Target:** Working MVP deployed to Hetzner VPS today
**Repo path on VPS:** `/opt/fitness-tracker/`
**Local dev path:** `~/code/fitness-tracker/` (clone of same repo)

---

## 1. Goal in one paragraph

Build a single-user fitness tracking system. Inputs arrive via a Telegram bot (text or screenshot) describing a strength or cycling session. The bot calls Claude API to parse the input into structured workout data, asks for confirmation in chat with an inline keyboard, persists to Postgres, computes a Power Score per exercise and per session using the formula in `services/power_score.py`, detects PRs, and exposes a Tailscale-only webapp at `https://fitness.tailnet/` with line charts of progress and a muscle-group heatmap. A weekly cron generates a Markdown training summary using Claude API.

No public access. No auth layer. Tailscale ACL is the only gate.

---

## 2. Hard constraints

- Single user. Telegram chat ID is hardcoded via env var. All other chat IDs are silently dropped.
- Webapp listens only on the Tailscale interface. No port exposed to the public internet.
- Bodyweight is fixed at **78 kg** for bodyweight movements. Stored as `BODYWEIGHT_KG` env var.
- LLM is Anthropic Claude API only. Model: `claude-sonnet-4-5-20250929` for extraction, same for weekly summary. No local LLM.
- Exercises are created on demand the first time they appear in a parsed session.
- No password auth. No user table. Session ID is implicit (the only user is Jacob).

---

## 3. Tech stack

| Layer | Choice | Pin |
|---|---|---|
| Language | Python | 3.11 |
| Web framework | FastAPI | latest stable |
| Templating | Jinja2 | latest |
| Frontend interactivity | HTMX | 1.9.x via CDN |
| Charts | Chart.js | 4.x via CDN |
| ORM | SQLAlchemy | 2.0 |
| Migrations | Alembic | latest |
| DB | PostgreSQL | 16 |
| Bot | python-telegram-bot | 21.x |
| LLM SDK | anthropic | latest |
| Reverse proxy | Caddy | 2.x |
| Containerization | Docker Compose | v2 |
| Process supervision | systemd (Compose service) | n/a |

No build step on the frontend. No npm. No React. HTMX + server-rendered Jinja templates only.

---

## 4. Repo structure

```
/opt/fitness-tracker/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app
│   ├── config.py                # pydantic-settings, reads .env
│   ├── db.py                    # engine, session
│   ├── models.py                # SQLAlchemy models
│   ├── schemas.py               # pydantic models for API
│   ├── routes/
│   │   ├── pages.py             # HTML routes (dashboard, sessions, exercises)
│   │   └── api.py               # JSON routes (chart data, bot ingest)
│   ├── services/
│   │   ├── power_score.py       # Power Score v1.0 implementation
│   │   ├── claude_extractor.py  # Claude API parsing
│   │   ├── claude_summary.py    # Weekly summary generator
│   │   ├── pr_detector.py       # PR detection
│   │   └── session_classifier.py # Lower/UpperPull/UpperPush inference
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       ├── session_detail.html
│       └── exercise_detail.html
├── bot/
│   ├── __init__.py
│   ├── main.py                  # python-telegram-bot entry
│   ├── handlers.py              # message + callback handlers
│   └── confirm_flow.py          # extract → confirm → persist
├── alembic/
│   ├── env.py
│   └── versions/
├── alembic.ini
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.bot
├── Caddyfile
├── pyproject.toml
├── .env.example
├── README.md
└── scripts/
    ├── seed_dev.py              # optional dev seed
    ├── recompute_all.py         # recompute Power Scores after formula tweaks
    └── weekly_summary.sh        # called by cron
```

---

## 5. Environment variables (`.env.example`)

```
# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=        # numeric user ID, integer

# Anthropic
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-5-20250929

# Database
DATABASE_URL=postgresql+psycopg://fitness:fitness@db:5432/fitness

# App config
BODYWEIGHT_KG=78
SESSION_MEDIAN_POWER=3161        # used for Index_vs_median
TZ=Europe/Lisbon

# Webapp binding
WEB_BIND_HOST=100.x.x.x          # Tailscale IP of VPS
WEB_BIND_PORT=8000
```

Caddy listens on the Tailscale interface only and proxies to `127.0.0.1:8000`.

---

## 6. Database schema

All tables in one Alembic baseline migration. Use `BigInteger` for IDs. `created_at` and `updated_at` on every row.

### `exercises`
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| name | text unique not null | normalized lowercase + canonical display name in `display_name` |
| display_name | text not null | |
| modality | enum('strength','cycling','mobility') not null | |
| muscle_groups | text[] not null | e.g. `{quads,glutes,core}` |
| exercise_class | enum('heavy_compound','bw_compound','db_compound','machine_compound','isolation','corrective') | nullable for cycling |
| ec_coefficient | numeric(4,2) not null | filled from class lookup |
| created_at | timestamptz default now() | |

### `sessions`
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| started_at | timestamptz not null | |
| session_type | enum('lower_core','upper_pull','upper_push','cycling','other') | |
| readiness | smallint check 1..10 | nullable for cycling |
| fatigue | smallint check 1..10 | nullable |
| sensitivity | smallint check 1..10 | nullable |
| quality | smallint check 1..10 | nullable |
| time_minutes | integer | |
| time_benchmark_minutes | integer | snapshot of benchmark used |
| notes | text | |
| total_power | numeric | nullable, computed |
| index_vs_median | numeric | nullable, computed |
| created_at | timestamptz default now() | |

### `strength_sets`
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| session_id | bigint FK → sessions.id, on delete cascade | |
| exercise_id | bigint FK → exercises.id | |
| set_index | smallint not null | 1-based |
| reps | smallint not null | |
| weight_kg | numeric(6,2) not null | use 78 for bodyweight movements |
| rir | smallint check 0..5 | nullable while logging cadence is established |
| local_sensitivity | enum('none','mild','moderate','severe') default 'none' | |
| local_sensitivity_note | text | |
| is_pr | boolean default false | |
| est_1rm | numeric | Epley: w * (1 + reps/30) |
| exercise_power | numeric | computed via formula |
| created_at | timestamptz default now() | |

### `cycling_efforts`
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| session_id | bigint FK → sessions.id, on delete cascade | |
| distance_km | numeric(6,2) | |
| kcal | integer | |
| duration_min | integer | |
| avg_hr | smallint | nullable |
| notes | text | |
| created_at | timestamptz default now() | |

### `raw_inputs`
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| session_id | bigint FK → sessions.id nullable | null if parsing failed |
| telegram_msg_id | bigint | |
| kind | enum('text','image') | |
| raw_text | text | nullable |
| image_path | text | nullable, stored under `data/uploads/` |
| parsed_payload | jsonb | nullable |
| claude_model | text | |
| created_at | timestamptz default now() | |

### `summaries`
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| period_start | date | |
| period_end | date | |
| body_md | text | |
| generated_at | timestamptz default now() | |

Indexes: `strength_sets(exercise_id, created_at)`, `sessions(started_at)`, `exercises(name)`.

---

## 7. Power Score implementation (`app/services/power_score.py`)

Implements **Power Formula v1.0** verbatim. Pure functions, no DB calls inside the math. Pass dependencies in.

### Constants

```python
EC_LOOKUP = {
    "heavy_compound": 1.00,
    "bw_compound": 0.95,
    "db_compound": 0.92,
    "machine_compound": 0.85,
    "isolation": 0.70,
    "corrective": 0.55,
}

RIR_EFFORT = {0: 0.95, 1: 1.00, 2: 0.93, 3: 0.82, 4: 0.70, 5: 0.70}

LS_PENALTY = {"none": 1.00, "mild": 0.85, "moderate": 0.65, "severe": 0.40}

TIME_BENCHMARKS_MIN = {
    "lower_core": 94.5,
    "upper_pull": 77.0,
    "upper_push": 81.0,
    "cycling": None,         # not scored
    "other": 85.0,           # fallback
}

SESSION_MEDIAN_POWER = 3161  # from env, configurable
```

### Per-set / per-exercise calculation

```python
def epley_e1rm(weight_kg: float, reps: int) -> float:
    return weight_kg * (1 + reps / 30)

def exercise_power(
    sets: list[dict],            # [{reps, weight_kg, rir, local_sensitivity}]
    ec: float,
    peak_e1rm: float,            # max e1RM ever logged for this exercise
    readiness: int,              # 1..10
) -> float:
    if not sets:
        return 0.0
    n = len(sets)
    avg_weight = sum(s["weight_kg"] for s in sets) / n
    avg_reps = sum(s["reps"] for s in sets) / n
    V = n * avg_reps * avg_weight

    RI = (avg_weight * (1 + avg_reps / 30)) / peak_e1rm if peak_e1rm > 0 else 1.0

    rir_values = [s.get("rir") for s in sets if s.get("rir") is not None]
    if rir_values:
        E = sum(RIR_EFFORT.get(min(r, 4), 0.70) for r in rir_values) / len(rir_values)
    else:
        E = 1.00  # no RIR logged → neutral

    LS = min(LS_PENALTY[s.get("local_sensitivity", "none")] for s in sets)

    R_term = (readiness / 10) ** 0.4 if readiness else 1.0

    return (V * ec * RI * E * LS) / R_term
```

### Per-session calculation

```python
def session_power(
    exercise_powers: list[float],
    quality: int,
    fatigue: int,
    sensitivity: int,
    time_minutes: int,
    benchmark_minutes: float,
) -> float:
    base = sum(exercise_powers)

    Q_t = (quality / 10) ** 1.2 if quality else 1.0
    F_t = max(0.10, 1 - 0.04 * (fatigue - 7.75) ** 2) if fatigue else 1.0

    if sensitivity is None:
        S_t = 1.0
    elif sensitivity >= 9:
        S_t = 1.00
    elif sensitivity >= 7:
        S_t = 1 - 0.04 * (9 - sensitivity)
    elif sensitivity >= 5:
        S_t = 0.92 - 0.08 * (7 - sensitivity)
    else:
        S_t = max(0.10, 0.76 - 0.15 * (5 - sensitivity))

    T_t = (benchmark_minutes / time_minutes) ** 0.4 if time_minutes else 1.0

    return base * Q_t * F_t * S_t * T_t

def index_vs_median(total: float, median: float = SESSION_MEDIAN_POWER) -> float:
    return (total / median) * 100
```

### Persistence rule

When a session is committed:
1. For each strength_set, compute `est_1rm`.
2. Look up `peak_e1rm` for that exercise across all prior sets.
3. Compute `exercise_power` per exercise (group sets by exercise_id).
4. Write `exercise_power` back to one set per exercise (the first one) or to a derived view — easier path is a separate `exercise_session_scores` table; **for MVP just store on `strength_sets.exercise_power` for the first set of that exercise in the session, leave others null**.
5. Compute `session.total_power` and `session.index_vs_median`. Write to row.
6. Run PR detection (see §9).

A `scripts/recompute_all.py` script must exist that re-runs steps 1-6 across the entire DB. Do not skip this. The formula will change.

---

## 8. Claude extraction prompt (`app/services/claude_extractor.py`)

System prompt (verbatim):

```
You are a structured data extractor for a personal fitness tracker.
The user logs strength sessions and cycling rides.
Input is free-text or a screenshot of a workout note. Output is strict JSON.

Schema:
{
  "modality": "strength" | "cycling",
  "started_at": ISO8601 string or null,
  "session_type": "lower_core" | "upper_pull" | "upper_push" | "cycling" | "other",
  "readiness": 1-10 or null,
  "fatigue": 1-10 or null,
  "sensitivity": 1-10 or null,
  "quality": 1-10 or null,
  "time_minutes": integer or null,
  "notes": string or null,
  "exercises": [           # only if modality=strength
    {
      "name": string,
      "exercise_class": "heavy_compound" | "bw_compound" | "db_compound" |
                        "machine_compound" | "isolation" | "corrective",
      "muscle_groups": [string, ...],
      "sets": [
        { "reps": int, "weight_kg": float, "rir": int|null,
          "local_sensitivity": "none"|"mild"|"moderate"|"severe",
          "local_sensitivity_note": string|null }
      ]
    }
  ],
  "cycling": {              # only if modality=cycling
    "distance_km": float|null,
    "kcal": int|null,
    "duration_min": int|null,
    "avg_hr": int|null
  } | null
}

Rules:
- For bodyweight movements (pull-ups, dips, push-ups), set weight_kg to the
  user's bodyweight, which is provided as a constant in the user message.
- Classify exercise_class accurately. Cable rows = machine_compound.
  Barbell back squat = heavy_compound. DB curl = isolation. Face pulls = corrective.
- session_type: infer from exercise mix. Squat/deadlift/lunges = lower_core.
  Pull-ups/rows/face pulls = upper_pull. Bench/OHP/dips = upper_push. Cycling rides = cycling.
- If a value is not present in the input, return null. Do not guess.
- Output strict JSON only. No commentary. No markdown fences.
```

User message includes the bodyweight (`f"BODYWEIGHT_KG={settings.BODYWEIGHT_KG}"`) followed by the raw text or the image as a base64 content block.

Use Anthropic SDK's vision support for screenshots. Pass `media_type` correctly. Set `max_tokens=2048`. Temperature 0.

Validate the response with a pydantic model. On validation failure, send the user the error and the raw model output for manual fix.

---

## 9. PR detection (`app/services/pr_detector.py`)

After session commit, for each strength set in the session:

- Compute current `est_1rm`.
- Query max `est_1rm` for that exercise across all prior sets (excluding the current session).
- If current > prior max, mark `is_pr = true` on that set.

Also flag rep PRs (heaviest weight ever for the same rep count on that exercise) as `is_pr = true`. One boolean column is fine for MVP — both PR types share it.

Show PR markers on charts as gold dots.

---

## 10. Bot flow (`bot/`)

### Auth
First line of every handler:
```python
if update.effective_user.id != settings.TELEGRAM_ALLOWED_USER_ID:
    return
```
Silent drop. No reply.

### Commands
- `/start` — replies with usage instructions
- `/undo` — soft-deletes the last session and triggers recompute
- `/summary` — generates a weekly summary on demand
- `/help` — shows usage

### Free-text or photo flow
1. Receive message. Persist to `raw_inputs` immediately.
2. Send "parsing..." reply.
3. Call `claude_extractor.extract(text_or_image, bodyweight)`.
4. Render the parsed JSON as a human-readable summary:
   ```
   Lower body + core, 95 min, R8/F8/S9/Q7
   • Back squat: 3×5 @ 140 (RIR 1)
   • RDL: 3×8 @ 110
   • Leg press: 3×10 @ 200 [mild left knee]
   ```
5. Inline keyboard: `✅ Save` / `✏️ Edit (resend corrected)` / `❌ Discard`.
6. On Save: persist via the same code path the API uses, run Power Score + PR detection, reply with computed scores:
   ```
   Saved.
   Total Power: 3,420 (Index 108)
   Top exercise: Back squat — 1,210
   PR: Back squat 1RM 162.4 kg (e1RM)
   ```

### Edit
For MVP, "edit" simply prompts the user to resend a corrected message. No in-bot field-by-field editing. That's v1.1.

---

## 11. Webapp pages

Use Tailwind via CDN play script, or just write small CSS. No build step.

### `GET /` Dashboard
- Header: this week's totals (sessions, total power index avg, total cycling km)
- Chart 1: line chart, X = session date, Y = `index_vs_median`. Hover shows session_type and total_power. Last 90 days.
- Chart 2: line chart, X = session date, Y = sum of cycling km that week (bar) overlaid with kcal (line). Last 90 days.
- Chart 3: muscle-group heatmap. Rows = muscle groups (chest, back, quads, hamstrings, glutes, shoulders, biceps, triceps, core, calves). Columns = last 12 ISO weeks. Cell intensity = sum of `exercise_power` for sets where the exercise's `muscle_groups` array contains that group, in that week. Use a simple HTML table with background-color = `rgba(0, 200, 100, intensity)` where intensity is normalized per row. No body-diagram visualization in MVP.
- Section: latest summary excerpt (if exists).
- Section: link list of last 10 sessions.

### `GET /sessions/{id}`
- Header: date, session_type, R/F/S/Q, time, total_power, index_vs_median.
- Table of strength sets grouped by exercise, with PR badges.
- Cycling block if applicable.
- Notes.

### `GET /exercises/{id}`
- Header: name, class, muscle groups, EC coefficient.
- Chart: line chart of `exercise_power` per session over time.
- Chart: line chart of `est_1rm` peak per session over time.
- Table: last 20 sets logged.

### `GET /api/chart/sessions` and friends
JSON endpoints used by Chart.js. Return `{labels: [...], datasets: [...]}` directly to keep the frontend dumb.

---

## 12. Weekly summary (`app/services/claude_summary.py`)

Cron entry on the VPS:
```
0 9 * * 1   /opt/fitness-tracker/scripts/weekly_summary.sh
```

The script calls a CLI entry that:
1. Pulls last 7 days of sessions, exercises, sets, cycling efforts.
2. Renders them as a compact text block.
3. Sends to Claude with this prompt:

```
You are reviewing one week of training data for a single user.
Be blunt and specific. No filler. No "great work" framing.

Identify:
1. Volume and intensity trends per muscle group.
2. Specific exercises that progressed or regressed (compare to prior 4-week average if visible).
3. Readiness/Fatigue/Sensitivity signals worth flagging.
4. One actionable recommendation for next week. Just one.

Output: Markdown, ~250 words. No headers above H3.
```

4. Saves output to `summaries` table.
5. Sends the Markdown to Jacob's Telegram chat as a message.

---

## 13. Docker Compose

Three services: `db`, `api`, `bot`. Plus host-level Caddy outside Compose (simpler for Tailscale binding).

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: fitness
      POSTGRES_PASSWORD: fitness
      POSTGRES_DB: fitness
    volumes:
      - ./data/pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    env_file: .env
    depends_on: [db]
    ports:
      - "127.0.0.1:8000:8000"   # only loopback; Caddy proxies from Tailscale interface
    volumes:
      - ./data/uploads:/app/data/uploads
    restart: unless-stopped

  bot:
    build:
      context: .
      dockerfile: Dockerfile.bot
    env_file: .env
    depends_on: [api, db]
    volumes:
      - ./data/uploads:/app/data/uploads
    restart: unless-stopped
```

`Caddyfile`:
```
fitness.YOUR-TAILNET.ts.net {
    bind 100.x.x.x
    reverse_proxy 127.0.0.1:8000
}
```

---

## 13a. Historical data ingestion (xlsx format)

Jacob has 29 prior sessions logged in `TrainerGPT_26_.xlsx` — a single sheet named `2026` with this exact column layout:

| Column | Notes |
|---|---|
| Day | Date. **Appears once per session** on the first row only. Forward-fill required. |
| Session | e.g. "Lower Body + Core", "Upper Push Chest Focus", "Upper Pull Back Focus". Forward-fill. |
| Block | One of: Warm-up, Activation, Core, Strength, Accessory, Cool-down, Cardio. |
| Order | Numeric sequence within the session. |
| Item | Exercise name (free text — see canonicalization below). |
| Sets | Integer or NaN. |
| Reps | Integer or NaN. |
| Weight | String: "40kg", "32.5kg", "Kinesis Station Level 3", or NaN. Parse `^(\d+\.?\d*)\s*kg`. |
| Notes | "Failure", "Until Failure", or duration strings like "14 minutes". No RIR data historically. |
| Readiness, Fatigue, Sensitivity, Quality | 1–10, decimal allowed. **Appear once per session**, forward/back-fill within Day group. |
| Time | "93 minutes" — parse integer. Once per session. |

A single row represents one exercise prescription (`3 sets × 10 reps @ 40kg`) — not a single set. The backfill script must expand this into N `strength_sets` rows of identical reps/weight, indexed `1..N`. Set-level granularity is lost for history; new logging via the bot will capture it properly.

**Bodyweight movements** (any Item containing pull up / pullup / dip / push up / chinup) have NaN weight in the spreadsheet. Substitute `BODYWEIGHT_KG = 78` before computing e1RM.

**Notes on RIR.** Historical data has no RIR. Backfill writes `rir = NULL`. The Power Score formula falls back to `E = 1.00` (neutral) when RIR is missing. Do not invent RIR values to fill the gap.

**Notes on local sensitivity.** Historical data has no LS tags. Backfill writes `local_sensitivity = 'none'` for all historical sets.

Same hierarchical layout will continue to be how Jacob mentally organizes sessions, so the Telegram bot extractor must understand a screenshot of this sheet. Add an example of this exact format to the few-shot block in the Claude extraction prompt.

## 13b. Seed exercise table and peak e1RM bootstrap

Ship `seed_exercises.json` at the repo root containing 22 pre-classified exercises with peak e1RMs computed from the historical data. Loaded by `scripts/seed.py` at first migration. This solves the cold-start problem in the Power Score formula — `peak_e1rm` is non-zero from the first session, so `RI` is meaningful immediately.

Seed values (computed via Epley `w × (1 + reps/30)` from Jacob's 29-session history):

| Exercise | Class | EC | Peak e1RM (kg) |
|---|---|---|---|
| Leg press | machine_compound | 0.85 | 133.33 |
| Neutral grip lat pulldown | machine_compound | 0.85 | 120.00 |
| Dips | bw_compound | 0.95 | 117.00 |
| Seated cable row | machine_compound | 0.85 | 112.00 |
| Machine chest press | machine_compound | 0.85 | 112.00 |
| Neutral grip pull-up | bw_compound | 0.95 | 98.80 |
| Romanian deadlift | heavy_compound | 1.00 | 97.50 |
| Back squat | heavy_compound | 1.00 | 84.00 |
| Machine overhead press | machine_compound | 0.85 | 84.00 |
| Flat barbell bench press | heavy_compound | 1.00 | 72.00 |
| Abductor machine | corrective | 0.55 | 67.50 |
| Squat machine | machine_compound | 0.85 | 60.00 |
| Leg extension | isolation | 0.70 | 56.00 |
| Seated hamstring curl | isolation | 0.70 | 51.10 |
| Incline dumbbell press | db_compound | 0.92 | 50.67 |
| Dumbbell row | db_compound | 0.92 | 39.00 |
| Cable tricep pushdown | isolation | 0.70 | 37.50 |
| Cable chest fly | isolation | 0.70 | 30.00 |
| Bicep curl | isolation | 0.70 | 26.25 |
| Face pulls | corrective | 0.55 | 25.00 |
| Reverse pec deck | corrective | 0.55 | 21.00 |
| Pec deck fly | isolation | 0.70 | 14.00 |

The full JSON is included as a separate artifact alongside this brief.

**Important caveat on seed peak e1RMs.** These are derived from `sets × reps × weight` rows assuming the prescribed reps were achieved cleanly. The "Failure" / "Until Failure" notes in the historical data suggest several of these reps were absolute-failure attempts, which inflates Epley estimates. Treat the seed values as **soft anchors**: `peak_e1rm_seed` should be stored as a separate field from the live `peak_e1rm` which gets computed from real logged sets going forward. After ~6 weeks of new data, deprecate the seed anchor in `recompute_all.py` and use only live data.

## 13c. Exercise alias map

A canonicalization step is required before any exercise lookup. The historical data already contains 11 collisions across 22 canonical exercises (e.g., "Bicep curl" / "Bicep Curls" / "Bicep curls" / "Bicep curl"; "Leg press" / "Leg press machine"; "Neutral grip lat pulldown" / "Machine pulldown" / "Lateral pulldown" / "Neautral grip pulldown" — yes, the typo is in the source). Without canonicalization, the DB will fragment progress charts across multiple rows for the same movement.

Implementation: load `aliases` dict from `seed_exercises.json` at startup. Before persisting any extracted exercise from the bot, run:

```python
def canonicalize(raw_name: str) -> str:
    key = raw_name.strip().lower()
    return aliases.get(key, key)
```

Maintain `aliases` as a plain JSON dict that you can hand-edit when new variants appear. Any exercise that doesn't match the seed and isn't in aliases creates a new row — that's expected. You'll periodically inspect the `exercises` table and add aliases for misclassifications.

This is the v1.1 admin-reclassify endpoint replaced with a 30-second JSON edit. Acceptable for MVP.

## 14. Build order (recommended for shipping today)

1. **Hour 0-1.** Repo scaffold, pyproject.toml, Dockerfiles, docker-compose, alembic baseline migration, `.env.example`, `BODYWEIGHT_KG` constant, copy `seed_exercises.json` to repo root.
2. **Hour 1-2.** SQLAlchemy models. Run migration locally. Run `scripts/seed.py` to load 22 exercises with peak e1RM seeds.
3. **Hour 2-3.** `power_score.py` with unit tests against the v1.0 spec values. Test cases: a known session that should produce ~3,161, an outlier with low readiness, an exercise with mild local sensitivity. Verify Index_vs_median ≈ 100 for the median case.
4. **Hour 3-4.** `scripts/backfill_xlsx.py` — ingest the 29 historical sessions. Verify dashboard shows them after seed + backfill. This validates the schema and Power Score against real data before any bot work.
5. **Hour 4-6.** Claude extractor with one happy-path text input and one screenshot of the xlsx layout. Validate JSON parsing. Wire to a `POST /api/sessions/from_raw` endpoint.
6. **Hour 6-8.** Telegram bot with auth check, free-text + photo handlers, confirm flow, persistence path. PR detector wired in.
7. **Hour 8-10.** Dashboard page with three charts wired to JSON endpoints. Session detail and exercise detail pages.
8. **Hour 10-11.** Deploy to VPS. Caddy config. Tailscale bind verification. Telegram long-poll started.
9. **Hour 11-12.** Smoke test end-to-end: log a real session via Telegram, verify it lands on the dashboard with correct Power Score next to the 29 backfilled ones.

Weekly summary cron is **deferred to tomorrow**. PR notifications via Telegram message are in scope but the dashboard is the primary surface.

---

## 15. Acceptance criteria

A build is "done" when all of these pass:

- [ ] `python scripts/seed.py` populates 22 exercises with peak e1RM seeds.
- [ ] `python scripts/backfill_xlsx.py /path/to/TrainerGPT_26_.xlsx` ingests 29 sessions and ~340 set rows (113 prescription rows × ~3 sets each) without error. Dashboard shows 29 historical points before any bot interaction.
- [ ] `docker compose up -d` brings up db, api, bot. No errors in logs after 30 seconds.
- [ ] Sending a text message describing a strength session to the Telegram bot from Jacob's account produces a confirmation message with the parsed structure.
- [ ] Tapping ✅ Save persists the session and replies with computed Total Power.
- [ ] A session of "back squat 3x5 @ 140, RDL 3x8 @ 110, leg press 3x10 @ 200, R8 F8 S9 Q7, 95 min" produces an Index_vs_median between 95 and 115. (Sanity range, not exact match — exact match requires peak_e1rm history.)
- [ ] Sending a screenshot of a workout note produces the same flow.
- [ ] Visiting `https://fitness.<tailnet>.ts.net/` from a Tailscale-connected device shows the dashboard with at least one session.
- [ ] The same URL from a non-Tailscale device fails to connect (not 401, but a connection refusal/timeout).
- [ ] A second exercise with the same name as an existing one does not create a duplicate `exercises` row.
- [ ] Sending a message from any Telegram user ID other than `TELEGRAM_ALLOWED_USER_ID` produces no reply and no DB write.
- [ ] `python scripts/recompute_all.py` runs without error and updates `total_power` on every session.

---

## 16. Non-goals for v1.0 (do not build)

- Web-based session editing UI (use `/undo` + resend in Telegram).
- Manual exercise CRUD UI (let on-demand creation handle it; edit in psql if needed).
- Multi-user, sharing, OAuth.
- Mobile app.
- Strava/Garmin/Apple Health integration.
- Body-diagram heatmap.
- Form-check from video.
- Goal targets and deadlines.
- Push notifications outside Telegram.
- Backups (set up tomorrow with `pg_dump` cron to a separate volume).

---

## 17. Open questions Claude Code may flag

These are not blockers. Make a default decision and note it in the PR description.

1. Telegram bot mode: long-polling vs webhook. **Default: long-polling** — simpler, no public URL needed, fits the Tailscale-only posture.
2. Image storage: filesystem vs Postgres bytea. **Default: filesystem** under `data/uploads/`, path stored in `raw_inputs.image_path`.
3. Migration strategy for the inevitable formula change: write all derived columns, never read them in charts without an option to recompute. Charts should query the raw fields and compute on the fly OR read derived fields with a clear "as of last recompute" indication.

---

## 18. What this brief deliberately does not specify

- Exact CSS. Ship something that renders cleanly on mobile Safari. No design system.
- Test coverage targets. Cover `power_score.py` thoroughly. Cover one happy-path bot flow. Skip the rest for MVP.
- Logging stack. Use Python `logging` with `INFO` level to stdout. Docker captures it. No Loki/Grafana yet.
- Error tracking. Sentry deferred.

End of brief.
