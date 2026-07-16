# Sync Pipeline + Revenue Metrics

Backend assignment, two parts, one FastAPI service:

1. **Sync pipeline** — pulls records from HubSpot (CRM contacts + deals), Stripe test mode (payments) and Google Calendar (events) into one normalized Postgres schema on Supabase. Incremental sync with a per-source cursor, automatic fallback to a full backfill when a cursor goes stale or gets rejected, idempotent writes, and per-source isolation so one broken source can't wedge the run.
2. **Metrics service** — one canonical definition of "revenue collected" computed from an *allow-list* of statuses, exposed as a summary total and a per-day breakdown that structurally cannot disagree.

No UI; everything is curl-able. Live deployment runs on Render's free tier.

## Live deployment

- **Base URL:** https://sync-metrics-api-ttg1.onrender.com
- **Interactive API docs (Swagger):** https://sync-metrics-api-ttg1.onrender.com/docs
- Quick checks: [/health](https://sync-metrics-api-ttg1.onrender.com/health) · [/sync/status](https://sync-metrics-api-ttg1.onrender.com/sync/status) · [revenue summary](https://sync-metrics-api-ttg1.onrender.com/metrics/revenue?start=2026-07-01&end=2026-07-31) · [daily breakdown](https://sync-metrics-api-ttg1.onrender.com/metrics/revenue/daily?start=2026-07-01&end=2026-07-31)

`POST /sync/run` is protected with an `x-api-key` header on the public deployment (a sync also runs automatically every 30 minutes). Note: free-tier services sleep when idle, so the first request can take ~50 seconds.

## How it works

```
HubSpot ─┐
Stripe  ─┼─ app/sources/*  ──►  app/sync.py  ──►  Supabase Postgres
GCal    ─┘   (normalize to        (runner:          ├─ records       (problem 1)
              one Record shape)    cursors,          ├─ transactions  (problem 2)
                                   fallback,         └─ sync_state    (cursors)
                                   upserts)
                                                          │
                              app/metrics.py  ◄───────────┘
                              (the ONE revenue definition)
                                   │
                    /metrics/revenue   /metrics/revenue/daily
```

Each source module exposes the same two functions — `full_fetch()` and `incremental_fetch(cursor)` — and raises `StaleCursor` when the source rejects its cursor. The runner in [app/sync.py](app/sync.py) doesn't know or care what a cursor looks like: HubSpot and Stripe use a timestamp with a one-minute overlap window (safe because writes are idempotent), Google Calendar uses its real `syncToken`, which is also the source that genuinely expires cursors with a 410.

### The guarantees, and where they live

| Requirement | Where |
|---|---|
| Stale/rejected cursor → full backfill, not data loss | `_sync_source` in `app/sync.py`; each source raises `StaleCursor` |
| Duplicate webhook / re-run → no duplicate rows | `ON CONFLICT` upserts keyed on the source's own id; proven by `tests/test_idempotency.py` |
| One source down → others still land | per-source try/except in `sync.run`; the failure is recorded in `sync_state.last_error` |
| Revenue counted from an allow-list | two layers: raw→canonical map in `app/statuses.py` (unmapped → `unknown`), then `COLLECTED_STATUSES` in `app/metrics.py` |
| Both revenue views always agree | the summary is computed *from* the daily rows — same query, same allow-list; `tests/test_metrics_consistency.py` asserts it |
| A second revenue definition gets caught | `tests/test_single_definition.py` fails the suite if any other module under `app/` sums transaction amounts or declares its own allow-list |

## Running locally

Needs Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in your credentials
python -m scripts.init_db   # create tables (idempotent)

# seed the sources (once each)
python -m scripts.seed_hubspot
python -m scripts.seed_stripe
python -m scripts.seed_gcal

# run the pipeline
python -m scripts.run_sync           # incremental (first run = full)
python -m scripts.run_sync --full    # force a backfill

# or serve the API
uvicorn app.main:app --reload
```

Tests: `pytest`. The status-map and single-definition tests are pure; the DB tests run against `DATABASE_URL` inside a transaction that always rolls back, so they never touch real data.

### Environment variables

| Var | What |
|---|---|
| `DATABASE_URL` | Supabase Postgres. **Use the session-pooler string** (`...pooler.supabase.com:5432`) — the direct connection is IPv6-only and unreachable from Render's free tier. |
| `HUBSPOT_TOKEN` | Private app token, contacts + deals read (write only for seeding) |
| `STRIPE_SECRET_KEY` | Test-mode secret key (`sk_test_...`); the seed script refuses live keys |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to the key file, or the JSON pasted inline (for Render) |
| `GOOGLE_CALENDAR_ID` | Calendar shared with the service account's email |
| `SYNC_API_KEY` | Optional; if set, `POST /sync/run` requires it as `x-api-key` |
| `SYNC_INTERVAL_MINUTES` | In-process sync loop; `0` disables it |

## API

```bash
BASE=https://sync-metrics-api-ttg1.onrender.com   # or http://localhost:8000

curl $BASE/health
curl -X POST "$BASE/sync/run" -H "x-api-key: $SYNC_API_KEY"
curl -X POST "$BASE/sync/run?source=stripe" -H "x-api-key: $SYNC_API_KEY"
curl "$BASE/sync/status"
curl "$BASE/records?source=gcal&limit=10"

curl "$BASE/metrics/revenue?start=2026-07-01&end=2026-07-31"
curl "$BASE/metrics/revenue/daily?start=2026-07-01&end=2026-07-31"
```

Amounts are integer cents throughout (floats and money don't mix). Date ranges are inclusive, bucketed by UTC day.

## Demoing the failure cases

**Stale cursor → full backfill.** Corrupt a cursor by hand, then sync:

```sql
update sync_state set sync_cursor = 'not-a-real-cursor' where source = 'stripe';
```

The next run logs `stripe cursor is stale ... falling back to full backfill`, reports `"mode": "full_backfill"`, and row counts stay correct. The same works for `gcal` (Google rejects the bad syncToken; a real expiry returns 410, handled by the same path).

**Duplicate delivery.** Run the sync twice back-to-back; the second run reports `inserted: 0` and `select count(*)` is unchanged. Also proven by `tests/test_idempotency.py`.

**One source down.** Set `HUBSPOT_TOKEN` to garbage and sync: the response shows `hubspot: {ok: false, error: ...}` while Stripe and GCal land their data. The error is queryable at `/sync/status`, and the old cursor is kept so the retry covers the missed window.

**New status can't leak into revenue.** Insert a transaction with a status nobody has mapped (`settled_v2`): it normalizes to `unknown` and both revenue views ignore it — `tests/test_metrics_consistency.py::test_only_allowlisted_statuses_count`.

## Tradeoffs

- **Timestamp cursors with overlap for HubSpot/Stripe** instead of storing per-record high-water marks. Simpler, and re-reading a one-minute sliver is free because writes are idempotent. The tradeoff: HubSpot's search API caps results at 10k, fine at this scale.
- **Polling, not webhooks.** Webhooks need public endpoints during development and don't change the correctness story — idempotent upserts are exactly what makes webhook replays safe, which the tests demonstrate directly.
- **Row-at-a-time upserts.** At a few hundred records a batched `COPY`/`executemany` would be premature; the `xmax = 0` trick gives honest inserted-vs-updated counts for observability.
- **HubSpot deals as the second revenue source.** Deal stages (`closedwon`/`closedlost`) are a genuinely different status vocabulary from Stripe's, which is the point of the exercise; a third finance API would add setup cost without new behavior.
- **In-process sync loop** instead of a Render cron job (paid) — plus a `POST /sync/run` endpoint so a run can be triggered live. Render's free tier spins down on idle; the first request may take ~50s.
- **Summary derived from the daily rows** rather than two SQL queries that "should" match. Agreement is structural, not tested-by-hope; the tests are a second line of defense.

## Sources & references

- HubSpot CRM API v3: objects list/search, private apps — https://developers.hubspot.com/docs/api/crm/contacts , https://developers.hubspot.com/docs/api/crm/search (search filter on `lastmodifieddate` / `hs_lastmodifieddate`, default pipeline stage ids)
- Stripe API: charges list with `created[gte]`, pagination via `starting_after`, test payment methods (`pm_card_visa`, `pm_card_chargeDeclined`) — https://docs.stripe.com/api/charges/list , https://docs.stripe.com/testing
- Google Calendar API: incremental sync with `syncToken`, the documented 410-means-full-resync behavior — https://developers.google.com/calendar/api/guides/sync ; service-account auth — https://developers.google.com/identity/protocols/oauth2/service-account
- Supabase connection strings and the IPv4/pooler caveat — https://supabase.com/docs/guides/database/connecting-to-postgres
- Render blueprint spec (`render.yaml`) — https://render.com/docs/blueprint-spec
- Postgres `ON CONFLICT` + the `xmax = 0` insert-vs-update trick — https://stackoverflow.com/a/39204667
- Free-tier accounts used: HubSpot developer test account, Stripe test mode, Google Cloud (Calendar API + service account), Supabase free project, Render free web service

## AI usage

Built with Claude Code (Anthropic). I wrote the problem breakdown and design decisions in prompts and reviewed/tested everything that came back; the full conversation transcript is in this repo: [ai-conversation-export.txt](ai-conversation-export.txt) (API keys and passwords redacted; tool calls shown as one-line summaries).
