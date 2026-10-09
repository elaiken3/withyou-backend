-- pgTAP tests for the cloud AI usage counters (run with `supabase test db`).
begin;

create extension if not exists pgtap with schema extensions;

select plan(38);

-- ---------------------------------------------------------------------------------------------
-- Tables, keys and row level security
-- ---------------------------------------------------------------------------------------------

select has_table('public', 'ai_usage', 'ai_usage exists');
select has_table('public', 'ai_usage_global', 'ai_usage_global exists');
select col_is_pk('public', 'ai_usage', array['user_id', 'day'], 'ai_usage is keyed by user and day');
select col_is_pk('public', 'ai_usage_global', 'day', 'ai_usage_global is keyed by day');
select fk_ok('public', 'ai_usage', 'user_id', 'auth', 'users', 'id');

select ok(
  (select relrowsecurity from pg_class where oid = 'public.ai_usage'::regclass),
  'RLS is on for ai_usage'
);
select ok(
  (select relrowsecurity from pg_class where oid = 'public.ai_usage_global'::regclass),
  'RLS is on for ai_usage_global'
);
select is(
  (select count(*)::integer from pg_policies
   where schemaname = 'public' and tablename in ('ai_usage', 'ai_usage_global')),
  0,
  'no RLS policies: only the service role reads or writes usage'
);

select ok(
  not has_table_privilege('anon', 'public.ai_usage', 'select,insert,update,delete,truncate'),
  'anon has no access to ai_usage'
);
select ok(
  not has_table_privilege('authenticated', 'public.ai_usage', 'select,insert,update,delete,truncate'),
  'authenticated has no access to ai_usage'
);
select ok(
  not has_table_privilege('anon', 'public.ai_usage_global', 'select,insert,update,delete,truncate'),
  'anon has no access to ai_usage_global'
);
select ok(
  not has_table_privilege('authenticated', 'public.ai_usage_global', 'select,insert,update,delete,truncate'),
  'authenticated has no access to ai_usage_global'
);

-- ---------------------------------------------------------------------------------------------
-- Functions and who may run them
-- ---------------------------------------------------------------------------------------------

select has_function('public', 'ai_consume_quota', array['uuid', 'integer', 'integer']);
select is_definer('public', 'ai_consume_quota', array['uuid', 'integer', 'integer']);
select ok(
  (select proconfig from pg_proc
   where oid = 'public.ai_consume_quota(uuid, integer, integer)'::regprocedure)
    @> array['search_path=""'],
  'ai_consume_quota runs with an empty search_path'
);
select ok(
  not has_function_privilege('anon', 'public.ai_consume_quota(uuid, integer, integer)', 'execute'),
  'anon cannot run ai_consume_quota'
);
select ok(
  not has_function_privilege('authenticated', 'public.ai_consume_quota(uuid, integer, integer)', 'execute'),
  'authenticated cannot run ai_consume_quota'
);
select ok(
  has_function_privilege('service_role', 'public.ai_consume_quota(uuid, integer, integer)', 'execute'),
  'service_role can run ai_consume_quota'
);
select ok(
  not has_function_privilege('anon', 'public.ai_usage_purge(integer)', 'execute')
    and not has_function_privilege('authenticated', 'public.ai_usage_purge(integer)', 'execute')
    and not has_function_privilege('service_role', 'public.ai_usage_purge(integer)', 'execute'),
  'only the owner can run ai_usage_purge'
);
select ok(
  exists (select 1 from pg_extension where extname = 'pg_cron')
    or not exists (select 1 from pg_available_extensions where name = 'pg_cron'),
  'pg_cron is enabled wherever it is available (daily retention)'
);

-- ---------------------------------------------------------------------------------------------
-- Quota semantics
-- ---------------------------------------------------------------------------------------------

insert into auth.users (id, email) values
  ('00000000-0000-4000-8000-0000000000a1', 'ai-usage-test-a1@example.com'),
  ('00000000-0000-4000-8000-0000000000a2', 'ai-usage-test-a2@example.com');

-- Other activity may already have counted today; work relative to it.
create temporary table quota_start on commit drop as
select coalesce(
  (select count from public.ai_usage_global where day = (now() at time zone 'utc')::date),
  0
) as global_count;

select ok(
  public.ai_consume_quota('00000000-0000-4000-8000-0000000000a1', 2, 1000000),
  'first request of the day is allowed'
);
select ok(
  public.ai_consume_quota('00000000-0000-4000-8000-0000000000a1', 2, 1000000),
  'second request is allowed'
);
select ok(
  not public.ai_consume_quota('00000000-0000-4000-8000-0000000000a1', 2, 1000000),
  'third request is refused at a per-user limit of 2'
);
select is(
  (select count from public.ai_usage
   where user_id = '00000000-0000-4000-8000-0000000000a1'
     and day = (now() at time zone 'utc')::date),
  2,
  'a refused request is not counted for the user'
);
select is(
  (select count from public.ai_usage_global where day = (now() at time zone 'utc')::date),
  (select global_count from quota_start) + 2,
  'only allowed requests count toward the global total'
);
select ok(
  not public.ai_consume_quota(
    '00000000-0000-4000-8000-0000000000a2', 60, (select global_count from quota_start) + 2
  ),
  'a new user is refused when the global limit is reached'
);
select is(
  (select count(*)::integer from public.ai_usage where user_id = '00000000-0000-4000-8000-0000000000a2'),
  0,
  'refused at the global limit: no row for the user'
);
select is(
  (select count from public.ai_usage_global where day = (now() at time zone 'utc')::date),
  (select global_count from quota_start) + 2,
  'refused at the global limit: the global total is unchanged'
);
select ok(
  public.ai_consume_quota(
    '00000000-0000-4000-8000-0000000000a2', 60, (select global_count from quota_start) + 3
  ),
  'allowed again when the global limit has room'
);
select ok(
  not public.ai_consume_quota('00000000-0000-4000-8000-0000000000a2', 0, 1000000),
  'a limit of 0 turns cloud AI off'
);

set local role anon;
select throws_ok(
  $$select public.ai_consume_quota('00000000-0000-4000-8000-0000000000a1', 60, 3000)$$,
  '42501',
  null,
  'anon gets permission denied'
);
reset role;

set local role authenticated;
select throws_ok(
  $$select public.ai_consume_quota('00000000-0000-4000-8000-0000000000a1', 60, 3000)$$,
  '42501',
  null,
  'a signed-in user gets permission denied'
);
reset role;

-- ---------------------------------------------------------------------------------------------
-- Retention and deletion
-- ---------------------------------------------------------------------------------------------

insert into public.ai_usage (user_id, day, count) values
  ('00000000-0000-4000-8000-0000000000a2', (now() at time zone 'utc')::date - 36, 3),
  ('00000000-0000-4000-8000-0000000000a2', (now() at time zone 'utc')::date - 35, 4);
insert into public.ai_usage_global (day, count)
values ((now() at time zone 'utc')::date - 400, 9)
on conflict (day) do nothing;

select lives_ok($$select public.ai_usage_purge()$$, 'the retention purge runs');

select is(
  (select count(*)::integer from public.ai_usage
   where day < (now() at time zone 'utc')::date - 35),
  0,
  'usage older than 35 days is purged'
);
select is(
  (select count(*)::integer from public.ai_usage
   where user_id = '00000000-0000-4000-8000-0000000000a2'
     and day = (now() at time zone 'utc')::date - 35),
  1,
  'usage from exactly 35 days ago is kept'
);
select is(
  (select count(*)::integer from public.ai_usage_global
   where day < (now() at time zone 'utc')::date - 35),
  0,
  'old global totals are purged'
);

delete from auth.users where id = '00000000-0000-4000-8000-0000000000a1';

select is(
  (select count(*)::integer from public.ai_usage where user_id = '00000000-0000-4000-8000-0000000000a1'),
  0,
  'deleting the anonymous user deletes their usage rows'
);
select is(
  (select count(*)::integer from public.ai_usage where user_id = '00000000-0000-4000-8000-0000000000a2'),
  2,
  'other users are untouched'
);

select * from finish();
rollback;
