import fs from "node:fs";

import {
  buildCard,
  canControlTask,
  isNewDemandEvent,
  messageReferences,
  messageText,
  profileChoiceMarkdown,
  repositoryChoiceMarkdown,
  senderOpenId,
  sourceChoiceMarkdown,
  taskIdFromMessage,
} from "./messages.js";
import {
  publicRepositories,
  publicRoutes,
  repositoryCandidates,
  resolveProfileReply,
  resolveRepositoryReply,
  resolveSourceModeReply,
  routeCandidates,
  sourceModeCandidate,
} from "./routing.js";

function cardTemplate(status) {
  if (status === "completed") return "green";
  if (status === "blocked" || status === "failed") return "red";
  return "blue";
}

export class GatewayOrchestrator {
  constructor({ config, store, runner, sheetQuery, transport, logger }) {
    this.config = config;
    this.store = store;
    this.runner = runner;
    this.sheetQuery = sheetQuery;
    this.transport = transport;
    this.logger = logger;
    this.inflight = new Set();
  }

  async handleEvent(event) {
    const eventId = event.event_id || event.message?.message_id;
    if (!eventId || !event.message) return;
    if (!(await this.store.claimEvent(eventId))) return;
    queueMicrotask(() => {
      const operation = this.processEvent(event).catch((error) => {
        this.logger.error("处理飞书事件失败", {
          event_id: eventId,
          message: error.message,
        });
      });
      this.inflight.add(operation);
      void operation.finally(() => this.inflight.delete(operation));
    });
  }

  async waitForIdle() {
    await new Promise((resolve) => queueMicrotask(resolve));
    while (this.inflight.size) await Promise.all([...this.inflight]);
  }

  async processEvent(event) {
    const message = event.message;
    if (!this.config.allowedChatIds.has(message.chat_id)) {
      this.logger.warn("忽略未授权群消息", { chat_id: message.chat_id });
      return;
    }
    const openId = senderOpenId(event);
    if (!openId || event.sender?.sender_type !== "user") return;
    const text = messageText(message);
    const referencedTask = await this.store.findTaskByMessages(messageReferences(message));
    if (referencedTask) {
      await this.continueTask(referencedTask, message, openId, text);
      return;
    }
    if (!isNewDemandEvent(event, this.config)) return;
    if (!text) {
      await this.replyStandalone(
        message.message_id,
        "无法读取需求",
        "首版支持文本和富文本需求，请在 @机器人 后补充需求正文。",
        "orange",
      );
      return;
    }
    await this.createTask(event, text, openId);
  }

  async replyStandalone(messageId, title, markdown, template = "blue") {
    await this.transport.replyCard(
      messageId,
      buildCard({ title, markdown, template }),
    );
  }

  async replyForTask(task, messageId, card) {
    const botMessageId = await this.transport.replyCard(messageId, card);
    await this.store.bindMessage(task.id, botMessageId);
    return botMessageId;
  }

  async createTask(event, text, openId) {
    const message = event.message;
    const now = new Date();
    const task = await this.store.createTask({
      id: taskIdFromMessage(message.message_id, now),
      status: "routing",
      stage: "source_selection",
      owner_open_id: openId,
      chat_id: message.chat_id,
      source_message_id: message.message_id,
      original_text: text,
      source_mode: null,
      write_authorized: false,
      codex_thread_id: null,
      profile_id: null,
      profile_name: null,
      project_name: null,
      repository: null,
      repository_id: null,
      repository_name: null,
      created_at: now.toISOString(),
      updated_at: now.toISOString(),
    });
    await this.replyForTask(
      task,
      message.message_id,
      buildCard({
        title: "Codex 已接收需求",
        markdown: "正在识别需求表和代码仓库，完成后会在当前消息下回复分析结果。",
        template: "turquoise",
        taskId: task.id,
      }),
    );

    await this.determineSourceAndRoute(task, message.message_id);
  }

  async determineSourceAndRoute(task, messageId) {
    const candidate = sourceModeCandidate(task.original_text);
    if (candidate.decision === "selected") {
      await this.selectSourceAndRoute(task, messageId, candidate.source_mode);
      return;
    }
    const semantic = await this.runner.classifyRequirementSource(
      task.original_text,
      publicRoutes(this.config.routes),
    );
    if (semantic.decision === "needs_confirmation") {
      await this.askSource(task, messageId);
      return;
    }
    await this.selectSourceAndRoute(task, messageId, semantic.decision);
  }

  async askSource(task, messageId) {
    task = await this.store.updateTask(task.id, {
      status: "awaiting_source",
      stage: "source_selection",
    });
    await this.replyForTask(
      task,
      messageId,
      buildCard({
        title: "请选择需求来源",
        markdown: sourceChoiceMarkdown(),
        template: "orange",
        taskId: task.id,
        instruction: "请直接引用回复这张卡片，填写 1、2、查询需求表或处理当前描述。",
      }),
    );
  }

  async selectSourceAndRoute(task, messageId, sourceMode) {
    task = await this.store.updateTask(task.id, {
      status: "routing",
      stage: "profile_selection",
      source_mode: sourceMode,
    });
    const routing = routeCandidates(task.original_text, task.chat_id, this.config, {
      preferSemantic: sourceMode === "manual",
    });
    if (routing.decision === "selected") {
      await this.selectProfileAndStart(task, routing.route, messageId);
      return;
    }
    if (routing.decision === "ambiguous") {
      await this.askProfile(task, messageId, routing.candidates);
      return;
    }

    await this.store.updateTask(task.id, { status: "routing" });
    const semantic = await this.runner.routeRequirement(
      task.original_text,
      publicRoutes(routing.candidates),
    );
    const selected = routing.candidates.find(
      (route) => route.profile_id === semantic.selected_candidate_id,
    );
    if (semantic.decision === "selected" && selected) {
      await this.selectProfileAndStart(task, selected, messageId);
      return;
    }
    const candidateIds = new Set(semantic.candidate_ids);
    const candidates = routing.candidates.filter((route) => candidateIds.has(route.profile_id));
    await this.askProfile(task, messageId, candidates.length ? candidates : routing.candidates);
  }

  async askProfile(task, messageId, candidates) {
    await this.store.updateTask(task.id, {
      status: "awaiting_profile",
      stage: "profile_selection",
      profile_candidates: candidates.map((route) => route.profile_id),
    });
    await this.replyForTask(
      task,
      messageId,
      buildCard({
        title: "请选择需求表",
        markdown: profileChoiceMarkdown(candidates),
        template: "orange",
        taskId: task.id,
        instruction: "请直接引用回复这张卡片，填写序号、需求表名称或 profile ID。",
      }),
    );
  }

  async selectProfileAndStart(task, route, messageId) {
    task = await this.store.updateTask(task.id, {
      profile_id: route.profile_id,
      profile_name: route.display_name,
      project_name: route.project_name,
    });
    if (task.source_mode === "sheet") {
      try {
        const queryResult = await this.sheetQuery.query(route.profile_id);
        task = await this.store.updateTask(task.id, { sheet_query: queryResult });
        if (queryResult.count === 0) {
          task = await this.store.updateTask(task.id, {
            status: "completed",
            stage: "final",
          });
          await this.replyForTask(
            task,
            messageId,
            buildCard({
              title: `【${route.project_name || route.display_name}】没有待处理需求`,
              markdown: `已按 **${route.display_name}** 的已确认筛选条件完成查询，没有命中候选需求。`,
              template: "green",
              taskId: task.id,
            }),
          );
          return;
        }
      } catch (error) {
        task = await this.store.updateTask(task.id, {
          status: "query_failed",
          stage: "source_selection",
          error: error.message,
        });
        await this.replyForTask(
          task,
          messageId,
          buildCard({
            title: "需求表查询失败",
            markdown: error.message,
            template: "red",
            taskId: task.id,
            instruction: "修复配置或网络问题后引用回复“重试”；回复“取消”结束任务。",
          }),
        );
        return;
      }
    }
    if (!route.repositories.length) {
      await this.store.updateTask(task.id, {
        status: "blocked",
        stage: "blocked",
        error: "profile 未配置代码仓库候选",
      });
      await this.replyForTask(
        task,
        messageId,
        buildCard({
          title: "缺少代码仓库配置",
          markdown: `已识别为 **${route.display_name}**，但该 profile 没有配置代码仓库候选。`,
          template: "red",
          taskId: task.id,
          instruction: "请配置 profile_routes 或 default_repository 后重启网关，再重新提交需求。",
        }),
      );
      return;
    }
    const repositoryInput =
      task.source_mode === "sheet"
        ? JSON.stringify({ query: task.sheet_query.query, items: task.sheet_query.items })
        : task.original_text;
    const selection = repositoryCandidates(repositoryInput, route.repositories);
    if (selection.decision === "selected") {
      await this.selectRepositoryAndStart(task, route, selection.repository, messageId);
      return;
    }
    if (selection.decision === "ambiguous") {
      await this.askRepository(task, messageId, route, selection.candidates);
      return;
    }
    const semantic = await this.runner.routeRepository(
      repositoryInput,
      publicRepositories(selection.candidates),
    );
    const selected = selection.candidates.find(
      (repository) => repository.repository_id === semantic.selected_candidate_id,
    );
    if (semantic.decision === "selected" && selected) {
      await this.selectRepositoryAndStart(task, route, selected, messageId);
      return;
    }
    const candidateIds = new Set(semantic.candidate_ids);
    const candidates = selection.candidates.filter((repository) =>
      candidateIds.has(repository.repository_id),
    );
    await this.askRepository(
      task,
      messageId,
      route,
      candidates.length ? candidates : selection.candidates,
    );
  }

  async askRepository(task, messageId, route, candidates) {
    await this.store.updateTask(task.id, {
      status: "awaiting_repository",
      stage: "repository_selection",
      profile_id: route.profile_id,
      profile_name: route.display_name,
      repository_candidates: candidates.map((repository) => repository.repository_id),
    });
    await this.replyForTask(
      task,
      messageId,
      buildCard({
        title: "请选择代码仓库",
        markdown: repositoryChoiceMarkdown(candidates),
        template: "orange",
        taskId: task.id,
        instruction: "请直接引用回复这张卡片，填写序号、仓库名称或仓库 ID。",
      }),
    );
  }

  async selectRepositoryAndStart(task, route, repository, messageId) {
    if (!repository.path || !fs.existsSync(repository.path)) {
      await this.store.updateTask(task.id, {
        status: "blocked",
        stage: "blocked",
        repository_id: repository.repository_id,
        repository_name: repository.display_name,
        error: "仓库候选没有有效本地路径",
      });
      await this.replyForTask(
        task,
        messageId,
        buildCard({
          title: "代码仓库路径不可用",
          markdown: `已识别为 **${repository.display_name}**，但配置的本地路径不存在。`,
          template: "red",
          taskId: task.id,
          instruction: "请修正 repositories[].path 后重启网关，再重新提交需求。",
        }),
      );
      return;
    }
    task = await this.store.updateTask(task.id, {
      status: "running",
      stage: "analysis_confirmation",
      project_name: repository.project_name || route.project_name,
      repository_id: repository.repository_id,
      repository_name: repository.display_name,
      repository: repository.path,
    });
    try {
      const result = await this.runner.startTask(task, async (threadId) => {
        task = await this.store.updateTask(task.id, { codex_thread_id: threadId });
      });
      await this.publishAgentResult(task, messageId, result);
    } catch (error) {
      await this.handleRunError(task, messageId, error);
    }
  }

  async continueTask(task, message, openId, text) {
    if (!canControlTask(task, openId, this.config)) {
      await this.replyStandalone(
        message.message_id,
        "无权操作此任务",
        "只有需求发起人或已配置的管理员可以控制该 Codex 任务。",
        "red",
      );
      return;
    }
    if (!text) {
      await this.replyStandalone(
        message.message_id,
        "回复内容为空",
        "请引用回复并填写确认、修改内容、分支选择或取消。",
        "orange",
      );
      return;
    }
    if (task.status === "running") {
      await this.replyStandalone(
        message.message_id,
        "任务仍在处理中",
        "请等待当前 Codex turn 完成后再回复最新卡片。",
        "orange",
      );
      return;
    }
    if (task.status === "completed") {
      await this.replyStandalone(
        message.message_id,
        "任务已经完成",
        "如需新的修改，请重新 @机器人 创建一条新需求。",
      );
      return;
    }
    if (task.status === "awaiting_source") {
      const sourceMode = resolveSourceModeReply(text);
      if (!sourceMode) {
        await this.askSource(task, message.message_id);
        return;
      }
      await this.selectSourceAndRoute(task, message.message_id, sourceMode);
      return;
    }
    if (task.status === "query_failed") {
      if (/^(?:取消|停止|结束)$/u.test(text.trim())) {
        task = await this.store.updateTask(task.id, { status: "completed", stage: "final" });
        await this.replyForTask(
          task,
          message.message_id,
          buildCard({ title: "任务已取消", markdown: "没有修改代码或需求表。", taskId: task.id }),
        );
        return;
      }
      if (!/^(?:重试|继续)$/u.test(text.trim())) {
        await this.replyStandalone(
          message.message_id,
          "请选择重试或取消",
          "请引用回复“重试”重新查询，或回复“取消”结束任务。",
          "orange",
        );
        return;
      }
      const route = this.config.routes.find((item) => item.profile_id === task.profile_id);
      if (!route) {
        await this.replyStandalone(
          message.message_id,
          "需求表配置已变化",
          "原任务对应的 profile 已不存在，请重新 @机器人提交需求。",
          "red",
        );
        return;
      }
      await this.selectProfileAndStart(task, route, message.message_id);
      return;
    }
    if (task.status === "awaiting_profile") {
      const candidateIds = new Set(task.profile_candidates || []);
      const candidates = this.config.routes.filter((route) => candidateIds.has(route.profile_id));
      const route = resolveProfileReply(text, candidates);
      if (!route) {
        await this.askProfile(task, message.message_id, candidates);
        return;
      }
      await this.selectProfileAndStart(task, route, message.message_id);
      return;
    }
    if (task.status === "awaiting_repository") {
      const route = this.config.routes.find((item) => item.profile_id === task.profile_id);
      const candidateIds = new Set(task.repository_candidates || []);
      const candidates = (route?.repositories || []).filter((repository) =>
        candidateIds.has(repository.repository_id),
      );
      const repository = resolveRepositoryReply(text, candidates);
      if (!route) {
        await this.replyStandalone(
          message.message_id,
          "需求表配置已变化",
          "原任务对应的 profile 已不存在，请重新 @机器人提交需求。",
          "red",
        );
        return;
      }
      if (!repository) {
        await this.askRepository(task, message.message_id, route, candidates);
        return;
      }
      await this.selectRepositoryAndStart(task, route, repository, message.message_id);
      return;
    }
    if (["blocked", "failed"].includes(task.status) && !task.codex_thread_id) {
      await this.replyStandalone(
        message.message_id,
        "任务无法恢复",
        "当前任务尚未建立 Codex 线程。请修复卡片中提示的配置后重新 @机器人提交需求。",
        "red",
      );
      return;
    }

    task = await this.store.updateTask(task.id, { status: "running" });
    try {
      const result = await this.runner.continueTask(task, text, async (threadId) => {
        task = await this.store.updateTask(task.id, { codex_thread_id: threadId });
      });
      await this.publishAgentResult(task, message.message_id, result);
    } catch (error) {
      await this.handleRunError(task, message.message_id, error);
    }
  }

  async publishAgentResult(task, messageId, result) {
    const writeAuthorized = Boolean(task.write_authorized || result.write_authorized);
    task = await this.store.updateTask(task.id, {
      status: result.status,
      stage: result.stage,
      last_result: result,
      write_authorized: writeAuthorized,
      error: null,
    });
    await this.replyForTask(
      task,
      messageId,
      buildCard({
        title: result.card_title,
        markdown: result.card_markdown,
        template: cardTemplate(result.status),
        taskId: task.id,
        instruction: result.next_action || null,
      }),
    );
  }

  async handleRunError(task, messageId, error) {
    const latest = await this.store.getTask(task.id);
    const recoverable = Boolean(latest?.codex_thread_id);
    task = await this.store.updateTask(task.id, {
      status: recoverable ? "interrupted" : "failed",
      error: error.message,
    });
    await this.replyForTask(
      task,
      messageId,
      buildCard({
        title: recoverable ? "Codex 任务已中断" : "Codex 任务启动失败",
        markdown: `处理失败：${error.message}`,
        template: "red",
        taskId: task.id,
        instruction: recoverable
          ? "可以引用回复“继续”恢复同一个 Codex 线程；不会自动重复执行。"
          : "请检查本机 Codex 登录、模型和运行配置后重新提交需求。",
      }),
    );
  }

  async notifyInterruptedTasks() {
    const tasks = await this.store.markInterruptedRuns();
    for (const task of tasks) {
      const target = task.last_bot_message_id || task.source_message_id;
      try {
        await this.replyForTask(
          task,
          target,
          buildCard({
            title: "本地网关已恢复",
            markdown: "服务重启时此任务仍在运行，为避免重复修改代码，网关没有自动重跑。",
            template: "orange",
            taskId: task.id,
            instruction: "请引用回复“继续”以恢复同一个 Codex 线程，或回复“取消”。",
          }),
        );
      } catch (error) {
        this.logger.error("发送任务恢复提示失败", {
          task_id: task.id,
          message: error.message,
        });
      }
    }
  }
}
