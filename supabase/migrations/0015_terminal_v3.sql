-- ODD EYES Character Studio, migration 0015: terminal v3 (spec docs/superpowers/specs/2026-10-07-terminal-v3-design.md,
-- sections 4 and 7; plan docs/superpowers/plans/2026-10-07-terminal-v3.md, task 3): one clip for up to three characters
-- (studio.copy_drop), a family's posts two weeks apart (studio.free_slot), and the views per day (studio.v_views_daily).
--
-- WHY. The owner uses one saved clip for up to three characters (owner 2026-10-07: "we could even use our clips for various
-- characters"). The CLI files such a version with `studio drop copy` (studio.drop.copy_drop); the terminal's "Use for another
-- character" needs the same step as an RPC, with the same rules and the same plain refusal lines. A family's posts must stay two
-- weeks apart however a clip is scheduled: the Python scheduler keeps them apart (planning.family_days), so the terminal's
-- approve (approve_clip -> free_slot) must too. The studio-at-a-glance block shows views per day: the snapshots hold each post's
-- running totals, the view turns them into what each day added.
--
-- Additive / replacing only, schema studio only. To be applied to Supabase project hkcafvzjwkeibbmvskko ("faceless-youtube",
-- shared with another app) as migration `studio_0015_terminal_v3`, AFTER 0014; the controller (or the owner) applies it, it is
-- never run from the studio CLI. Apply it BEFORE the terminal that calls copy_drop or reads v_views_daily is deployed.
-- Re-run safe: every object is `create or replace` with an unchanged signature or column list, and every grant and revoke may
-- repeat.
--
-- 1. family_root_id(proposal, pick_id): the pick id of a drop's family root, as studio.favorites.family_root_id: drop.copy_of
--    when it is a non-empty string, else the pick itself. Text, so a malformed copy_of finds no root instead of failing a cast.
-- 2. family_days(clip_id): the London days the clip may not be posted on because of its family, as planning.family_days. The
--    clip's pick (its features.fav_id, else the oldest pick that names the clip), the family's picks whatever their status (a
--    skipped member's posts still count: a post is a post), their clips (a member's clip_id, or a clip whose features.fav_id is
--    a member), the clip itself left out. Every post of those clips in scheduled / posting / posted / needs_check, on ANY
--    account, dated by claimed_at else scheduled_for in London, takes that day and the 13 days either side (FAMILY_GAP_DAYS
--    14). A clip of no family (fewer than 2 members) or an unknown clip has none.
-- 3. free_slot (0006's, signature unchanged, word for word plus one step): the clip being scheduled (exclude_clip_id) also
--    skips its family's days, so next_free_slot, v_queue's next_slot and approve_clip's default slot keep a family's posts 14
--    days apart, in parity with planning.free_slot fed taken_days | family_days (`studio clip schedule`). An explicit
--    schedule_at given to approve_clip stays the owner's choice.
-- 4. copy_drop(pick_id, character_slug): the owner's "Use for another character". SECURITY DEFINER (it starts the check
--    through request_job, which reads the Vault), empty search_path, schema-qualified names, and request_job's owner check
--    first. pick_id is the root drop or any version of it: the version always points at the ROOT. The root row is locked
--    (for update) before the family is counted, so two taps cannot make a 4th member (nor one character twice). Refused,
--    nothing written, one plain line each, in the CLI's order and words (studio.drop.copy_drop): the original clip is gone;
--    asked from a version's card, "the original clip can't be used any more" (the root blocked or failed) or "the original
--    clip is being checked again: try in a few minutes" (uploading, checking, waiting); "the clip is not checked yet" (the
--    root not ready, making or made, or no source); "the clip's file is gone (deleted after posting): drop it again" (the
--    source has no storage_path); "unknown character '<slug>'"; "<Name> already has a version of this clip"; "a clip goes to
--    at most 3 characters" (MAX_FAMILY; skipped picks do not count); "<Name> is paused"; like for like (drop.like_for_like's
--    lines: the root's star kind against coalesce(setup.stars, setup.swap.stars), setup.stars being the seed's copy of
--    refs.json swap.stars, then its body against characters.bodies). Then the version is filed as the CLI files it: url owner-drop:<new id>, platform drop,
--    origin owner, approved, his character, the root's source_id and creator_handle, the root's fetched marker without
--    purged_at, and drop {state checking, the root's kind and own_footage, character_by owner, copy_of = the root,
--    requested.process}; studio.request_job(<new id>, 'process') then records requested.process and dispatches drop-process
--    exactly as the Checking button does (the token never leaves request_job). Returns {"pick_id": <new id>, "dispatched"}.
-- 5. set_drop_character (0013's, word for word but two changes): the drop it sends back to checking also loses its `score`
--    (no stale score survives a change of character, by hand included), and a character the family already has is refused
--    ("<Name> already has a version of this clip"), after the family's root row is locked as copy_drop locks it.
-- 6. add_drop (0013's, word for word but one expression): the provisional character of a drop filed without one reads who he
--    replaces from coalesce(setup.stars, setup.swap.stars). 0013 read setup.swap.stars only, a key the seed never writes (it
--    writes setup.stars), so the choice fell back to the bodies and picked Lenny where studio.drop.provisional picks Franz (the
--    first by slug who replaces a person). Now both pick the same character.
-- 7. v_views_daily(character_slug, day, views, follows): per London day, the views and follows each character's posts
--    gained: for each post and each London day it was measured, its latest snapshot of that day minus its latest snapshot
--    before that day (0 before its first; a snapshot without the number is skipped for that number), summed over the
--    character's posts (the posts joined to their clips). A day nobody measured follows on counts 0 follows. Running as the
--    caller (security_invoker) and readable by the terminal's role, exactly like v_library.
-- 8. Grants: every function revoked from public and granted to authenticated; the two definers also revoked from anon where
--    the role exists (their own owner check refuses everyone else too); v_views_daily granted to authenticated.
--
-- TO UNDO (in this order): re-run the free_slot section of 0006 and the add_drop and set_drop_character sections of 0013
-- (create or replace puts them back), then
--   drop view studio.v_views_daily;
--   drop function studio.copy_drop(uuid, text);
--   drop function studio.family_days(uuid);
--   drop function studio.family_root_id(jsonb, uuid);
-- The versions already filed stay as ordinary drops (their copy_of is then only data).

-- ---- 1. family_root_id -----------------------------------------------------------------------------------------------------

create or replace function studio.family_root_id(proposal jsonb, pick_id uuid)
returns text
language sql
immutable
security invoker
set search_path = ''
as $$
  select case
    when jsonb_typeof(family_root_id.proposal #> '{drop,copy_of}') = 'string'
         and family_root_id.proposal #>> '{drop,copy_of}' <> ''
      then family_root_id.proposal #>> '{drop,copy_of}'
    else family_root_id.pick_id::text
  end
$$;

-- ---- 2. family_days --------------------------------------------------------------------------------------------------------

create or replace function studio.family_days(clip_id uuid)
returns date[]
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  c studio.clips;
  pick studio.favorites;
  root_ text;
  members text[];
  days date[];
begin
  select * into c from studio.clips cl where cl.id = family_days.clip_id;
  if not found then
    return '{}'::date[];
  end if;
  -- the clip's pick: its features.fav_id, else the oldest pick that names the clip
  if jsonb_typeof(c.features -> 'fav_id') = 'string' then
    select * into pick from studio.favorites fa where fa.id::text = c.features ->> 'fav_id';
  end if;
  if pick.id is null then
    select * into pick from studio.favorites fa where fa.clip_id = c.id order by fa.created_at, fa.id limit 1;
  end if;
  if pick.id is null then
    return '{}'::date[];
  end if;
  -- the family, whatever the status of its members (a skipped member's posts still count: a post is a post)
  root_ := studio.family_root_id(pick.proposal, pick.id);
  select array_agg(fa.id::text) into members
    from studio.favorites fa
   where studio.family_root_id(fa.proposal, fa.id) = root_;
  if coalesce(cardinality(members), 0) < 2 then
    return '{}'::date[];
  end if;
  -- every post of another clip of the family that holds a day, on ANY account: that London day and the 13 days either side
  select coalesce(array_agg(distinct t.day + k.n order by t.day + k.n), '{}'::date[]) into days
    from (
      select (coalesce(p.claimed_at, p.scheduled_for) at time zone 'Europe/London')::date as day
        from studio.posts p
       where p.status in ('scheduled', 'posting', 'posted', 'needs_check')
         and p.clip_id <> c.id
         and (p.clip_id in (select fa.clip_id from studio.favorites fa where fa.id::text = any (members) and fa.clip_id is not null)
              or p.clip_id in (select cl.id from studio.clips cl where cl.features ->> 'fav_id' = any (members)))
    ) t
    cross join generate_series(-13, 13) as k(n);
  return days;
end;
$$;

-- ---- 3. free_slot ----------------------------------------------------------------------------------------------------------

create or replace function studio.free_slot(
  character_slug text,
  target_accounts uuid[],
  exclude_clip_id uuid default null,
  after_ts timestamptz default now()
)
returns timestamptz
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  entry jsonb;
  slot text;
  days text[];
  first_day date;
  taken date[];
  d date;
begin
  -- the first slot strictly after after_ts; raises like upcoming_slot for a missing slot or no cadence days
  first_day := (studio.upcoming_slot(free_slot.character_slug, free_slot.after_ts) at time zone 'Europe/London')::date;
  select st.cadence -> free_slot.character_slug into entry from studio.settings st where st.id = 1;
  slot := entry ->> 'slot';
  days := studio.cadence_days(entry);

  select coalesce(array_agg(distinct (coalesce(p.claimed_at, p.scheduled_for) at time zone 'Europe/London')::date), '{}'::date[])
    into taken
    from studio.posts p
   where p.account_id = any (coalesce(free_slot.target_accounts, '{}'::uuid[]))
     and p.status in ('scheduled', 'posting', 'posted', 'needs_check')
     and (free_slot.exclude_clip_id is null or p.clip_id <> free_slot.exclude_clip_id);

  -- the clip's family (terminal v3): no day within 13 days of another family member's post, on any account
  if free_slot.exclude_clip_id is not null then
    taken := taken || studio.family_days(free_slot.exclude_clip_id);
  end if;

  for i in 0..55 loop
    d := first_day + i;
    if (array['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])[extract(isodow from d)::int] = any (days)
       and not (d = any (taken)) then
      return (d + slot::time) at time zone 'Europe/London';
    end if;
  end loop;
  raise exception 'no free posting day for % in the next 56 days', free_slot.character_slug
    using errcode = 'check_violation';
end;
$$;

-- ---- 4. copy_drop ----------------------------------------------------------------------------------------------------------

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
  insert into studio.favorites (id, url, platform, origin, character_slug, creator_handle, proposal, status, source_id)
  values (new_id, 'owner-drop:' || new_id::text, 'drop', 'owner', ch.slug, root.creator_handle, proposal_, 'approved', source_::uuid);

  -- the check, as the Checking button asks for it: request_job records requested.process and dispatches drop-process (the token
  -- never leaves request_job)
  sent := studio.request_job(new_id, 'process');
  return jsonb_build_object('pick_id', new_id, 'dispatched', coalesce((sent ->> 'dispatched')::boolean, false));
end;
$$;

-- ---- 5. set_drop_character -------------------------------------------------------------------------------------------------

create or replace function studio.set_drop_character(pick_id uuid, character_slug text)
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
  slug_ text := nullif(btrim(set_drop_character.character_slug), '');
  root_ text;
  name_ text;
begin
  -- definer rights bypass RLS: the owner rule of every policy of this schema, checked here (as request_job does)
  if coalesce((select auth.jwt() ->> 'email'), '') <> 'o.schwend@gmail.com' then
    raise exception 'only the owner may choose the character' using errcode = 'insufficient_privilege';
  end if;
  if slug_ is null or not exists (select 1 from studio.characters ch where ch.slug = slug_) then
    raise exception 'unknown character %', coalesce(slug_, '(none)') using errcode = 'invalid_parameter_value';
  end if;
  if exists (select 1 from studio.characters ch where ch.slug = slug_ and ch.status = 'paused') then
    raise exception '% is paused: he takes no new videos', slug_ using errcode = 'invalid_parameter_value';
  end if;
  select * into f from studio.favorites fa where fa.id = set_drop_character.pick_id for update;
  if not found then
    raise exception 'unknown pick %', set_drop_character.pick_id using errcode = 'no_data_found';
  end if;
  d := f.proposal -> 'drop';
  if d is null or jsonb_typeof(d) <> 'object' then
    raise exception 'pick % is not a dropped video', f.id using errcode = 'check_violation';
  end if;
  state_ := d ->> 'state';
  if f.status in ('queued', 'made') then
    raise exception 'pick % is already %: its character is settled', f.id, f.status using errcode = 'check_violation';
  end if;
  if state_ is null or state_ not in ('uploading', 'checking', 'waiting', 'ready', 'blocked', 'failed') then
    raise exception 'the character changes before Make it (uploading, checking, waiting, ready, blocked or failed); this one is %', state_
      using errcode = 'check_violation';
  end if;

  if f.character_slug is not distinct from slug_ then
    -- the same character: recorded as the owner's choice (the studio never moves it again), nothing is checked again
    update studio.favorites fa
       set proposal = jsonb_set(fa.proposal, '{drop,character_by}', to_jsonb('owner'::text))
     where fa.id = f.id
    returning fa.* into f;
    return to_jsonb(f) || jsonb_build_object('dispatched', false);
  end if;

  -- a family has each character once (terminal v3): the family's root row is locked first, as copy_drop locks it, so a copy
  -- and a change of character cannot both give the family the same character; skipped picks are no members
  root_ := studio.family_root_id(f.proposal, f.id);
  perform 1 from studio.favorites fa where fa.id::text = root_ for update;
  if exists (select 1 from studio.favorites fa
              where fa.id <> f.id and fa.status <> 'skipped' and fa.character_slug = slug_
                and studio.family_root_id(fa.proposal, fa.id) = root_) then
    select ch.name into name_ from studio.characters ch where ch.slug = slug_;
    raise exception '% already has a version of this clip', name_ using errcode = 'check_violation';
  end if;

  -- what the old check worked out for the old character goes (its score too); the source, the star, the preview and the recommendation stay
  d := (d - 'hooks' - 'hook' - 'part' - 'gadgets' - 'window' - 'seconds' - 'credits' - 'deconstruct' - 'adjust' - 'score')
       || jsonb_build_object('character_by', 'owner');
  if state_ <> 'uploading' or coalesce(f.proposal ->> 'owner_clip_path', '') <> '' then
    d := d || jsonb_build_object('state', 'checking', 'reason', null, 'at', now());
  end if;
  update studio.favorites fa
     set character_slug = slug_,
         proposal = (fa.proposal - 'hook' - 'make_requested') || jsonb_build_object('drop', d)
   where fa.id = f.id
  returning fa.* into f;
  if d ->> 'state' = 'uploading' then
    return to_jsonb(f) || jsonb_build_object('dispatched', false);  -- the upload's own request_job starts the check
  end if;
  -- the check again, as the Checking button asks for it: request_job records requested.process and dispatches drop-process
  return studio.request_job(f.id, 'process');
end;
$$;

-- ---- 6. add_drop -----------------------------------------------------------------------------------------------------------

create or replace function studio.add_drop(character_slug text default null, link text default null)
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
  slug_ text := nullif(btrim(add_drop.character_slug), '');
  by_ text := 'owner';
  plat text;
  handle text;
  rec jsonb := jsonb_build_object('decision', 'approve', 'by', 'owner', 'reason', 'owner''s own video', 'at', now());
  drop_ jsonb;
begin
  if slug_ is null then
    -- "Recommend": a provisional character until the check recommends one (a person is the likelier star; the check moves it)
    -- (who he replaces: setup.stars, as the seed writes it since terminal v3; setup.swap.stars, the key 0013 read, still counts)
    select ch.slug into slug_
      from studio.characters ch
     where ch.status <> 'paused'
     order by case when jsonb_typeof(coalesce(ch.setup -> 'stars', ch.setup -> 'swap' -> 'stars')) = 'array'
                   then coalesce(ch.setup -> 'stars', ch.setup -> 'swap' -> 'stars') ? 'person'
                   else 'biped' = any (ch.bodies) and not 'quadruped' = any (ch.bodies) end desc nulls last,
              ch.slug
     limit 1;
    if slug_ is null then
      raise exception 'no character takes new videos: every one is paused' using errcode = 'invalid_parameter_value';
    end if;
    by_ := 'studio';
  elsif not exists (select 1 from studio.characters ch where ch.slug = slug_) then
    raise exception 'unknown character %', slug_ using errcode = 'invalid_parameter_value';
  end if;
  if clean is null then
    new_id := gen_random_uuid();
    drop_ := jsonb_build_object('state', 'uploading', 'kind', 'file', 'at', now(), 'reason', null, 'own_footage', false,
                                'character_by', by_);
    insert into studio.favorites (id, url, platform, origin, character_slug, proposal, status)
    values (new_id, 'owner-drop:' || new_id::text, 'drop', 'owner', slug_,
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
  drop_ := jsonb_build_object('state', 'checking', 'kind', 'link', 'at', now(), 'reason', null, 'own_footage', false,
                              'character_by', by_);
  select * into f from studio.favorites fa
   where fa.url = clean and (by_ = 'studio' or fa.character_slug = slug_)
   order by fa.created_at, fa.id limit 1 for update;
  if found then
    if f.status in ('queued', 'made') then
      return to_jsonb(f) || jsonb_build_object('duplicate', true);
    end if;
    if by_ = 'studio' and exists (select 1 from studio.characters ch where ch.slug = f.character_slug and ch.status <> 'paused') then
      slug_ := f.character_slug;  -- the pick's own character is the provisional one while he is not paused
    end if;
    update studio.favorites fa
       set status = 'approved',
           character_slug = slug_,
           proposal = (fa.proposal - 'hold_reason') || jsonb_build_object('decision', rec, 'drop', drop_)
     where fa.id = f.id
    returning fa.* into f;
    return to_jsonb(f) || jsonb_build_object('duplicate', true);
  end if;
  insert into studio.favorites (url, platform, creator_handle, origin, character_slug, proposal, status)
  values (clean, plat, handle, 'owner', slug_, jsonb_build_object('decision', rec, 'drop', drop_), 'approved')
  returning * into f;
  return to_jsonb(f) || jsonb_build_object('duplicate', false);
end;
$$;

-- ---- 7. v_views_daily ------------------------------------------------------------------------------------------------------

create or replace view studio.v_views_daily with (security_invoker = true) as
select
  c.character_slug,
  g.day,
  coalesce(sum(g.views), 0)::bigint as views,
  coalesce(sum(g.follows), 0)::bigint as follows
from (
  select
    m.post_id,
    m.day,
    views_end.views - coalesce(views_before.views, 0) as views,
    follows_end.follows - coalesce(follows_before.follows, 0) as follows
  from (
    select distinct s.post_id, (s.captured_at at time zone 'Europe/London')::date as day
    from studio.snapshots s
  ) m
  cross join lateral (
    select (m.day::timestamp at time zone 'Europe/London') as starts,
           ((m.day + 1)::timestamp at time zone 'Europe/London') as ends
  ) b
  left join lateral (
    select s.views from studio.snapshots s
    where s.post_id = m.post_id and s.captured_at >= b.starts and s.captured_at < b.ends and s.views is not null
    order by s.captured_at desc limit 1
  ) views_end on true
  left join lateral (
    select s.views from studio.snapshots s
    where s.post_id = m.post_id and s.captured_at < b.starts and s.views is not null
    order by s.captured_at desc limit 1
  ) views_before on true
  left join lateral (
    select s.follows from studio.snapshots s
    where s.post_id = m.post_id and s.captured_at >= b.starts and s.captured_at < b.ends and s.follows is not null
    order by s.captured_at desc limit 1
  ) follows_end on true
  left join lateral (
    select s.follows from studio.snapshots s
    where s.post_id = m.post_id and s.captured_at < b.starts and s.follows is not null
    order by s.captured_at desc limit 1
  ) follows_before on true
) g
join studio.posts p on p.id = g.post_id
join studio.clips c on c.id = p.clip_id
group by c.character_slug, g.day;

-- ---- 8. grants -------------------------------------------------------------------------------------------------------------

revoke all on function studio.family_root_id(jsonb, uuid) from public;
grant execute on function studio.family_root_id(jsonb, uuid) to authenticated;
revoke all on function studio.family_days(uuid) from public;
grant execute on function studio.family_days(uuid) to authenticated;
revoke all on function studio.free_slot(text, uuid[], uuid, timestamptz) from public;
grant execute on function studio.free_slot(text, uuid[], uuid, timestamptz) to authenticated;
revoke all on function studio.copy_drop(uuid, text) from public;
grant execute on function studio.copy_drop(uuid, text) to authenticated;
revoke all on function studio.set_drop_character(uuid, text) from public;
grant execute on function studio.set_drop_character(uuid, text) to authenticated;
revoke all on function studio.add_drop(text, text) from public;
grant execute on function studio.add_drop(text, text) to authenticated;
do $$
begin
  -- definer rights: no API role but the signed-in owner may even call them (their own check refuses everyone else too)
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'anon') then
    execute 'revoke all on function studio.copy_drop(uuid, text) from anon';
    execute 'revoke all on function studio.set_drop_character(uuid, text) from anon';
  end if;
end
$$;
grant select on studio.v_views_daily to authenticated;
