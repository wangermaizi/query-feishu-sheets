import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));

function configFixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "gateway-mcp-"));
  fs.writeFileSync(
    path.join(directory, "credentials.json"),
    JSON.stringify({ credentials: { bot: { app_id: "cli_test", app_secret: "secret" } } }),
  );
  fs.writeFileSync(
    path.join(directory, "profiles.json"),
    JSON.stringify({
      profiles: {
        product: { display_name: "产品需求表", default_repository: directory },
      },
    }),
  );
  fs.writeFileSync(
    path.join(directory, "orchestrator.json"),
    JSON.stringify({
      gateway: {
        enabled: true,
        credential: "bot",
        allowed_chat_ids: ["oc_allowed"],
        codex_path: process.execPath,
      },
    }),
  );
  return directory;
}

test("MCP server exposes sanitized gateway status tools", async () => {
  const directory = configFixture();
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [path.resolve(TEST_DIR, "..", "src", "mcp-server.js")],
    env: { ...process.env, FEISHU_ORCHESTRATOR_CONFIG_DIR: directory },
  });
  const client = new Client({ name: "gateway-test", version: "1.0.0" });
  try {
    await client.connect(transport);
    const response = await client.callTool({ name: "gateway_config", arguments: {} });
    const text = response.content[0].text;

    assert.equal(text.includes("secret"), false);
    assert.equal(response.structuredContent.valid, true);
  } finally {
    await client.close();
  }
});
