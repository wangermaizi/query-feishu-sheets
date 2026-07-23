import assert from "node:assert/strict";
import test from "node:test";

import {
  extractUserInput,
  preloadSheetQuery,
  prefixBridgePrompt,
  prepareCodexArgs,
  selectSheetProfile,
} from "../../bridge/codex-wrapper.mjs";

const runtime = { model: "gpt-5.6-sol", reasoningEffort: "ultra" };

test("bridge wrapper enforces the configured model and keeps rules enabled", () => {
  const result = prepareCodexArgs(
    [
      "exec",
      "--json",
      "--sandbox",
      "read-only",
      "--model",
      "gpt-5",
      "--ignore-rules",
      "-",
    ],
    runtime,
  );

  assert.equal(result.includes("--ignore-rules"), false);
  assert.equal(result[result.indexOf("--model") + 1], "gpt-5.6-sol");
  const reasoningIndex = result.indexOf("-c");
  assert.equal(result[reasoningIndex + 1], 'model_reasoning_effort="ultra"');
  assert.equal(result.at(-1), "-");
});

test("bridge wrapper rejects unrestricted filesystem access", () => {
  assert.throws(
    () => prepareCodexArgs(["exec", "--sandbox", "danger-full-access", "-"], runtime),
    /禁止 danger-full-access/u,
  );
});

test("bridge wrapper injects the requirement skill protocol", () => {
  const prompt = prefixBridgePrompt("<bridge_context>{}</bridge_context>\n修复导出功能");
  assert.match(prompt, /feishu-requirement-orchestrator/u);
  assert.match(prompt, /lark-bridge-channel\.md/u);
  assert.match(prompt, /修复导出功能/u);
});

test("bridge wrapper selects an explicitly named sheet from current user input", () => {
  const prompt = [
    '<quoted_messages>{"text":"上一轮提到了新入职"}</quoted_messages>',
    '<user_input>{"text":"帮我查询本周新应收需求"}</user_input>',
  ].join("\n");
  const profiles = {
    "new-onboarding": { display_name: "新入职管理", aliases: ["新入职"] },
    "new-receivables": { display_name: "新应收需求跟进", aliases: ["新应收"] },
  };
  assert.equal(extractUserInput(prompt), "帮我查询本周新应收需求");
  assert.equal(selectSheetProfile(extractUserInput(prompt), profiles), "new-receivables");
});

test("bridge wrapper does not repeat a sheet query for a confirmation reply", () => {
  const prompt = [
    '<quoted_messages>{"text":"是否查询新应收需求表"}</quoted_messages>',
    '<user_input>{"text":"确认"}</user_input>',
  ].join("\n");
  assert.equal(
    selectSheetProfile(extractUserInput(prompt), {
      "new-receivables": { aliases: ["新应收"] },
    }),
    null,
  );
});

test("bridge wrapper preloads a matched sheet query outside Codex", async () => {
  const fs = await import("node:fs");
  const os = await import("node:os");
  const path = await import("node:path");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "bridge-query-"));
  fs.writeFileSync(
    path.join(directory, "profiles.json"),
    JSON.stringify({ profiles: { receivables: { aliases: ["新应收"] } } }),
  );
  const calls = [];
  const context = await preloadSheetQuery(
    '<user_input>{"text":"查询新应收需求"}</user_input>',
    { directory, uvPath: "uv-test" },
    async (...args) => {
      calls.push(args);
      return { stdout: JSON.stringify({ count: 1, items: [{ title: "测试" }] }) };
    },
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "uv-test");
  assert.match(context, /source="bridge_preflight"/u);
  assert.match(context, /"count":1/u);
  fs.rmSync(directory, { recursive: true, force: true });
});
