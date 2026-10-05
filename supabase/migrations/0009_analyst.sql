-- ODD EYES Character Studio, migration 0009: the analyst's data on every pick card (owner request 2026-10-05).
--
-- Additive / replacing only, schema studio only. To be applied to Supabase project hkcafvzjwkeibbmvskko
-- ("faceless-youtube") as migration `studio_0009_analyst`; the controller applies it, it is never run from the studio
-- CLI. Apply it BEFORE the terminal that reads it is deployed (that terminal selects the new columns of v_picks and
-- v_pick_history on every load; the CLI itself needs nothing from it: the data rides in favorites.proposal).
--
-- v_picks and v_pick_history are re-created with the analyst's fields appended (`create or replace view` keeps every
-- earlier column and only appends): velocity (views per day since posting, a number, worked out when the pick was
-- filed), engagement ({likes, comments, shares, saves} from vidIQ when it returned them, a JSON object),
-- saturation_count (similar outliers of the last 7 days, a number), trait_matches (1-4 phrases of the character's
-- traits card, a JSON array), why (the analyst's reasoning, text) and analysis (the local check of a fetched or
-- attached clip: people, subject, camera, watermark, overlay, children, best window, bpm: a JSON object). The age of a
-- video needs no column: the terminal works it out from posted_at (0008) and the clock.
-- Absent or malformed values come back null (studio.num never turns a non-number into 0); the studio CLI validates
-- the shapes before it stores them (studio.favorites.validate_card).

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
  f.proposal -> 'analysis' as analysis
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
  f.proposal -> 'analysis' as analysis
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
left join studio.clips c on c.id = f.clip_id
where f.status <> 'new';

-- ---- grants ---------------------------------------------------------------------------------------

grant select on studio.v_picks to authenticated;
grant select on studio.v_pick_history to authenticated;
