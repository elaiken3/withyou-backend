// The one place that talks to Claude, through the official Anthropic SDK.
//
// Every request is a single user message with structured output (a JSON schema), at low effort.
// On models that support it, a refusal is retried server-side on Anthropic's recommended
// fallback model (`fallbacks: "default"`). Errors never carry provider text past this file.

import Anthropic from "@anthropic-ai/sdk";
import { type ClaudeRequest, UpstreamError } from "./handler.ts";

export const DEFAULT_MODEL = "claude-opus-5-5";
export const SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01";
const MAX_TOKENS = 16000;
const TIMEOUT_MS = 25_000;
const MAX_RETRIES = 1;

/**
 * Server-side fallback exists for Opus 5.x, Fable 5.x and Sonnet 5.5. Claude Haiku 5.5 has none,
 * so its requests go out without the beta.
 */
export function supportsServerFallback(model: string): boolean {
  return /^claude-(?:opus|fable)-5(?:-\d+)?$/.test(model) ||
    model === "claude-sonnet-5-5";
}

export interface ClaudeCallerOptions {
  /** For tests: a fake fetch, so no request leaves the process. */
  fetch?: typeof fetch;
  timeoutMs?: number;
  maxRetries?: number;
}

type Message = Anthropic.Message | Anthropic.Beta.BetaMessage;

/** Finds the JSON answer in a response, after checking why the model stopped. */
export function extractJson(message: Message): unknown {
  if (message.stop_reason === "refusal") throw new UpstreamError("refusal");
  if (message.stop_reason === "max_tokens") {
    throw new UpstreamError("max_tokens");
  }
  if (
    message.stop_reason !== "end_turn" &&
    message.stop_reason !== "stop_sequence"
  ) {
    throw new UpstreamError("unexpected_stop");
  }
  // Skip thinking and fallback blocks; the answer is the first text block.
  for (const block of message.content) {
    if (block.type === "text") {
      try {
        return JSON.parse(block.text);
      } catch {
        throw new UpstreamError("invalid_json");
      }
    }
  }
  throw new UpstreamError("no_text");
}

/** Maps SDK errors to an `UpstreamError` kind, most specific first. Anything else is rethrown. */
export function toUpstreamError(error: unknown): unknown {
  if (error instanceof UpstreamError) return error;
  if (error instanceof Anthropic.RateLimitError) {
    return new UpstreamError("rate_limited");
  }
  if (error instanceof Anthropic.AuthenticationError) {
    return new UpstreamError("auth");
  }
  if (error instanceof Anthropic.BadRequestError) {
    return new UpstreamError("bad_request");
  }
  if (error instanceof Anthropic.APIConnectionTimeoutError) {
    return new UpstreamError("timeout");
  }
  if (error instanceof Anthropic.APIConnectionError) {
    return new UpstreamError("connection");
  }
  if (error instanceof Anthropic.APIError) {
    return new UpstreamError("api_error");
  }
  if (error instanceof Anthropic.AnthropicError) {
    return new UpstreamError("sdk_error");
  }
  return error;
}

/**
 * Builds the `callClaude` dependency. Settings are read from the environment on each call:
 * ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL (optional, used by tests) and CLAUDE_MODEL (optional).
 */
export function createClaudeCaller(
  env: (name: string) => string | undefined,
  options: ClaudeCallerOptions = {},
): (request: ClaudeRequest) => Promise<unknown> {
  let cached: { key: string; client: Anthropic } | null = null;

  function client(apiKey: string, baseURL: string | undefined): Anthropic {
    const cacheKey = `${apiKey}\n${baseURL ?? ""}`;
    if (cached?.key !== cacheKey) {
      cached = {
        key: cacheKey,
        client: new Anthropic({
          apiKey,
          baseURL: baseURL ?? undefined,
          timeout: options.timeoutMs ?? TIMEOUT_MS,
          maxRetries: options.maxRetries ?? MAX_RETRIES,
          ...(options.fetch ? { fetch: options.fetch } : {}),
        }),
      };
    }
    return cached.client;
  }

  return async (request) => {
    const apiKey = env("ANTHROPIC_API_KEY");
    if (!apiKey) throw new UpstreamError("auth");
    const anthropic = client(apiKey, env("ANTHROPIC_BASE_URL"));
    const model = env("CLAUDE_MODEL") ?? DEFAULT_MODEL;

    let message: Message;
    try {
      if (supportsServerFallback(model)) {
        message = await anthropic.beta.messages.create({
          model,
          max_tokens: MAX_TOKENS,
          betas: [SERVER_FALLBACK_BETA],
          fallbacks: "default",
          system: request.system,
          messages: [{ role: "user", content: request.user }],
          output_config: {
            effort: "low",
            format: { type: "json_schema", schema: request.schema },
          },
        });
      } else {
        message = await anthropic.messages.create({
          model,
          max_tokens: MAX_TOKENS,
          system: request.system,
          messages: [{ role: "user", content: request.user }],
          output_config: {
            effort: "low",
            format: { type: "json_schema", schema: request.schema },
          },
        });
      }
    } catch (error) {
      throw toUpstreamError(error);
    }
    return extractJson(message);
  };
}
