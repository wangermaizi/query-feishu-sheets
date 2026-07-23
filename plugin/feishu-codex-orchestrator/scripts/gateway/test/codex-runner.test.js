import assert from "node:assert/strict";
import test from "node:test";

import { taskSandbox } from "../src/codex-runner.js";

test("keeps workspace write access after an implementation question", () => {
  assert.equal(taskSandbox({ stage: "analysis_confirmation", write_authorized: false }), "read-only");
  assert.equal(taskSandbox({ stage: "branch_choice", write_authorized: false }), "workspace-write");
  assert.equal(taskSandbox({ stage: "question", write_authorized: true }), "workspace-write");
  assert.equal(taskSandbox({ stage: "question", write_authorized: false }), "read-only");
});
