import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { StateStore } from "../src/state-store.js";

function store() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "feishu-gateway-state-"));
  return new StateStore(path.join(directory, "state.json"));
}

test("deduplicates events and resolves a task from bot message id", async () => {
  const value = store();
  assert.equal(await value.claimEvent("evt_1"), true);
  assert.equal(await value.claimEvent("evt_1"), false);
  await value.createTask({ id: "task-1", source_message_id: "om_source", status: "routing" });
  await value.bindMessage("task-1", "om_bot");

  assert.equal((await value.findTaskByMessages(["om_bot"])).id, "task-1");
});

test("marks running tasks interrupted after service restart", async () => {
  const value = store();
  await value.createTask({ id: "task-1", source_message_id: "om_1", status: "running" });
  await value.createTask({ id: "task-2", source_message_id: "om_2", status: "completed" });

  const interrupted = await value.markInterruptedRuns();

  assert.deepEqual(interrupted.map((task) => task.id), ["task-1"]);
  assert.equal((await value.getTask("task-1")).status, "interrupted");
  assert.equal((await value.getTask("task-2")).status, "completed");
});
