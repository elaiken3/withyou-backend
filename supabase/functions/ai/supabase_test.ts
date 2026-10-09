// Tests the Supabase-backed dependencies through the real supabase-js client and a fake fetch.

import assert from "node:assert/strict";
import { createSupabaseDeps, DependencyError, serverKey } from "./supabase.ts";

const URL_BASE = "http://supabase.test";
const USER_ID = "8b5f1c2e-3c1d-4a8e-9a43-6f0d1c2b3a4e";

interface Captured {
  method: string;
  url: URL;
  headers: Headers;
  body: string;
}

function setup(
  respond: (request: Captured) => Response | Promise<Response>,
  env: Record<string, string> = {
    SUPABASE_URL: URL_BASE,
    SUPABASE_SERVICE_ROLE_KEY: "service-role-key",
  },
) {
  const calls: Captured[] = [];
  const fake = async (input: string | URL | Request, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const captured: Captured = {
      method: request.method,
      url: new URL(request.url),
      headers: new Headers(init?.headers ?? request.headers),
      body: init?.body ? String(init.body) : await request.text(),
    };
    calls.push(captured);
    return await respond(captured);
  };
  const deps = createSupabaseDeps((name) => env[name], {
    fetch: fake as typeof fetch,
  });
  return { deps, calls };
}

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

Deno.test("verifyUser returns the user for a valid token", async () => {
  const { deps, calls } = setup(() =>
    json(200, {
      id: USER_ID,
      aud: "authenticated",
      role: "authenticated",
      is_anonymous: true,
    })
  );
  assert.deepEqual(await deps.verifyUser("user-access-token"), { id: USER_ID });
  assert.equal(calls[0].method, "GET");
  assert.equal(calls[0].url.pathname, "/auth/v1/user");
  assert.equal(
    calls[0].headers.get("authorization"),
    "Bearer user-access-token",
  );
});

Deno.test("verifyUser returns null when auth rejects the token", async () => {
  for (const status of [401, 403, 404]) {
    const { deps } = setup(() =>
      json(status, { code: status, error_code: "bad_jwt", msg: "invalid JWT" })
    );
    assert.equal(await deps.verifyUser("expired"), null, `HTTP ${status}`);
  }
});

Deno.test("verifyUser throws when auth is unreachable or failing", async () => {
  const unreachable = setup(() => {
    throw new TypeError("connection refused");
  });
  await assert.rejects(unreachable.deps.verifyUser("token"), DependencyError);
  for (const status of [500, 502, 503]) {
    const failing = setup(() => json(status, { code: status, msg: "down" }));
    await assert.rejects(
      failing.deps.verifyUser("token"),
      DependencyError,
      `HTTP ${status}`,
    );
  }
});

Deno.test("consumeQuota calls ai_consume_quota with the limits", async () => {
  const { deps, calls } = setup(() => json(200, true));
  assert.equal(
    await deps.consumeQuota(USER_ID, { perUser: 60, global: 3000 }),
    true,
  );
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].url.pathname, "/rest/v1/rpc/ai_consume_quota");
  assert.deepEqual(JSON.parse(calls[0].body), {
    p_user: USER_ID,
    p_user_limit: 60,
    p_global_limit: 3000,
  });
  assert.equal(calls[0].headers.get("apikey"), "service-role-key");
});

Deno.test("consumeQuota returns false when a limit is reached", async () => {
  const { deps } = setup(() => json(200, false));
  assert.equal(
    await deps.consumeQuota(USER_ID, { perUser: 1, global: 1 }),
    false,
  );
});

Deno.test("consumeQuota throws on a database error", async () => {
  const { deps } = setup(() =>
    json(404, { code: "PGRST202", message: "Could not find the function" })
  );
  await assert.rejects(
    deps.consumeQuota(USER_ID, { perUser: 1, global: 1 }),
    DependencyError,
  );
});

Deno.test("deleteUserData deletes usage rows, then the auth user", async () => {
  const { deps, calls } = setup((request) =>
    request.url.pathname.startsWith("/rest/") ? new Response(null, { status: 204 }) : json(200, {
      id: USER_ID,
    })
  );
  await deps.deleteUserData(USER_ID);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].method, "DELETE");
  assert.equal(calls[0].url.pathname, "/rest/v1/ai_usage");
  assert.equal(calls[0].url.searchParams.get("user_id"), `eq.${USER_ID}`);
  assert.equal(calls[1].method, "DELETE");
  assert.equal(calls[1].url.pathname, `/auth/v1/admin/users/${USER_ID}`);
});

Deno.test("deleteUserData treats an already-deleted auth user as done", async () => {
  const { deps } = setup((request) =>
    request.url.pathname.startsWith("/rest/") ? new Response(null, { status: 204 }) : json(404, {
      code: 404,
      error_code: "user_not_found",
      msg: "User not found",
    })
  );
  await deps.deleteUserData(USER_ID);
});

Deno.test("deleteUserData fails loudly when either delete fails", async () => {
  const usageFails = setup(() => json(500, { code: "XX000", message: "boom" }));
  await assert.rejects(
    usageFails.deps.deleteUserData(USER_ID),
    DependencyError,
  );
  assert.equal(
    usageFails.calls.length,
    1,
    "the auth user is kept if usage rows couldn't be deleted",
  );

  const authFails = setup((request) =>
    request.url.pathname.startsWith("/rest/")
      ? new Response(null, { status: 204 })
      : json(500, { code: 500, msg: "boom" })
  );
  await assert.rejects(authFails.deps.deleteUserData(USER_ID), DependencyError);
});

Deno.test("SUPABASE_SECRET_KEY is used when the service role key isn't set", async () => {
  const { deps, calls } = setup(() => json(200, true), {
    SUPABASE_URL: URL_BASE,
    SUPABASE_SECRET_KEY: "sb_secret_test",
  });
  await deps.consumeQuota(USER_ID, { perUser: 1, global: 1 });
  assert.equal(calls[0].headers.get("apikey"), "sb_secret_test");
});

Deno.test("missing Supabase settings throw instead of guessing", async () => {
  const { deps, calls } = setup(() => json(200, true), {});
  await assert.rejects(deps.verifyUser("token"), DependencyError);
  assert.equal(calls.length, 0);
});

Deno.test("serverKey prefers the service role key, then the secret key, then SUPABASE_SECRET_KEYS", () => {
  const from = (values: Record<string, string>) => serverKey((name) => values[name]);
  assert.equal(
    from({ SUPABASE_SERVICE_ROLE_KEY: "a", SUPABASE_SECRET_KEY: "b" }),
    "a",
  );
  assert.equal(
    from({ SUPABASE_SECRET_KEY: "b", SUPABASE_SECRET_KEYS: '{"default":"c"}' }),
    "b",
  );
  assert.equal(
    from({ SUPABASE_SECRET_KEYS: '{"other":"d","default":"c"}' }),
    "c",
  );
  assert.equal(from({ SUPABASE_SECRET_KEYS: '{"other":"d"}' }), "d");
  assert.equal(from({ SUPABASE_SECRET_KEYS: "not json" }), undefined);
  assert.equal(from({ SUPABASE_SECRET_KEYS: "[]" }), undefined);
  assert.equal(from({}), undefined);
});
