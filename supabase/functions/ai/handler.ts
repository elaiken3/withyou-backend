// Request handling for the `ai` Edge Function, with every outside dependency injected so it can
// be tested without a network. index.ts wires in the real Supabase and Claude clients.
//
// Privacy rule for this file: request text and model output are never logged. Log entries carry
// only the task name, the HTTP status, the latency and a short error class.

import { AI_TASKS, InputError, isAiTask, isRecord } from "./tasks.ts";
import type { AiTaskName, JsonSchema } from "./tasks.ts";

export const MAX_BODY_BYTES = 16 * 1024;
export const DEFAULT_DAILY_LIMIT_PER_USER = 60;
export const DEFAULT_DAILY_LIMIT_GLOBAL = 3000;

export type TaskName = AiTaskName | "delete_me";

export interface QuotaLimits {
  perUser: number;
  global: number;
}

/** What the handler asks Claude for: a system prompt, one user message and a JSON schema. */
export interface ClaudeRequest {
  task: AiTaskName;
  system: string;
  user: string;
  schema: JsonSchema;
}

export interface LogEntry {
  task: TaskName | "unknown";
  status: number;
  latency_ms: number;
  error?: string;
}

export interface Deps {
  /** The signed-in user for an access token, or `null` if the token isn't valid. Throws if auth is unreachable. */
  verifyUser(token: string): Promise<{ id: string } | null>;
  /** Counts one request for today (UTC). `false` (and nothing counted) when a limit is reached. */
  consumeQuota(userId: string, limits: QuotaLimits): Promise<boolean>;
  /** Deletes the person's usage rows and their anonymous auth user. */
  deleteUserData(userId: string): Promise<void>;
  /** Returns Claude's answer parsed as JSON. Throws `UpstreamError` for refusals and API failures. */
  callClaude(request: ClaudeRequest): Promise<unknown>;
  now(): Date;
  env(name: string): string | undefined;
  log(entry: LogEntry): void;
}

export type UpstreamErrorKind =
  | "refusal"
  | "max_tokens"
  | "unexpected_stop"
  | "no_text"
  | "invalid_json"
  | "rate_limited"
  | "auth"
  | "bad_request"
  | "timeout"
  | "connection"
  | "api_error"
  | "sdk_error";

/** A failure on Claude's side. Never carries provider text, only a kind. */
export class UpstreamError extends Error {
  readonly kind: UpstreamErrorKind;

  constructor(kind: UpstreamErrorKind) {
    super(`upstream ${kind}`);
    this.name = "UpstreamError";
    this.kind = kind;
  }
}

type ErrorCode =
  | "invalid_input"
  | "unauthorized"
  | "method_not_allowed"
  | "too_large"
  | "quota_exceeded"
  | "upstream_error"
  | "not_configured"
  | "internal";

const MESSAGES: Record<ErrorCode, string> = {
  invalid_input: "That request didn’t look right.",
  unauthorized: "Sign-in is missing or has expired.",
  method_not_allowed: "Please use POST.",
  too_large: "That request is too large.",
  quota_exceeded:
    "That’s all the cloud AI for today. It’s back tomorrow, and the simple version still works.",
  upstream_error: "Cloud AI isn’t available right now. The simple version still works.",
  not_configured: "Cloud AI isn’t set up on this server.",
  internal: "Something went wrong on our side.",
};

const REFUSAL_MESSAGE = "Cloud AI can’t help with this one. The simple version still works.";

/** Seconds from `now` until the next midnight UTC, when the daily counters start over. */
export function secondsUntilUtcMidnight(now: Date): number {
  const next = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + 1,
  );
  return Math.max(1, Math.ceil((next - now.getTime()) / 1000));
}

/** A non-negative whole number from the environment, or the default when unset or invalid. */
export function readLimit(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  const trimmed = value.trim();
  if (!/^\d{1,9}$/.test(trimmed)) return fallback;
  return Number(trimmed);
}

function json(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...headers,
    },
  });
}

function errorResponse(
  status: number,
  code: ErrorCode,
  message: string = MESSAGES[code],
  headers: Record<string, string> = {},
): Response {
  return json(status, { ok: false, error: code, message }, headers);
}

/** Reads at most `limit` bytes; `null` when the body is larger. */
async function readBody(
  request: Request,
  limit: number,
): Promise<Uint8Array | null> {
  const declared = request.headers.get("content-length");
  if (declared !== null && Number(declared) > limit) return null;
  if (request.body === null) return new Uint8Array(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

function bearerToken(request: Request): string | null {
  const header = request.headers.get("authorization");
  if (!header) return null;
  const match = /^Bearer\s+(\S+)\s*$/i.exec(header);
  return match ? match[1] : null;
}

/** A short, fixed error class for logs. Never an error message, which could quote request text. */
function errorClass(error: unknown): string {
  const name = error instanceof Error ? error.name : typeof error;
  return name.replace(/[^A-Za-z0-9_]/g, "").slice(0, 40) || "unknown";
}

export function createHandler(
  deps: Deps,
): (request: Request) => Promise<Response> {
  return async (request) => {
    const started = Date.now();
    let task: LogEntry["task"] = "unknown";
    let errorTag: string | undefined;

    const finish = (response: Response, error?: string): Response => {
      const entry: LogEntry = {
        task,
        status: response.status,
        latency_ms: Date.now() - started,
      };
      if (error) entry.error = error;
      deps.log(entry);
      return response;
    };

    try {
      if (request.method !== "POST") {
        return finish(
          errorResponse(405, "method_not_allowed", undefined, {
            allow: "POST",
          }),
          "method_not_allowed",
        );
      }

      const bytes = await readBody(request, MAX_BODY_BYTES);
      if (bytes === null) {
        return finish(errorResponse(413, "too_large"), "too_large");
      }

      const token = bearerToken(request);
      if (token === null) {
        return finish(errorResponse(401, "unauthorized"), "unauthorized");
      }
      errorTag = "auth_check";
      const user = await deps.verifyUser(token);
      errorTag = undefined;
      if (user === null) {
        return finish(errorResponse(401, "unauthorized"), "unauthorized");
      }

      let body: unknown;
      try {
        body = JSON.parse(
          new TextDecoder("utf-8", { fatal: true }).decode(bytes),
        );
      } catch {
        return finish(
          errorResponse(400, "invalid_input", "The body should be JSON."),
          "invalid_json",
        );
      }
      if (!isRecord(body)) {
        return finish(
          errorResponse(
            400,
            "invalid_input",
            "The body should be a JSON object.",
          ),
          "invalid_input",
        );
      }

      const name = body.task;
      if (name === "delete_me") {
        task = "delete_me";
        errorTag = "delete";
        await deps.deleteUserData(user.id);
        errorTag = undefined;
        return finish(
          json(200, { ok: true, task: "delete_me", result: { deleted: true } }),
        );
      }
      if (!isAiTask(name)) {
        return finish(
          errorResponse(400, "invalid_input", "Unknown task."),
          "unknown_task",
        );
      }
      task = name;

      if (!isRecord(body.input)) {
        return finish(
          errorResponse(400, "invalid_input", "input should be an object."),
          "invalid_input",
        );
      }
      let prepared;
      try {
        prepared = AI_TASKS[name](body.input);
      } catch (error) {
        if (error instanceof InputError) {
          return finish(
            errorResponse(400, "invalid_input", error.message),
            "invalid_input",
          );
        }
        throw error;
      }

      if (!deps.env("ANTHROPIC_API_KEY")) {
        return finish(errorResponse(503, "not_configured"), "not_configured");
      }

      const limits: QuotaLimits = {
        perUser: readLimit(
          deps.env("AI_DAILY_LIMIT_PER_USER"),
          DEFAULT_DAILY_LIMIT_PER_USER,
        ),
        global: readLimit(
          deps.env("AI_DAILY_LIMIT_GLOBAL"),
          DEFAULT_DAILY_LIMIT_GLOBAL,
        ),
      };
      errorTag = "quota";
      const allowed = await deps.consumeQuota(user.id, limits);
      errorTag = undefined;
      if (!allowed) {
        return finish(
          errorResponse(429, "quota_exceeded", undefined, {
            "retry-after": String(secondsUntilUtcMidnight(deps.now())),
          }),
          "quota_exceeded",
        );
      }

      let raw: unknown;
      try {
        raw = await deps.callClaude({
          task: name,
          system: prepared.system,
          user: prepared.user,
          schema: prepared.schema,
        });
      } catch (error) {
        if (error instanceof UpstreamError) {
          const message = error.kind === "refusal" ? REFUSAL_MESSAGE : MESSAGES.upstream_error;
          return finish(
            errorResponse(502, "upstream_error", message),
            `upstream_${error.kind}`,
          );
        }
        throw error;
      }

      const result = prepared.parseOutput(raw);
      if (result === null) {
        return finish(errorResponse(502, "upstream_error"), "invalid_output");
      }
      return finish(json(200, { ok: true, task: name, result }));
    } catch (error) {
      const where = errorTag ? `${errorTag}_` : "";
      return finish(
        errorResponse(500, "internal"),
        `internal_${where}${errorClass(error)}`,
      );
    }
  };
}
