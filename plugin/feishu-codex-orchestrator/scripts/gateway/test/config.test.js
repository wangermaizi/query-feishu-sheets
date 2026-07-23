import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { ConfigError, loadGatewayConfig, publicConfig } from "../src/config.js";

function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "feishu-gateway-config-"));
  fs.writeFileSync(
    path.join(directory, "credentials.json"),
    JSON.stringify({ credentials: { bot: { app_id: "cli_test", app_secret: "secret" } } }),
  );
  fs.writeFileSync(
    path.join(directory, "profiles.json"),
    JSON.stringify({
      profiles: {
        product: {
          display_name: "产品需求表",
          aliases: ["产品需求"],
          default_repository: directory,
          default_project_name: "产品平台",
        },
      },
    }),
  );
  fs.writeFileSync(
    path.join(directory, "orchestrator.json"),
    JSON.stringify({
      runtime: { model: "gpt-5.6-sol", reasoning_effort: "ultra" },
      gateway: {
        enabled: true,
        credential: "bot",
        allowed_chat_ids: ["oc_allowed"],
        admin_open_ids: ["ou_admin"],
      },
    }),
  );
  return directory;
}

test("loads gateway config without exposing the app secret", () => {
  const directory = fixture();
  const config = loadGatewayConfig({ FEISHU_ORCHESTRATOR_CONFIG_DIR: directory });
  const visible = publicConfig(config);

  assert.equal(config.appSecret, "secret");
  assert.equal(config.routes[0].repository, directory);
  assert.equal(visible.runtime.reasoning_effort, "ultra");
  assert.equal(JSON.stringify(visible).includes("secret"), false);
});

test("rejects an enabled gateway without authorized chats", () => {
  const directory = fixture();
  const file = path.join(directory, "orchestrator.json");
  const settings = JSON.parse(fs.readFileSync(file, "utf8"));
  settings.gateway.allowed_chat_ids = [];
  fs.writeFileSync(file, JSON.stringify(settings));

  assert.throws(
    () => loadGatewayConfig({ FEISHU_ORCHESTRATOR_CONFIG_DIR: directory }),
    ConfigError,
  );
});

test("supports multiple repository candidates for one profile", () => {
  const directory = fixture();
  const file = path.join(directory, "orchestrator.json");
  const settings = JSON.parse(fs.readFileSync(file, "utf8"));
  settings.gateway.profile_routes = {
    product: {
      repositories: [
        { id: "oas", display_name: "OAS", path: directory },
        { id: "preboard", display_name: "Preboard", path: directory },
      ],
    },
  };
  fs.writeFileSync(file, JSON.stringify(settings));

  const config = loadGatewayConfig({ FEISHU_ORCHESTRATOR_CONFIG_DIR: directory });

  assert.deepEqual(
    config.routes[0].repositories.map((item) => item.repository_id),
    ["oas", "preboard"],
  );
  assert.equal(config.routes[0].repository, null);
});

test("reuses the existing semantic repository routing configuration", () => {
  const directory = fixture();
  const file = path.join(directory, "orchestrator.json");
  const settings = JSON.parse(fs.readFileSync(file, "utf8"));
  settings.repository_routing = {
    mode: "semantic",
    routes: [
      { label: "OA前端", path: directory },
      { label: "入职助手前端", path: directory },
    ],
  };
  fs.writeFileSync(file, JSON.stringify(settings));

  const config = loadGatewayConfig({ FEISHU_ORCHESTRATOR_CONFIG_DIR: directory });

  assert.deepEqual(
    config.routes[0].repositories.map((item) => item.repository_id),
    ["OA前端", "入职助手前端"],
  );
});
