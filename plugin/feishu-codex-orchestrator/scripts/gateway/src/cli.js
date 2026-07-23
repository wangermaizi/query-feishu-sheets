import fs from "node:fs";

import { loadGatewayConfig, publicConfig } from "./config.js";
import { StateStore } from "./state-store.js";

function sanitizedTask(task) {
  const { owner_open_id, ...publicTask } = task;
  return publicTask;
}

async function main() {
  const command = process.argv[2] || "validate";
  const config = loadGatewayConfig();
  if (command === "validate") {
    process.stdout.write(`${JSON.stringify({ valid: true, config: publicConfig(config) }, null, 2)}\n`);
    return;
  }
  if (command === "status") {
    let status = { state: "not_started" };
    try {
      status = JSON.parse(fs.readFileSync(config.statusFile, "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    process.stdout.write(`${JSON.stringify(status, null, 2)}\n`);
    return;
  }
  if (command === "tasks") {
    const store = new StateStore(config.stateFile);
    const tasks = (await store.listTasks()).map(sanitizedTask);
    process.stdout.write(`${JSON.stringify({ tasks }, null, 2)}\n`);
    return;
  }
  throw new Error("命令必须是 validate、status 或 tasks");
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({ error: error.message })}\n`);
  process.exitCode = 1;
});
