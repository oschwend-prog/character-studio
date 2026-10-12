-- ODD EYES Character Studio, migration 0017: add_drop merges the earlier drop on a duplicate (terminal v3, task 14, item 4).
--
-- WHY. Dropping a link that is already a pick of that character (or, for "Recommend", of any character) files the same pick
-- again as a fresh drop. 0012/0013/0015's add_drop did that by replacing `proposal.drop` wholesale
-- (`jsonb_build_object('decision', rec, 'drop', drop_)`), so everything the earlier drop had worked out or been given (the
-- check's hooks, window and deconstruct, the owner's Adjust, the make request, the recommendation, ...) was lost. Now the earlier
-- drop's keys stay and the new drop's keys win: `proposal.drop = old drop || drop_`. The new drop still sets state 'checking',
-- kind, at, reason null, own_footage false and character_by, so the duplicate is checked again exactly as before; only the keys
-- the new drop does not mention survive. A `drop` that is missing or not an object is treated as empty (jsonb 'null' || object
-- would make an array).
--
-- Additive / replacing only, schema studio only: ONE function, `create or replace` with the signature, the language, the
-- security (invoker, empty search_path) and the grants of 0015's add_drop (the latest definition: 0013's was re-created there);
-- the body is 0015's word for word except the one `update` in the duplicate branch. To be applied to Supabase project
-- hkcafvzjwkeibbmvskko ("faceless-youtube", shared with another app) as migration `studio_0017_add_drop_merge`, AFTER 0016; the
-- controller (or the owner) applies it, it is never run from the studio CLI. Re-run safe: `create or replace` with an unchanged
-- signature, and the grants may repeat.
--
-- TO UNDO: re-run the add_drop section of 0015 (create or replace puts it back).

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
           -- the earlier drop's keys stay (hooks, window, the owner's Adjust, ...), the new keys win; a drop that is not an object
           -- (never written by the studio) is replaced, not merged: jsonb 'null' || object would make an array
           proposal = (fa.proposal - 'hold_reason') || jsonb_build_object('decision', rec, 'drop',
                        (case when jsonb_typeof(fa.proposal -> 'drop') = 'object' then fa.proposal -> 'drop' else '{}'::jsonb end) || drop_)
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

-- ---- grants ------------------------------------------------------------------------------------------------------------------

revoke all on function studio.add_drop(text, text) from public;
grant execute on function studio.add_drop(text, text) to authenticated;
