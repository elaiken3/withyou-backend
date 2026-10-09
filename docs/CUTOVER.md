# Cutover: Supabase cloud AI, and retiring Fly.io + MongoDB

This is the one-time checklist for moving WithYou's backend to Supabase. Do the steps in order.
Nothing here affects people using the app until the app build with cloud AI ships, and cloud AI is
off by default even then.

What you need:

- The [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started)
  (`brew install supabase/tap/supabase`), plus `jq` and `curl`
- An Anthropic API key from the [Anthropic Console](https://console.anthropic.com/)
- A Supabase organization. An existing **Pro** organization can host this project; a new project
  there is billed for its compute size (the smallest size is normally covered by the
  organization's monthly compute credit, so check Billing in the dashboard)
- `flyctl` and `gh` for the clean-up at the end

Run the commands from the root of this repo.


## 1. Create and link the project

Find your organization id, then create the project (pick the region closest to most people):

```bash
supabase login
supabase orgs list
supabase projects create withyou --org-id <org-id> --region us-east-1 --db-password '<a long random password>'
```

Keep the database password in your password manager. The output (and `supabase projects list`)
shows the project ref, a 20-letter id like `abcdefghijklmnopqrst`.

```bash
export PROJECT_REF=<project-ref>
supabase link --project-ref "$PROJECT_REF"
```

You can also create the project in the dashboard (New project) and only run `supabase link`.


## 2. Turn on anonymous sign-ins

In the dashboard: **Authentication → Sign In / Providers → Allow anonymous sign-ins** → on → Save.

Each install signs in anonymously once (no email, no password) and then only refreshes its token.
The per-person daily limit applies to one anonymous account, and anyone can make more accounts, so
also limit how fast new ones can be made:

- **Authentication → Rate Limits**: set anonymous sign-ins to about **5 per hour per IP** (the
  default is 30). At 30 an hour, one IP could use up the whole global daily limit in a couple of
  hours, pausing cloud AI for everyone until UTC midnight. The global limit still caps the cost.
- Later, turn on CAPTCHA (**Authentication → Attack Protection**), but only once the app sends a
  CAPTCHA token with its sign-in, or sign-ins will fail.

`supabase/config.toml` already turns this on for local development. Don't use
`supabase config push` for this: it would also push local-only settings such as `site_url`.


## 3. Set the function's secrets

```bash
supabase secrets set ANTHROPIC_API_KEY=sk-ant-...
```

Tip: to keep the key out of your shell history, put it in a file and use
`supabase secrets set --env-file <file>`, then delete the file.

Optional (the defaults are shown):

```bash
supabase secrets set CLAUDE_MODEL=claude-opus-5-5
supabase secrets set AI_DAILY_LIMIT_PER_USER=60 AI_DAILY_LIMIT_GLOBAL=3000
```

**Cost.** Claude Opus 5.5 (the default) costs $4 per million input tokens and $20 per million
output tokens. A typical request is about 1,000 input tokens and a few hundred output tokens, so
roughly 1 to 3 US cents. At the default global limit of 3,000 requests a day, the worst case is
roughly $30 to $90 a day. `CLAUDE_MODEL=claude-haiku-5-5` ($0.10 / $0.50 per million tokens) brings
a request well under a tenth of a cent, with simpler suggestions. Whatever you choose:

- set `AI_DAILY_LIMIT_GLOBAL` to what you're comfortable spending per day, and
- set a monthly spend limit for the key's workspace in the Anthropic Console.

Secrets apply to new function instances right away; changing them later needs no redeploy.
`supabase secrets list` shows what is set (values are hidden).


## 4. Create the tables and deploy the function

```bash
supabase db push
supabase functions deploy ai --no-verify-jwt
```

`db push` applies `supabase/migrations/`: the two usage tables, `ai_consume_quota`, and a daily
pg_cron job that deletes counts older than 35 days. To confirm the job, run this in the dashboard's
SQL editor:

```sql
select jobname, schedule, command from cron.job;
-- withyou-ai-usage-retention | 17 3 * * * | select public.ai_usage_purge()
```

`--no-verify-jwt` matches `config.toml`: the function checks each access token itself.


## 5. Check it works

Get the publishable key (`sb_publishable_...`) from **Project Settings → API Keys**, or with
`supabase projects api-keys --project-ref "$PROJECT_REF"`.

```bash
export SUPABASE_URL="https://$PROJECT_REF.supabase.co"
export SUPABASE_KEY="sb_publishable_..."

# 1. No token: expect 401 unauthorized
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$SUPABASE_URL/functions/v1/ai" \
  -H "apikey: $SUPABASE_KEY" -H "Content-Type: application/json" \
  -d '{"task": "break_down", "input": {"title": "Clean the kitchen"}}'

# 2. Sign in anonymously, like the app does
TOKEN=$(curl -sS -X POST "$SUPABASE_URL/auth/v1/signup" \
  -H "apikey: $SUPABASE_KEY" -H "Content-Type: application/json" -d '{}' | jq -r .access_token)
echo "${TOKEN:0:12}..."   # should not be "null"

# 3. A real request: expect {"ok":true,"task":"break_down","result":{"steps":[...]}}
curl -sS -X POST "$SUPABASE_URL/functions/v1/ai" \
  -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"task": "break_down", "input": {"title": "Clean the kitchen"}}'

# 4. Clean up the test user: expect {"ok":true,"task":"delete_me","result":{"deleted":true}}
curl -sS -X POST "$SUPABASE_URL/functions/v1/ai" \
  -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"task": "delete_me", "input": {}}'
```

If step 2 returns an error about anonymous sign-ins, step 2 of this checklist isn't saved yet.
If step 3 returns 503 `not_configured`, the Anthropic key isn't set. Logs are under
**Edge Functions → ai → Logs**; they show only task, status, latency and an error code.


## 6. Automatic deploys from GitHub (optional)

`.github/workflows/deploy.yml` runs CI and then `db push` and `functions deploy ai` on every push to
`main` (and on demand). It skips with a notice until these repository secrets exist:

```bash
gh secret set SUPABASE_ACCESS_TOKEN --repo elaiken3/withyou-backend   # supabase.com/dashboard/account/tokens
gh secret set SUPABASE_PROJECT_REF  --repo elaiken3/withyou-backend --body "$PROJECT_REF"
gh secret set SUPABASE_DB_PASSWORD  --repo elaiken3/withyou-backend   # the password from step 1
```

`gh secret set` without `--body` prompts for the value, which keeps it out of your shell history.


## 7. Point the app at Supabase

In the iOS repo, put the project host (no `https://`, because `//` starts a comment in xcconfig
files) and the publishable key in `WithYou/Config/WithYou.local.xcconfig`, which is gitignored:

```text
WITHYOU_SUPABASE_HOST = <project-ref>.supabase.co
WITHYOU_SUPABASE_ANON_KEY = sb_publishable_...
```

The old `WITHYOU_API_KEY` line can go. For TestFlight and App Store builds, set the same two values
wherever release builds get their configuration. The publishable key is safe to ship in the app:
it only allows what anonymous sign-in and the function allow.

Build, turn on **Settings → Use cloud AI**, and try "Sort it out for me" on a typed thought. On an
iPhone with Apple Intelligence, requests stay on the device, so test cloud AI on one without it (or
the simulator).


## 8. Retire Fly.io and MongoDB

Do this once the app build without the old backend is the one people have. Older builds only ever
registered devices and never received a push, so nothing breaks for them except a failed
registration they don't see.

```bash
# The Fly app (API and worker)
fly apps destroy withyou-backend

# The deploy token for Fly in this repo
gh secret delete FLY_API_TOKEN --repo elaiken3/withyou-backend
```

MongoDB Atlas: **Database → Clusters → (the WithYou cluster) → … → Terminate**. If you want a copy
first, the data was only install ids, device tokens, preferences and daily counts; nothing needs to
be kept. With the Atlas CLI instead: `atlas clusters delete <cluster-name> --projectId <project-id>`.
If the Atlas project has nothing else in it, delete the project too, and remove any database users
and network access entries that were only for Fly.

Optional: the APNs key (`AuthKey_XXXX.p8`) was only used by the old worker. If nothing else uses it,
revoke it under **Certificates, Identifiers & Profiles → Keys** in the Apple Developer site.


## If something goes wrong

- **Turn cloud AI off right away:** `supabase secrets set AI_DAILY_LIMIT_GLOBAL=0`. Every AI request
  then gets 429 and the app quietly uses on-device AI or simple rules. Set it back to turn cloud AI
  on again.
- **Bad function deploy:** redeploy the previous commit with `supabase functions deploy ai --no-verify-jwt`
  from a checkout of it.
- **Delete one person's data by hand:** their usage rows go when their auth user is deleted
  (**Authentication → Users → delete**); the `ai_usage` foreign key cascades.
