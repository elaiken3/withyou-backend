// Tests the real Anthropic SDK call path against a fake fetch: no request leaves the process.

import assert from "node:assert/strict";
import {
  createClaudeCaller,
  DEFAULT_MODEL,
  SERVER_FALLBACK_BETA,
  supportsServerFallback,
} from "./claude.ts";
import { type ClaudeRequest, UpstreamError } from "./handler.ts";

interface Captured {
  url: string;
  headers: Headers;
  body: Record<string, unknown>;
}

const REQUEST: ClaudeRequest = {
  task: "break_down",
  system: "stable system prompt",
  user: '<request_data>\n{"title":"Clean the kitchen"}\n</request_data>',
  schema: {
    type: "object",
    additionalProperties: false,
    required: ["steps"],
    properties: { steps: { type: "array", items: { type: "string" } } },
  },
};

function message(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id: "msg_test",
    type: "message",
    role: "assistant",
    model: DEFAULT_MODEL,
    content: [{
      type: "text",
      text: '{"steps":["Wipe the counter","Rinse one cup"]}',
    }],
    stop_reason: "end_turn",
    stop_sequence: null,
    stop_details: null,
    usage: { input_tokens: 120, output_tokens: 40 },
    ...overrides,
  };
}

function fakeFetch(
  respond: (captured: Captured) => Response | Promise<Response>,
): { fetch: typeof fetch; calls: Captured[] } {
  const calls: Captured[] = [];
  const fake = async (input: string | URL | Request, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    const headers = new Headers(init?.headers);
    const body = JSON.parse(String(init?.body ?? "{}"));
    const captured = { url, headers, body };
    calls.push(captured);
    return await respond(captured);
  };
  return { fetch: fake as typeof fetch, calls };
}

function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json",
      "x-should-retry": "false",
      ...headers,
    },
  });
}

function envWith(values: Record<string, string>) {
  const env: Record<string, string> = {
    ANTHROPIC_API_KEY: "sk-test",
    ...values,
  };
  return (name: string) => env[name];
}

async function upstreamKind(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    assert.ok(
      error instanceof UpstreamError,
      `expected UpstreamError, got ${error}`,
    );
    return error.kind;
  }
  throw new Error("expected the call to fail");
}

Deno.test("supportsServerFallback: Opus 5.x, Fable 5.x and Sonnet 5.5 only", () => {
  for (
    const model of [
      "claude-opus-5-5",
      "claude-opus-5",
      "claude-fable-5-1",
      "claude-fable-5",
      "claude-sonnet-5-5",
    ]
  ) {
    assert.ok(supportsServerFallback(model), model);
  }
  for (
    const model of [
      "claude-haiku-5-5",
      "claude-sonnet-5",
      "claude-opus-4-8",
      "claude-sonnet-4-6",
      "",
    ]
  ) {
    assert.ok(!supportsServerFallback(model), model);
  }
});

Deno.test("default model: beta endpoint with server-side fallback, low effort and a JSON schema", async () => {
  const { fetch, calls } = fakeFetch(() => jsonResponse(200, message()));
  const call = createClaudeCaller(
    envWith({ ANTHROPIC_BASE_URL: "http://claude.test" }),
    { fetch },
  );
  const result = await call(REQUEST);
  assert.deepEqual(result, { steps: ["Wipe the counter", "Rinse one cup"] });

  assert.equal(calls.length, 1);
  const [{ url, headers, body }] = calls;
  assert.equal(new URL(url).origin, "http://claude.test");
  assert.equal(new URL(url).pathname, "/v1/messages");
  assert.equal(headers.get("x-api-key"), "sk-test");
  assert.ok(
    headers.get("anthropic-beta")?.split(",").includes(SERVER_FALLBACK_BETA),
  );
  assert.equal(body.model, "claude-opus-5-5");
  assert.equal(body.max_tokens, 16000);
  assert.equal(body.fallbacks, "default");
  assert.equal(body.system, REQUEST.system);
  assert.deepEqual(body.messages, [{ role: "user", content: REQUEST.user }]);
  assert.deepEqual(body.output_config, {
    effort: "low",
    format: { type: "json_schema", schema: REQUEST.schema },
  });
  for (
    const forbidden of [
      "thinking",
      "temperature",
      "top_p",
      "top_k",
      "betas",
      "stream",
    ]
  ) {
    assert.ok(!(forbidden in body), `${forbidden} must not be sent`);
  }
});

Deno.test("CLAUDE_MODEL=claude-haiku-5-5 uses the plain endpoint without fallbacks", async () => {
  const { fetch, calls } = fakeFetch(() =>
    jsonResponse(200, message({ model: "claude-haiku-5-5" }))
  );
  const call = createClaudeCaller(
    envWith({ CLAUDE_MODEL: "claude-haiku-5-5" }),
    { fetch },
  );
  await call(REQUEST);
  const [{ headers, body }] = calls;
  assert.equal(body.model, "claude-haiku-5-5");
  assert.equal(headers.get("anthropic-beta"), null);
  assert.ok(!("fallbacks" in body));
  assert.deepEqual(body.output_config, {
    effort: "low",
    format: { type: "json_schema", schema: REQUEST.schema },
  });
});

Deno.test("the answer is the first text block, after thinking and fallback blocks", async () => {
  const { fetch } = fakeFetch(() =>
    jsonResponse(
      200,
      message({
        model: "claude-opus-4-8",
        content: [
          { type: "thinking", thinking: "", signature: "sig" },
          {
            type: "fallback",
            from: { model: "claude-opus-5-5" },
            to: { model: "claude-opus-4-8" },
          },
          { type: "text", text: '{"steps":["A","B"]}' },
          { type: "text", text: "not json" },
        ],
      }),
    )
  );
  const call = createClaudeCaller(envWith({}), { fetch });
  assert.deepEqual(await call(REQUEST), { steps: ["A", "B"] });
});

Deno.test("stop reasons: refusal, max_tokens and others are upstream errors", async () => {
  const cases: [Record<string, unknown>, string][] = [
    [{
      stop_reason: "refusal",
      content: [],
      stop_details: { type: "refusal", category: "cyber", explanation: null },
    }, "refusal"],
    [{
      stop_reason: "refusal",
      content: [{ type: "text", text: '{"steps":["A","B"]}' }],
    }, "refusal"],
    [{
      stop_reason: "max_tokens",
      content: [{ type: "text", text: '{"steps":["A"' }],
    }, "max_tokens"],
    [{ stop_reason: "model_context_window_exceeded" }, "unexpected_stop"],
    [
      { content: [{ type: "text", text: "Here are your steps: 1. Wipe" }] },
      "invalid_json",
    ],
    [
      { content: [{ type: "thinking", thinking: "", signature: "sig" }] },
      "no_text",
    ],
  ];
  for (const [overrides, kind] of cases) {
    const { fetch } = fakeFetch(() => jsonResponse(200, message(overrides)));
    const call = createClaudeCaller(envWith({}), { fetch });
    assert.equal(
      await upstreamKind(call(REQUEST)),
      kind,
      JSON.stringify(overrides),
    );
  }
});

Deno.test("HTTP errors map to upstream kinds and never leak provider text", async () => {
  const cases: [number, string, string][] = [
    [429, "rate_limit_error", "rate_limited"],
    [401, "authentication_error", "auth"],
    [400, "invalid_request_error", "bad_request"],
    [403, "permission_error", "api_error"],
    [404, "not_found_error", "api_error"],
    [500, "api_error", "api_error"],
    [529, "overloaded_error", "api_error"],
  ];
  for (const [status, type, kind] of cases) {
    const { fetch, calls } = fakeFetch(() =>
      jsonResponse(status, {
        type: "error",
        error: { type, message: "provider detail Zq7" },
      })
    );
    const call = createClaudeCaller(envWith({}), { fetch });
    try {
      await call(REQUEST);
      assert.fail("expected an error");
    } catch (error) {
      assert.ok(error instanceof UpstreamError);
      assert.equal(error.kind, kind, `HTTP ${status}`);
      assert.ok(!error.message.includes("Zq7"));
    }
    assert.equal(calls.length, 1, "x-should-retry: false is honored");
  }
});

Deno.test("a retryable failure is retried once (maxRetries 1)", async () => {
  const { fetch, calls } = fakeFetch(() =>
    jsonResponse(529, {
      type: "error",
      error: { type: "overloaded_error", message: "busy" },
    }, {
      "x-should-retry": "true",
      "retry-after-ms": "1",
    })
  );
  const call = createClaudeCaller(envWith({}), { fetch });
  assert.equal(await upstreamKind(call(REQUEST)), "api_error");
  assert.equal(calls.length, 2);
});

Deno.test("an unreachable API is a connection error", async () => {
  const { fetch } = fakeFetch(() => {
    throw new TypeError("connection refused");
  });
  const call = createClaudeCaller(envWith({}), { fetch, maxRetries: 0 });
  assert.equal(await upstreamKind(call(REQUEST)), "connection");
});

Deno.test("a slow API is a timeout", async () => {
  const { fetch } = fakeFetch(() => new Promise<Response>(() => {}));
  const slowFetch =
    ((input: string | URL | Request, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
        );
        void fetch(input, init);
      })) as typeof globalThis.fetch;
  const call = createClaudeCaller(envWith({}), {
    fetch: slowFetch,
    timeoutMs: 20,
    maxRetries: 0,
  });
  assert.equal(await upstreamKind(call(REQUEST)), "timeout");
});

Deno.test("a new API key is picked up without a restart", async () => {
  const { fetch, calls } = fakeFetch(() => jsonResponse(200, message()));
  const env: Record<string, string> = { ANTHROPIC_API_KEY: "sk-one" };
  const call = createClaudeCaller((name) => env[name], { fetch });
  await call(REQUEST);
  await call(REQUEST);
  env.ANTHROPIC_API_KEY = "sk-two";
  await call(REQUEST);
  assert.deepEqual(calls.map((c) => c.headers.get("x-api-key")), [
    "sk-one",
    "sk-one",
    "sk-two",
  ]);
});

Deno.test("no API key is an upstream auth error, without a request", async () => {
  const { fetch, calls } = fakeFetch(() => jsonResponse(200, message()));
  const call = createClaudeCaller(() => undefined, { fetch });
  assert.equal(await upstreamKind(call(REQUEST)), "auth");
  assert.equal(calls.length, 0);
});
