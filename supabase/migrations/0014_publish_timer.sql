-- ODD EYES Character Studio, migration 0014: a database timer starts the publish job when a post is due.
--
-- WHY. `.github/workflows/publish.yml` ran `studio publish due` only on GitHub's `schedule` crons, and GitHub's scheduler is
-- best-effort: on 2026-10-07 it skipped every run between 18:53 and 21:00 London, so the owner's first post (19:30) did not go
-- out until it was triggered by hand. Posting needs a reliable trigger. The database already knows when a post is due and
-- already holds the GitHub dispatch token (Vault `github_dispatch_token`, 0012), so the database asks GitHub to run the job:
-- GitHub's own schedule stays in publish.yml as the fallback, the repository_dispatch (event `publish`) is the primary start.
--
-- Additive only, schema studio only (plus the pg_cron extension, which Supabase offers: it creates schema `cron`, and the one
-- cron job below). To be applied to Supabase project hkcafvzjwkeibbmvskko ("faceless-youtube", shared with another app) as
-- migration `studio_0014_publish_timer`, AFTER 0013; the controller (or the owner) applies it, it is never run from the studio
-- CLI. Apply it AFTER `.github/workflows/publish.yml` with `repository_dispatch: types: [publish]` is on the default branch
-- (a dispatch starts the workflow file of the default branch only); before that the dispatch is accepted and starts nothing.
--
-- 1. pg_cron is enabled when the database has it (Supabase does; a plain Postgres test database does not, and then nothing
--    happens: no extension, no job).
-- 2. studio.timer_state(name, last_at): the one place the last dispatch time lives. studio.settings is a typed single row (the
--    cap, the kill switch, `cadence` keyed by character slug: the code reads `cadence -> slug` and loops over its keys), so a
--    key for a timer would pollute it; a tiny table of its own is the smallest footprint that does not touch anything
--    existing. RLS is on and there is no policy and no grant: no API role can read or write it, only the definer functions
--    below (running as the table owner) do.
-- 3. studio.dispatch_publish(): SECURITY DEFINER (it reads the Vault, which the API roles may not), empty search_path,
--    schema-qualified names only. It posts {"event_type": "publish"} to GitHub's repository_dispatch endpoint through pg_net
--    with the Vault token, exactly like request_job (0012): the token never leaves the function, it is not returned, not
--    raised, not logged; a failure is swallowed ({"dispatched": false, "reason": ...}). On success it returns
--    {"dispatched": true, "request_id": <the pg_net request id>} (the request is sent after the transaction commits; its answer
--    lands in net._http_response under that id, 204 = GitHub accepted the dispatch).
-- 4. studio.publish_tick(): dispatches ONLY when there is work: a post with status 'scheduled' and scheduled_for <= now() (the
--    publisher's own claim predicate), the kill switch is off (the publisher claims nothing while it is on, so a dispatch
--    would only burn Actions minutes), and no dispatch was made in the last 10 minutes (timer_state 'publish_dispatch', the row
--    locked so two ticks cannot both dispatch). last_at is stored only when the dispatch was really queued. Returns what it did:
--    {"dispatched": bool, "due": n, "reason": ...} (reason: nothing_due, kill_switch, recent_dispatch, or the dispatch's own).
-- 5. The cron job `studio-publish-tick`, every 5 minutes, runs `select studio.publish_tick()`. Re-running this migration
--    unschedules the job by name first, so there is never a duplicate. A 19:30 post is therefore started at 19:30-19:35 (the
--    job then takes about a minute), whatever GitHub's scheduler does.
-- 6. Grants: both functions are revoked from public, anon, authenticated and service_role (only the cron job, which runs as the
--    role that scheduled it, calls them); timer_state is revoked from the same roles.
--
-- TO SWITCH IT OFF: select cron.unschedule('studio-publish-tick');   (GitHub's own schedule in publish.yml keeps running)
-- TO SWITCH IT ON AGAIN: re-run the last `do` block of this file, or
--   select cron.schedule('studio-publish-tick', '*/5 * * * *', 'select studio.publish_tick()');

-- ---- 1. pg_cron ------------------------------------------------------------------------------------------------------------

do $$
begin
  if exists (select 1 from pg_catalog.pg_available_extensions where name = 'pg_cron')
     and not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_cron') then
    create extension if not exists pg_cron;
  end if;
end
$$;

-- ---- 2. timer_state --------------------------------------------------------------------------------------------------------

create table studio.timer_state (
  name    text primary key,
  last_at timestamptz
);
alter table studio.timer_state enable row level security;

-- ---- 3. dispatch_publish ---------------------------------------------------------------------------------------------------

create or replace function studio.dispatch_publish()
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  token text;
  req bigint;
begin
  if to_regclass('vault.decrypted_secrets') is null
     or not exists (select 1 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid = p.pronamespace
                    where n.nspname = 'net' and p.proname = 'http_post') then
    return jsonb_build_object('dispatched', false, 'reason', 'no_vault_or_pg_net');
  end if;

  -- the GitHub dispatch: its own block, so a failure never shows the token and never fails the cron job
  begin
    select s.decrypted_secret into token from vault.decrypted_secrets s where s.name = 'github_dispatch_token' limit 1;
    if coalesce(token, '') = '' then
      return jsonb_build_object('dispatched', false, 'reason', 'no_token');
    end if;
    req := net.http_post(
      url := 'https://api.github.com/repos/oschwend-prog/character-studio/dispatches',
      body := jsonb_build_object('event_type', 'publish'),
      headers := jsonb_build_object('Authorization', 'Bearer ' || token, 'Accept', 'application/vnd.github+json',
                                    'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'odd-eyes-studio',
                                    'Content-Type', 'application/json'),
      timeout_milliseconds := 5000
    );
  exception when others then
    token := null;
    return jsonb_build_object('dispatched', false, 'reason', 'dispatch_failed');
  end;
  token := null;
  return jsonb_build_object('dispatched', true, 'request_id', req);
end;
$$;

-- ---- 4. publish_tick -------------------------------------------------------------------------------------------------------

create or replace function studio.publish_tick()
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  due_n int;
  paused boolean;
  last_ timestamptz;
  sent jsonb;
begin
  select count(*) into due_n from studio.posts p where p.status = 'scheduled' and p.scheduled_for <= now();
  if due_n = 0 then
    return jsonb_build_object('dispatched', false, 'due', 0, 'reason', 'nothing_due');
  end if;
  select st.kill_switch into paused from studio.settings st where st.id = 1;
  if coalesce(paused, false) then
    return jsonb_build_object('dispatched', false, 'due', due_n, 'reason', 'kill_switch');
  end if;
  insert into studio.timer_state (name) values ('publish_dispatch') on conflict (name) do nothing;
  select t.last_at into last_ from studio.timer_state t where t.name = 'publish_dispatch' for update;
  if last_ is not null and last_ > now() - interval '10 minutes' then
    return jsonb_build_object('dispatched', false, 'due', due_n, 'reason', 'recent_dispatch', 'last_at', last_);
  end if;
  sent := studio.dispatch_publish();
  if coalesce((sent ->> 'dispatched')::boolean, false) then
    update studio.timer_state t set last_at = now() where t.name = 'publish_dispatch';
  end if;
  return sent || jsonb_build_object('due', due_n);
end;
$$;

-- ---- 6. grants (before the job exists: nothing but the cron job may call these) --------------------------------------------

revoke all on function studio.dispatch_publish() from public;
revoke all on function studio.publish_tick() from public;
revoke all on studio.timer_state from public;
do $$
declare
  r text;
begin
  -- definer rights: no API role may even call them (a role that does not exist on this database is skipped)
  foreach r in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_catalog.pg_roles where rolname = r) then
      execute format('revoke all on function studio.dispatch_publish() from %I', r);
      execute format('revoke all on function studio.publish_tick() from %I', r);
      execute format('revoke all on studio.timer_state from %I', r);
    end if;
  end loop;
end
$$;

-- ---- 5. the cron job -------------------------------------------------------------------------------------------------------

do $$
begin
  if to_regclass('cron.job') is not null then
    if exists (select 1 from cron.job j where j.jobname = 'studio-publish-tick') then
      perform cron.unschedule('studio-publish-tick');
    end if;
    perform cron.schedule('studio-publish-tick', '*/5 * * * *', 'select studio.publish_tick()');
  end if;
end
$$;
