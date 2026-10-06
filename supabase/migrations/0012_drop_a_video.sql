-- ODD EYES Character Studio, migration 0012: Drop a video (plan docs/superpowers/plans/2026-10-06-drop-a-video.md).
--
-- Additive / replacing only, schema studio only (plus enabling the pg_net extension when the database offers it). To be
-- applied to Supabase project hkcafvzjwkeibbmvskko ("faceless-youtube") as migration `studio_0012_drop_a_video`, AFTER 0011;
-- the controller (or the owner) applies it, it is never run from the studio CLI. Apply it BEFORE the terminal that calls
-- add_drop / request_job is deployed. Owner step after applying it: a fine-grained GitHub token for this repo only
-- (Contents: read and write) stored in Supabase Vault under the name `github_dispatch_token`. Until it exists, request_job
-- records the request and the 2-hourly `studio-drop` sweep picks it up.
--
-- 1. pg_net (net.http_post) is enabled when the database has it (Supabase does); elsewhere nothing happens.
-- 2. add_drop(character_slug, link): the owner drops a video on "In the works". Security invoker (the owner's RLS applies),
--    empty search_path; mirrors studio.drop.add_drop. A file (link null) is a new pick keyed 'owner-drop:<pick id>', platform
--    'drop', origin owner, status approved, proposal {decision (by owner, at), drop {state 'uploading', kind 'file'}}: the
--    browser then uploads the video to sources/owner/<pick id>/<file> and calls attach_clip (0008). A link must be the
--    canonical TikTok / Instagram Reel / YouTube Shorts (or watch) URL; it is filed at state 'checking' with the TikTok
--    handle as its creator, and a link this character already has becomes that pick's drop (a pick already queued or made
--    is returned untouched with duplicate true).
-- 3. request_job(pick_id, kind, adjust): the owner's button. SECURITY DEFINER (it reads the Vault, which the owner's role
--    may not), with a fixed empty search_path, schema-qualified names only, and its own owner check (the same e-mail rule as
--    every policy of this schema). kind 'process' (Checking: from uploading with the file attached, checking, waiting or
--    failed) or 'make' (Make it: from ready or failed, once the check has priced it). 'make' is the owner's approval of
--    that one video: it stores proposal.make_requested = {at, by: 'owner'} (the only writer of it; `studio drop make` refuses
--    a pick without it) and the owner's Adjust (adjust: star, part, gadgets, hook, start_s, length_s, crop_x, each checked
--    here and again by the CLI). Then a GitHub repository_dispatch ('drop-process' / 'drop-make', client_payload.pick_id)
--    through net.http_post with the Vault token. The token never leaves the function: it is not returned, not raised, not
--    logged; any failure of the dispatch is swallowed (dispatched false) and the sweep picks the job up.
-- 4. v_tracker is re-created with every column of 0011, in the same order, and appended: `drop_card` (proposal.drop without
--    the job's internals: the deconstruct, the make record with its signed URL, the lease) and `make_requested_at`.
-- 5. set_drop_footage(pick_id, own_footage): the owner's toggle on a drop card (owner 2026-10-06, for the reporting of an income
--    campaign later): "own footage" (the owner's recording, or footage used with permission) versus "downloaded clip" (the
--    default, false). Security invoker (the owner's RLS applies), empty search_path; it changes nothing about the generation.

-- ---- 1. pg_net -------------------------------------------------------------------------------------------------------------

do $$
begin
  if exists (select 1 from pg_catalog.pg_available_extensions where name = 'pg_net')
     and not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_net') then
    create extension if not exists pg_net with schema extensions;
  end if;
end
$$;

-- ---- 2. add_drop -----------------------------------------------------------------------------------------------------------

create or replace function studio.add_drop(character_slug text, link text default null)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  f studio.favorites;
  new_id uuid;
  clean text := nullif(btrim(add_drop.link), '');
  plat text;
  handle text;
  rec jsonb := jsonb_build_object('decision', 'approve', 'by', 'owner', 'reason', 'owner''s own video', 'at', now());
  drop_ jsonb;
begin
  if not exists (select 1 from studio.characters ch where ch.slug = add_drop.character_slug) then
    raise exception 'unknown character %', add_drop.character_slug using errcode = 'invalid_parameter_value';
  end if;
  if clean is null then
    new_id := gen_random_uuid();
    drop_ := jsonb_build_object('state', 'uploading', 'kind', 'file', 'at', now(), 'reason', null, 'own_footage', false);
    insert into studio.favorites (id, url, platform, origin, character_slug, proposal, status)
    values (new_id, 'owner-drop:' || new_id::text, 'drop', 'owner', add_drop.character_slug,
            jsonb_build_object('decision', rec, 'drop', drop_), 'approved')
    returning * into f;
    return to_jsonb(f) || jsonb_build_object('duplicate', false);
  end if;
  plat := case
    when clean ~ '^https://www\.tiktok\.com/@[[:alnum:]_.-]+/video/[0-9]+$' then 'tiktok'
    when clean ~ '^https://www\.instagram\.com/reel/[[:alnum:]_-]+/$' then 'instagram'
    when clean ~ '^https://www\.youtube\.com/shorts/[[:alnum:]_-]+$' then 'youtube'
    when clean ~ '^https://www\.youtube\.com/watch\?v=[[:alnum:]_-]{11}$' then 'youtube'
  end;
  if plat is null then
    raise exception 'not a canonical TikTok, Instagram Reel or YouTube link: %', clean using errcode = 'invalid_parameter_value';
  end if;
  if plat = 'tiktok' then
    handle := '@' || substring(clean from '^https://www\.tiktok\.com/@([[:alnum:]_.-]+)/video/');
  end if;
  drop_ := jsonb_build_object('state', 'checking', 'kind', 'link', 'at', now(), 'reason', null, 'own_footage', false);
  select * into f from studio.favorites fa
   where fa.url = clean and fa.character_slug = add_drop.character_slug
   order by fa.created_at, fa.id limit 1 for update;
  if found then
    if f.status in ('queued', 'made') then
      return to_jsonb(f) || jsonb_build_object('duplicate', true);
    end if;
    update studio.favorites fa
       set status = 'approved',
           proposal = (fa.proposal - 'hold_reason') || jsonb_build_object('decision', rec, 'drop', drop_)
     where fa.id = f.id
    returning fa.* into f;
    return to_jsonb(f) || jsonb_build_object('duplicate', true);
  end if;
  insert into studio.favorites (url, platform, creator_handle, origin, character_slug, proposal, status)
  values (clean, plat, handle, 'owner', add_drop.character_slug, jsonb_build_object('decision', rec, 'drop', drop_), 'approved')
  returning * into f;
  return to_jsonb(f) || jsonb_build_object('duplicate', false);
end;
$$;

-- ---- 3. request_job ---------------------------------------------------------------------------------------------------------

create or replace function studio.request_job(pick_id uuid, kind text, adjust jsonb default null)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  f studio.favorites;
  d jsonb;
  state_ text;
  clean jsonb := '{}'::jsonb;
  k text;
  v jsonb;
  start_ double precision;
  length_ double precision;
  dur double precision;
  token text;
  dispatched boolean := false;
begin
  -- definer rights bypass RLS: the owner rule of every policy of this schema, checked here
  if coalesce((select auth.jwt() ->> 'email'), '') <> 'o.schwend@gmail.com' then
    raise exception 'only the owner may ask for a job' using errcode = 'insufficient_privilege';
  end if;
  if request_job.kind is null or request_job.kind not in ('process', 'make') then
    raise exception 'kind must be process or make, got %', request_job.kind using errcode = 'invalid_parameter_value';
  end if;
  select * into f from studio.favorites fa where fa.id = request_job.pick_id for update;
  if not found then
    raise exception 'unknown pick %', request_job.pick_id using errcode = 'no_data_found';
  end if;
  d := f.proposal -> 'drop';
  if d is null or jsonb_typeof(d) <> 'object' then
    raise exception 'pick % is not a dropped video', f.id using errcode = 'check_violation';
  end if;
  state_ := d ->> 'state';
  if f.status = 'made' then
    raise exception 'pick % is already made', f.id using errcode = 'check_violation';
  end if;

  if request_job.kind = 'process' then
    if state_ is null or state_ not in ('uploading', 'checking', 'waiting', 'failed') then
      raise exception 'a check runs on an uploading, checking, waiting or failed drop; this one is %', state_ using errcode = 'check_violation';
    end if;
    if state_ = 'uploading' and coalesce(f.proposal ->> 'owner_clip_path', '') = '' then
      raise exception 'the upload has not finished: attach the video first' using errcode = 'check_violation';
    end if;
    d := d || jsonb_build_object('state', 'checking', 'reason', null, 'at', now(),
                                 'requested', coalesce(d -> 'requested', '{}'::jsonb) || jsonb_build_object('process', now()));
    update studio.favorites fa set proposal = fa.proposal || jsonb_build_object('drop', d) where fa.id = f.id
    returning fa.* into f;
  else
    if state_ is null or state_ not in ('ready', 'failed') or not (d ? 'credits') or not (d ? 'source_id') then
      raise exception 'Make it needs a checked and priced drop (ready); this one is %', state_ using errcode = 'check_violation';
    end if;
    if request_job.adjust is not null and jsonb_typeof(request_job.adjust) <> 'null' then
      if jsonb_typeof(request_job.adjust) <> 'object' then
        raise exception 'adjust must be an object' using errcode = 'invalid_parameter_value';
      end if;
      for k, v in select e.key, e.value from jsonb_each(request_job.adjust) as e loop
        if k not in ('star', 'part', 'gadgets', 'hook', 'start_s', 'length_s', 'crop_x') then
          raise exception 'adjust has an unknown key %', k using errcode = 'invalid_parameter_value';
        end if;
        if k in ('star', 'hook') and (jsonb_typeof(v) <> 'string' or char_length(btrim(v #>> '{}')) not between 1 and 80
                                      or position(chr(10) in v #>> '{}') > 0) then
          raise exception 'adjust.% must be one line of 1-80 characters', k using errcode = 'invalid_parameter_value';
        end if;
        if k = 'part' and (jsonb_typeof(v) <> 'string' or v #>> '{}' not in ('cameo', 'featured', 'star')) then
          raise exception 'adjust.part must be cameo, featured or star' using errcode = 'invalid_parameter_value';
        end if;
        if k = 'gadgets' and (jsonb_typeof(v) <> 'array' or jsonb_array_length(v) > 3
                              or exists (select 1 from jsonb_array_elements(v) g(x)
                                         where jsonb_typeof(g.x) <> 'string' or char_length(btrim(g.x #>> '{}')) not between 1 and 40)) then
          raise exception 'adjust.gadgets takes at most 3 items of 1-40 characters' using errcode = 'invalid_parameter_value';
        end if;
        if k in ('start_s', 'length_s') and jsonb_typeof(v) <> 'number' then
          raise exception 'adjust.% must be a number', k using errcode = 'invalid_parameter_value';
        end if;
        if k = 'crop_x' and not (jsonb_typeof(v) = 'null' or (jsonb_typeof(v) = 'number' and (v #>> '{}')::double precision between 0 and 1)) then
          raise exception 'adjust.crop_x must be from 0 to 1, or null' using errcode = 'invalid_parameter_value';
        end if;
      end loop;
      if request_job.adjust ? 'start_s' or request_job.adjust ? 'length_s' then
        start_ := coalesce((request_job.adjust ->> 'start_s')::double precision, (d #>> '{window,start_s}')::double precision, 0);
        length_ := coalesce((request_job.adjust ->> 'length_s')::double precision, (d #>> '{window,length_s}')::double precision, 0);
        dur := (d ->> 'duration_s')::double precision;
        if start_ < 0 or length_ < 6 or length_ > 16 then
          raise exception 'the section must start at 0 s or later and last 6-16 s' using errcode = 'invalid_parameter_value';
        end if;
        if dur is not null and start_ + length_ > dur + 0.15 then
          raise exception 'the section runs past the end of the % s video', round(dur::numeric, 1) using errcode = 'invalid_parameter_value';
        end if;
      end if;
      clean := request_job.adjust;
    end if;
    d := (d - 'adjust') || jsonb_build_object('state', 'making', 'reason', null, 'at', now(),
                                              'requested', coalesce(d -> 'requested', '{}'::jsonb) || jsonb_build_object('make', now()));
    if clean <> '{}'::jsonb then
      d := d || jsonb_build_object('adjust', clean);
    end if;
    update studio.favorites fa
       set proposal = fa.proposal || jsonb_build_object('drop', d, 'make_requested', jsonb_build_object('at', now(), 'by', 'owner'))
     where fa.id = f.id
    returning fa.* into f;
  end if;

  -- the GitHub dispatch: its own block, so a failure rolls back nothing above and never shows the token
  begin
    if to_regclass('vault.decrypted_secrets') is not null
       and exists (select 1 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid = p.pronamespace
                   where n.nspname = 'net' and p.proname = 'http_post') then
      select s.decrypted_secret into token from vault.decrypted_secrets s where s.name = 'github_dispatch_token' limit 1;
      if coalesce(token, '') <> '' then
        perform net.http_post(
          url := 'https://api.github.com/repos/oschwend-prog/character-studio/dispatches',
          body := jsonb_build_object('event_type', 'drop-' || request_job.kind,
                                     'client_payload', jsonb_build_object('pick_id', f.id::text)),
          headers := jsonb_build_object('Authorization', 'Bearer ' || token, 'Accept', 'application/vnd.github+json',
                                        'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'odd-eyes-studio',
                                        'Content-Type', 'application/json'),
          timeout_milliseconds := 5000
        );
        dispatched := true;
      end if;
    end if;
  exception when others then
    dispatched := false;
  end;
  token := null;
  return to_jsonb(f) || jsonb_build_object('dispatched', dispatched);
end;
$$;

-- ---- 5. set_drop_footage ------------------------------------------------------------------------------------------------------

create or replace function studio.set_drop_footage(pick_id uuid, own_footage boolean)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  f studio.favorites;
begin
  if set_drop_footage.own_footage is null then
    raise exception 'own_footage must be true or false' using errcode = 'invalid_parameter_value';
  end if;
  select * into f from studio.favorites fa where fa.id = set_drop_footage.pick_id for update;
  if not found then
    raise exception 'unknown pick %', set_drop_footage.pick_id using errcode = 'no_data_found';
  end if;
  if jsonb_typeof(f.proposal -> 'drop') is distinct from 'object' then
    raise exception 'pick % is not a dropped video', f.id using errcode = 'check_violation';
  end if;
  update studio.favorites fa
     set proposal = jsonb_set(fa.proposal, '{drop,own_footage}', to_jsonb(set_drop_footage.own_footage))
   where fa.id = f.id
  returning fa.* into f;
  return to_jsonb(f);
end;
$$;

-- ---- 4. v_tracker (0011's columns, then the drop) ----------------------------------------------------------------------------

create or replace view studio.v_tracker with (security_invoker = true) as
select
  f.id as pick_id,
  f.character_slug,
  ch.name as character_name,
  f.url,
  f.platform,
  f.creator_handle,
  f.views,
  f.outlier_x,
  f.proposal ->> 'tier' as tier,
  f.proposal ->> 'theme' as theme,
  f.proposal ->> 'concept' as concept,
  f.proposal ->> 'hook' as hook,
  f.proposal ->> 'thumbnail_url' as thumbnail_url,
  f.proposal ->> 'preview_url' as preview_url,
  coalesce(f.proposal ->> 'source_kind' = 'higgsfield_library' or coalesce(btrim(f.proposal ->> 'preset_id'), '') <> '', false) as gallery,
  f.proposal ->> 'posted_at' as posted_at,
  studio.num(f.proposal -> 'velocity') as velocity,
  f.proposal ->> 'mode' as proposed_mode,
  f.proposal ->> 'owner_mode' as owner_mode,
  f.proposal ->> 'owner_presence' as owner_presence,
  f.proposal ->> 'owner_music' as owner_music,
  f.proposal ->> 'owner_clip_path' as owner_clip_path,
  f.status,
  f.proposal -> 'decision' as decision,
  coalesce(da.decided_at, f.created_at) as approved_at,
  f.note,
  f.source_id,
  f.proposal -> 'analysis' as analysis,
  f.proposal -> 'fetch_failed' as fetch_failed,
  c.id as clip_id,
  c.state as clip_state,
  c.mode as clip_mode,
  greatest(c.created_at, cl.last_entry, cp.last_claim) as clip_state_since,
  coalesce(nullif(btrim(c.reject_reason), ''), qp.problems, nullif(btrim(c.qa ->> 'error'), '')) as clip_failure,
  coalesce(sp.spent, 0) as credits_spent,
  p.id as post_id,
  p.status as post_status,
  p.scheduled_for as post_scheduled_for,
  case when p.status = 'posted' then coalesce(p.claimed_at, p.scheduled_for) end as post_posted_at,
  p.url as post_url,
  p.error as post_error,
  sn.views as latest_views,
  c.caption,
  c.hashtags,
  c.features ->> 'first_comment' as first_comment,
  da.decided_at as decided_at,
  case when jsonb_typeof(f.proposal -> 'drop') = 'object' then (f.proposal -> 'drop') - 'deconstruct' - 'make' - 'job' end as drop_card,
  f.proposal #>> '{make_requested,at}' as make_requested_at
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
cross join lateral (select f.proposal #>> '{decision,at}' as decided) dt
cross join lateral (
  select case
    when dt.decided ~ '^[12][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?(Z|[+-]([01][0-9]|1[0-4]):[0-5][0-9])$'
      then case
        when substr(dt.decided, 9, 2)::int
             <= extract(day from make_date(substr(dt.decided, 1, 4)::int, substr(dt.decided, 6, 2)::int, 1) + interval '1 month' - interval '1 day')
          then dt.decided::timestamptz
      end
  end as decided_at
) da
left join lateral (
  select x.id, x.state, x.mode, x.created_at, x.reject_reason, x.qa, x.caption, x.hashtags, x.features
  from studio.clips x
  where x.id = f.clip_id or x.features ->> 'fav_id' = f.id::text
  order by x.created_at desc, x.id desc
  limit 1
) c on true
left join lateral (
  select max(l.created_at) as last_entry from studio.ledger l where l.clip_id = c.id
) cl on true
left join lateral (
  select max(q.claimed_at) as last_claim from studio.posts q where q.clip_id = c.id
) cp on true
left join lateral (
  select string_agg(e.problem, ' / ') as problems
  from jsonb_array_elements_text(
    case when jsonb_typeof(c.qa -> 'problems') = 'array' then c.qa -> 'problems' else '[]'::jsonb end
  ) as e(problem)
) qp on true
left join lateral (
  select sum(l.credits) as spent
  from studio.ledger l
  join studio.clips y on y.id = l.clip_id
  where l.kind = 'settle' and (y.id = f.clip_id or y.features ->> 'fav_id' = f.id::text)
) sp on true
left join lateral (
  select q.id, q.status, q.scheduled_for, q.claimed_at, q.url, q.error
  from studio.posts q
  where q.clip_id = c.id
  order by q.scheduled_for desc,
           case q.status when 'failed' then 0 when 'needs_check' then 1 when 'posting' then 2 when 'scheduled' then 3 else 4 end,
           q.id
  limit 1
) p on true
left join lateral (
  select s.views from studio.snapshots s where s.post_id = p.id order by s.captured_at desc limit 1
) sn on true
where f.status in ('approved', 'analysed', 'queued')
   or (f.status = 'made'
       and not coalesce(p.status = 'posted' and coalesce(p.claimed_at, p.scheduled_for) < now() - interval '7 days', false));

-- ---- grants ------------------------------------------------------------------------------------------------------------------

revoke all on function studio.add_drop(text, text) from public;
grant execute on function studio.add_drop(text, text) to authenticated;
revoke all on function studio.set_drop_footage(uuid, boolean) from public;
grant execute on function studio.set_drop_footage(uuid, boolean) to authenticated;
revoke all on function studio.request_job(uuid, text, jsonb) from public;
grant execute on function studio.request_job(uuid, text, jsonb) to authenticated;
do $$
begin
  -- definer rights: no API role but the signed-in owner may even call it (its own check refuses everyone else too)
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'anon') then
    execute 'revoke all on function studio.request_job(uuid, text, jsonb) from anon';
  end if;
end
$$;
grant select on studio.v_tracker to authenticated;
