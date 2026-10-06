-- ODD EYES Character Studio, migration 0013: the character of a dropped video (owner 2026-10-06: the core of the terminal is
-- putting our characters into his saved videos; one table of his drops, a character menu per row with the studio's
-- recommendation, and a drop needs no character to start with).
--
-- Additive / replacing only, schema studio only. To be applied to Supabase project hkcafvzjwkeibbmvskko ("faceless-youtube") as
-- migration `studio_0013_drop_character`, AFTER 0012; the controller (or the owner) applies it, it is never run from the studio
-- CLI. Apply it BEFORE the terminal that drops a video without a character, or calls set_drop_character, is deployed.
--
-- 1. add_drop(character_slug, link): the character is optional now ("Recommend", the Drop box's default). A drop filed without
--    one goes under a provisional character: the first one not paused (by slug) who replaces a person (his seeded swap rule,
--    setup.swap.stars, when the seed wrote one; else a character drawn only on two legs), with drop.character_by = 'studio'.
--    The free check (studio drop process) recommends the character for the clip and, while the choice is the studio's, moves
--    the drop to him and looks once more in his voice (Gemini only: nothing is paid before Make it). A drop filed with a
--    character records character_by = 'owner', which the studio never overrides. A link filed without a character is matched
--    against every pick of that URL (the oldest), not one character's, and keeps that pick's character while he is not paused.
--    Everything else is 0012's: the file key, the canonical links, the TikTok handle, the duplicate rule, own_footage false.
-- 2. set_drop_character(pick_id, character_slug): the owner's menu on a row of the drops table. SECURITY DEFINER (it starts the
--    check through request_job, which reads the Vault) with a fixed empty search_path, schema-qualified names and 0012's owner
--    check first. Allowed while the drop is uploading, checking, waiting, ready, blocked or failed and the pick is neither
--    queued nor made; the character must exist and not be paused. It sets favorites.character_slug and
--    drop.character_by = 'owner', clears what the old check worked out for the old character (the hooks and the hook, his
--    part, the gadgets, the window, the seconds, the price, the deconstruct with its caption, the Adjust; the pick's hook and
--    the owner's Make it of the other character), keeps what does not depend on him (the source, the star, the preview, the
--    recommendation, own_footage), and asks for the check again: state 'checking', then studio.request_job(pick, 'process'),
--    which records requested.process and dispatches drop-process exactly as the Checking button does (the token never leaves
--    request_job; its result, with `dispatched`, is returned). An upload whose file is not attached yet stays 'uploading': the
--    upload's own request_job starts the check. The same character again only records it as the owner's choice.
-- 3. v_tracker is not touched: its drop_card (proposal.drop without the job's internals) already carries the check's
--    drop.recommended ({slug, reason}) and drop.character_by.

-- ---- 1. add_drop -----------------------------------------------------------------------------------------------------------

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
    select ch.slug into slug_
      from studio.characters ch
     where ch.status <> 'paused'
     order by case when jsonb_typeof(ch.setup #> '{swap,stars}') = 'array' then (ch.setup #> '{swap,stars}') ? 'person'
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

-- ---- 2. set_drop_character --------------------------------------------------------------------------------------------------

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

  -- what the old check worked out for the old character goes; the source, the star, the preview and the recommendation stay
  d := (d - 'hooks' - 'hook' - 'part' - 'gadgets' - 'window' - 'seconds' - 'credits' - 'deconstruct' - 'adjust')
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

-- ---- grants ------------------------------------------------------------------------------------------------------------------

revoke all on function studio.add_drop(text, text) from public;
grant execute on function studio.add_drop(text, text) to authenticated;
revoke all on function studio.set_drop_character(uuid, text) from public;
grant execute on function studio.set_drop_character(uuid, text) to authenticated;
do $$
begin
  -- definer rights: no API role but the signed-in owner may even call it (its own check refuses everyone else too)
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'anon') then
    execute 'revoke all on function studio.set_drop_character(uuid, text) from anon';
  end if;
end
$$;
