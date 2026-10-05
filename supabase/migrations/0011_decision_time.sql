-- ODD EYES Character Studio, migration 0011: when the owner decided (follow-up to 0010, owner request 2026-10-05).
--
-- Additive / replacing only, schema studio only. To be applied to Supabase project hkcafvzjwkeibbmvskko ("faceless-youtube")
-- as migration `studio_0011_decision_time`, AFTER 0010; the controller applies it, it is never run from the studio CLI. The
-- terminal needs nothing new from it to load (it only appends one column to v_tracker); it makes "In the works" count the
-- time at Approved from the decision instead of from the filing.
--
-- 1. decide_pick is re-created with the exact signature, body, security invoker, empty search_path and grants of 0008. The one
--    change: the decision record it stores (on the pick and on a "Both" sibling) also carries 'at', now(), like
--    studio.favorites._record does since 2026-10-05. The terminal's call is unchanged (same ten parameters, same defaults),
--    and `create or replace` with the same signature keeps ONE function for PostgREST.
-- 2. v_tracker is re-created with every column of 0010, in the same order, and:
--      - approved_at = the decision record's `at` when it is a valid ISO time, else the pick's created_at (records written
--        before 2026-10-05, and add_owner_link's, carry no `at`). The text is checked by its shape and by the length of its
--        month before the cast, so a malformed `at` falls back instead of failing the view;
--      - decided_at appended: that checked decision time alone (null when the record has none): the go-live check reads it.

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
  record_ := jsonb_build_object('decision', decide_pick.decision, 'by', 'owner', 'reason', clean, 'at', now());

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
  da.decided_at as decided_at
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

-- ---- grants ---------------------------------------------------------------------------------------

revoke all on function studio.decide_pick(uuid, text, text, text, text, text, text, text, text[], text) from public;
grant execute on function studio.decide_pick(uuid, text, text, text, text, text, text, text, text[], text) to authenticated;
grant select on studio.v_tracker to authenticated;
