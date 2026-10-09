// Supabase-backed dependencies for the handler: checking access tokens, the daily quota and
// deleting a person's data. Uses a service-role client, which only ever runs on the server.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { QuotaLimits } from "./handler.ts";

export class DependencyError extends Error {
  constructor(what: string) {
    super(what);
    this.name = `DependencyError_${what}`;
  }
}

export interface SupabaseDeps {
  verifyUser(token: string): Promise<{ id: string } | null>;
  consumeQuota(userId: string, limits: QuotaLimits): Promise<boolean>;
  deleteUserData(userId: string): Promise<void>;
}

function isClientError(status: unknown): boolean {
  return typeof status === "number" && status >= 400 && status < 500;
}

/**
 * The server key: SUPABASE_SERVICE_ROLE_KEY (set for every Edge Function), else SUPABASE_SECRET_KEY,
 * else the "default" entry of SUPABASE_SECRET_KEYS (a JSON object, for projects on the new keys).
 */
export function serverKey(
  env: (name: string) => string | undefined,
): string | undefined {
  const direct = env("SUPABASE_SERVICE_ROLE_KEY") ?? env("SUPABASE_SECRET_KEY");
  if (direct) return direct;
  const keys = env("SUPABASE_SECRET_KEYS");
  if (!keys) return undefined;
  try {
    const parsed: unknown = JSON.parse(keys);
    if (typeof parsed !== "object" || parsed === null) return undefined;
    const record = parsed as Record<string, unknown>;
    if (typeof record.default === "string") return record.default;
    return Object.values(record).find((value): value is string => typeof value === "string");
  } catch {
    return undefined;
  }
}

/** Reads SUPABASE_URL and the server key when first needed. */
export function createSupabaseDeps(
  env: (name: string) => string | undefined,
  options: { fetch?: typeof fetch } = {},
): SupabaseDeps {
  let client: SupabaseClient | null = null;

  function admin(): SupabaseClient {
    if (client) return client;
    const url = env("SUPABASE_URL");
    const key = serverKey(env);
    if (!url || !key) throw new DependencyError("config");
    client = createClient(url, key, {
      auth: {
        persistSession: false,
        autoRefreshToken: false,
        detectSessionInUrl: false,
      },
      ...(options.fetch ? { global: { fetch: options.fetch } } : {}),
    });
    return client;
  }

  return {
    async verifyUser(token) {
      const { data, error } = await admin().auth.getUser(token);
      if (error) {
        // 4xx: the token is wrong, expired or its user is gone. Anything else: auth is unreachable.
        if (isClientError(error.status)) return null;
        throw new DependencyError("auth");
      }
      return data.user ? { id: data.user.id } : null;
    },

    async consumeQuota(userId, limits) {
      const { data, error } = await admin().rpc("ai_consume_quota", {
        p_user: userId,
        p_user_limit: limits.perUser,
        p_global_limit: limits.global,
      });
      if (error) throw new DependencyError("quota");
      return data === true;
    },

    async deleteUserData(userId) {
      const { error } = await admin().from("ai_usage").delete().eq(
        "user_id",
        userId,
      );
      if (error) throw new DependencyError("delete_usage");
      const { error: authError } = await admin().auth.admin.deleteUser(userId);
      // 404: already gone, which is what the person asked for.
      if (authError && authError.status !== 404) {
        throw new DependencyError("delete_user");
      }
    },
  };
}
