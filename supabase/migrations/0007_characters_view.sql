-- ODD EYES Character Studio, migration 0007: the Characters page, the "Make it" sheet and the Scanner card.
--
-- Additive / replacing only, schema studio only. To be applied to Supabase project hkcafvzjwkeibbmvskko
-- ("faceless-youtube") as migration `studio_0007_characters_view`; the controller applies it, it is never run
-- from the studio CLI. Apply it BEFORE the terminal that reads it is deployed (that terminal selects
-- studio.v_characters and the new columns of v_picks / v_pick_history on every load).
--
-- 1. characters.setup: what `studio seed` writes from characters/<slug>/refs.json and the Characters page
--    shows beside the accounts: {"closeup": bool, "planned_handles": {"tiktok": .., "instagram": ..}}.
-- 2. runs.details: the structured numbers of a run (`studio run log --details-file`), e.g.
--    {"scan": {"queries": [..], "outliers": n, "picks_added": n, "auto_approved": n, "held": n,
--    "skipped": n, "vidiq_credits": n}}. The Scanner card reads them; the table is already readable by
--    `authenticated` under the owner policy of 0001, so the terminal selects it directly.
-- 3. v_characters: one row per character with its accounts as a jsonb array (security_invoker: the owner's
--    RLS on characters and accounts decides what is seen).
-- 4. v_picks and v_pick_history are re-created with the owner's three instructions appended
--    (owner_note, owner_mode, owner_presence): `create or replace view` keeps every earlier column.
-- 5. decide_pick gains four trailing parameters, all optional, so the call of 0004 still works unchanged:
--      also_character  approve only. A known character other than the chosen one: ONE sibling favorites
--                      row is filed for it (a copy of this pick, approved), so "Both" makes one clip each.
--                      Idempotent: a row with the same url and that character is reused, never doubled.
--      owner_note      the owner's note for the analyst; trimmed, at most 280 characters, stored in
--                      proposal.owner_note.
--      owner_mode      how to loop the character in: 'dropin' or 'recreate', stored in proposal.owner_mode;
--                      absent = the analyst decides.
--      owner_presence  how big his part is in a Drop-in: 'cameo', 'featured' or 'star', stored in
--                      proposal.owner_presence, and only when the mode is 'dropin'.
--    A blank or null value keeps what is stored (the idiom of approve_clip); the instructions are only
--    written when approving. A function with one more defaulted parameter is a second function, not a
--    replacement, and PostgREST cannot choose between the two for a call that fits both: so the 4-argument
--    function of 0004 is removed here, as the one statement of the migrations that removes anything.
-- 6. Realtime: characters, accounts and runs join the publication, so the page follows a re-seed, a
--    go-live and a scan while it is open.

-- ---- 1. characters.setup ------------------------------------------------------------------------

alter table studio.characters add column if not exists setup jsonb not null default '{}'::jsonb;

-- ---- 2. runs.details ----------------------------------------------------------------------------

alter table studio.runs add column if not exists details jsonb not null default '{}'::jsonb;

-- ---- 3. v_characters ----------------------------------------------------------------------------

create or replace view studio.v_characters with (security_invoker = true) as
select
  ch.slug,
  ch.name,
  ch.status,
  ch.bodies,
  ch.setup,
  coalesce((
    select jsonb_agg(jsonb_build_object(
             'platform', a.platform,
             'handle', a.handle,
             'has_postiz', coalesce(a.postiz_integration_id, '') <> '',
             'mode', a.mode) order by a.platform)
    from studio.accounts a
    where a.character_slug = ch.slug
  ), '[]'::jsonb) as accounts
from studio.characters ch
order by ch.slug;

-- ---- 4. v_picks and v_pick_history (the three owner columns appended) ---------------------------

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
  f.proposal ->> 'owner_presence' as owner_presence
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
  f.proposal ->> 'owner_presence' as owner_presence
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
left join studio.clips c on c.id = f.clip_id
where f.status <> 'new';

-- ---- 5. decide_pick -----------------------------------------------------------------------------

drop function if exists studio.decide_pick(uuid, text, text, text);

create or replace function studio.decide_pick(
  pick_id uuid,
  decision text,
  reason text default null,
  character_slug text default null,
  also_character text default null,
  owner_note text default null,
  owner_mode text default null,
  owner_presence text default null
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

-- ---- grants -------------------------------------------------------------------------------------

revoke all on function studio.decide_pick(uuid, text, text, text, text, text, text, text) from public;
grant execute on function studio.decide_pick(uuid, text, text, text, text, text, text, text) to authenticated;
grant select on studio.v_characters to authenticated;
grant select on studio.v_picks to authenticated;
grant select on studio.v_pick_history to authenticated;

-- ---- 6. Realtime --------------------------------------------------------------------------------

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'studio' and tablename = 'characters') then
      alter publication supabase_realtime add table studio.characters;
    end if;
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'studio' and tablename = 'accounts') then
      alter publication supabase_realtime add table studio.accounts;
    end if;
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'studio' and tablename = 'runs') then
      alter publication supabase_realtime add table studio.runs;
    end if;
  end if;
end
$$;
