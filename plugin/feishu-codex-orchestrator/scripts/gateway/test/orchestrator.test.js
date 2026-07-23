import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { GatewayOrchestrator } from "../src/orchestrator.js";
import { StateStore } from "../src/state-store.js";

function event({
  eventId = "evt_1",
  messageId = "om_source",
  text = "产品需求表增加导出功能",
  openId = "ou_owner",
  parentId,
} = {}) {
  return {
    event_id: eventId,
    sender: { sender_type: "user", sender_id: { open_id: openId } },
    message: {
      message_id: messageId,
      parent_id: parentId,
      chat_id: "oc_allowed",
      chat_type: "group",
      message_type: "text",
      content: JSON.stringify({ text: `@_user_1 ${text}` }),
      mentions: [{ key: "@_user_1", name: "机器人" }],
    },
  };
}

function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "gateway-orchestrator-"));
  const store = new StateStore(path.join(directory, "state.json"));
  const sent = [];
  let nextMessage = 0;
  const transport = {
    async replyCard(messageId, card) {
      const botMessageId = `om_bot_${++nextMessage}`;
      sent.push({ messageId, card, botMessageId });
      return botMessageId;
    },
  };
  const runner = {
    starts: [],
    continuations: [],
    async classifyRequirementSource() {
      return { decision: "manual", reason: "具体修改内容" };
    },
    async routeRequirement() {
      return {
        decision: "selected",
        selected_candidate_id: "product",
        candidate_ids: [],
        reason: "产品语义明确",
      };
    },
    async routeRepository() {
      return {
        decision: "selected",
        selected_candidate_id: "default",
        candidate_ids: [],
        reason: "唯一仓库",
      };
    },
    async startTask(task, onThreadId) {
      this.starts.push(task.id);
      await onThreadId("thr_1");
      return {
        status: "awaiting_user",
        stage: "analysis_confirmation",
        card_title: "产品平台需求分析",
        card_markdown: "分析内容",
        next_action: "回复确认、修改或取消",
        write_authorized: false,
      };
    },
    async continueTask(task, text) {
      this.continuations.push({ taskId: task.id, threadId: task.codex_thread_id, text });
      return {
        status: "awaiting_user",
        stage: "branch_choice",
        card_title: "请选择分支",
        card_markdown: "分支方案",
        next_action: "回复使用当前分支或创建新分支",
        write_authorized: false,
      };
    },
  };
  const sheetQuery = {
    calls: [],
    async query(profileId) {
      this.calls.push(profileId);
      return {
        query: { profile: profileId, filters: [{ column: "状态", operator: "equals" }] },
        count: 1,
        items: [{ 序号: "REQ-1", 模块: "产品", 反馈: "增加导出功能" }],
      };
    },
  };
  const config = {
    allowedChatIds: new Set(["oc_allowed"]),
    adminOpenIds: new Set(["ou_admin"]),
    chatDefaults: {},
    requireGroupMention: true,
    routes: [
      {
        profile_id: "product",
        display_name: "产品需求表",
        aliases: ["产品需求"],
        description: "产品研发",
        repositories: [
          {
            repository_id: "default",
            display_name: "产品平台",
            aliases: [],
            description: "",
            path: directory,
            project_name: "产品平台",
          },
        ],
        project_name: "产品平台",
      },
      {
        profile_id: "support",
        display_name: "客服需求表",
        aliases: ["客服需求"],
        description: "客户支持",
        repositories: [
          {
            repository_id: "default",
            display_name: "客服平台",
            aliases: [],
            description: "",
            path: directory,
            project_name: "客服平台",
          },
        ],
        project_name: "客服平台",
      },
    ],
  };
  const logger = { info() {}, warn() {}, error() {} };
  const orchestrator = new GatewayOrchestrator({
    config,
    store,
    runner,
    sheetQuery,
    transport,
    logger,
  });
  return { orchestrator, store, runner, sheetQuery, sent };
}

test("new bot mention starts one Codex thread and binds response messages", async () => {
  const { orchestrator, store, runner, sheetQuery, sent } = fixture();
  await orchestrator.handleEvent(event());
  await orchestrator.waitForIdle();

  const tasks = await store.listTasks();
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].codex_thread_id, "thr_1");
  assert.equal(tasks[0].status, "awaiting_user");
  assert.equal(runner.starts.length, 1);
  assert.deepEqual(sheetQuery.calls, []);
  assert.equal(sent.length, 2);
  assert.equal((await store.findTaskByMessages([sent[1].botMessageId])).id, tasks[0].id);
});

test("quoted reply resumes the same Codex thread", async () => {
  const { orchestrator, store, runner, sent } = fixture();
  await orchestrator.handleEvent(event());
  await orchestrator.waitForIdle();
  const task = (await store.listTasks())[0];
  const analysisCard = sent.at(-1).botMessageId;

  await orchestrator.handleEvent(
    event({
      eventId: "evt_2",
      messageId: "om_reply",
      text: "确认，使用当前分支",
      parentId: analysisCard,
    }),
  );
  await orchestrator.waitForIdle();

  assert.deepEqual(runner.continuations, [
    { taskId: task.id, threadId: "thr_1", text: "确认，使用当前分支" },
  ]);
  assert.equal((await store.getTask(task.id)).stage, "branch_choice");
});

test("other group members cannot control the task", async () => {
  const { orchestrator, store, runner, sent } = fixture();
  await orchestrator.handleEvent(event());
  await orchestrator.waitForIdle();
  const task = (await store.listTasks())[0];
  const analysisCard = sent.at(-1).botMessageId;

  await orchestrator.handleEvent(
    event({
      eventId: "evt_2",
      messageId: "om_reply",
      text: "确认",
      openId: "ou_other",
      parentId: analysisCard,
    }),
  );
  await orchestrator.waitForIdle();

  assert.equal(runner.continuations.length, 0);
  assert.equal((await store.getTask(task.id)).stage, "analysis_confirmation");
  assert.equal(sent.at(-1).card.header.title.content, "无权操作此任务");
});

test("duplicate Feishu event does not start duplicate tasks", async () => {
  const { orchestrator, store, runner } = fixture();
  await orchestrator.handleEvent(event());
  await orchestrator.handleEvent(event());
  await orchestrator.waitForIdle();

  assert.equal((await store.listTasks()).length, 1);
  assert.equal(runner.starts.length, 1);
});

test("sheet request queries the selected profile before starting Codex", async () => {
  const { orchestrator, store, runner, sheetQuery } = fixture();
  await orchestrator.handleEvent(event({ text: "获取产品需求表里的待处理需求" }));
  await orchestrator.waitForIdle();

  const task = (await store.listTasks())[0];
  assert.deepEqual(sheetQuery.calls, ["product"]);
  assert.equal(task.source_mode, "sheet");
  assert.equal(task.sheet_query.count, 1);
  assert.equal(runner.starts.length, 1);
});

test("ambiguous source asks the user and continues from the quoted choice", async () => {
  const value = fixture();
  value.runner.classifyRequirementSource = async () => ({
    decision: "needs_confirmation",
    reason: "意图不明确",
  });
  await value.orchestrator.handleEvent(event({ text: "帮我看一下需求" }));
  await value.orchestrator.waitForIdle();

  let task = (await value.store.listTasks())[0];
  assert.equal(task.status, "awaiting_source");
  const choiceCard = value.sent.at(-1).botMessageId;

  await value.orchestrator.handleEvent(
    event({ eventId: "evt_2", messageId: "om_choice", text: "2", parentId: choiceCard }),
  );
  await value.orchestrator.waitForIdle();

  task = await value.store.getTask(task.id);
  assert.equal(task.source_mode, "manual");
  assert.equal(value.runner.starts.length, 1);
});

test("write authorization survives a question card", async () => {
  const value = fixture();
  value.runner.continueTask = async (task, text) => {
    value.runner.continuations.push({ writeAuthorized: task.write_authorized, text });
    if (value.runner.continuations.length === 1) {
      return {
        status: "awaiting_user",
        stage: "question",
        card_title: "需要确认",
        card_markdown: "请选择产品行为",
        next_action: "回复选择",
        write_authorized: true,
      };
    }
    return {
      status: "completed",
      stage: "final",
      card_title: "处理完成",
      card_markdown: "修改完成",
      next_action: "",
      write_authorized: true,
    };
  };
  await value.orchestrator.handleEvent(event());
  await value.orchestrator.waitForIdle();
  const task = (await value.store.listTasks())[0];
  let card = value.sent.at(-1).botMessageId;

  await value.orchestrator.handleEvent(
    event({ eventId: "evt_2", messageId: "om_branch", text: "使用当前分支", parentId: card }),
  );
  await value.orchestrator.waitForIdle();
  card = value.sent.at(-1).botMessageId;
  assert.equal((await value.store.getTask(task.id)).write_authorized, true);

  await value.orchestrator.handleEvent(
    event({ eventId: "evt_3", messageId: "om_answer", text: "选择方案 A", parentId: card }),
  );
  await value.orchestrator.waitForIdle();

  assert.deepEqual(value.runner.continuations.map((item) => item.writeAuthorized), [false, true]);
  assert.equal((await value.store.getTask(task.id)).status, "completed");
});
