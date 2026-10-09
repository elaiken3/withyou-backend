// The function's deno.json is what Supabase bundles with; the repo-root deno.json lets `deno check`,
// `deno lint` and `deno test` run from the repo root. Their pinned versions must match.

import assert from "node:assert/strict";

async function readJson(relative: string): Promise<Record<string, unknown>> {
  return JSON.parse(
    await Deno.readTextFile(new URL(relative, import.meta.url)),
  );
}

Deno.test("dependency pins match between the function and the repo root", async () => {
  const fn = await readJson("./deno.json");
  const root = await readJson("../../../deno.json");
  assert.deepEqual(root.imports, fn.imports);
});

Deno.test("dependencies are pinned to exact npm versions", async () => {
  const fn = await readJson("./deno.json");
  for (
    const [name, specifier] of Object.entries(
      fn.imports as Record<string, string>,
    )
  ) {
    assert.match(
      specifier,
      /^npm:@?[a-z0-9./_-]+@\d+\.\d+\.\d+$/,
      `${name} is not pinned exactly`,
    );
  }
});

Deno.test("the gateway's JWT check is off for ai (the function checks tokens itself)", async () => {
  const config = await Deno.readTextFile(
    new URL("../../config.toml", import.meta.url),
  );
  assert.match(config, /\[functions\.ai\]\s*\nverify_jwt = false/);
  assert.match(config, /\nenable_anonymous_sign_ins = true/);
  assert.match(config, /\nproject_id = "withyou"/);
});
