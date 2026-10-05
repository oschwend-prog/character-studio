-- ODD EYES Character Studio, migration 0006: one slot rule, and a unique key on reviews.
--
-- Additive / replacing only, schema studio only. To be applied to Supabase project
-- hkcafvzjwkeibbmvskko ("faceless-youtube") as migration `studio_0006`; the controller applies it, it is
-- never run from the studio CLI.
--
-- 1. free_slot: the ONE default-slot rule, in Python as studio.planning.free_slot. The first cadence slot
--    at or after upcoming_slot(after_ts) on a London day on which none of the target accounts already has
--    a post in scheduled / posting / posted / needs_check (a failed post never took the slot). A post's day
--    is that of claimed_at, else scheduled_for (the same day studio.publish.base caps on). One clip's own
--    posts can be left out (a half-written earlier call). Raises when the next 56 days hold no free
--    cadence day. An explicit schedule_at given to approve_clip stays the owner's choice.
-- 2. next_free_slot(clip_id): the same answer for a clip, NULL instead of an error (for v_queue).
-- 3. approve_clip replaces the one of 0005: the default slot is free_slot(...) over the clip's target
--    accounts, so two clips approved for the same accounts never land on the same day. Everything else
--    (the block reason, the blank-keeps-old caption and hook, the all-or-nothing writes) is unchanged.
-- 4. v_queue re-created with the same columns, `next_slot` now being next_free_slot, so the terminal shows
--    the slot approve_clip will use.
-- 5. reviews gets a unique key on (week, character_slug): `studio review save` upserts on it. Duplicate
--    rows from before the key (the old save raced) are folded away first: the oldest row of a pair is
--    kept, because that is the one the old save kept rewriting, so it holds the latest report.

-- ---- 1. free_slot -------------------------------------------------------------------------------

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

-- ---- 2. next_free_slot --------------------------------------------------------------------------

create or replace function studio.next_free_slot(clip_id uuid, after_ts timestamptz default now())
returns timestamptz
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  c studio.clips;
  targets uuid[];
begin
  select * into c from studio.clips cl where cl.id = next_free_slot.clip_id;
  if not found then
    return null;
  end if;
  select coalesce(array_agg(t.id), '{}'::uuid[]) into targets from studio.accounts_for_clip(c.id) t;
  return studio.free_slot(c.character_slug, targets, c.id, next_free_slot.after_ts);
exception when others then
  return null;
end;
$$;

-- ---- 3. approve_clip ----------------------------------------------------------------------------

create or replace function studio.approve_clip(clip_id uuid, caption text default null, hook text default null, schedule_at timestamptz default null)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  c studio.clips;
  blocked text;
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
  blocked := studio.queue_block_reason(c.id);
  if blocked is not null then
    raise exception 'cannot approve clip %: %', c.id, blocked using errcode = 'check_violation';
  end if;
  select array_agg(t.id order by t.platform) into targets from studio.accounts_for_clip(c.id) t;
  slot_at := coalesce(approve_clip.schedule_at, studio.free_slot(c.character_slug, targets, c.id, now()));

  update studio.clips cl
     set state = 'approved',
         caption = coalesce(nullif(btrim(approve_clip.caption), ''), cl.caption),
         hook = coalesce(nullif(btrim(approve_clip.hook), ''), cl.hook)
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

-- ---- 4. v_queue (same columns as 0005; next_slot is now the free slot) --------------------------

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
  studio.next_free_slot(c.id, now()) as next_slot,
  fp.id as pick_id,
  fp.url as pick_url,
  studio.queue_block_reason(c.id) as blocked_reason
from studio.clips c
join studio.characters ch on ch.slug = c.character_slug
left join studio.sources s on s.id = c.source_id
left join lateral (
  select f.id, f.url from studio.favorites f
  where f.clip_id = c.id or f.id::text = c.features ->> 'fav_id'
  order by f.created_at limit 1
) fp on true
where c.state = 'awaiting_approval';

-- ---- 5. reviews: one row per (week, character) ---------------------------------------------------

delete from studio.reviews r
 using studio.reviews keep
 where r.week = keep.week
   and r.character_slug = keep.character_slug
   and (r.created_at, r.id) > (keep.created_at, keep.id);

create unique index if not exists reviews_week_character_slug_key
  on studio.reviews (week, character_slug);

-- ---- grants -------------------------------------------------------------------------------------

revoke all on function studio.free_slot(text, uuid[], uuid, timestamptz) from public;
grant execute on function studio.free_slot(text, uuid[], uuid, timestamptz) to authenticated;
revoke all on function studio.next_free_slot(uuid, timestamptz) from public;
grant execute on function studio.next_free_slot(uuid, timestamptz) to authenticated;
grant select on studio.v_queue to authenticated;
