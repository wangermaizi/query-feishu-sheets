import path from "node:path";
import { fileURLToPath } from "node:url";

import { Codex } from "@openai/codex-sdk";

const SOURCE_DIR = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = path.resolve(SOURCE_DIR, "..", "..", "..");
const SKILL_PATH = path.join(
  PLUGIN_ROOT,
  "skills",
  "feishu-requirement-orchestrator",
  "SKILL.md",
);

const ROUTING_SCHEMA = {
  type: "object",
  properties: {
    decision: { type: "string", enum: ["selected", "needs_confirmation"] },
    selected_candidate_id: { type: "string" },
    candidate_ids: { type: "array", items: { type: "string" } },
    reason: { type: "string" },
  },
  required: ["decision", "selected_candidate_id", "candidate_ids", "reason"],
  additionalProperties: false,
};

const SOURCE_MODE_SCHEMA = {
  type: "object",
  properties: {
    decision: { type: "string", enum: ["sheet", "manual", "needs_confirmation"] },
    reason: { type: "string" },
  },
  required: ["decision", "reason"],
  additionalProperties: false,
};

export const GATEWAY_RESPONSE_SCHEMA = {
  type: "object",
  properties: {
    status: {
      type: "string",
      enum: ["awaiting_user", "completed", "blocked", "failed"],
    },
    stage: {
      type: "string",
      enum: [
        "analysis_confirmation",
        "branch_choice",
        "implementation",
        "review",
        "question",
        "final",
        "blocked",
      ],
    },
    card_title: { type: "string" },
    card_markdown: { type: "string" },
    next_action: { type: "string" },
    write_authorized: { type: "boolean" },
  },
  required: [
    "status",
    "stage",
    "card_title",
    "card_markdown",
    "next_action",
    "write_authorized",
  ],
  additionalProperties: false,
};

function parseStructuredResponse(value, label) {
  try {
    return JSON.parse(value);
  } catch (error) {
    throw new Error(`${label}没有返回有效 JSON: ${error.message}`);
  }
}

export function taskSandbox(task) {
  return task.write_authorized || ["branch_choice", "implementation", "review"].includes(task.stage)
    ? "workspace-write"
    : "read-only";
}

export class CodexRunner {
  constructor(config) {
    this.config = config;
    this.codex = new Codex({ codexPathOverride: config.codexPath });
  }

  threadOptions(workingDirectory, sandboxMode) {
    return {
      model: this.config.model,
      modelReasoningEffort: this.config.reasoningEffort,
      workingDirectory,
      sandboxMode,
      approvalPolicy: "never",
      networkAccessEnabled: this.config.networkAccessEnabled,
      skipGitRepoCheck: false,
    };
  }

  async runThread({ thread, prompt, outputSchema, onThreadId }) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.config.turnTimeoutMs);
    let finalResponse = "";
    try {
      const { events } = await thread.runStreamed(prompt, {
        outputSchema,
        signal: controller.signal,
      });
      for await (const event of events) {
        if (event.type === "thread.started") await onThreadId?.(event.thread_id);
        if (event.type === "item.completed" && event.item.type === "agent_message") {
          finalResponse = event.item.text;
        }
        if (event.type === "turn.failed") throw new Error(event.error.message);
        if (event.type === "error") throw new Error(event.message);
      }
      if (!finalResponse) throw new Error("Codex 没有返回最终消息");
      return finalResponse;
    } catch (error) {
      if (controller.signal.aborted) {
        throw new Error(`Codex 运行超过 ${this.config.turnTimeoutMs / 60000} 分钟`);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  async routeCandidates(text, candidates, kind) {
    const thread = this.codex.startThread(
      this.threadOptions(PLUGIN_ROOT, "read-only"),
    );
    const prompt = [
      `你只负责把用户的软件需求路由到一个已配置的${kind}候选。`,
      "结合候选 ID、显示名、别名、用途描述、项目名和需求语义判断。",
      "只有一个可信候选时返回 selected；两个或更多候选都合理时返回 needs_confirmation。",
      "不要读取或修改代码，不要虚构 profile。",
      `用户需求：${text}`,
      `候选项：${JSON.stringify(candidates)}`,
    ].join("\n\n");
    const response = await this.runThread({
      thread,
      prompt,
      outputSchema: ROUTING_SCHEMA,
    });
    return parseStructuredResponse(response, `${kind}路由`);
  }

  routeRequirement(text, routes) {
    const candidates = routes.map((route) => ({
      candidate_id: route.profile_id,
      ...route,
    }));
    return this.routeCandidates(text, candidates, "需求表");
  }

  async classifyRequirementSource(text, routes) {
    const thread = this.codex.startThread(this.threadOptions(PLUGIN_ROOT, "read-only"));
    const prompt = [
      "判断飞书用户这句话是在要求读取需求表，还是已经直接描述了一项软件需求。",
      "要求获取、读取、查询、筛选或处理某张需求表里的需求，返回 sheet。",
      "已经说明要新增、修复、优化或调整的具体产品行为，返回 manual。",
      "两种意图同时存在且无法确定主要目标时返回 needs_confirmation。",
      "不要读取代码或需求表。",
      `用户消息：${text}`,
      `可用需求表：${JSON.stringify(routes)}`,
    ].join("\n\n");
    const response = await this.runThread({
      thread,
      prompt,
      outputSchema: SOURCE_MODE_SCHEMA,
    });
    return parseStructuredResponse(response, "需求来源判断");
  }

  routeRepository(text, repositories) {
    return this.routeCandidates(text, repositories, "代码仓库");
  }

  async startTask(task, onThreadId) {
    const thread = this.codex.startThread(
      this.threadOptions(task.repository, "read-only"),
    );
    const sourcePrompt =
      task.source_mode === "sheet"
        ? [
            "这是飞书需求表查询模式。网关已经在 Codex 沙箱外只读查询需求表；必须使用下面的完整查询结果，不要再次查询飞书。",
            "按 Skill 的飞书需求表模式评估全部候选，保留表中需求 ID/序号和原始内容，生成普通语言说明，并逐条核验目标仓库中的实现状态与必要性。",
            "一次性把全部分析结果交给用户确认；本轮禁止修改代码。",
            `需求表查询结果：\n${JSON.stringify(task.sheet_query)}`,
          ].join("\n\n")
        : [
            "这是用户直接描述的手动需求。",
            "把它作为一项新需求处理；profile 只用于项目归属，仓库候选只用于代码路由。不得查询需求表，不得搜索或匹配表内具体记录，也不得绑定已有需求 ID。",
            "先完成只读必要性核验、普通语言说明、验收标准草稿和分析确认；本轮禁止修改代码。",
          ].join("\n\n");
    const prompt = [
      `使用位于 ${SKILL_PATH} 的 feishu-requirement-orchestrator Skill。`,
      "当前输入来自飞书机器人网关，必须阅读 references/bot-channel.md 并按其中协议返回结构化结果。",
      sourcePrompt,
      "不要直接调用 publish_result.py 或向飞书发送消息，网关会发送你的结构化结果。",
      `网关任务 ID：${task.id}`,
      `需求表 profile：${task.profile_id}（${task.profile_name}）`,
      `项目名：${task.project_name || "尚未配置"}`,
      `代码仓库候选：${task.repository_name || task.repository_id}`,
      `目标仓库：${task.repository}`,
      `发起人原始需求：\n${task.original_text}`,
      "本轮 write_authorized 必须返回 false。",
    ].join("\n\n");
    const response = await this.runThread({
      thread,
      prompt,
      outputSchema: GATEWAY_RESPONSE_SCHEMA,
      onThreadId,
    });
    return parseStructuredResponse(response, "需求分析");
  }

  async continueTask(task, userText, onThreadId) {
    if (!task.codex_thread_id) throw new Error("任务缺少 Codex thread_id，无法恢复");
    const sandboxMode = taskSandbox(task);
    const thread = this.codex.resumeThread(
      task.codex_thread_id,
      this.threadOptions(task.repository, sandboxMode),
    );
    const prompt = [
      "这是飞书用户对你上一张卡片的引用回复。恢复同一需求，不要创建新需求。",
      `当前网关阶段：${task.stage}`,
      `此前是否已经确认代码写入位置：${task.write_authorized ? "是" : "否"}`,
      `用户回复：${userText}`,
      sandboxMode === "read-only"
        ? "本轮保持只读；如果需要进入修改阶段，先返回 branch_choice 等待用户明确选择。"
        : "用户已处于允许写入的阶段；继续遵循 Skill 的分支、实施、Review 和发布边界。",
      "不要直接向飞书发送消息。按 bot-channel.md 协议返回结构化卡片内容。",
      "只有用户已明确选择当前分支或确认新分支名称，write_authorized 才能返回 true；一旦已授权，后续追问不得将其改回 false。",
    ].join("\n\n");
    const response = await this.runThread({
      thread,
      prompt,
      outputSchema: GATEWAY_RESPONSE_SCHEMA,
      onThreadId,
    });
    return parseStructuredResponse(response, "需求后续处理");
  }
}
