import fs from "node:fs";
import path from "node:path";

import { loadGatewayConfig } from "./config.js";
import { CodexRunner } from "./codex-runner.js";
import { FeishuTransport } from "./feishu-transport.js";
import { Logger } from "./logger.js";
import { GatewayOrchestrator } from "./orchestrator.js";
import { StateStore } from "./state-store.js";
import { SheetQueryRunner } from "./sheet-query.js";

function applyCommandLineConfig() {
  const index = process.argv.indexOf("--config-dir");
  if (index >= 0) {
    const value = process.argv[index + 1];
    if (!value) throw new Error("--config-dir 缺少路径");
    process.env.FEISHU_ORCHESTRATOR_CONFIG_DIR = path.resolve(value);
  }
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function acquireSingleton(directory) {
  const lockFile = path.join(directory, ".gateway.pid");
  fs.mkdirSync(directory, { recursive: true });
  if (fs.existsSync(lockFile)) {
    try {
      const existing = JSON.parse(fs.readFileSync(lockFile, "utf8"));
      if (Number.isInteger(existing.pid) && processExists(existing.pid)) {
        throw new Error(`飞书 Codex 网关已经运行，PID=${existing.pid}`);
      }
    } catch (error) {
      if (error.message.includes("已经运行")) throw error;
    }
    fs.rmSync(lockFile, { force: true });
  }
  const payload = { pid: process.pid, started_at: new Date().toISOString() };
  fs.writeFileSync(lockFile, `${JSON.stringify(payload)}\n`, { encoding: "utf8", flag: "wx" });
  return () => {
    try {
      const current = JSON.parse(fs.readFileSync(lockFile, "utf8"));
      if (current.pid === process.pid) fs.rmSync(lockFile, { force: true });
    } catch {}
  };
}

async function main() {
  applyCommandLineConfig();
  const config = loadGatewayConfig();
  const releaseSingleton = acquireSingleton(config.directory);
  process.once("exit", releaseSingleton);
  const logger = new Logger(config.logFile);
  const store = new StateStore(config.stateFile);
  const runner = new CodexRunner(config);
  const sheetQuery = new SheetQueryRunner(config);
  const transport = new FeishuTransport(config, logger);
  const orchestrator = new GatewayOrchestrator({
    config,
    store,
    runner,
    sheetQuery,
    transport,
    logger,
  });

  const shutdown = (signal) => {
    logger.info("网关正在停止", { signal });
    transport.close();
    releaseSingleton();
    process.exit(0);
  };
  process.once("SIGINT", () => shutdown("SIGINT"));
  process.once("SIGTERM", () => shutdown("SIGTERM"));
  process.on("unhandledRejection", (error) => {
    logger.error("未处理的异步错误", { message: error?.message || String(error) });
  });

  transport.start((event) => orchestrator.handleEvent(event));
  await orchestrator.notifyInterruptedTasks();
  logger.info("飞书 Codex 网关已启动", {
    model: config.model,
    reasoning_effort: config.reasoningEffort,
    profiles: config.routes.length,
  });
}

main().catch((error) => {
  process.stderr.write(`启动飞书 Codex 网关失败: ${error.message}\n`);
  process.exitCode = 1;
});
