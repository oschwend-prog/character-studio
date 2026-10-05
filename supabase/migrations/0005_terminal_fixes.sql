-- ODD EYES Character Studio, migration 0005: terminal fixes from the Task 15 review.
--
-- Additive only, schema studio only. Applied to Supabase project hkcafvzjwkeibbmvskko
-- ("faceless-youtube") as migration `studio_0005_terminal_fixes`.
--
-- 1. queue_block_reason(clip_id): why a clip awaiting approval cannot be approved yet, or NULL when it
--    can. One sentence, the same wording approve_clip raises: no master file, no connected account, or
--    no account that may take this dropin clip (planning.accounts_for_clip).
-- 2. approve_clip refuses a clip without a master (the publisher would fail it three times anyway),
--    through that helper, and never stores an empty caption or hook: a blank value keeps what is there.
-- 3. v_queue appends `blocked_reason`, so the terminal gates Approve, Schedule and Approve all on the
--    database's own answer. CREATE OR REPLACE VIEW keeps every existing column and adds this one last.

create or replace function studio.queue_block_reason(clip_id uuid)
returns text
language sql
stable
security invoker
set search_path = ''
as $$
  select case
    when c.id is null then 'unknown clip'
    when coalesce(c.master_path, '') = '' then 'no master file yet'
    when not exists (
      select 1 from studio.accounts a
      where a.character_slug = c.character_slug and coalesce(a.postiz_integration_id, '') <> ''
    ) then 'no connected account for ' || c.character_slug || ': no Postiz integration id yet (connect it, then run seed)'
    when not exists (select 1 from studio.accounts_for_clip(c.id))
      then 'no account of ' || c.character_slug || ' may take this ' || c.mode
        || ' clip: every connected account is at or over its dropin share'
  end
  from (select 1) as one
  left join studio.clips c on c.id = queue_block_reason.clip_id
$$;

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
  slot_at := coalesce(approve_clip.schedule_at, studio.upcoming_slot(c.character_slug, now()));

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

-- Same columns as 0004, in the same order, plus blocked_reason at the end.
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

revoke all on function studio.queue_block_reason(uuid) from public;
grant execute on function studio.queue_block_reason(uuid) to authenticated;
grant select on studio.v_queue to authenticated;
