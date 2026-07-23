#!/usr/bin/env node

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath, pathToFileURL } from "node:url";

const BRIDGE_DIR = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = path.resolve(BRIDGE_DIR, "..", "..");
const SKILL_ROOT = path.join(
  PLUGIN_ROOT,
  "skills",
  "feishu-requirement-orchestrator",
);
const QUERY_SCRIPT = path.join(SKILL_ROOT, "scripts", "query_sheet.py");
const execFileAsync = promisify(execFile);
const SHEET_INTENT = [
  /(?:获取|读取|查询|查找|拉取|筛选|列出|查看|看看|处理).{0,18}(?:需求表|表格|表中|表里|待处理需求|处理中需求|需求列表|有哪些需求|有什么需求|需求)/u,
  /(?:需求表|表格|表中|表里).{0,18}(?:获取|读取|查询|查找|处理|需求)/u,
];

function configDirectory(env = process.env) {
  return path.resolve(
    env.FEISHU_ORCHESTRATOR_CONFIG_DIR ||
      path.join(os.homedir(), ".codex", "feishu-requirement-orchestrator"),
  );
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

export function loadWrapperConfig(env = process.env) {
  const directory = configDirectory(env);
  const settings = readJson(path.join(directory, "orchestrator.json"));
  const runtime = settings.runtime || {};
  const gateway = settings.gateway || {};
  const codexPath =
    env.FEISHU_ORCHESTRATOR_CODEX_BIN || gateway.codex_path || env.CODEX_BIN || "codex";
  return {
    directory,
    codexPath: path.isAbsolute(codexPath) ? path.resolve(codexPath) : codexPath,
    model: runtime.model || "gpt-5.6-sol",
    reasoningEffort: runtime.reasoning_effort || "ultra",
    uvPath:
      env.FEISHU_ORCHESTRATOR_UV_BIN || gateway.uv_path || env.UV_BIN || "uv",
  };
}

function optionValue(args, option) {
  const index = args.indexOf(option);
  return index >= 0 ? args[index + 1] : undefined;
}

export function prepareCodexArgs(inputArgs, runtime) {
  const args = [...inputArgs];
  const sandbox = optionValue(args, "--sandbox");
  if (sandbox === "danger-full-access") {
    throw new Error(
      "Bridge POC 禁止 danger-full-access；请把 profile 默认权限设为 read-only，最大权限设为 workspace-write",
    );
  }
  if (sandbox && !["read-only", "workspace-write"].includes(sandbox)) {
    throw new Error(`Bridge POC 不支持沙箱模式: ${sandbox}`);
  }

  const sanitized = args.filter((value) => value !== "--ignore-rules");
  if (!sanitized.includes("exec")) return sanitized;

  const modelIndex = sanitized.indexOf("--model");
  if (modelIndex >= 0) {
    sanitized.splice(modelIndex, 2);
  }
  const execIndex = sanitized.indexOf("exec");
  sanitized.splice(
    execIndex + 1,
    0,
    "--model",
    runtime.model,
    "-c",
    `model_reasoning_effort=${JSON.stringify(runtime.reasoningEffort)}`,
  );
  return sanitized;
}

function normalize(value) {
  return String(value || "")
    .toLocaleLowerCase("zh-CN")
    .replace(/[\s\p{P}\p{S}]/gu, "")
    .replace(/(需求表|表格|表)$/u, "");
}

export function extractUserInput(prompt) {
  const match = String(prompt).match(/<user_input>\s*([\s\S]*?)\s*<\/user_input>/u);
  if (!match) return "";
  try {
    const value = JSON.parse(match[1]);
    return typeof value?.text === "string" ? value.text : "";
  } catch {
    return "";
  }
}

export function selectSheetProfile(text, profiles) {
  if (!SHEET_INTENT.some((pattern) => pattern.test(String(text || "")))) return null;
  const normalizedText = normalize(text);
  const matches = Object.entries(profiles || {}).filter(([profileId, profile]) =>
    [profileId, profile?.display_name, ...(profile?.aliases || [])]
      .map(normalize)
      .some((name) => name && normalizedText.includes(name)),
  );
  return matches.length === 1 ? matches[0][0] : null;
}

function queryContext(profileId, result) {
  return [
    `<sheet_query profile_id=${JSON.stringify(profileId)} source="bridge_preflight">`,
    JSON.stringify(result),
    "</sheet_query>",
  ].join("\n");
}

export async function preloadSheetQuery(prompt, runtime, execute = execFileAsync) {
  const userInput = extractUserInput(prompt);
  if (!userInput) return null;
  const profilesPayload = readJson(path.join(runtime.directory, "profiles.json"));
  const profileId = selectSheetProfile(userInput, profilesPayload.profiles);
  if (!profileId) return null;
  try {
    const { stdout } = await execute(
      runtime.uvPath,
      ["run", QUERY_SCRIPT, "query", "--profile", profileId],
      {
        cwd: PLUGIN_ROOT,
        encoding: "utf8",
        env: {
          ...process.env,
          FEISHU_ORCHESTRATOR_CONFIG_DIR: runtime.directory,
          PYTHONUTF8: "1",
        },
        maxBuffer: 20 * 1024 * 1024,
        timeout: 120000,
        windowsHide: true,
      },
    );
    const result = JSON.parse(stdout);
    if (
      !result ||
      !Number.isInteger(result.count) ||
      !Array.isArray(result.items) ||
      result.items.length !== result.count
    ) {
      throw new Error("需求表查询结果结构无效");
    }
    return queryContext(profileId, result);
  } catch (error) {
    const detail = String(error.stderr || error.message || "未知错误")
      .replace(/(app_secret|authorization|tenant_access_token)[^\r\n]*/giu, "$1=[REDACTED]")
      .trim()
      .slice(0, 1000);
    return queryContext(profileId, { error: `需求表查询失败: ${detail}` });
  }
}

export function prefixBridgePrompt(prompt, preloadedContext = null) {
  const skill = path.join(SKILL_ROOT, "SKILL.md");
  const protocol = path.join(SKILL_ROOT, "references", "lark-bridge-channel.md");
  const sections = [
    `使用位于 ${skill} 的 feishu-requirement-orchestrator Skill。`,
    `当前输入来自 Lark Coding Agent Bridge，必须阅读 ${protocol} 并按其中通道协议处理。`,
    "不得因为 Bridge 提供通用 Codex 会话而绕过需求分析确认、分支确认、复杂度分级、Review 门禁或 Git 发布边界。",
    "如果存在 source=\"bridge_preflight\" 的 <sheet_query>，它是 Bridge 已在 Codex 沙箱外完成的只读查询结果；直接使用，禁止再次运行 query_sheet.py 或 uv 查询。",
    "以下是 Bridge 注入的上下文和用户消息：",
    prompt,
  ];
  if (preloadedContext) sections.push(preloadedContext);
  return sections.join("\n\n");
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

async function run() {
  const config = loadWrapperConfig();
  const args = prepareCodexArgs(process.argv.slice(2), config);
  const isExecution = args.includes("exec");
  let prompt = null;
  let preloadedContext = null;
  if (isExecution) {
    prompt = await readStdin();
    preloadedContext = await preloadSheetQuery(prompt, config);
  }
  const child = spawn(config.codexPath, args, {
    env: process.env,
    stdio: isExecution ? ["pipe", "inherit", "inherit"] : "inherit",
    windowsHide: true,
  });
  if (isExecution) {
    child.stdin.end(prefixBridgePrompt(prompt, preloadedContext), "utf8");
  }
  child.once("error", (error) => {
    process.stderr.write(`无法启动 Codex: ${error.message}\n`);
    process.exitCode = 1;
  });
  child.once("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exitCode = code ?? 1;
  });
}

const invokedDirectly =
  process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (invokedDirectly) {
  run().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
