-- ODD EYES Character Studio, migration 0018: the owner's Adjust may ask for a section of 4-16 s (owner 2026-10-14).
--
-- WHY. The owner relaxed the rules that blocked good clips (2026-10-14): a section of 4 s is enough when that is all the clean
-- section a clip has, so a master is 4-16 s now (studio.media.qa.MASTER_SECONDS, studio.drop.MASTER_MIN_S, the terminal's
-- DROP_MIN_SECONDS). 0012's request_job still refused an Adjust whose start or length (the length defaulting to the check's own
-- window) came out under 6 s: "the section must start at 0 s or later and last 6-16 s", so a drop whose check chose a 4.5 s section
-- could not be Adjusted at all. The CLI's own check (studio.drop.validate_adjust) is the binding one and says 4-16 s; this brings
-- the database's check, which runs first, in line with it.
--
-- WHAT. ONE function, `create or replace` with the signature, the language, the security (definer, empty search_path), the owner
-- check, the dispatch and the grants of 0012's request_job (it has been re-created by no later migration): the body is 0012's WORD
-- FOR WORD except two strings, `length_ < 6 or length_ > 16` -> `length_ < 4 or length_ > 16` and the message `last 6-16 s` ->
-- `last 4-16 s`. Nothing else in schema studio changes. To be applied to Supabase project hkcafvzjwkeibbmvskko ("faceless-youtube",
-- shared with another app) as migration `studio_0018_section_min_4s`, AFTER 0017; the controller (or the owner) applies it, it is
-- never run from the studio CLI. Re-run safe: `create or replace` with an unchanged signature, and the grants may repeat.
--
-- TO UNDO: re-run the request_job section of 0012 (create or replace puts it back).

create or replace function studio.request_job(pick_id uuid, kind text, adjust jsonb default null)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  f studio.favorites;
  d jsonb;
  state_ text;
  clean jsonb := '{}'::jsonb;
  k text;
  v jsonb;
  start_ double precision;
  length_ double precision;
  dur double precision;
  token text;
  dispatched boolean := false;
begin
  -- definer rights bypass RLS: the owner rule of every policy of this schema, checked here
  if coalesce((select auth.jwt() ->> 'email'), '') <> 'o.schwend@gmail.com' then
    raise exception 'only the owner may ask for a job' using errcode = 'insufficient_privilege';
  end if;
  if request_job.kind is null or request_job.kind not in ('process', 'make') then
    raise exception 'kind must be process or make, got %', request_job.kind using errcode = 'invalid_parameter_value';
  end if;
  select * into f from studio.favorites fa where fa.id = request_job.pick_id for update;
  if not found then
    raise exception 'unknown pick %', request_job.pick_id using errcode = 'no_data_found';
  end if;
  d := f.proposal -> 'drop';
  if d is null or jsonb_typeof(d) <> 'object' then
    raise exception 'pick % is not a dropped video', f.id using errcode = 'check_violation';
  end if;
  state_ := d ->> 'state';
  if f.status = 'made' then
    raise exception 'pick % is already made', f.id using errcode = 'check_violation';
  end if;

  if request_job.kind = 'process' then
    if state_ is null or state_ not in ('uploading', 'checking', 'waiting', 'failed') then
      raise exception 'a check runs on an uploading, checking, waiting or failed drop; this one is %', state_ using errcode = 'check_violation';
    end if;
    if state_ = 'uploading' and coalesce(f.proposal ->> 'owner_clip_path', '') = '' then
      raise exception 'the upload has not finished: attach the video first' using errcode = 'check_violation';
    end if;
    d := d || jsonb_build_object('state', 'checking', 'reason', null, 'at', now(),
                                 'requested', coalesce(d -> 'requested', '{}'::jsonb) || jsonb_build_object('process', now()));
    update studio.favorites fa set proposal = fa.proposal || jsonb_build_object('drop', d) where fa.id = f.id
    returning fa.* into f;
  else
    if state_ is null or state_ not in ('ready', 'failed') or not (d ? 'credits') or not (d ? 'source_id') then
      raise exception 'Make it needs a checked and priced drop (ready); this one is %', state_ using errcode = 'check_violation';
    end if;
    if request_job.adjust is not null and jsonb_typeof(request_job.adjust) <> 'null' then
      if jsonb_typeof(request_job.adjust) <> 'object' then
        raise exception 'adjust must be an object' using errcode = 'invalid_parameter_value';
      end if;
      for k, v in select e.key, e.value from jsonb_each(request_job.adjust) as e loop
        if k not in ('star', 'part', 'gadgets', 'hook', 'start_s', 'length_s', 'crop_x') then
          raise exception 'adjust has an unknown key %', k using errcode = 'invalid_parameter_value';
        end if;
        if k in ('star', 'hook') and (jsonb_typeof(v) <> 'string' or char_length(btrim(v #>> '{}')) not between 1 and 80
                                      or position(chr(10) in v #>> '{}') > 0) then
          raise exception 'adjust.% must be one line of 1-80 characters', k using errcode = 'invalid_parameter_value';
        end if;
        if k = 'part' and (jsonb_typeof(v) <> 'string' or v #>> '{}' not in ('cameo', 'featured', 'star')) then
          raise exception 'adjust.part must be cameo, featured or star' using errcode = 'invalid_parameter_value';
        end if;
        if k = 'gadgets' and (jsonb_typeof(v) <> 'array' or jsonb_array_length(v) > 3
                              or exists (select 1 from jsonb_array_elements(v) g(x)
                                         where jsonb_typeof(g.x) <> 'string' or char_length(btrim(g.x #>> '{}')) not between 1 and 40)) then
          raise exception 'adjust.gadgets takes at most 3 items of 1-40 characters' using errcode = 'invalid_parameter_value';
        end if;
        if k in ('start_s', 'length_s') and jsonb_typeof(v) <> 'number' then
          raise exception 'adjust.% must be a number', k using errcode = 'invalid_parameter_value';
        end if;
        if k = 'crop_x' and not (jsonb_typeof(v) = 'null' or (jsonb_typeof(v) = 'number' and (v #>> '{}')::double precision between 0 and 1)) then
          raise exception 'adjust.crop_x must be from 0 to 1, or null' using errcode = 'invalid_parameter_value';
        end if;
      end loop;
      if request_job.adjust ? 'start_s' or request_job.adjust ? 'length_s' then
        start_ := coalesce((request_job.adjust ->> 'start_s')::double precision, (d #>> '{window,start_s}')::double precision, 0);
        length_ := coalesce((request_job.adjust ->> 'length_s')::double precision, (d #>> '{window,length_s}')::double precision, 0);
        dur := (d ->> 'duration_s')::double precision;
        if start_ < 0 or length_ < 4 or length_ > 16 then
          raise exception 'the section must start at 0 s or later and last 4-16 s' using errcode = 'invalid_parameter_value';
        end if;
        if dur is not null and start_ + length_ > dur + 0.15 then
          raise exception 'the section runs past the end of the % s video', round(dur::numeric, 1) using errcode = 'invalid_parameter_value';
        end if;
      end if;
      clean := request_job.adjust;
    end if;
    d := (d - 'adjust') || jsonb_build_object('state', 'making', 'reason', null, 'at', now(),
                                              'requested', coalesce(d -> 'requested', '{}'::jsonb) || jsonb_build_object('make', now()));
    if clean <> '{}'::jsonb then
      d := d || jsonb_build_object('adjust', clean);
    end if;
    update studio.favorites fa
       set proposal = fa.proposal || jsonb_build_object('drop', d, 'make_requested', jsonb_build_object('at', now(), 'by', 'owner'))
     where fa.id = f.id
    returning fa.* into f;
  end if;

  -- the GitHub dispatch: its own block, so a failure rolls back nothing above and never shows the token
  begin
    if to_regclass('vault.decrypted_secrets') is not null
       and exists (select 1 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid = p.pronamespace
                   where n.nspname = 'net' and p.proname = 'http_post') then
      select s.decrypted_secret into token from vault.decrypted_secrets s where s.name = 'github_dispatch_token' limit 1;
      if coalesce(token, '') <> '' then
        perform net.http_post(
          url := 'https://api.github.com/repos/oschwend-prog/character-studio/dispatches',
          body := jsonb_build_object('event_type', 'drop-' || request_job.kind,
                                     'client_payload', jsonb_build_object('pick_id', f.id::text)),
          headers := jsonb_build_object('Authorization', 'Bearer ' || token, 'Accept', 'application/vnd.github+json',
                                        'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'odd-eyes-studio',
                                        'Content-Type', 'application/json'),
          timeout_milliseconds := 5000
        );
        dispatched := true;
      end if;
    end if;
  exception when others then
    dispatched := false;
  end;
  token := null;
  return to_jsonb(f) || jsonb_build_object('dispatched', dispatched);
end;
$$;

-- ---- grants (as 0012) ------------------------------------------------------------------------------------------------------------

revoke all on function studio.request_job(uuid, text, jsonb) from public;
grant execute on function studio.request_job(uuid, text, jsonb) to authenticated;
do $$
begin
  -- definer rights: no API role but the signed-in owner may even call it (its own check refuses everyone else too)
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'anon') then
    execute 'revoke all on function studio.request_job(uuid, text, jsonb) from anon';
  end if;
end
$$;
