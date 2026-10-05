-- ODD EYES Character Studio, migration 0004: the terminal's read views and owner RPCs.
--
-- Additive only. Creates functions and views in schema studio, adds three studio tables to the
-- Realtime publication, and one read policy on storage.objects for the private `clips` bucket (so
-- the owner's browser can sign URLs for masters). Applied to Supabase project hkcafvzjwkeibbmvskko
-- ("faceless-youtube") as migration `studio_0004_terminal_rpc`.
--
-- Who may do what: every function runs as the caller (security invoker) with an empty search_path,
-- and every view has security_invoker = true, so the owner-only RLS policies of 0001 decide what is
-- seen and written. Only `authenticated` gets select / execute; the CLI keeps connecting as the
-- table owner and never needs any of this.
--
-- The rules mirror the Python studio, which stays the reference (tests in tests/test_schema.py pin
-- the text):
--   accounts_for_clip  = studio.planning.accounts_for_clip: recreate -> every connected account of
--                        the character; dropin -> only accounts whose rolling dropin ratio (last 10
--                        posts by scheduled_for, this clip's own posts left out) is under their share.
--   upcoming_slot      = studio.planning.upcoming_slot: the first cadence slot strictly after a moment,
--                        London wall-clock time.
--   approve_clip       = studio.clips.schedule_clip after awaiting_approval -> approved: one post per
--                        target account at the slot (or schedule_at), clip -> scheduled, all or nothing.
--   decide_pick        = studio.favorites.decide with by = 'owner'; add_owner_link = add_favorite.
--   v_budget           = studio.budget.committed: settled + reservations not yet closed, London month.
--   v_health           = studio.health.check: stale daily run, failed / needs_check posts, >= 80% of cap.
-- Posting autopilot (accounts.mode = 'auto') unlocks per account after 6 approved posts (owner
-- directive 2026-10-04); set_account_mode refuses it earlier and v_channels says so.
--
-- The integration tests apply this text to a scratch schema by substituting the schema identifier,
-- so every object stays schema-qualified.

-- ---- small helpers ----------------------------------------------------------------------------

-- A jsonb number as double precision; anything else (absent, string, null) is NULL, never 0.
create or replace function studio.num(value jsonb)
returns double precision
language sql
immutable
security invoker
set search_path = ''
as $$
  select case when jsonb_typeof(value) = 'number' then (value #>> '{}')::double precision end
$$;

-- The cadence days of one character's cadence entry, as 'mon'..'sun' (a string or a list in the json).
create or replace function studio.cadence_days(entry jsonb)
returns text[]
language sql
immutable
security invoker
set search_path = ''
as $$
  select coalesce(array_agg(distinct left(lower(btrim(d.day)), 3)), '{}'::text[])
  from jsonb_array_elements_text(
    case jsonb_typeof(entry -> 'days')
      when 'array' then entry -> 'days'
      when 'string' then jsonb_build_array(entry -> 'days')
      else '[]'::jsonb
    end
  ) as d(day)
$$;

-- The character's first posting slot strictly after `after_ts`, on a cadence day (London days and
-- wall-clock time). Raises like the Python for a missing or malformed slot or no cadence days.
create or replace function studio.upcoming_slot(character_slug text, after_ts timestamptz default now())
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
  today date;
  d date;
  candidate timestamptz;
begin
  select st.cadence -> upcoming_slot.character_slug into entry from studio.settings st where st.id = 1;
  if entry is null or jsonb_typeof(entry) <> 'object' or not entry ? 'slot' then
    raise exception 'no posting slot configured for %', upcoming_slot.character_slug
      using errcode = 'invalid_parameter_value';
  end if;
  slot := entry ->> 'slot';
  if jsonb_typeof(entry -> 'slot') <> 'string' or slot !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then
    raise exception 'slot for % must be ''HH:MM'' (London time), got %', upcoming_slot.character_slug, entry -> 'slot'
      using errcode = 'invalid_parameter_value';
  end if;
  days := studio.cadence_days(entry);
  if cardinality(days) = 0 then
    raise exception 'no posting days configured for %', upcoming_slot.character_slug
      using errcode = 'invalid_parameter_value';
  end if;
  today := (upcoming_slot.after_ts at time zone 'Europe/London')::date;
  for i in 0..7 loop
    d := today + i;
    if (array['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])[extract(isodow from d)::int] = any (days) then
      candidate := (d + slot::time) at time zone 'Europe/London';
      if candidate > upcoming_slot.after_ts then
        return candidate;
      end if;
    end if;
  end loop;
  raise exception 'no upcoming slot found for %', upcoming_slot.character_slug;
end;
$$;

-- upcoming_slot for a view: NULL instead of an error when the cadence has no slot for the character.
create or replace function studio.next_slot(character_slug text, after_ts timestamptz default now())
returns timestamptz
language plpgsql
stable
security invoker
set search_path = ''
as $$
begin
  return studio.upcoming_slot(next_slot.character_slug, next_slot.after_ts);
exception when others then
  return null;
end;
$$;

-- Share of dropin clips among the account's last 10 posts (any status), oldest-to-newest by
-- scheduled_for then id, optionally leaving one clip's posts out. 0 without history.
create or replace function studio.dropin_ratio(account_id uuid, exclude_clip_id uuid default null)
returns double precision
language sql
stable
security invoker
set search_path = ''
as $$
  select coalesce(avg(case when c.mode = 'dropin' then 1.0 else 0.0 end), 0)::double precision
  from (
    select p.clip_id
    from studio.posts p
    where p.account_id = dropin_ratio.account_id
      and (dropin_ratio.exclude_clip_id is null or p.clip_id <> dropin_ratio.exclude_clip_id)
    order by p.scheduled_for desc, p.id desc
    limit 10
  ) w
  join studio.clips c on c.id = w.clip_id
$$;

-- The connected accounts a clip goes to (planning.accounts_for_clip).
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
    and (c.mode = 'recreate' or studio.dropin_ratio(a.id, c.id) < a.dropin_share)
  order by a.character_slug, a.platform
$$;

-- Posts the owner has approved on an account: every post row is created by an approval (the
-- terminal, or `studio clip schedule`, which autopilot only reaches once it is unlocked).
create or replace function studio.approved_posts(account_id uuid)
returns integer
language sql
stable
security invoker
set search_path = ''
as $$
  select count(*)::int from studio.posts p where p.account_id = approved_posts.account_id
$$;

-- ---- owner RPCs -------------------------------------------------------------------------------

-- Approve a clip awaiting approval (optionally with an edited caption / hook) and schedule it: one
-- post per target account at `schedule_at`, or the character's next cadence slot. All or nothing.
create or replace function studio.approve_clip(clip_id uuid, caption text default null, hook text default null, schedule_at timestamptz default null)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  c studio.clips;
  targets uuid[];
  slot_at timestamptz;
  out_posts jsonb;
begin
  select * into c from studio.clips cl where cl.id = approve_clip.clip_id for update;
  if not found then
    raise exception 'unknown clip %', approve_clip.clip_id using errcode = 'no_data_found';
  end if;
  if c.state not in ('awaiting_approval', 'approved') then
    raise exception 'clip % is %: only a clip awaiting approval can be approved', c.id, c.state
      using errcode = 'check_violation';
  end if;
  if not exists (
    select 1 from studio.accounts a
    where a.character_slug = c.character_slug and coalesce(a.postiz_integration_id, '') <> ''
  ) then
    raise exception 'no connected account for %: no Postiz integration id yet (connect it, then run seed)', c.character_slug
      using errcode = 'check_violation';
  end if;
  select array_agg(t.id order by t.platform) into targets from studio.accounts_for_clip(c.id) t;
  if targets is null then
    raise exception 'no account of % may take this % clip: every connected account is at or over its dropin share', c.character_slug, c.mode
      using errcode = 'check_violation';
  end if;
  slot_at := coalesce(approve_clip.schedule_at, studio.upcoming_slot(c.character_slug, now()));

  update studio.clips cl
     set state = 'approved',
         caption = coalesce(approve_clip.caption, cl.caption),
         hook = coalesce(approve_clip.hook, cl.hook)
   where cl.id = c.id;
  insert into studio.posts (clip_id, account_id, scheduled_for)
  select c.id, t.account_id, slot_at
  from unnest(targets) as t(account_id)
  where not exists (select 1 from studio.posts p where p.clip_id = c.id and p.account_id = t.account_id)
  on conflict on constraint posts_clip_id_account_id_key do nothing;
  update studio.clips cl set state = 'scheduled' where cl.id = c.id;

  select coalesce(jsonb_agg(jsonb_build_object(
           'post_id', p.id, 'account_id', p.account_id, 'platform', a.platform, 'handle', a.handle,
           'scheduled_for', p.scheduled_for, 'status', p.status) order by a.platform), '[]'::jsonb)
    into out_posts
    from studio.posts p join studio.accounts a on a.id = p.account_id
   where p.clip_id = c.id;
  return jsonb_build_object('clip_id', c.id, 'state', 'scheduled', 'scheduled_for', slot_at, 'posts', out_posts);
end;
$$;

-- Reject a clip awaiting approval. The reason is required: it feeds QA and the playbook.
create or replace function studio.reject_clip(clip_id uuid, reason text)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  c studio.clips;
begin
  if coalesce(btrim(reject_clip.reason), '') = '' then
    raise exception 'a rejection needs a reason (it feeds QA and the playbook)' using errcode = 'invalid_parameter_value';
  end if;
  select * into c from studio.clips cl where cl.id = reject_clip.clip_id for update;
  if not found then
    raise exception 'unknown clip %', reject_clip.clip_id using errcode = 'no_data_found';
  end if;
  if c.state <> 'awaiting_approval' then
    raise exception 'clip % is %: only a clip awaiting approval can be rejected', c.id, c.state
      using errcode = 'check_violation';
  end if;
  update studio.clips cl set state = 'rejected', reject_reason = btrim(reject_clip.reason) where cl.id = c.id;
  return jsonb_build_object('clip_id', c.id, 'state', 'rejected');
end;
$$;

-- "Regenerate": the clip leaves the queue (rejected, reason 'regenerate: <note>') and a new planned
-- clip with the same character, source, mode and feature tags is left for the next daily run, which
-- reuses a planned clip carrying features.regenerate_of (daily-run skill, step 3).
create or replace function studio.regenerate_clip(clip_id uuid, note text default null)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  c studio.clips;
  clean text := nullif(btrim(regenerate_clip.note), '');
  new_id uuid;
begin
  select * into c from studio.clips cl where cl.id = regenerate_clip.clip_id for update;
  if not found then
    raise exception 'unknown clip %', regenerate_clip.clip_id using errcode = 'no_data_found';
  end if;
  if c.state <> 'awaiting_approval' then
    raise exception 'clip % is %: only a clip awaiting approval can be regenerated', c.id, c.state
      using errcode = 'check_violation';
  end if;
  update studio.clips cl
     set state = 'rejected', reject_reason = 'regenerate' || coalesce(': ' || clean, '')
   where cl.id = c.id;
  insert into studio.clips (character_slug, source_id, mode, state, features)
  values (
    c.character_slug, c.source_id, c.mode, 'planned',
    (c.features - 'rerolls' - 'outlier_x' - 'regenerate_of' - 'regenerate_note')
      || jsonb_build_object('rerolls', 0, 'regenerate_of', c.id)
      || case when clean is null then '{}'::jsonb else jsonb_build_object('regenerate_note', clean) end
  )
  returning id into new_id;
  return jsonb_build_object('clip_id', c.id, 'state', 'rejected', 'new_clip_id', new_id);
end;
$$;

-- The monthly cap and the kill switch; NULL leaves a value as it is.
create or replace function studio.set_budget(cap integer default null, kill boolean default null)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  s studio.settings;
begin
  if set_budget.cap is not null and set_budget.cap < 0 then
    raise exception 'the cap must be 0 credits or more, got %', set_budget.cap using errcode = 'invalid_parameter_value';
  end if;
  update studio.settings st
     set monthly_cap_credits = coalesce(set_budget.cap, st.monthly_cap_credits),
         kill_switch = coalesce(set_budget.kill, st.kill_switch)
   where st.id = 1
  returning st.* into s;
  if not found then
    raise exception 'settings not found (signed in as the owner?)' using errcode = 'no_data_found';
  end if;
  return jsonb_build_object('cap', s.monthly_cap_credits, 'kill_switch', s.kill_switch);
end;
$$;

-- Posting mode of one account ('approval' | 'auto') and optionally its dropin share. 'auto' is
-- refused until the account has 6 approved posts; switching back to 'approval' is always allowed.
create or replace function studio.set_account_mode(account_id uuid, mode text, dropin_share numeric default null)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  a studio.accounts;
  approved integer;
begin
  if set_account_mode.mode is null or set_account_mode.mode not in ('approval', 'auto') then
    raise exception 'mode must be approval or auto, got %', set_account_mode.mode using errcode = 'invalid_parameter_value';
  end if;
  if set_account_mode.dropin_share is not null and (set_account_mode.dropin_share < 0 or set_account_mode.dropin_share > 1) then
    raise exception 'dropin share must be between 0 and 1, got %', set_account_mode.dropin_share using errcode = 'invalid_parameter_value';
  end if;
  select * into a from studio.accounts ac where ac.id = set_account_mode.account_id for update;
  if not found then
    raise exception 'unknown account %', set_account_mode.account_id using errcode = 'no_data_found';
  end if;
  approved := studio.approved_posts(a.id);
  if set_account_mode.mode = 'auto' and a.mode <> 'auto' and approved < 6 then
    raise exception 'autopilot unlocks after 6 approved posts on % (% so far)', coalesce(a.handle, a.platform), approved
      using errcode = 'check_violation';
  end if;
  update studio.accounts ac
     set mode = set_account_mode.mode,
         dropin_share = coalesce(set_account_mode.dropin_share::double precision, ac.dropin_share)
   where ac.id = a.id
  returning ac.* into a;
  return jsonb_build_object('account_id', a.id, 'mode', a.mode, 'dropin_share', a.dropin_share, 'approved_posts', approved);
end;
$$;

-- The owner's decision on a Viral Pick (approve or skip, optionally re-assigning the character).
-- Recorded like `studio fav decide --by owner`: proposal.decision = {decision, by, reason}, a
-- hold_reason is cleared, an analysed pick stays analysed on approve, queued / made are past deciding.
create or replace function studio.decide_pick(pick_id uuid, decision text, reason text default null, character_slug text default null)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  f studio.favorites;
  clean text := nullif(btrim(decide_pick.reason), '');
  new_slug text;
  new_status text;
begin
  if decide_pick.decision is null or decide_pick.decision not in ('approve', 'skip') then
    raise exception 'decision must be approve or skip, got %', decide_pick.decision using errcode = 'invalid_parameter_value';
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
  new_status := case
    when decide_pick.decision = 'skip' then 'skipped'
    when f.status in ('approved', 'analysed') then f.status
    else 'approved'
  end;
  update studio.favorites fa
     set status = new_status,
         character_slug = new_slug,
         proposal = (fa.proposal - 'hold_reason')
           || jsonb_build_object('decision', jsonb_build_object('decision', decide_pick.decision, 'by', 'owner', 'reason', clean))
   where fa.id = f.id
  returning fa.* into f;
  return to_jsonb(f);
end;
$$;

-- The owner's own link (the terminal's paste box): origin 'owner', approved on the spot, never
-- downloaded. The terminal sends the canonical URL (the same form as favorites.parse_video_url);
-- anything else is refused. A link already in the list is not added twice: a new or skipped one is
-- approved by the owner, anything further along is returned untouched.
create or replace function studio.add_owner_link(url text, character_slug text, note text default null)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  f studio.favorites;
  plat text;
  clean_note text := nullif(btrim(add_owner_link.note), '');
  rec jsonb := jsonb_build_object('decision', 'approve', 'by', 'owner', 'reason', 'owner''s own favourite');
begin
  plat := case
    when add_owner_link.url ~ '^https://www\.tiktok\.com/@[[:alnum:]_.-]+/video/[0-9]+$' then 'tiktok'
    when add_owner_link.url ~ '^https://www\.instagram\.com/reel/[[:alnum:]_-]+/$' then 'instagram'
    when add_owner_link.url ~ '^https://www\.youtube\.com/shorts/[[:alnum:]_-]+$' then 'youtube'
  end;
  if plat is null then
    raise exception 'not a canonical TikTok, Instagram Reel or YouTube Shorts URL: %', add_owner_link.url
      using errcode = 'invalid_parameter_value';
  end if;
  if not exists (select 1 from studio.characters ch where ch.slug = add_owner_link.character_slug) then
    raise exception 'unknown character %', add_owner_link.character_slug using errcode = 'invalid_parameter_value';
  end if;
  select * into f from studio.favorites fa where fa.url = add_owner_link.url order by fa.created_at limit 1 for update;
  if found then
    if f.status in ('new', 'skipped') then
      update studio.favorites fa
         set status = 'approved',
             proposal = (fa.proposal - 'hold_reason') || jsonb_build_object('decision', rec),
             note = coalesce(clean_note, fa.note)
       where fa.id = f.id
      returning fa.* into f;
    end if;
    return to_jsonb(f) || jsonb_build_object('duplicate', true);
  end if;
  insert into studio.favorites (url, platform, origin, character_slug, proposal, note, status)
  values (add_owner_link.url, plat, 'owner', add_owner_link.character_slug, jsonb_build_object('decision', rec), clean_note, 'approved')
  returning * into f;
  return to_jsonb(f) || jsonb_build_object('duplicate', false);
end;
$$;

-- ---- views (all security_invoker: the owner's RLS applies) ---------------------------------------

-- One row per social account: results, mode, autopilot lock and what posts today (London day).
create or replace view studio.v_channels with (security_invoker = true) as
select
  a.id as account_id,
  a.character_slug,
  ch.name as character_name,
  ch.status as character_status,
  a.platform,
  a.handle,
  coalesce(a.postiz_integration_id, '') <> '' as connected,
  a.mode,
  a.dropin_share,
  studio.dropin_ratio(a.id) as dropin_ratio,
  studio.approved_posts(a.id) as approved_posts,
  6 as autopilot_min_approved,
  studio.approved_posts(a.id) >= 6 as autopilot_unlocked,
  coalesce(ps.posted, 0) as posts_posted,
  coalesce(ps.scheduled, 0) as posts_scheduled,
  coalesce(ps.problems, 0) as posts_problem,
  ps.views_7d,
  ps.follows,
  ox.median_outlier_x,
  ox.hit_rate,
  coalesce(ox.measured, 0) as measured_clips,
  (select r.bar_status from studio.reviews r
    where r.character_slug = a.character_slug
    order by r.week desc, r.created_at desc limit 1) as bar_status,
  studio.next_slot(a.character_slug, now()) as next_slot,
  coalesce(td.posts, '[]'::jsonb) as today_posts
from studio.accounts a
join studio.characters ch on ch.slug = a.character_slug
left join lateral (
  select
    count(*) filter (where p.status = 'posted') as posted,
    count(*) filter (where p.status in ('scheduled', 'posting')) as scheduled,
    count(*) filter (where p.status in ('failed', 'needs_check')) as problems,
    sum(l.views) filter (
      where p.status = 'posted' and coalesce(p.claimed_at, p.scheduled_for) >= now() - interval '7 days'
    ) as views_7d,
    sum(l.follows) filter (where p.status = 'posted') as follows
  from studio.posts p
  left join lateral (
    select s.views, s.follows from studio.snapshots s where s.post_id = p.id order by s.captured_at desc limit 1
  ) l on true
  where p.account_id = a.id
) ps on true
left join lateral (
  select
    percentile_cont(0.5) within group (order by x.v) as median_outlier_x,
    avg(case when x.v >= 3 then 1.0 else 0.0 end)::double precision as hit_rate,
    count(*) as measured
  from (
    select distinct c.id, studio.num(c.features -> 'outlier_x') as v
    from studio.posts p join studio.clips c on c.id = p.clip_id
    where p.account_id = a.id and p.status = 'posted'
  ) x
  where x.v is not null
) ox on true
left join lateral (
  select jsonb_agg(jsonb_build_object(
           'post_id', p.id, 'clip_id', p.clip_id, 'scheduled_for', p.scheduled_for, 'status', p.status,
           'hook', c.hook, 'mode', c.mode, 'url', p.url) order by p.scheduled_for) as posts
  from studio.posts p join studio.clips c on c.id = p.clip_id
  where p.account_id = a.id
    and (p.scheduled_for at time zone 'Europe/London')::date = (now() at time zone 'Europe/London')::date
) td on true;

-- Clips waiting for the owner, with where they would go and when.
create or replace view studio.v_queue with (security_invoker = true) as
select
  c.id,
  c.character_slug,
  ch.name as character_name,
  c.mode,
  c.state,
  c.master_path,
  c.hook,
  c.caption,
  c.hashtags,
  coalesce(c.credits_actual, c.credits_reserved) as cost_credits,
  c.qa,
  c.features,
  c.created_at,
  s.kind as source_kind,
  s.url as source_url,
  s.credit_handle as source_credit,
  s.trend as source_trend,
  coalesce((
    select jsonb_agg(jsonb_build_object('account_id', t.id, 'platform', t.platform, 'handle', t.handle, 'mode', t.mode)
                     order by t.platform)
    from studio.accounts_for_clip(c.id) t
  ), '[]'::jsonb) as targets,
  studio.next_slot(c.character_slug, now()) as next_slot,
  fp.id as pick_id,
  fp.url as pick_url
from studio.clips c
join studio.characters ch on ch.slug = c.character_slug
left join studio.sources s on s.id = c.source_id
left join lateral (
  select f.id, f.url from studio.favorites f
  where f.clip_id = c.id or f.id::text = c.features ->> 'fav_id'
  order by f.created_at limit 1
) fp on true
where c.state = 'awaiting_approval';

-- Every clip ever made, with its posts and each post's latest metric snapshot.
create or replace view studio.v_library with (security_invoker = true) as
select
  c.id,
  c.character_slug,
  ch.name as character_name,
  c.mode,
  c.state,
  c.hook,
  c.caption,
  c.master_path,
  c.reject_reason,
  c.created_at,
  coalesce(c.credits_actual, c.credits_reserved) as cost_credits,
  studio.num(c.features -> 'outlier_x') as outlier_x,
  c.features ->> 'format_id' as format_id,
  coalesce(pp.posts, '[]'::jsonb) as posts,
  coalesce(pp.platforms, '{}'::text[]) as platforms,
  pp.views,
  pp.posted_at
from studio.clips c
join studio.characters ch on ch.slug = c.character_slug
left join lateral (
  select
    jsonb_agg(jsonb_build_object(
      'post_id', p.id, 'platform', a.platform, 'handle', a.handle, 'status', p.status,
      'scheduled_for', p.scheduled_for, 'url', p.url, 'views', l.views, 'likes', l.likes,
      'comments', l.comments, 'shares', l.shares, 'saves', l.saves, 'captured_at', l.captured_at
    ) order by a.platform) as posts,
    array_agg(distinct a.platform) as platforms,
    sum(l.views) as views,
    min(coalesce(p.claimed_at, p.scheduled_for)) filter (where p.status = 'posted') as posted_at
  from studio.posts p
  join studio.accounts a on a.id = p.account_id
  left join lateral (
    select s.views, s.likes, s.comments, s.shares, s.saves, s.captured_at
    from studio.snapshots s where s.post_id = p.id order by s.captured_at desc limit 1
  ) l on true
  where p.clip_id = c.id
) pp on true;

-- This London month's credits: settled + still-reserved, per character, projected month-end.
create or replace view studio.v_budget with (security_invoker = true) as
with m as (
  select
    to_char(now() at time zone 'Europe/London', 'YYYY-MM') as month,
    extract(day from now() at time zone 'Europe/London')::int as day_of_month,
    extract(day from date_trunc('month', now() at time zone 'Europe/London') + interval '1 month' - interval '1 day')::int
      as days_in_month
),
closes as (
  select l.clip_id, max(l.created_at) as last_close
  from studio.ledger l cross join m
  where l.month = m.month and l.kind in ('settle', 'release')
  group by l.clip_id
),
per_clip as (
  select
    l.clip_id,
    coalesce(sum(l.credits) filter (where l.kind = 'settle'), 0)::int as settled,
    coalesce(sum(l.credits) filter (
      where l.kind = 'reserve' and (cl.last_close is null or l.created_at > cl.last_close)
    ), 0)::int as reserved
  from studio.ledger l
  cross join m
  left join closes cl on cl.clip_id = l.clip_id
  where l.month = m.month
  group by l.clip_id
),
per_character as (
  select ch.slug, ch.name,
         coalesce(sum(pc.settled), 0)::int as settled,
         coalesce(sum(pc.reserved), 0)::int as reserved
  from studio.characters ch
  left join studio.clips c on c.character_slug = ch.slug
  left join per_clip pc on pc.clip_id = c.id
  group by ch.slug, ch.name
),
total as (
  select coalesce(sum(pc.settled), 0)::int as settled, coalesce(sum(pc.reserved), 0)::int as reserved from per_clip pc
)
select
  m.month,
  st.monthly_cap_credits as cap,
  st.kill_switch,
  t.settled,
  t.reserved,
  t.settled + t.reserved as committed,
  m.day_of_month,
  m.days_in_month,
  round((t.settled + t.reserved)::numeric / m.day_of_month * m.days_in_month)::int as projected,
  coalesce((
    select jsonb_agg(jsonb_build_object(
             'slug', pc.slug, 'name', pc.name, 'settled', pc.settled, 'reserved', pc.reserved,
             'committed', pc.settled + pc.reserved) order by pc.slug)
    from per_character pc
  ), '[]'::jsonb) as by_character
from studio.settings st
cross join m
cross join total t
where st.id = 1;

-- What `studio health` would report now, one row per problem.
create or replace view studio.v_health with (security_invoker = true) as
select 'daily_run'::text as kind, 'critical'::text as severity, d.message, null::uuid as ref_id, now() as since
from (
  select case
    when not exists (select 1 from studio.runs r where r.kind = 'daily')
      then 'no daily run has ever been logged (the daily routine has not reported in)'
    else 'no daily run finished without error in the last 26 h (last daily run: ' || (
      select case
        when r.finished_at is not null
          then r.status || ' at ' || to_char(r.finished_at at time zone 'Europe/London', 'YYYY-MM-DD HH24:MI')
        else 'started ' || to_char(r.started_at at time zone 'Europe/London', 'YYYY-MM-DD HH24:MI') || ' and never finished'
      end
      from studio.runs r where r.kind = 'daily'
      order by coalesce(r.finished_at, r.started_at) desc limit 1
    ) || ')'
  end as message
  where not exists (
    select 1 from studio.runs r
    where r.kind = 'daily' and r.finished_at is not null
      and r.finished_at >= now() - interval '26 hours' and r.status <> 'error'
  )
) d
union all
select
  'post',
  case when p.status = 'failed' then 'critical' else 'warning' end,
  'post on ' || coalesce(a.handle, 'an unknown account') || ' is ' || p.status
    || coalesce(': ' || left(regexp_replace(btrim(p.error), '\s+', ' ', 'g'), 300), ''),
  p.id,
  coalesce(p.claimed_at, p.scheduled_for)
from studio.posts p
left join studio.accounts a on a.id = p.account_id
where p.status in ('failed', 'needs_check')
union all
select
  'budget',
  case when b.committed >= b.cap then 'critical' else 'warning' end,
  'credits committed in ' || b.month || ': ' || b.committed || ' of ' || b.cap
    || ' (' || round(b.committed * 100.0 / b.cap) || '%), at or past 80% of the monthly cap',
  null,
  now()
from studio.v_budget b
where b.cap > 0 and b.committed * 100 >= b.cap * 80;

-- New Viral Picks, best first, with the six sub-scores as columns.
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
  f.created_at
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
where f.status = 'new'
order by f.total_score desc nulls last, f.created_at;

-- Decided picks (approved, analysed, queued, made, skipped) with the clip each one produced.
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
  c.state as clip_state
from studio.favorites f
left join studio.characters ch on ch.slug = f.character_slug
left join studio.clips c on c.id = f.clip_id
where f.status <> 'new';

-- ---- grants: the owner's browser signs in as `authenticated`; RLS does the rest -------------------

revoke all on function studio.num(jsonb) from public;
revoke all on function studio.cadence_days(jsonb) from public;
revoke all on function studio.upcoming_slot(text, timestamptz) from public;
revoke all on function studio.next_slot(text, timestamptz) from public;
revoke all on function studio.dropin_ratio(uuid, uuid) from public;
revoke all on function studio.accounts_for_clip(uuid) from public;
revoke all on function studio.approved_posts(uuid) from public;
revoke all on function studio.approve_clip(uuid, text, text, timestamptz) from public;
revoke all on function studio.reject_clip(uuid, text) from public;
revoke all on function studio.regenerate_clip(uuid, text) from public;
revoke all on function studio.set_budget(integer, boolean) from public;
revoke all on function studio.set_account_mode(uuid, text, numeric) from public;
revoke all on function studio.decide_pick(uuid, text, text, text) from public;
revoke all on function studio.add_owner_link(text, text, text) from public;

grant execute on function studio.num(jsonb) to authenticated;
grant execute on function studio.cadence_days(jsonb) to authenticated;
grant execute on function studio.upcoming_slot(text, timestamptz) to authenticated;
grant execute on function studio.next_slot(text, timestamptz) to authenticated;
grant execute on function studio.dropin_ratio(uuid, uuid) to authenticated;
grant execute on function studio.accounts_for_clip(uuid) to authenticated;
grant execute on function studio.approved_posts(uuid) to authenticated;
grant execute on function studio.approve_clip(uuid, text, text, timestamptz) to authenticated;
grant execute on function studio.reject_clip(uuid, text) to authenticated;
grant execute on function studio.regenerate_clip(uuid, text) to authenticated;
grant execute on function studio.set_budget(integer, boolean) to authenticated;
grant execute on function studio.set_account_mode(uuid, text, numeric) to authenticated;
grant execute on function studio.decide_pick(uuid, text, text, text) to authenticated;
grant execute on function studio.add_owner_link(text, text, text) to authenticated;

grant select on studio.v_channels to authenticated;
grant select on studio.v_queue to authenticated;
grant select on studio.v_library to authenticated;
grant select on studio.v_budget to authenticated;
grant select on studio.v_health to authenticated;
grant select on studio.v_picks to authenticated;
grant select on studio.v_pick_history to authenticated;

-- ---- Realtime: the terminal listens to clips, posts and Viral Picks (RLS filters the events) -------

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'studio' and tablename = 'clips') then
      alter publication supabase_realtime add table studio.clips;
    end if;
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'studio' and tablename = 'posts') then
      alter publication supabase_realtime add table studio.posts;
    end if;
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'studio' and tablename = 'favorites') then
      alter publication supabase_realtime add table studio.favorites;
    end if;
  end if;
end
$$;

-- ---- Storage: the owner may read (sign URLs for) objects of the private clips bucket ---------------

do $$
begin
  if to_regclass('storage.objects') is not null
     and not exists (select 1 from pg_policies
                     where schemaname = 'storage' and tablename = 'objects' and policyname = 'odd_eyes_owner_reads_clips') then
    create policy odd_eyes_owner_reads_clips on storage.objects for select to authenticated
      using (bucket_id = 'clips' and (select auth.jwt() ->> 'email') = 'o.schwend@gmail.com');
  end if;
end
$$;
