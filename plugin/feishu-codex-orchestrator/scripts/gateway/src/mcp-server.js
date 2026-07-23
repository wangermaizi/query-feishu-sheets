import fs from "node:fs";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { loadGatewayConfig, publicConfig } from "./config.js";
import { StateStore } from "./state-store.js";

function result(value) {
  return {
    content: [{ type: "text", text: JSON.stringify(value, null, 2) }],
    structuredContent: value,
  };
}

function safeTask(task) {
  const { owner_open_id, original_text, ...visible } = task;
  return visible;
}

const server = new McpServer({
  name: "feishu-codex-gateway",
  version: "0.4.0",
});

server.registerTool(
  "gateway_config",
  {
    title: "查看飞书 Codex 网关配置",
    description: "验证并返回不包含密钥的网关、需求表路由和运行配置。",
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async () => result({ valid: true, config: publicConfig(loadGatewayConfig()) }),
);

server.registerTool(
  "gateway_status",
  {
    title: "查看飞书 Codex 网关状态",
    description: "查看登录自启后台网关最近报告的连接状态。",
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async () => {
    const config = loadGatewayConfig();
    try {
      return result(JSON.parse(fs.readFileSync(config.statusFile, "utf8")));
    } catch (error) {
      if (error?.code === "ENOENT") return result({ state: "not_started" });
      throw error;
    }
  },
);

server.registerTool(
  "gateway_tasks",
  {
    title: "查看飞书 Codex 任务",
    description: "列出本地网关任务状态，不返回用户身份和原始需求正文。",
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async () => {
    const config = loadGatewayConfig();
    const tasks = (await new StateStore(config.stateFile).listTasks()).map(safeTask);
    return result({ tasks });
  },
);

await server.connect(new StdioServerTransport());
