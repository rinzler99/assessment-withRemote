-- One row per source; holds the incremental cursor and last-run info.
create table if not exists sync_state (
    source       text primary key,
    sync_cursor  text,
    last_mode    text,
    last_run_at  timestamptz,
    last_error   text
);

-- Problem 1: every record from every source, in one shape. The primary key
-- is the source's own id, which is what makes writes idempotent.
create table if not exists records (
    source         text not null,
    source_id      text not null,
    kind           text not null,          -- contact | deal | payment | event
    title          text,
    status         text,                   -- source's raw status vocabulary
    amount_cents   bigint,
    currency       text,
    occurred_at    timestamptz,
    raw            jsonb,
    first_seen_at  timestamptz not null default now(),
    last_synced_at timestamptz not null default now(),
    primary key (source, source_id)
);

-- Problem 2: normalized money movements. canonical_status is derived from
-- the source status via the allow-list in app/statuses.py; anything
-- unrecognized lands here as 'unknown' and never counts as revenue.
create table if not exists transactions (
    source           text not null,
    source_txn_id    text not null,
    amount_cents     bigint not null,
    currency         text not null,
    raw_status       text not null,
    canonical_status text not null,
    occurred_at      timestamptz not null,
    last_synced_at   timestamptz not null default now(),
    primary key (source, source_txn_id)
);

create index if not exists transactions_occurred_at_idx
    on transactions (occurred_at);
