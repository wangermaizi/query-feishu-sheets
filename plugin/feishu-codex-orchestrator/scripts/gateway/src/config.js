import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

export class ConfigError extends Error {}

export function configDirectory(env = process.env) {
  return path.resolve(
    env.FEISHU_ORCHESTRATOR_CONFIG_DIR ||
      path.join(os.homedir(), ".codex", "feishu-requirement-orchestrator"),
  );
}

function readObject(file, label) {
  let value;
  try {
    value = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new ConfigError(`缺少${label}: ${file}`);
    }
    throw new ConfigError(`${label}不是有效 JSON: ${file}`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ConfigError(`${label}必须是 JSON 对象: ${file}`);
  }
  return value;
}

function stringArray(value, label) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item.trim())) {
    throw new ConfigError(`${label}必须为非空字符串数组`);
  }
  return [...new Set(value.map((item) => item.trim()))];
}

function nonEmpty(value, label) {
  if (typeof value !== "string" || !value.trim()) {
    throw new ConfigError(`${label}不能为空`);
  }
  return value.trim();
}

function codexExecutable(gateway) {
  const configured = gateway.codex_path || process.env.CODEX_BIN;
  if (configured) {
    const resolved = path.resolve(configured);
    if (!fs.existsSync(resolved)) throw new ConfigError(`Codex 可执行文件不存在: ${resolved}`);
    return resolved;
  }
  if (process.platform === "win32") {
    const result = spawnSync("where.exe", ["codex.exe"], { encoding: "utf8" });
    const candidate = result.stdout?.split(/\r?\n/).find((value) => value.trim());
    if (candidate && fs.existsSync(candidate.trim())) return path.resolve(candidate.trim());
    throw new ConfigError("找不到 codex.exe；请安装 Codex 桌面应用或配置 gateway.codex_path");
  }
  const result = spawnSync("sh", ["-lc", "command -v codex"], { encoding: "utf8" });
  const candidate = result.stdout?.trim();
  if (!candidate) throw new ConfigError("找不到 codex；请安装 Codex CLI 或配置 gateway.codex_path");
  return path.resolve(candidate);
}

function uvExecutable(gateway) {
  const configured = gateway.uv_path || process.env.UV_BIN;
  if (configured) {
    const resolved = path.resolve(configured);
    if (!fs.existsSync(resolved)) throw new ConfigError(`uv 可执行文件不存在: ${resolved}`);
    return resolved;
  }
  if (process.platform === "win32") {
    const result = spawnSync("where.exe", ["uv.exe"], { encoding: "utf8" });
    const candidate = result.stdout?.split(/\r?\n/).find((value) => value.trim());
    if (candidate && fs.existsSync(candidate.trim())) return path.resolve(candidate.trim());
    throw new ConfigError("找不到 uv.exe；请安装 uv 或配置 gateway.uv_path");
  }
  const result = spawnSync("sh", ["-lc", "command -v uv"], { encoding: "utf8" });
  const candidate = result.stdout?.trim();
  if (!candidate) throw new ConfigError("找不到 uv；请安装 uv 或配置 gateway.uv_path");
  return path.resolve(candidate);
}

function repositoryRoute(value, index, fallbackProject) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ConfigError(`repositories[${index}] 必须是对象`);
  }
  const repositoryPath = value.path || value.repository;
  const identity = value.repository_id || value.id || value.label || value.name;
  return {
    repository_id: nonEmpty(identity, `repositories[${index}].id`),
    display_name: nonEmpty(
      value.display_name || value.label || value.name || identity,
      `repositories[${index}].display_name`,
    ),
    aliases: stringArray(value.aliases, `repositories[${index}].aliases`),
    description: typeof value.description === "string" ? value.description.trim() : "",
    path:
      typeof repositoryPath === "string" && repositoryPath.trim()
        ? path.resolve(repositoryPath)
        : null,
    project_name:
      typeof (value.project_name || fallbackProject) === "string"
        ? (value.project_name || fallbackProject).trim()
        : null,
  };
}

function profileRoute(profileId, profile, settings, gateway) {
  const override = gateway.profile_routes?.[profileId] || {};
  const projectName =
    override.project_name || profile.default_project_name || settings.default_project_name || null;
  const configuredRepositories =
    override.repositories ||
    profile.repositories ||
    (settings.repository_routing?.mode === "semantic"
      ? settings.repository_routing.routes
      : undefined);
  let repositories;
  if (configuredRepositories !== undefined) {
    if (!Array.isArray(configuredRepositories) || !configuredRepositories.length) {
      throw new ConfigError(`profile_routes.${profileId}.repositories 必须是非空数组`);
    }
    repositories = configuredRepositories.map((value, index) =>
      repositoryRoute(value, index, projectName),
    );
  } else {
    const repository =
      override.repository || profile.default_repository || settings.default_repository || null;
    repositories = repository
      ? [
          repositoryRoute(
            {
              id: "default",
              display_name: projectName || profile.display_name || profileId,
              path: repository,
              project_name: projectName,
            },
            0,
            projectName,
          ),
        ]
      : [];
  }
  const ids = repositories.map((item) => item.repository_id);
  if (new Set(ids).size !== ids.length) {
    throw new ConfigError(`profile_routes.${profileId}.repositories 的 id 不能重复`);
  }
  return {
    profile_id: profileId,
    display_name: profile.display_name || profileId,
    aliases: stringArray(profile.aliases, `profiles.${profileId}.aliases`),
    description: typeof profile.description === "string" ? profile.description.trim() : "",
    repositories,
    repository: repositories.length === 1 ? repositories[0].path : null,
    project_name: typeof projectName === "string" && projectName.trim() ? projectName.trim() : null,
  };
}

export function loadGatewayConfig(env = process.env) {
  const directory = configDirectory(env);
  const settings = readObject(path.join(directory, "orchestrator.json"), "运行配置");
  const credentials = readObject(path.join(directory, "credentials.json"), "飞书凭证");
  const profilesPayload = readObject(path.join(directory, "profiles.json"), "需求表配置");
  const gateway = settings.gateway;
  if (!gateway || typeof gateway !== "object" || Array.isArray(gateway)) {
    throw new ConfigError("orchestrator.json 缺少 gateway 配置");
  }
  if (gateway.enabled !== true) {
    throw new ConfigError("飞书 Codex 网关尚未启用，请设置 gateway.enabled=true");
  }

  const credentialName = nonEmpty(
    gateway.credential || settings.delivery?.credential,
    "gateway.credential",
  );
  const credential = credentials.credentials?.[credentialName];
  if (!credential || typeof credential !== "object") {
    throw new ConfigError(`找不到飞书凭证: ${credentialName}`);
  }
  const appId = nonEmpty(credential.app_id, `credentials.${credentialName}.app_id`);
  const appSecret = nonEmpty(credential.app_secret, `credentials.${credentialName}.app_secret`);

  const fallbackChatId = settings.delivery?.chat_id;
  const allowedChatIds = stringArray(
    gateway.allowed_chat_ids || (fallbackChatId ? [fallbackChatId] : []),
    "gateway.allowed_chat_ids",
  );
  if (!allowedChatIds.length) {
    throw new ConfigError("gateway.allowed_chat_ids 至少需要一个已授权群");
  }

  const profiles = profilesPayload.profiles;
  if (!profiles || typeof profiles !== "object" || Array.isArray(profiles)) {
    throw new ConfigError("profiles.json 缺少 profiles 对象");
  }
  const routes = Object.entries(profiles).map(([id, profile]) => {
    if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
      throw new ConfigError(`需求表配置无效: ${id}`);
    }
    return profileRoute(id, profile, settings, gateway);
  });
  if (!routes.length) {
    throw new ConfigError("至少需要一个需求表 profile");
  }

  const chatDefaults = gateway.chat_default_profiles || {};
  if (!chatDefaults || typeof chatDefaults !== "object" || Array.isArray(chatDefaults)) {
    throw new ConfigError("gateway.chat_default_profiles 必须是对象");
  }
  for (const [chatId, profileId] of Object.entries(chatDefaults)) {
    if (!allowedChatIds.includes(chatId)) {
      throw new ConfigError(`默认需求表对应的群未授权: ${chatId}`);
    }
    if (!routes.some((route) => route.profile_id === profileId)) {
      throw new ConfigError(`群 ${chatId} 的默认 profile 不存在: ${profileId}`);
    }
  }

  const runtime = settings.runtime || {};
  const timeoutMinutes = gateway.turn_timeout_minutes ?? 180;
  if (!Number.isInteger(timeoutMinutes) || timeoutMinutes < 5 || timeoutMinutes > 1440) {
    throw new ConfigError("gateway.turn_timeout_minutes 必须是 5 到 1440 的整数");
  }

  return {
    directory,
    stateFile: path.join(directory, "gateway-state.json"),
    statusFile: path.join(directory, "gateway-status.json"),
    logFile: path.join(directory, "gateway.log"),
    credentialName,
    appId,
    appSecret,
    allowedChatIds: new Set(allowedChatIds),
    adminOpenIds: new Set(stringArray(gateway.admin_open_ids, "gateway.admin_open_ids")),
    chatDefaults,
    routes,
    requireGroupMention: gateway.require_group_mention !== false,
    model: nonEmpty(runtime.model || "gpt-5.6-sol", "runtime.model"),
    reasoningEffort: nonEmpty(runtime.reasoning_effort || "ultra", "runtime.reasoning_effort"),
    failOnUnsupported: runtime.fail_on_unsupported !== false,
    turnTimeoutMs: timeoutMinutes * 60 * 1000,
    networkAccessEnabled: gateway.network_access === true,
    codexPath: codexExecutable(gateway),
    uvPath: uvExecutable(gateway),
  };
}

export function publicConfig(config) {
  return {
    directory: config.directory,
    credential: config.credentialName,
    allowed_chat_ids: [...config.allowedChatIds],
    admin_open_ids: [...config.adminOpenIds],
    chat_default_profiles: config.chatDefaults,
    profiles: config.routes,
    runtime: {
      model: config.model,
      reasoning_effort: config.reasoningEffort,
      turn_timeout_minutes: config.turnTimeoutMs / 60000,
      network_access: config.networkAccessEnabled,
      codex_path: config.codexPath,
      uv_path: config.uvPath,
    },
  };
}
