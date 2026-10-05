-- ODD EYES Character Studio, migration 0008: Drop-in first (owner decisions 2026-10-05).
--
-- Additive / replacing only, schema studio only (plus two policies on storage.objects for the owner's own
-- uploads). To be applied to Supabase project hkcafvzjwkeibbmvskko ("faceless-youtube") as migration
-- `studio_0008_dropin_first`; the controller applies it, it is never run from the studio CLI. Apply it BEFORE the
-- CLI and the terminal that use it are run or deployed: `studio source add` writes sources.has_minors and the
-- terminal selects the new view columns and calls decide_pick / attach_clip with the new arguments on every load.
--
-- 1. sources.has_minors: a child is visible in the clip (null = not checked yet). A Drop-in source is eligible
--    when it is not synthetic and has_watermark, has_overlay and has_minors are all false (studio.sources
--    dropin_eligible); other_people is still recorded and shown but no longer blocks.
-- 2. accounts_for_clip is replaced: a dropin_share of 1 or more means "no cap" (Drop-in is the default for every
--    video), so such an account takes a Drop-in even with ten Drop-ins in its last ten posts. Mirrors
--    studio.planning._under_share.
-- 3. decide_pick gains two more trailing parameters, both optional, so every earlier call still works unchanged:
--      owner_props   text[]  "Gadgets & jewellery": at most 3 items of 1-40 characters each, trimmed; stored in
--                            proposal.owner_props as a JSON array (the character wears or holds them).
--      owner_music   text    original | in_app | ai_beat: where the music comes from; stored in
--                            proposal.owner_music. 'original' (keep the clip's own audio: the default of a Drop-in,
--                            owner decision 2026-10-05) is refused for a pick whose mode is Recreate, which has no
--                            original audio: its default is ai_beat (its synthetic driver's beat), or in_app.
--    Both are written only when approving; a blank or null value (or an empty array) keeps what is stored, like
--    every other owner field; a skip stores nothing. The "Both" sibling gets the same values. A function with more
--    defaulted parameters is a second function, not a replacement, so the 8-argument function of 0007 is removed
--    here (the second statement of the migrations that removes anything); the refusals, security invoker, the empty
--    search_path and the grants are the ones of 0007.
-- 4. attach_clip(pick_id, storage_path): the owner attached the video file for a Drop-in (a screen recording, or the
--    creator's own file: we never download from TikTok or Instagram). The browser uploads it to bucket `sources` at
--    owner/<pick id>/<file> and this function stores the path as proposal.owner_clip_path (a pick that is already
--    queued or made is refused). `studio source ingest-owner` turns it into a source.
-- 5. Storage: the owner (the same e-mail rule as every other policy of this schema) may insert and read the objects
--    under sources/owner/ and nothing else of that bucket, from the browser. Nobody else.
-- 6. v_picks and v_pick_history are re-created with the card appended (create or replace view keeps every earlier
--    column): owner_props, owner_music, owner_clip_path (what the owner chose), tier, theme (the analyst's tier and the
--    scan theme it matched), posted_at (text: the tier rule reads it), gallery (a Genjutsu gallery clip) and
--    thumbnail_url / preview_url (https URLs a tool returned: never fetched or rehosted by us).

-- ---- 1. sources.has_minors ----------------------------------------------------------------------

alter table studio.sources add column if not exists has_minors boolean;

-- ---- 2. accounts_for_clip: a share of 1 is "no cap" ---------------------------------------------

create or replace function studio.accounts_for_clip(clip_id uuid)
returns setof studio.accounts
language sql
stable
security invoker
set search_path = ''
as $$
  select a.*
  from studio.clips c
  join studio.accounts a on a.character_slug = c.character_slug
  where c.id = accounts_for_clip.clip_id
    and coalesce(a.postiz_integration_id, '') <> ''
    and (c.mode = 'recreate' or a.dropin_share >= 1 or studio.dropin_ratio(a.id, c.id) < a.dropin_share)
  order by a.character_slug, a.platform
$$;

-- ---- 3. decide_pick: owner_props and owner_music ------------------------------------------------

drop function if exists studio.decide_pick(uuid, text, text, text, text, text, text, text);

create or replace function studio.decide_pick(
  pick_id uuid,
  decision text,
  reason text default null,
  character_slug text default null,
  also_character text default null,
  owner_note text default null,
  owner_mode text default null,
  owner_presence text default null,
  owner_props text[] default null,
  owner_music text default null
)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  f studio.favorites;
  sib studio.favorites;
  clean text := nullif(btrim(decide_pick.reason), '');
  clean_note text := nullif(btrim(decide_pick.owner_note), '');
  clean_mode text := nullif(btrim(decide_pick.owner_mode), '');
  clean_presence text := nullif(btrim(decide_pick.owner_presence), '');
  clean_music text := nullif(btrim(decide_pick.owner_music), '');
  clean_props jsonb := '[]'::jsonb;
  also text := nullif(btrim(decide_pick.also_character), '');
  new_slug text;
  new_status text;
  owner jsonb := '{}'::jsonb;
  record_ jsonb;
begin
  if decide_pick.decision is null or decide_pick.decision not in ('approve', 'skip') then
    raise exception 'decision must be approve or skip, got %', decide_pick.decision using errcode = 'invalid_parameter_value';
  end if;
  if clean_note is not null and char_length(clean_note) > 280 then
    raise exception 'the note is limited to 280 characters, got %', char_length(clean_note) using errcode = 'invalid_parameter_value';
  end if;
  if clean_mode is not null and clean_mode not in ('dropin', 'recreate') then
    raise exception 'owner_mode must be dropin or recreate, got %', clean_mode using errcode = 'invalid_parameter_value';
  end if;
  if clean_presence is not null and clean_presence not in ('cameo', 'featured', 'star') then
    raise exception 'owner_presence must be cameo, featured or star, got %', clean_presence using errcode = 'invalid_parameter_value';
  end if;
  if clean_music is not null and clean_music not in ('in_app', 'original', 'ai_beat') then
    raise exception 'owner_music must be in_app, original or ai_beat, got %', clean_music using errcode = 'invalid_parameter_value';
  end if;
  if decide_pick.owner_props is not null then
    select coalesce(jsonb_agg(btrim(p) order by ord), '[]'::jsonb) into clean_props
      from unnest(decide_pick.owner_props) with ordinality as u(p, ord);
    if jsonb_array_length(clean_props) > 3 then
      raise exception 'owner_props takes at most 3 items, got %', jsonb_array_length(clean_props) using errcode = 'invalid_parameter_value';
    end if;
    if exists (select 1 from jsonb_array_elements_text(clean_props) e(t) where t is null or char_length(t) not between 1 and 40) then
      raise exception 'each of owner_props must be 1 to 40 characters' using errcode = 'invalid_parameter_value';
    end if;
  end if;
  if also is not null and decide_pick.decision <> 'approve' then
    raise exception 'also_character only applies when approving' using errcode = 'invalid_parameter_value';
  end if;
  select * into f from studio.favorites fa where fa.id = decide_pick.pick_id for update;
  if not found then
    raise exception 'unknown pick %', decide_pick.pick_id using errcode = 'no_data_found';
  end if;
  if f.status in ('queued', 'made') then
    raise exception 'pick % is already %: too late to decide', f.id, f.status using errcode = 'check_violation';
  end if;
  if clean_music = 'original' and coalesce(clean_mode, f.proposal ->> 'owner_mode') = 'recreate' then
    raise exception 'owner_music original needs the dropin mode: a Recreate has no original audio (use ai_beat or in_app)' using errcode = 'invalid_parameter_value';
  end if;
  new_slug := coalesce(nullif(btrim(decide_pick.character_slug), ''), f.character_slug);
  if new_slug is not null and not exists (select 1 from studio.characters ch where ch.slug = new_slug) then
    raise exception 'unknown character %', new_slug using errcode = 'invalid_parameter_value';
  end if;
  if decide_pick.decision = 'approve' and new_slug is null then
    raise exception 'choose a character before approving this pick' using errcode = 'check_violation';
  end if;
  if also is not null then
    if not exists (select 1 from studio.characters ch where ch.slug = also) then
      raise exception 'unknown character %', also using errcode = 'invalid_parameter_value';
    end if;
    if also = new_slug then
      raise exception 'also_character must be a different character from %', new_slug using errcode = 'invalid_parameter_value';
    end if;
  end if;

  -- the owner's instructions of this call (only an approval carries them); a blank keeps what is stored
  if decide_pick.decision = 'approve' then
    if clean_note is not null then
      owner := owner || jsonb_build_object('owner_note', clean_note);
    end if;
    if clean_mode is not null then
      owner := owner || jsonb_build_object('owner_mode', clean_mode);
    end if;
    -- his part only means something in a Drop-in: ignored for Recreate and for "the analyst decides"
    if clean_presence is not null and coalesce(clean_mode, f.proposal ->> 'owner_mode') = 'dropin' then
      owner := owner || jsonb_build_object('owner_presence', clean_presence);
    end if;
    -- gadgets & jewellery: what the character wears or holds, in a Drop-in or a Recreate alike
    if jsonb_array_length(clean_props) > 0 then
      owner := owner || jsonb_build_object('owner_props', clean_props);
    end if;
    -- where the music comes from (a Recreate may say ai_beat or in_app; 'original' was refused above for it)
    if clean_music is not null then
      owner := owner || jsonb_build_object('owner_music', clean_music);
    end if;
  end if;
  record_ := jsonb_build_object('decision', decide_pick.decision, 'by', 'owner', 'reason', clean);

  new_status := case
    when decide_pick.decision = 'skip' then 'skipped'
    when f.status in ('approved', 'analysed') then f.status
    else 'approved'
  end;
  update studio.favorites fa
     set status = new_status,
         character_slug = new_slug,
         proposal = (fa.proposal - 'hold_reason') || owner || jsonb_build_object('decision', record_)
   where fa.id = f.id
  returning fa.* into f;

  if also is null then
    return to_jsonb(f);
  end if;

  -- "Both": one sibling row for the other character, the same video with the same instructions
  select * into sib from studio.favorites fa
   where fa.url = f.url and fa.character_slug = also and fa.id <> f.id
   order by fa.created_at, fa.id limit 1 for update;
  if found then
    if sib.status not in ('queued', 'made') then
      update studio.favorites fa
         set status = case when sib.status in ('approved', 'analysed') then sib.status else 'approved' end,
             proposal = (fa.proposal - 'hold_reason') || owner || jsonb_build_object('decision', record_)
       where fa.id = sib.id
      returning fa.* into sib;
    end if;
  else
    insert into studio.favorites
      (url, platform, creator_handle, views, outlier_x, origin, character_slug, proposal, scores, total_score, status)
    values
      (f.url, f.platform, f.creator_handle, f.views, f.outlier_x, f.origin, also, f.proposal, f.scores, f.total_score, 'approved')
    returning * into sib;
  end if;
  return to_jsonb(f) || jsonb_build_object('sibling', to_jsonb(sib));
end;
$$;

-- ---- 4. attach_clip -------------------------------------------------------------------------------

create or replace function studio.attach_clip(pick_id uuid, storage_path text)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  f studio.favorites;
  clean text := nullif(btrim(attach_clip.storage_path), '');
begin
  if clean is null then
    raise exception 'storage_path is required' using errcode = 'invalid_parameter_value';
  end if;
  -- the browser writes exactly owner/<pick id>/<file> into bucket sources: nothing else is accepted
  if clean !~ ('^owner/' || attach_clip.pick_id::text || '/[^/[:space:]]+$') then
    raise exception 'storage_path must be owner/<pick id>/<file>, got %', clean using errcode = 'invalid_parameter_value';
  end if;
  select * into f from studio.favorites fa where fa.id = attach_clip.pick_id for update;
  if not found then
    raise exception 'unknown pick %', attach_clip.pick_id using errcode = 'no_data_found';
  end if;
  if f.status in ('queued', 'made') then
    raise exception 'pick % is already %: too late to attach a clip', f.id, f.status using errcode = 'check_violation';
  end if;
  update studio.favorites fa
     set proposal = fa.proposal || jsonb_build_object('owner_clip_path', clean),
         -- a new file means the source made from an earlier one no longer fits: `ingest-owner` links the new one
         source_id = case when fa.proposal ->> 'owner_clip_path' is distinct from clean then null else fa.source_id end
   where fa.id = f.id
  returning fa.* into f;
  return to_jsonb(f);
end;
$$;

-- ---- 5. storage: the owner's own uploads --------------------------------------------------------

do $$
begin
  if to_regclass('storage.objects') is not null then
    if not exists (select 1 from pg_policies
                   where schemaname = 'storage' and tablename = 'objects' and policyname = 'odd_eyes_owner_uploads_sources') then
      create policy odd_eyes_owner_uploads_sources on storage.objects for insert to authenticated
        with check (bucket_id = 'sources' and name like 'owner/%' and (select auth.jwt() ->> 'email') = 'o.schwend@gmail.com');
    end if;
    if not exists (select 1 from pg_policies
                   where schemaname = 'storage' and tablename = 'objects' and policyname = 'odd_eyes_owner_reads_sources') then
      create policy odd_eyes_owner_reads_sources on storage.objects for select to authenticated
        using (bucket_id = 'sources' and name like 'owner/%' and (select auth.jwt() ->> 'email') = 'o.schwend@gmail.com');
    end if;
  end if;
end
$$;

-- ---- 6. v_picks and v_pick_history (the card appended) --------------------------------------------

create or replace view studio.v_picks with (security_invoker = true) as
select
  f.id,
  f.url,
  f.platform,
  f.creator_handle,
  f.views,
  f.outlier_x,
  f.origin,
  f.character_slug,
  ch.name as character_name,
  f.proposal ->> 'intended_character' as intended_character,
  f.total_score,
  studio.num(f.scores -> 'virality') as virality,
  studio.num(f.scores -> 'reach') as reach,
  studio.num(f.scores -> 'freshness') as freshness,
  studio.num(f.scores -> 'fit') as fit,
  studio.num(f.scores -> 'feasibility') as feasibility,
  studio.num(f.scores -> 'saturation') as saturation,
  f.proposal ->> 'mode' as proposed_mode,
  f.proposal ->> 'hook' as hook,
  f.proposal ->> 'prop' as prop,
  f.proposal ->> 'concept' as concept,
  f.proposal ->> 'enhancement' as enhancement,
  f.proposal -> 'needs' as needs,
  f.proposal -> 'decision' as decision,
  f.proposal ->> 'hold_reason' as hold_reason,
  f.note,
  f.status,
  f.created_at,
  f.proposal ->> 'owner_note' as owner_note,
  f.proposal ->> 'owner_mode' as owner_mode,
  f.proposal ->> 'owner_presence' as owner_presence,
  f.proposal -> 'owner_props' as owner_props,
  f.proposal ->> 'owner_music' as owner_music,
  f.proposal ->> 'owner_clip_path' as owner_clip_path,
  f.proposal ->> 'tier' as tier,
  f.proposal ->> 'theme' as theme,
  f.proposal ->> 'posted_at' as posted_at,
  coalesce(f.proposal ->> 'source_kind' = 'higgsfield_library' or coalesce(btrim(f.proposal ->> 'preset_id'), '') <> '', false) as gallery,
  f.proposal ->> 'thumbnail_url' as thumbnail_url,
  f.proposal ->> 'preview_url' as preview_url
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
where f.status = 'new'
order by f.total_score desc nulls last, f.created_at;

create or replace view studio.v_pick_history with (security_invoker = true) as
select
  f.id,
  f.url,
  f.platform,
  f.creator_handle,
  f.views,
  f.outlier_x,
  f.origin,
  f.character_slug,
  ch.name as character_name,
  f.total_score,
  f.proposal ->> 'hook' as hook,
  f.proposal ->> 'concept' as concept,
  f.proposal -> 'decision' as decision,
  f.note,
  f.status,
  f.created_at,
  f.clip_id,
  c.state as clip_state,
  f.proposal ->> 'owner_note' as owner_note,
  f.proposal ->> 'owner_mode' as owner_mode,
  f.proposal ->> 'owner_presence' as owner_presence,
  f.proposal -> 'owner_props' as owner_props,
  f.proposal ->> 'owner_music' as owner_music,
  f.proposal ->> 'owner_clip_path' as owner_clip_path,
  f.proposal ->> 'tier' as tier,
  f.proposal ->> 'theme' as theme,
  f.proposal ->> 'posted_at' as posted_at,
  coalesce(f.proposal ->> 'source_kind' = 'higgsfield_library' or coalesce(btrim(f.proposal ->> 'preset_id'), '') <> '', false) as gallery,
  f.proposal ->> 'thumbnail_url' as thumbnail_url,
  f.proposal ->> 'preview_url' as preview_url
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
left join studio.clips c on c.id = f.clip_id
where f.status <> 'new';

-- ---- grants ---------------------------------------------------------------------------------------

revoke all on function studio.decide_pick(uuid, text, text, text, text, text, text, text, text[], text) from public;
grant execute on function studio.decide_pick(uuid, text, text, text, text, text, text, text, text[], text) to authenticated;
revoke all on function studio.attach_clip(uuid, text) from public;
grant execute on function studio.attach_clip(uuid, text) to authenticated;
grant select on studio.v_picks to authenticated;
grant select on studio.v_pick_history to authenticated;
