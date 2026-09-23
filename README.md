# Appointment Backend

A headless REST API for a multi-industry appointment system (restaurants, hotels, salons,
spas, car service, and professional services). The API itself has no UI of its own — any
frontend (including whatever CMS your team puts in front of it) talks to it entirely over
JSON.

Built with **Python + FastAPI + SQLAlchemy**, running against **SQLite for local dev**
(zero setup) or **PostgreSQL for production** (recommended, and what this README assumes
beyond your laptop).

This branch is a backend-only extract of the project (no bundled frontend) — see the
project's other branches for the standalone React app implementing the Customer, Business,
and Admin portals.

## Why this stack

- **Headless is the whole point of this backend.** "Headless CMS" just means content/data
  lives behind an API instead of behind server-rendered pages. This project *is* that API
  layer — FastAPI serves nothing but JSON, so your frontend (or any CMS glue your team
  wants to bolt on) can consume it exactly the same way it would consume Contentful,
  Strapi, etc. There's no separate "CMS" to add for this to work.
- **FastAPI** because it's async-ready, has request/response validation built in
  (Pydantic), and generates interactive API docs for free at `/docs` — genuinely useful
  when handing this off to a frontend team.
- **PostgreSQL** because the spec's own data model (PART 1) is highly relational: a central
  `Appointment` table hubs out to `User`, `Business`, `Service`, `Staff`/`Space_Inventory`,
  and four different 1-to-1 "details" tables. That's a textbook fit for a relational
  database with real foreign keys and transactions — not a document store. SQLite works
  fine for local development and the whole test suite runs against it, but switch to
  Postgres for anything beyond a single developer's machine (see `docker-compose.yml`).

## Quick start

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt   # includes pytest for running the test suite

cp .env.example .env                  # defaults to a local SQLite file - no DB setup needed
# (optional) start Postgres for something closer to production:
#   docker compose up -d
#   pip install -r requirements-postgres.txt
#   then set DATABASE_URL in .env to the postgresql+psycopg://... URL

alembic upgrade head        # creates all tables
python -m app.bootstrap_admin         # creates the first SuperAdmin (see .env for creds)
python -m app.seed_demo_data          # optional: fills in demo customers/businesses/appointments

uvicorn app.main:app --reload
```

Then open **http://localhost:8000/docs** for interactive API docs, or **/health** for a
liveness check.

### Trying the API with demo data

`python -m app.seed_demo_data` populates the database with one business per category (Salon,
Spa, Car Service, Professional, Restaurant, Hotel), each with its own staff/services or
room/table inventory, 3 customers, and 7 appointments spanning every status (Pending,
Confirmed, Cancelled, Completed) - so you can try every endpoint in `/docs` immediately
without manually registering/approving/booking everything by hand first. It also leaves one
business `Pending` so you can try the admin-approval flow yourself. Credentials for
everything it creates are printed when it runs (all demo accounts use the password
`Password123!`). Safe to re-run - it no-ops if the demo data is already there.

With that seeded, log in with any of the printed accounts and exercise the API directly via
`/docs`.

Run the test suite (uses an isolated in-memory SQLite DB, doesn't touch `.env`/`dev.db`):

```bash
pytest -v
```

## Project layout

```
app/
  config.py          Settings (env vars) - the one place DATABASE_URL, JWT secret, etc. live
  database.py         SQLAlchemy engine/session
  enums.py             Every Enum in the schema, plus a couple of derived lookup sets
  security.py          Password hashing + JWT issuance/verification
  dependencies.py      RBAC gateway: get_current_customer/business/admin, login gates
  models/               SQLAlchemy models (one file per PART 1 section)
  schemas/               Pydantic request/response models
  services/
    availability.py        THE AVAILABILITY ENGINE (PART 2.2 / staff & space conflict checks)
    state_machine.py        Appointment lifecycle transitions + locking (PART 2.4)
    google_calendar.py       Dual-sync orchestrator (PART 2.3) - safe no-op until configured
    analytics.py              Admin dashboard metrics (PART 6.2)
    audit.py                   Admin_Audit_Log helper (PART 1.1)
  routers/                One file per API surface: auth, users, businesses, resources,
                           appointments, admin
  bootstrap_admin.py     One-off script: creates the first SuperAdmin
  seed_demo_data.py       One-off script: fills in demo data to try every endpoint
alembic/                Database migrations
tests/                  pytest suite (auth/RBAC, availability engine, full booking flow)
```

## API overview

All endpoints are under `/api/v1`. Full interactive reference is at `/docs` once running;
this is the shape of it:

| Area | Prefix | Who |
|---|---|---|
| Auth | `/auth/{customer,business,admin}/{register,login}` | everyone |
| Customer profile | `/users/me` | Customer |
| Discovery + business profile | `/businesses`, `/businesses/me` | public + Business |
| Services/Staff/Inventory | `/businesses/{id}/...` (public), `/businesses/me/...` (Business) | public + Business |
| Bookings | `/appointments`, `/appointments/me`, `/appointments/business`, `/appointments/{id}` | Customer + Business |
| Admin | `/admin/dashboard`, `/admin/customers`, `/admin/businesses`, `/admin/audit-log`, overrides | Admin |

Auth is a bearer JWT (`Authorization: Bearer <token>`) with a `role` claim
(`customer` / `business` / `admin`) baked in — there's no single shared "users" table since
customers, businesses, and admins are genuinely different entities per the spec.

### Frontend-facing UX notes

- The Customer Dashboard's color-coded calendar (PART 4.2) and the Business "Action
  Required" / "Today" widgets (PART 5.2) are all just `GET /appointments/me` and
  `GET /appointments/business` with `status`/date query params — no separate endpoints
  needed, the frontend composes the widgets from filtered lists.
- The discovery gallery (`GET /businesses`) supports `category`, `search`, and pagination,
  and only ever returns `Approved` businesses — enforced server-side, not left to the
  client to filter.

## Design decisions / small deviations from the original spec

You said I could make small changes for a better result — here's exactly what changed and why:

1. **`Business` gained `email` + `password_hash`.** The spec's login gate ("if a Business
   is Pending/Suspended → 403") only makes sense if a business can actually log in. The
   original `Business` entity had no credentials at all, so I added the same
   email/password pattern `User` and `AdminUser` already use.
2. **`Staff.working_hours_id`** referenced an undefined "schedule" entity. Replaced with a
   `working_hours` JSON column (same shape as `Business.operating_hours`) so it's usable
   immediately instead of pointing at a table that doesn't exist. `null` = falls back to
   the business's own operating hours.
3. **A few UX fields added to `Business`**: `description`, `address`, `city`,
   `cover_image_url`, `average_rating`, `rating_count`. PART 4.3 explicitly describes
   discovery tiles showing "picture, name, rating, location" — the original entity had
   nowhere to store any of that.
4. **`appointment_type` is derived server-side** from the business's `category` at booking
   time, not accepted from the client request — otherwise a booking could claim a type
   that doesn't match the business being booked.
5. **Business-side Google Calendar sync uses a service account**, not a second OAuth
   token, since the spec only ever stores a `google_calendar_id` for the business (no
   business-side token field). The calendar just needs to be shared with the service
   account's email — a standard pattern for a multi-tenant backend writing into many
   different businesses' calendars. See `GOOGLE_SERVICE_ACCOUNT_FILE` in `.env.example`.
6. **`Completed` is a reachable state**, not just declared in the enum: a business can mark
   a `Confirmed` appointment `Completed` once its end time has passed
   (`POST /appointments/{id}/complete`) — needed for "historical" appointments in a
   customer's profile (PART 3.1) to mean something.
7. **GDPR hard-delete is implemented as anonymization**, exactly as PART 3.1 specifies
   ("Hard Delete (GDPR anonymization)") — the row is scrubbed (name/email/phone/tokens)
   and flagged, never physically deleted, since appointment history elsewhere still
   references it.
8. **Google Calendar sync never blocks or fails a booking.** If `GOOGLE_CALENDAR_ENABLED`
   is off (the default — this repo ships with no real Google credentials) or a sync call
   throws, it's logged and skipped. The booking workflow, accept/reject flow, and
   cancellations all work fully without any Google setup.
9. **`User.phone_number` validates international numbers.** A customer chooses their own
   country by typing its `+<country code>` prefix (e.g. `+60123456789`, `+14155552671`); the
   backend checks it's a real, dialable number for that country (via the `phonenumbers`
   library) and normalizes it to E.164 before storing it — see `app/schemas/validators.py`.
   A number with no `+` prefix, or garbage, is rejected with a 422.
10. **Password strength is enforced on every password a client sets** (registration, admin
    password resets): at least 8 characters, with an uppercase letter, a lowercase letter, a
    digit, and a symbol — see `validate_password_strength` in `app/schemas/validators.py`. A
    *login* password is never re-validated this way, since it only needs to match whatever
    hash is already stored (including for accounts created before this rule existed).
11. **Timezones are explicit, not assumed.** `Business` gained a `timezone` field (an IANA
    zone like `Asia/Kuala_Lumpur`) - the spec's `operating_hours` are plain wall-clock times
    with no timezone of their own, and a booking is fundamentally a slot on *the business's*
    clock, not the customer's. Every appointment's `start_datetime` is required to be
    timezone-aware (a naive datetime is rejected with a 422 - PART 2's original code silently
    assumed UTC, which is exactly how a cross-timezone booking could silently land on the
    wrong hour). `User` also gained an optional `timezone` (a display preference only - it
    never affects availability/conflict checking). Separately, a real bug this surfaced: SQLite
    (the local-dev default) has no native tz-aware datetime type - SQLAlchemy's
    `DateTime(timezone=True)` on SQLite silently stores an aware datetime's naive wall-clock
    fields *without* converting to UTC first, so `14:00+08:00` and `06:00Z` (the same instant)
    were stored as different, non-conflicting values. Fixed with a custom `UTCDateTime` column
    type (`app/db_types.py`) that always normalizes to UTC on the way in and out, backend-agnostic
    - see its tests in `tests/test_timezone.py` for exactly this scenario.

## Running against Postgres

```bash
docker compose up -d
pip install -r requirements-postgres.txt
```

Then in `.env`:

```
DATABASE_URL=postgresql+psycopg://appointments:appointments@localhost:5432/appointments
```

Re-run `alembic upgrade head` against the new URL.

(We use `psycopg` v3 rather than `psycopg2-binary` - it publishes prebuilt wheels for new
Python releases much faster, which matters if you're ever on a very recent Python version.)

## Google Calendar setup (optional)

Sync is off by default and everything works without it. To turn it on:

1. Create OAuth 2.0 credentials in Google Cloud Console for the **customer-side** flow
   (your frontend runs the consent screen and hands the resulting token to
   `PUT /users/me/google-calendar` — this backend never runs that redirect itself).
2. Create a **service account**, download its JSON key, point
   `GOOGLE_SERVICE_ACCOUNT_FILE` at it, and have each business share their Google Calendar
   with that service account's email (this is how the **business-side** writes happen).
3. Set `GOOGLE_CALENDAR_ENABLED=true`.

## Next steps / production hardening

This is a solid, fully working foundation, but a few things are intentionally left simple
and worth revisiting before a real production launch:

- **Refresh tokens** — access tokens are long-lived (`ACCESS_TOKEN_EXPIRE_MINUTES`) with no
  refresh/rotation flow yet.
- **Rate limiting** on auth endpoints.
- **A scheduled job** to auto-transition `Confirmed` appointments to `Completed` once their
  end time passes, instead of relying on the business to click it.
- **Full OAuth token refresh handling** for `User.google_calendar_token` (currently treated
  as an opaque, already-valid token).
- Swap the dev `JWT_SECRET_KEY` for a real generated secret before deploying anywhere.
