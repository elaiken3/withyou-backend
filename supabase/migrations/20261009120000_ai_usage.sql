-- WithYou cloud AI: daily usage counters, and nothing else.
--
-- The server never stores the text of a request or Claude's reply. These tables only count how
-- many cloud AI requests each anonymous account, and everyone together, made on a UTC day, so the
-- `ai` Edge Function can keep to its daily limits. Rows older than 35 days are deleted every day.

create table public.ai_usage (
  user_id uuid not null references auth.users (id) on delete cascade,
  day date not null,
  count integer not null default 0 check (count >= 0),
  primary key (user_id, day)
);

comment on table public.ai_usage is
  'Cloud AI requests per anonymous user per UTC day. No request content. Kept 35 days.';

create index ai_usage_day_idx on public.ai_usage (day);

create table public.ai_usage_global (
  day date primary key,
  count integer not null default 0 check (count >= 0)
);

comment on table public.ai_usage_global is
  'Cloud AI requests from everyone per UTC day. Kept 35 days.';

-- Only the service role (the Edge Function) touches these tables. RLS is on with no policies,
-- so the Data API shows nothing to anon or signed-in callers even if a grant slips back in.
alter table public.ai_usage enable row level security;
alter table public.ai_usage_global enable row level security;

revoke all on table public.ai_usage, public.ai_usage_global from public, anon, authenticated;
grant select, insert, update, delete on table public.ai_usage, public.ai_usage_global
  to service_role;

-- Counts one request for p_user today (UTC) and returns true, or returns false without counting
-- anything when the person's or everyone's limit for today is already reached.
create or replace function public.ai_consume_quota(
  p_user uuid,
  p_user_limit integer,
  p_global_limit integer
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_day date := (now() at time zone 'utc')::date;
  v_global integer;
  v_user integer;
begin
  if p_user is null or coalesce(p_user_limit, 0) < 1 or coalesce(p_global_limit, 0) < 1 then
    return false;
  end if;

  -- Every call locks today's global row first, then the person's row, always in that order.
  -- Concurrent calls wait their turn instead of racing past a limit, and can't deadlock.
  insert into public.ai_usage_global as g (day, count)
  values (v_day, 0)
  on conflict (day) do nothing;

  select g.count into v_global
  from public.ai_usage_global as g
  where g.day = v_day
  for update;

  select u.count into v_user
  from public.ai_usage as u
  where u.user_id = p_user and u.day = v_day
  for update;

  if v_global >= p_global_limit or coalesce(v_user, 0) >= p_user_limit then
    return false;
  end if;

  update public.ai_usage_global as g
  set count = g.count + 1
  where g.day = v_day;

  insert into public.ai_usage as u (user_id, day, count)
  values (p_user, v_day, 1)
  on conflict (user_id, day) do update set count = u.count + 1;

  return true;
end;
$$;

comment on function public.ai_consume_quota(uuid, integer, integer) is
  'Atomically counts one cloud AI request for today (UTC); false and no change when a limit is reached.';

-- Deletes counters older than p_keep_days (35 by default). Run daily by pg_cron below.
create or replace function public.ai_usage_purge(p_keep_days integer default 35)
returns void
language sql
security definer
set search_path = ''
as $$
  delete from public.ai_usage
  where day < (now() at time zone 'utc')::date - p_keep_days;

  delete from public.ai_usage_global
  where day < (now() at time zone 'utc')::date - p_keep_days;
$$;

-- Functions are executable by PUBLIC by default; only the service role may count quota, and only
-- the owner (postgres, which runs the cron job) may purge.
revoke all on function public.ai_consume_quota(uuid, integer, integer)
  from public, anon, authenticated;
grant execute on function public.ai_consume_quota(uuid, integer, integer) to service_role;

revoke all on function public.ai_usage_purge(integer) from public, anon, authenticated, service_role;

-- Retention: run the purge every day at 03:17 UTC. pg_cron is available on Supabase (local and
-- hosted); the guard keeps this migration working on a plain Postgres without it.
do $do$
begin
  if exists (select 1 from pg_available_extensions where name = 'pg_cron') then
    create extension if not exists pg_cron;
    -- Scheduling under the same name again replaces the job, so this is safe to re-run.
    perform cron.schedule(
      'withyou-ai-usage-retention',
      '17 3 * * *',
      'select public.ai_usage_purge()'
    );
  else
    raise notice 'pg_cron is not available: run select public.ai_usage_purge(); once a day another way.';
  end if;
end
$do$;
