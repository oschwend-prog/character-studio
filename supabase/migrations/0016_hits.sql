-- ODD EYES Character Studio, migration 0016: the cloud hits job (spec docs/superpowers/specs/2026-10-07-terminal-v3-design.md,
-- section 10; plan docs/superpowers/plans/2026-10-07-terminal-v3.md, task 6): the posts the daily ScrapeCreators pull keeps
-- (studio.hits, read by the terminal as studio.v_hits), the owner's buttons on a hit (studio.set_hit_status: "Use this clip"
-- marks it dropped, "Not for us" dismissed) and on a drop (studio.set_drop_keep: Keep, so retention never deletes its clip),
-- studio.copy_drop carrying the hits job's tag into a version, and what the ScrapeCreators jobs spend each London day
-- (studio.hits_spend).
--
-- WHY. The owner asked for a cloud job that finds what is hot without the Mac (2026-10-07: "set up the scrapecreators cloud
-- job"; "let it scrape if necessary. I just don't want it to need the Mac running and browsing to get it done"). The workflow
-- .github/workflows/studio-hits.yml runs `studio hits pull` once a day: ScrapeCreators' API answers with metadata only (no
-- download), the job keeps one row per post here, files the best as drops (`studio.hits.auto_file`, tagged drop.auto_filed)
-- and deletes the clips nobody used (`studio source purge --stale`, which spares a drop the owner marked Keep). The terminal
-- shows the hits ("Hot right now", "Worth saving") and needs two owner-only buttons for them and for Keep; a version of an
-- auto-filed clip must keep the tag (the learning tag source_kind reads it; retention gives a hit's clip 30 days). The credit
-- caps are per London day (controller ruling 2026-10-08): a second run the same day must start from what the first spent, and
-- the drop job's one-post downloads (10 credits each) count into the same day, so the day's spend lives in the database.
--
-- Additive / replacing only, schema studio only. To be applied to Supabase project hkcafvzjwkeibbmvskko ("faceless-youtube",
-- shared with another app) as migration `studio_0016_hits`, AFTER 0015; the controller (or the owner) applies it, it is never
-- run from the studio CLI. Apply it BEFORE the first run of studio-hits.yml (the job writes studio.hits and studio.hits_spend)
-- and before the terminal
-- that reads v_hits is deployed. Re-run safe: the table is created if missing, its policy only when it is not there yet, the
-- view and every function are `create or replace` with an unchanged column list or signature, and every grant and revoke may
-- repeat.
--
-- 1. hits: one row per post (url unique: the canonical TikTok video or Instagram Reel link), the fields of spec section 10 as
--    studio.models.Hit holds them (platform tiktok or instagram; creator_handle; followers, views, likes, comments, shares and
--    saves, each NULL when the API did not give it, never 0; posted_at; caption, at most 300 characters; sound; duration_s;
--    thumbnail_url, stored, never fetched; the keyword and the character it was searched for, character_slug NULL for the
--    general lane; reach = views / followers; score 0-100; status new, dropped or dismissed; created_at = first seen, last_seen).
--    hits_spend(day, search_credits, download_credits, downloads, updated_at): one row per London day, what the searches of
--    `studio hits pull` and the one-post downloads of the drop job were charged and how many downloads were made (the
--    dataclass HitSpend). Written only by the jobs through the studio CLI (PostgresStore.add_hit_spend: one insert ... on
--    conflict (day) do update that adds, so two writers both count); hits.daily_credit_cap covers the day's total,
--    hits.download_cap_per_day its downloads.
-- 2. Row level security like every table of 0001: the one owner_all policy (the owner's e-mail in USING and WITH CHECK). The CLI
--    connects as the table owner, which bypasses RLS. The terminal's role may only read it: hits changes through the RPC.
--    hits_spend is like 0014's timer_state: RLS on, no policy and no grant, so no API role can read or write it.
-- 3. v_hits: the new hits, best first (score, then the latest seen), with the character's name, readable by the terminal's role
--    and running as the caller (security_invoker), like v_views_daily.
-- 4. set_hit_status(hit_id, status): the owner's "Use this clip" (dropped, after add_drop(link)) and "Not for us" (dismissed),
--    or back to new. SECURITY DEFINER (studio.hits is read-only for the terminal's role), empty search_path, schema-qualified
--    names, and the owner check of set_drop_character first. Refused: anyone else (insufficient_privilege), a status the table
--    does not know (invalid_parameter_value), an unknown hit (no_data_found). Returns the row.
-- 5. set_drop_keep(pick_id, keep): the owner's Keep on a drop's card, drop.keep true or false (studio.drop.set_keep in the CLI).
--    Like 0012's set_drop_footage (security invoker: RLS applies), with the owner check of set_drop_character first. Refused:
--    anyone else, a null keep, an unknown pick, a pick that is not a drop. Returns the row.
-- 6. copy_drop (0015's, word for word plus one step): a version of a drop the hits job filed (drop.auto_filed true) carries
--    auto_filed too, as studio.drop.copy_drop does; a root without the tag gives a version without it (0015's version exactly).
-- 7. Grants: hits revoked from public and from the terminal's role, then select granted back to it; v_hits granted to it; the
--    three functions revoked from public and granted to it; hits_spend revoked from public and the terminal's role; everything
--    revoked from anon where the role exists.
--
-- TO UNDO (in this order): re-run the copy_drop section of 0015 (create or replace puts it back), then
--   drop function studio.set_drop_keep(uuid, boolean);
--   drop function studio.set_hit_status(uuid, text);
--   drop view studio.v_hits;
--   drop table studio.hits_spend;
--   drop table studio.hits;
-- The drops already filed stay as ordinary drops (their auto_filed and hit are then only data).

-- ---- 1. hits -----------------------------------------------------------------------------------------------------------------

create table if not exists studio.hits (
  id             uuid primary key default gen_random_uuid(),
  platform       text not null check (platform in ('tiktok', 'instagram')),
  url            text not null unique,
  creator_handle text,
  followers      bigint check (followers is null or followers >= 0),
  views          bigint check (views is null or views >= 0),
  likes          bigint check (likes is null or likes >= 0),
  comments       bigint check (comments is null or comments >= 0),
  shares         bigint check (shares is null or shares >= 0),
  saves          bigint check (saves is null or saves >= 0),
  posted_at      timestamptz,
  caption        text check (caption is null or char_length(caption) <= 300),
  sound          text,
  duration_s     double precision,
  thumbnail_url  text,
  keyword        text,
  character_slug text references studio.characters (slug),
  reach          double precision,
  score          integer not null default 0 check (score between 0 and 100),
  status         text not null default 'new' check (status in ('new', 'dropped', 'dismissed')),
  created_at     timestamptz not null default now(),
  last_seen      timestamptz not null default now()
);

create table if not exists studio.hits_spend (
  day              date primary key,
  search_credits   integer not null default 0 check (search_credits >= 0),
  download_credits integer not null default 0 check (download_credits >= 0),
  downloads        integer not null default 0 check (downloads >= 0),
  updated_at       timestamptz not null default now()
);

-- ---- 2. row level security ---------------------------------------------------------------------------------------------------

alter table studio.hits enable row level security;
alter table studio.hits_spend enable row level security;
do $$
begin
  if not exists (select 1 from pg_catalog.pg_policies
                 where schemaname = 'studio' and tablename = 'hits' and policyname = 'owner_all') then
    create policy owner_all on studio.hits for all to authenticated
      using (auth.jwt()->>'email' = 'o.schwend@gmail.com')
      with check (auth.jwt()->>'email' = 'o.schwend@gmail.com');
  end if;
end
$$;

-- ---- 3. v_hits ---------------------------------------------------------------------------------------------------------------

create or replace view studio.v_hits with (security_invoker = true) as
select
  h.id as hit_id,
  h.platform,
  h.url,
  h.creator_handle,
  h.followers,
  h.views,
  h.likes,
  h.comments,
  h.shares,
  h.saves,
  h.posted_at,
  h.caption,
  h.sound,
  h.duration_s,
  h.thumbnail_url,
  h.keyword,
  h.character_slug,
  ch.name as character_name,
  h.reach,
  h.score,
  h.created_at as first_seen,
  h.last_seen
from studio.hits h
left join studio.characters ch on ch.slug = h.character_slug
where h.status = 'new'
order by h.score desc, h.last_seen desc, h.id;

-- ---- 4. set_hit_status -------------------------------------------------------------------------------------------------------

create or replace function studio.set_hit_status(hit_id uuid, status text)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  h studio.hits;
  status_ text := nullif(btrim(set_hit_status.status), '');
begin
  -- definer rights bypass RLS: the owner rule of every policy of this schema, checked here (as set_drop_character does)
  if coalesce((select auth.jwt() ->> 'email'), '') <> 'o.schwend@gmail.com' then
    raise exception 'only the owner may mark a hit' using errcode = 'insufficient_privilege';
  end if;
  if status_ is null or status_ not in ('new', 'dropped', 'dismissed') then
    raise exception 'a hit is new, dropped or dismissed, not %', coalesce(quote_literal(status_), 'nothing')
      using errcode = 'invalid_parameter_value';
  end if;
  update studio.hits hi set status = status_ where hi.id = set_hit_status.hit_id returning hi.* into h;
  if not found then
    raise exception 'unknown hit %', set_hit_status.hit_id using errcode = 'no_data_found';
  end if;
  return to_jsonb(h);
end;
$$;

-- ---- 5. set_drop_keep --------------------------------------------------------------------------------------------------------

create or replace function studio.set_drop_keep(pick_id uuid, keep boolean)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  f studio.favorites;
begin
  -- the owner rule of every policy of this schema, checked first (as set_drop_character does); RLS applies as well
  if coalesce((select auth.jwt() ->> 'email'), '') <> 'o.schwend@gmail.com' then
    raise exception 'only the owner may keep a clip' using errcode = 'insufficient_privilege';
  end if;
  if set_drop_keep.keep is null then
    raise exception 'keep must be true or false' using errcode = 'invalid_parameter_value';
  end if;
  select * into f from studio.favorites fa where fa.id = set_drop_keep.pick_id for update;
  if not found then
    raise exception 'unknown pick %', set_drop_keep.pick_id using errcode = 'no_data_found';
  end if;
  if jsonb_typeof(f.proposal -> 'drop') is distinct from 'object' then
    raise exception 'pick % is not a dropped video', f.id using errcode = 'check_violation';
  end if;
  update studio.favorites fa
     set proposal = jsonb_set(fa.proposal, '{drop,keep}', to_jsonb(set_drop_keep.keep))
   where fa.id = f.id
  returning fa.* into f;
  return to_jsonb(f);
end;
$$;

-- ---- 6. copy_drop ------------------------------------------------------------------------------------------------------------

create or replace function studio.copy_drop(pick_id uuid, character_slug text)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  f studio.favorites;
  root studio.favorites;
  root_id text;
  d jsonb;
  state_ text;
  source_ text;
  path_ text;
  slug_ text := nullif(btrim(copy_drop.character_slug), '');
  ch studio.characters;
  members int;
  has_him boolean;
  star jsonb;
  kind_ text;
  body_ text;
  wants text;
  stars_ jsonb;
  words constant jsonb := '{"person": "a person", "dog": "a dog", "animal": "a small animal"}';
  at_ timestamptz := now();
  new_id uuid := gen_random_uuid();
  proposal_ jsonb;
  sent jsonb;
begin
  -- definer rights bypass RLS: the owner rule of every policy of this schema, checked here (as request_job does)
  if coalesce((select auth.jwt() ->> 'email'), '') <> 'o.schwend@gmail.com' then
    raise exception 'only the owner may use a clip for another character' using errcode = 'insufficient_privilege';
  end if;
  select * into f from studio.favorites fa where fa.id = copy_drop.pick_id;
  if not found then
    raise exception 'unknown pick %', copy_drop.pick_id using errcode = 'no_data_found';
  end if;
  -- the ROOT, locked before the family is counted: two taps (or a tap and a change of character) wait for each other here, so
  -- a family never gets a 4th member or one character twice. Compared as text: a malformed copy_of finds no root.
  root_id := studio.family_root_id(f.proposal, f.id);
  select * into root from studio.favorites fa where fa.id::text = root_id for update;
  if not found or jsonb_typeof(root.proposal -> 'drop') is distinct from 'object' then
    raise exception 'the original clip % is gone', root_id using errcode = 'check_violation';
  end if;
  d := root.proposal -> 'drop';
  state_ := d ->> 'state';
  source_ := coalesce(root.source_id::text, nullif(d ->> 'source_id', ''));
  -- asked from a version's card: say what is true of the original
  if root.id <> f.id and state_ in ('blocked', 'failed') then
    raise exception 'the original clip can''t be used any more' using errcode = 'check_violation';
  end if;
  if root.id <> f.id and state_ in ('uploading', 'checking', 'waiting') then
    raise exception 'the original clip is being checked again: try in a few minutes' using errcode = 'check_violation';
  end if;
  if state_ is null or state_ not in ('ready', 'making', 'made') or source_ is null then
    raise exception 'the clip is not checked yet' using errcode = 'check_violation';
  end if;
  select s.storage_path into path_ from studio.sources s where s.id::text = source_;
  if coalesce(path_, '') = '' then
    raise exception 'the clip''s file is gone (deleted after posting): drop it again' using errcode = 'check_violation';
  end if;
  select * into ch from studio.characters c where c.slug = slug_;
  if not found then
    raise exception 'unknown character %', coalesce(quote_literal(slug_), 'None') using errcode = 'invalid_parameter_value';
  end if;
  -- the family: the root and its versions, skipped picks not counted, at most 3 (MAX_FAMILY), each character once
  select count(*), coalesce(bool_or(fa.character_slug = ch.slug), false) into members, has_him
    from studio.favorites fa
   where fa.status <> 'skipped' and studio.family_root_id(fa.proposal, fa.id) = studio.family_root_id(root.proposal, root.id);
  if has_him then
    raise exception '% already has a version of this clip', ch.name using errcode = 'check_violation';
  end if;
  if members >= 3 then
    raise exception 'a clip goes to at most 3 characters' using errcode = 'check_violation';
  end if;
  if ch.status = 'paused' then
    raise exception '% is paused', ch.name using errcode = 'invalid_parameter_value';
  end if;
  -- like for like (drop.like_for_like, with its lines): the root's star kind against the kinds he replaces (setup.stars, the
  -- seed's copy of refs.json swap.stars; setup.swap.stars, the key 0013 read, still counts), then the star's body against his
  -- bodies. A character seeded before terminal v3 has neither: then only the body is checked here (and his own free check
  -- still blocks a wrong kind of star).
  stars_ := coalesce(ch.setup -> 'stars', ch.setup -> 'swap' -> 'stars');
  star := case when jsonb_typeof(d -> 'star') = 'object' then d -> 'star' else '{}'::jsonb end;
  kind_ := star ->> 'kind';
  body_ := star ->> 'body';
  if kind_ = 'none' then
    raise exception 'nobody to replace: the clip has no clear star' using errcode = 'check_violation';
  end if;
  if jsonb_typeof(stars_) = 'array' and (kind_ is null or not stars_ ? kind_) then
    select string_agg(coalesce(words ->> e.s, e.s), ' or ' order by e.n) into wants
      from jsonb_array_elements_text(stars_) with ordinality as e(s, n);
    raise exception 'the wrong star: % replaces %, this clip''s star is %', ch.name, coalesce(wants, ''),
      coalesce(words ->> kind_, kind_, 'None') using errcode = 'check_violation';
  end if;
  if body_ is null or not (body_ = any (ch.bodies)) then
    raise exception 'the wrong star: % has no % body', ch.name, coalesce(body_, 'None') using errcode = 'check_violation';
  end if;

  -- the version: a file drop sharing the root's full clip (nothing is uploaded again), its own free check to come
  proposal_ := jsonb_build_object(
    'decision', jsonb_build_object('decision', 'approve', 'by', 'owner', 'reason', 'owner''s own video', 'at', at_),
    'drop', jsonb_build_object('state', 'checking', 'kind', coalesce(d -> 'kind', to_jsonb('file'::text)), 'at', at_, 'reason', null,
                               'own_footage', coalesce(d -> 'own_footage' = 'true'::jsonb, false), 'character_by', 'owner',
                               'copy_of', root.id, 'requested', jsonb_build_object('process', at_))
  );
  if jsonb_typeof(root.proposal -> 'fetched') = 'object' then
    -- one download, shared (studio.fetch): `source purge` deletes the clip only once the last member is done
    proposal_ := proposal_ || jsonb_build_object('fetched', (root.proposal -> 'fetched') - 'purged_at');
  end if;
  if d -> 'auto_filed' = 'true'::jsonb then
    -- the hits job's tag (drop.auto_filed: the learning tag source_kind, retention's 30 days) goes into the version too
    proposal_ := jsonb_set(proposal_, '{drop,auto_filed}', 'true'::jsonb);
  end if;
  insert into studio.favorites (id, url, platform, origin, character_slug, creator_handle, proposal, status, source_id)
  values (new_id, 'owner-drop:' || new_id::text, 'drop', 'owner', ch.slug, root.creator_handle, proposal_, 'approved', source_::uuid);

  -- the check, as the Checking button asks for it: request_job records requested.process and dispatches drop-process (the token
  -- never leaves request_job)
  sent := studio.request_job(new_id, 'process');
  return jsonb_build_object('pick_id', new_id, 'dispatched', coalesce((sent ->> 'dispatched')::boolean, false));
end;
$$;

-- ---- 7. grants ---------------------------------------------------------------------------------------------------------------

revoke all on studio.hits from public;
revoke all on studio.hits from authenticated;
grant select on studio.hits to authenticated;
revoke all on studio.v_hits from public;
grant select on studio.v_hits to authenticated;
revoke all on function studio.set_hit_status(uuid, text) from public;
grant execute on function studio.set_hit_status(uuid, text) to authenticated;
revoke all on function studio.set_drop_keep(uuid, boolean) from public;
grant execute on function studio.set_drop_keep(uuid, boolean) to authenticated;
revoke all on function studio.copy_drop(uuid, text) from public;
grant execute on function studio.copy_drop(uuid, text) to authenticated;
revoke all on studio.hits_spend from public;
revoke all on studio.hits_spend from authenticated;
do $$
begin
  -- no API role but the signed-in owner may read or call any of it (the owner checks refuse everyone else too)
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'anon') then
    execute 'revoke all on studio.hits from anon';
    execute 'revoke all on studio.hits_spend from anon';
    execute 'revoke all on studio.v_hits from anon';
    execute 'revoke all on function studio.set_hit_status(uuid, text) from anon';
    execute 'revoke all on function studio.set_drop_keep(uuid, boolean) from anon';
    execute 'revoke all on function studio.copy_drop(uuid, text) from anon';
  end if;
end
$$;
