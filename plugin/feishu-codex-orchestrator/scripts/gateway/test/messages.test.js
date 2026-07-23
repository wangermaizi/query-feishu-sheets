import assert from "node:assert/strict";
import test from "node:test";

import {
  canControlTask,
  messageReferences,
  messageText,
  taskIdFromMessage,
} from "../src/messages.js";

test("extracts text and removes Feishu mention placeholders", () => {
  const message = {
    message_type: "text",
    content: JSON.stringify({ text: "@_user_1 修复导出失败" }),
    mentions: [{ key: "@_user_1" }],
  };
  assert.equal(messageText(message), "修复导出失败");
});

test("reply lookup uses parent, root and thread ids", () => {
  assert.deepEqual(
    messageReferences({ parent_id: "p", root_id: "r", thread_id: "t" }),
    ["p", "r", "t"],
  );
});

test("only owner or configured administrator can control a task", () => {
  const task = { owner_open_id: "ou_owner" };
  const config = { adminOpenIds: new Set(["ou_admin"]) };
  assert.equal(canControlTask(task, "ou_owner", config), true);
  assert.equal(canControlTask(task, "ou_admin", config), true);
  assert.equal(canControlTask(task, "ou_other", config), false);
});

test("task id uses Asia Shanghai date and message suffix", () => {
  const value = taskIdFromMessage("om_abcdef123456", new Date("2026-07-22T16:30:00Z"));
  assert.equal(value, "FEISHU-20260723-abcdef123456");
});
