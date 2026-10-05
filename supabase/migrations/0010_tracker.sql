-- ODD EYES Character Studio, migration 0010: the long list and the "In the works" tracker (owner request 2026-10-05).
--
-- Views only: additive / replacing, schema studio only. To be applied to Supabase project hkcafvzjwkeibbmvskko
-- ("faceless-youtube") as migration `studio_0010_tracker`; the controller applies it, it is never run from the studio CLI.
-- Apply it BEFORE the terminal that reads it is deployed (that terminal selects v_tracker and the new columns of v_picks on
-- every load; the CLI needs nothing from it: the data rides in favorites.proposal, checked by studio.favorites.validate_card).
--
-- 1. v_picks and v_pick_history are re-created with the long list's fields appended (`create or replace view` keeps every
--    column of 0009, in the same order, and only appends): recognisability (0-10, how instantly people know an iconic
--    moment), original_views (the famous original's views), original_url, source_status and audio_risk (one line each on
--    the clip and the audio), est_credits (the analyst's estimate), season (when it peaks), checks (what to watch for, a
--    JSON array) and source_candidates (clean clips that might drive a Drop-in, a JSON array). Numbers go through
--    studio.num and the two arrays through jsonb_typeof: a malformed value comes back null, never 0 or a wrong shape.
-- 2. v_tracker (new): one row per approved pick until it is posted, for the terminal's "In the works" tab. A pick whose
--    status is approved, analysed, queued or made; a made pick drops off 7 days after its post went out. Per pick:
--      - the card (tier, theme, concept, hook, pictures, gallery, the analyst's and the owner's mode, the owner's music,
--        the numbers the derived tier reads), the pick status, its decision record and note, its source and clip check;
--      - approved_at: no decision time is stored anywhere (fav decide and decide_pick record {decision, by, reason}) and
--        favorites has no updated_at, so it is the pick's created_at (the standing rule decides in the run that files);
--      - its clip: the newest clip made from it, linked by favorites.clip_id or by the clip's features.fav_id (a
--        Regenerate or a remake after a dropped clip carries fav_id, so the newest attempt is the one shown);
--      - clip_state_since: clips keep no state-change time either, so it is the latest known event of the clip, its
--        creation, its last ledger entry (the reserve when generation starts, the settle when it is generated) or a post's
--        claim (best effort: enough for the "stuck for 6 h" rule of Generating and Quality check);
--      - clip_failure: the reject reason, else the QA problems (qa.problems joined with " / "), else qa.error;
--      - credits_spent: every settled ledger entry of every clip of the pick (a re-roll and a remake included);
--      - its post: the clip's latest post (by scheduled_for; for the two posts of one slot the least advanced, so a failed
--        or needs_check post shows), with its status, slot, posted time (claimed_at, else the slot), URL, error, and the
--        views of its latest metric snapshot.

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
  f.proposal ->> 'preview_url' as preview_url,
  studio.num(f.proposal -> 'velocity') as velocity,
  f.proposal -> 'engagement' as engagement,
  studio.num(f.proposal -> 'saturation_count') as saturation_count,
  f.proposal -> 'trait_matches' as trait_matches,
  f.proposal ->> 'why' as why,
  f.proposal -> 'analysis' as analysis,
  studio.num(f.proposal -> 'recognisability') as recognisability,
  studio.num(f.proposal -> 'original_views') as original_views,
  f.proposal ->> 'original_url' as original_url,
  f.proposal ->> 'source_status' as source_status,
  f.proposal ->> 'audio_risk' as audio_risk,
  studio.num(f.proposal -> 'est_credits') as est_credits,
  f.proposal ->> 'season' as season,
  case when jsonb_typeof(f.proposal -> 'checks') = 'array' then f.proposal -> 'checks' end as checks,
  case when jsonb_typeof(f.proposal -> 'source_candidates') = 'array' then f.proposal -> 'source_candidates' end as source_candidates
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
  f.proposal ->> 'preview_url' as preview_url,
  studio.num(f.proposal -> 'velocity') as velocity,
  f.proposal -> 'engagement' as engagement,
  studio.num(f.proposal -> 'saturation_count') as saturation_count,
  f.proposal -> 'trait_matches' as trait_matches,
  f.proposal ->> 'why' as why,
  f.proposal -> 'analysis' as analysis,
  studio.num(f.proposal -> 'recognisability') as recognisability,
  studio.num(f.proposal -> 'original_views') as original_views,
  f.proposal ->> 'original_url' as original_url,
  f.proposal ->> 'source_status' as source_status,
  f.proposal ->> 'audio_risk' as audio_risk,
  studio.num(f.proposal -> 'est_credits') as est_credits,
  f.proposal ->> 'season' as season,
  case when jsonb_typeof(f.proposal -> 'checks') = 'array' then f.proposal -> 'checks' end as checks,
  case when jsonb_typeof(f.proposal -> 'source_candidates') = 'array' then f.proposal -> 'source_candidates' end as source_candidates
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
left join studio.clips c on c.id = f.clip_id
where f.status <> 'new';

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
  f.created_at as approved_at,
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
  sn.views as latest_views
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
left join lateral (
  select x.id, x.state, x.mode, x.created_at, x.reject_reason, x.qa
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

grant select on studio.v_picks to authenticated;
grant select on studio.v_pick_history to authenticated;
grant select on studio.v_tracker to authenticated;
