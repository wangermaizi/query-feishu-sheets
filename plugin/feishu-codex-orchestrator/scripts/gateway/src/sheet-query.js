import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);
const SOURCE_DIR = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = path.resolve(SOURCE_DIR, "..", "..", "..");
const QUERY_SCRIPT = path.join(
  PLUGIN_ROOT,
  "skills",
  "feishu-requirement-orchestrator",
  "scripts",
  "query_sheet.py",
);

function parseQueryResult(stdout) {
  let value;
  try {
    value = JSON.parse(stdout);
  } catch (error) {
    throw new Error(`需求表查询没有返回有效 JSON: ${error.message}`);
  }
  if (!value || typeof value !== "object" || !Number.isInteger(value.count)) {
    throw new Error("需求表查询结果结构无效");
  }
  if (!Array.isArray(value.items) || value.items.length !== value.count) {
    throw new Error("需求表查询结果数量不一致");
  }
  return value;
}

export class SheetQueryRunner {
  constructor(config, execute = execFileAsync) {
    this.config = config;
    this.execute = execute;
  }

  async query(profileId) {
    try {
      const { stdout } = await this.execute(
        this.config.uvPath,
        ["run", QUERY_SCRIPT, "query", "--profile", profileId],
        {
          cwd: PLUGIN_ROOT,
          encoding: "utf8",
          env: {
            ...process.env,
            FEISHU_ORCHESTRATOR_CONFIG_DIR: this.config.directory,
            PYTHONUTF8: "1",
          },
          maxBuffer: 20 * 1024 * 1024,
          timeout: 120000,
          windowsHide: true,
        },
      );
      return parseQueryResult(stdout);
    } catch (error) {
      if (error.killed) throw new Error("需求表查询超过 2 分钟");
      if (error.message.startsWith("需求表查询")) throw error;
      const detail = String(error.stderr || error.message || "未知错误").trim().slice(0, 1000);
      throw new Error(`需求表查询失败: ${detail}`);
    }
  }
}

export { parseQueryResult };
