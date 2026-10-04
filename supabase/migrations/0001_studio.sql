-- ODD EYES Character Studio, migration 0001: schema `studio`.
--
-- Additive only. Creates objects in schema studio (plus two private Storage buckets) and
-- touches nothing else in the project. Applied to Supabase project hkcafvzjwkeibbmvskko
-- ("faceless-youtube") as migration `studio_0001`.
--
-- The integration tests apply this same text to a scratch schema by renaming the
-- schema identifier, so keep every object schema-qualified with `studio.`.

create schema if not exists studio;

-- settings: one row, id = 1 ---------------------------------------------------------
create table studio.settings (
  id                  int primary key default 1 check (id = 1),
  monthly_cap_credits int not null default 6000 check (monthly_cap_credits >= 0),
  kill_switch         boolean not null default false,
  cadence             jsonb not null default '{}'::jsonb
);

-- characters and their social accounts ----------------------------------------------
create table studio.characters (
  slug       text primary key,
  name       text not null,
  status     text not null default 'designing',
  bodies     text[] not null default '{}' check (bodies <@ array['biped', 'quadruped']),
  created_at timestamptz not null default now()
);

create table studio.accounts (
  id                    uuid primary key default gen_random_uuid(),
  character_slug        text not null references studio.characters (slug),
  platform              text not null check (platform in ('tiktok', 'instagram')),
  handle                text not null,
  postiz_integration_id text,
  mode                  text not null default 'approval' check (mode in ('approval', 'auto')),
  dropin_share          double precision not null default 0.7 check (dropin_share between 0 and 1),
  created_at            timestamptz not null default now(),
  unique (platform, handle)
);

-- source library: every driving clip, with its checks -------------------------------
create table studio.sources (
  id            uuid primary key default gen_random_uuid(),
  kind          text not null check (kind in ('higgsfield_library', 'owner_inbox', 'synthetic')),
  url           text,
  storage_path  text,
  preset_id     text,
  body          text not null check (body in ('biped', 'quadruped')),
  bodies        int not null default 1,
  duration_s    double precision not null,
  has_watermark boolean,
  has_overlay   boolean,
  other_people  int,
  trend         text,
  credit_handle text,
  created_at    timestamptz not null default now()
);

-- clips: one row per made clip, driven through the state machine --------------------
create table studio.clips (
  id               uuid primary key default gen_random_uuid(),
  character_slug   text not null references studio.characters (slug),
  source_id        uuid references studio.sources (id),
  mode             text not null check (mode in ('dropin', 'recreate')),
  state            text not null default 'planned' check (state in (
                     'planned', 'generating', 'gen_failed', 'generated', 'qa_failed',
                     'qa_passed', 'mastered', 'awaiting_approval', 'approved', 'rejected',
                     'scheduled', 'posted', 'dropped')),
  hf_job_id        text,
  credits_reserved int not null default 0,
  credits_actual   int,
  qa               jsonb not null default '{}'::jsonb,
  master_path      text,
  hook             text,
  caption          text,
  hashtags         text[] not null default '{}',
  features         jsonb not null default '{}'::jsonb,
  reject_reason    text,
  created_at       timestamptz not null default now()
);
create index clips_state_idx on studio.clips (state);
create index clips_source_id_idx on studio.clips (source_id);

-- posts: one per (clip, account); claimed atomically by the publisher ---------------
create table studio.posts (
  id               uuid primary key default gen_random_uuid(),
  clip_id          uuid not null references studio.clips (id),
  account_id       uuid not null references studio.accounts (id),
  scheduled_for    timestamptz not null,
  status           text not null default 'scheduled'
                   check (status in ('scheduled', 'posting', 'posted', 'failed', 'needs_check')),
  claimed_at       timestamptz,
  attempts         int not null default 0,
  platform_post_id text,
  url              text,
  error            text,
  unique (clip_id, account_id)
);
create index posts_status_scheduled_for_idx on studio.posts (status, scheduled_for);

-- metric snapshots: a missing metric is NULL, never 0 -------------------------------
create table studio.snapshots (
  post_id          uuid not null references studio.posts (id),
  captured_at      timestamptz not null default now(),
  views            bigint,
  likes            bigint,
  comments         bigint,
  shares           bigint,
  saves            bigint,
  watch_time_s     double precision,
  follows          bigint,
  non_follower_pct double precision,
  primary key (post_id, captured_at)
);

-- credit ledger: committed = settled + open reservations ----------------------------
create table studio.ledger (
  id         uuid primary key default gen_random_uuid(),
  clip_id    uuid not null references studio.clips (id),
  month      text not null check (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  kind       text not null check (kind in ('reserve', 'settle', 'release')),
  credits    int not null,
  created_at timestamptz not null default now()
);
create index ledger_month_idx on studio.ledger (month);

-- scheduled-run log and weekly reviews ----------------------------------------------
create table studio.runs (
  id          uuid primary key default gen_random_uuid(),
  kind        text not null,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null,
  summary     text
);

create table studio.reviews (
  id             uuid primary key default gen_random_uuid(),
  week           date not null,
  character_slug text not null references studio.characters (slug),
  report_md      text not null,
  bar_status     text,
  created_at     timestamptz not null default now()
);

-- Viral Picks: scan results arrive as `new`; only `approved` ones are produced -------
create table studio.favorites (
  id             uuid primary key default gen_random_uuid(),
  url            text not null,
  platform       text,
  creator_handle text,
  views          bigint,
  outlier_x      numeric,
  origin         text not null default 'scan' check (origin in ('scan', 'owner')),
  character_slug text references studio.characters (slug),
  proposal       jsonb not null default '{}'::jsonb,
  scores         jsonb not null default '{}'::jsonb,
  total_score    numeric,
  note           text,
  status         text not null default 'new'
                 check (status in ('new', 'approved', 'skipped', 'analysed', 'queued', 'made')),
  breakdown_md   text,
  source_id      uuid references studio.sources (id),
  clip_id        uuid references studio.clips (id),
  created_at     timestamptz not null default now()
);

-- row level security: the owner and nobody else (the CLI connects as the table owner,
-- which bypasses RLS) ---------------------------------------------------------------
alter table studio.settings   enable row level security;
alter table studio.characters enable row level security;
alter table studio.accounts   enable row level security;
alter table studio.sources    enable row level security;
alter table studio.clips      enable row level security;
alter table studio.posts      enable row level security;
alter table studio.snapshots  enable row level security;
alter table studio.ledger     enable row level security;
alter table studio.runs       enable row level security;
alter table studio.reviews    enable row level security;
alter table studio.favorites  enable row level security;

create policy owner_all on studio.settings   for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.characters for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.accounts   for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.sources    for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.clips      for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.posts      for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.snapshots  for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.ledger     for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.runs       for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.reviews    for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
create policy owner_all on studio.favorites  for all to authenticated
  using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
  with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');

grant usage on schema studio to authenticated;
grant select, insert, update, delete on all tables in schema studio to authenticated;

-- seed: the single settings row, with the weekly cadence per character ---------------
insert into studio.settings (id, monthly_cap_credits, kill_switch, cadence)
values (
  1, 6000, false,
  '{"biscuit":{"days":["tue","wed","thu"],"slot":"19:00"},"reginald":{"days":["tue","wed","thu"],"slot":"19:30"}}'::jsonb
)
on conflict (id) do nothing;

-- private Storage buckets (skipped silently on a database without Supabase Storage) --
do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public)
    values ('sources', 'sources', false), ('clips', 'clips', false)
    on conflict (id) do nothing;
  end if;
end
$$;
