const MAX_CARD_TEXT = 12000;

export function senderOpenId(event) {
  return event.sender?.sender_id?.open_id || null;
}

export function messageReferences(message) {
  return [message.parent_id, message.root_id, message.thread_id].filter(Boolean);
}

function postText(value) {
  const paragraphs = [];
  for (const locale of Object.values(value || {})) {
    if (!locale || typeof locale !== "object") continue;
    for (const paragraph of locale.content || []) {
      if (!Array.isArray(paragraph)) continue;
      paragraphs.push(
        paragraph
          .map((item) => (item?.tag === "text" || item?.tag === "a" ? item.text || "" : ""))
          .join(""),
      );
    }
  }
  return paragraphs.filter(Boolean).join("\n");
}

export function messageText(message) {
  let payload;
  try {
    payload = JSON.parse(message.content || "{}");
  } catch {
    return "";
  }
  let value = "";
  if (message.message_type === "text") value = payload.text || "";
  if (message.message_type === "post") value = postText(payload);
  for (const mention of message.mentions || []) {
    if (mention.key) value = value.replaceAll(mention.key, " ");
  }
  return value.replace(/\s+/g, " ").trim();
}

export function isNewDemandEvent(event, config) {
  if (event.message.chat_type === "p2p") return true;
  if (!config.requireGroupMention) return true;
  return Array.isArray(event.message.mentions) && event.message.mentions.length > 0;
}

export function canControlTask(task, openId, config) {
  return Boolean(openId && (openId === task.owner_open_id || config.adminOpenIds.has(openId)));
}

export function taskIdFromMessage(messageId, now = new Date()) {
  const date = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(now)
    .replaceAll("-", "");
  const suffix = String(messageId).replace(/[^A-Za-z0-9]/g, "").slice(-12) || Date.now();
  return `FEISHU-${date}-${suffix}`;
}

export function buildCard({ title, markdown, template = "blue", taskId, instruction }) {
  const body = String(markdown || "").slice(0, MAX_CARD_TEXT);
  const elements = [
    { tag: "div", text: { tag: "lark_md", content: body || "暂无内容" } },
  ];
  if (instruction) {
    elements.push({ tag: "hr" });
    elements.push({
      tag: "div",
      text: { tag: "lark_md", content: `**下一步**\n${instruction}` },
    });
  }
  if (taskId) {
    elements.push({
      tag: "note",
      elements: [{ tag: "plain_text", content: `任务 ${taskId}` }],
    });
  }
  return {
    config: { wide_screen_mode: true },
    header: {
      template,
      title: { tag: "plain_text", content: String(title || "Codex 需求任务").slice(0, 80) },
    },
    elements,
  };
}

export function profileChoiceMarkdown(routes) {
  return routes
    .map(
      (route, index) =>
        `${index + 1}. **${route.display_name}**（${route.profile_id}）` +
        `${route.description ? `\n   ${route.description}` : ""}`,
    )
    .join("\n");
}

export function sourceChoiceMarkdown() {
  return [
    "无法确定你希望从需求表读取需求，还是直接处理当前描述。",
    "",
    "1. **查询需求表**：按已配置筛选条件读取表内候选需求。",
    "2. **处理当前描述**：把当前消息作为一项新需求进行分析。",
  ].join("\n");
}

export function repositoryChoiceMarkdown(repositories) {
  return repositories
    .map(
      (repository, index) =>
        `${index + 1}. **${repository.display_name}**（${repository.repository_id}）` +
        `${repository.description ? `\n   ${repository.description}` : ""}`,
    )
    .join("\n");
}
