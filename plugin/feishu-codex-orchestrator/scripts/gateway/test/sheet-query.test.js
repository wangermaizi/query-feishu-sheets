import assert from "node:assert/strict";
import test from "node:test";

import { parseQueryResult, SheetQueryRunner } from "../src/sheet-query.js";

test("validates the sheet query payload", () => {
  assert.equal(parseQueryResult('{"count":1,"items":[{"id":"1"}]}').count, 1);
  assert.throws(() => parseQueryResult('{"count":2,"items":[]}'), /数量不一致/u);
});

test("runs the read-only query helper without opening a window", async () => {
  let invocation;
  const execute = async (...args) => {
    invocation = args;
    return { stdout: '{"count":0,"items":[]}' };
  };
  const runner = new SheetQueryRunner(
    { uvPath: "C:\\tools\\uv.exe", directory: "C:\\config" },
    execute,
  );

  const result = await runner.query("product");

  assert.equal(result.count, 0);
  assert.equal(invocation[0], "C:\\tools\\uv.exe");
  assert.deepEqual(invocation[1].slice(-3), ["query", "--profile", "product"]);
  assert.equal(invocation[2].windowsHide, true);
  assert.equal(invocation[2].env.FEISHU_ORCHESTRATOR_CONFIG_DIR, "C:\\config");
});
