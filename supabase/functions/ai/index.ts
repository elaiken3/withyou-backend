// Entry point for the `ai` Edge Function. Wiring only; the logic lives in handler.ts.

import { createClaudeCaller } from "./claude.ts";
import { createHandler } from "./handler.ts";
import { createSupabaseDeps } from "./supabase.ts";

function env(name: string): string | undefined {
  const value = Deno.env.get(name);
  return value === undefined || value.trim() === "" ? undefined : value;
}

const supabase = createSupabaseDeps(env);

const handler = createHandler({
  verifyUser: supabase.verifyUser,
  consumeQuota: supabase.consumeQuota,
  deleteUserData: supabase.deleteUserData,
  callClaude: createClaudeCaller(env),
  now: () => new Date(),
  env,
  // Task, status, latency and error class only. Never request text or model output.
  log: (entry) => console.log(JSON.stringify({ fn: "ai", ...entry })),
});

Deno.serve(handler);
