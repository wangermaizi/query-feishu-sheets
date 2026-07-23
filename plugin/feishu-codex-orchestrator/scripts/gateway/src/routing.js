function normalize(value) {
  return String(value || "")
    .toLocaleLowerCase("zh-CN")
    .replace(/[\s\p{P}\p{S}]/gu, "")
    .replace(/(需求表|表格|表)$/u, "");
}

const SHEET_INTENT = [
  /(?:获取|读取|查询|查找|拉取|筛选|列出|查看|看看|处理).{0,18}(?:需求表|表格|表中|表里|待处理需求|处理中需求|需求列表|有哪些需求|有什么需求|需求)/u,
  /(?:需求表|表格|表中|表里).{0,18}(?:获取|读取|查询|查找|处理|需求)/u,
];
const MANUAL_INTENT =
  /(?:新增|增加|修复|解决|优化|调整|修改|重构|实现|支持|改成|改为|异常|报错|失败|不能|无法)/u;

export function sourceModeCandidate(text) {
  const value = String(text || "");
  const sheet = SHEET_INTENT.some((pattern) => pattern.test(value));
  const manual = MANUAL_INTENT.test(value);
  if (sheet && !manual) return { decision: "selected", source_mode: "sheet" };
  if (manual && !sheet) return { decision: "selected", source_mode: "manual" };
  return { decision: "semantic_required" };
}

export function resolveSourceModeReply(text) {
  const value = normalize(text);
  if (/^(?:1|需求表|查询需求表|读取需求表|表格)$/u.test(value)) return "sheet";
  if (/^(?:2|直接描述|当前描述|处理当前描述|手动需求|描述需求)$/u.test(value)) return "manual";
  return null;
}

export function routeCandidates(text, chatId, config, { preferSemantic = false } = {}) {
  const normalizedText = normalize(text);
  const exact = config.routes.filter((route) =>
    [route.profile_id, route.display_name, ...route.aliases]
      .map(normalize)
      .some((name) => name && normalizedText.includes(name)),
  );
  if (exact.length === 1) {
    return { decision: "selected", reason: "explicit_name", route: exact[0] };
  }
  if (exact.length > 1) {
    return { decision: "ambiguous", reason: "multiple_names", candidates: exact };
  }
  const defaultProfile = preferSemantic ? null : config.chatDefaults[chatId];
  if (defaultProfile) {
    return {
      decision: "selected",
      reason: "chat_default",
      route: config.routes.find((item) => item.profile_id === defaultProfile),
    };
  }
  if (config.routes.length === 1) {
    return { decision: "selected", reason: "only_profile", route: config.routes[0] };
  }
  return { decision: "semantic_required", candidates: config.routes };
}

export function resolveProfileReply(text, routes) {
  const numeric = Number.parseInt(String(text).trim(), 10);
  if (String(numeric) === String(text).trim() && numeric >= 1 && numeric <= routes.length) {
    return routes[numeric - 1];
  }
  const normalized = normalize(text);
  const matches = routes.filter((route) =>
    [route.profile_id, route.display_name, ...route.aliases]
      .map(normalize)
      .some((name) => name && (name === normalized || normalized.includes(name))),
  );
  return matches.length === 1 ? matches[0] : null;
}

export function publicRoutes(routes) {
  return routes.map(({ profile_id, display_name, aliases, description, project_name }) => ({
    profile_id,
    display_name,
    aliases,
    description,
    project_name,
  }));
}

export function repositoryCandidates(text, repositories) {
  if (repositories.length === 1) {
    return { decision: "selected", reason: "only_repository", repository: repositories[0] };
  }
  const normalizedText = normalize(text);
  const matches = repositories.filter((repository) =>
    [repository.repository_id, repository.display_name, ...repository.aliases]
      .map(normalize)
      .some((name) => name && normalizedText.includes(name)),
  );
  if (matches.length === 1) {
    return { decision: "selected", reason: "explicit_repository", repository: matches[0] };
  }
  if (matches.length > 1) {
    return { decision: "ambiguous", reason: "multiple_repositories", candidates: matches };
  }
  return { decision: "semantic_required", candidates: repositories };
}

export function resolveRepositoryReply(text, repositories) {
  const numeric = Number.parseInt(String(text).trim(), 10);
  if (
    String(numeric) === String(text).trim() &&
    numeric >= 1 &&
    numeric <= repositories.length
  ) {
    return repositories[numeric - 1];
  }
  const normalized = normalize(text);
  const matches = repositories.filter((repository) =>
    [repository.repository_id, repository.display_name, ...repository.aliases]
      .map(normalize)
      .some((name) => name && (name === normalized || normalized.includes(name))),
  );
  return matches.length === 1 ? matches[0] : null;
}

export function publicRepositories(repositories) {
  return repositories.map(
    ({ repository_id, display_name, aliases, description, project_name }) => ({
      candidate_id: repository_id,
      display_name,
      aliases,
      description,
      project_name,
    }),
  );
}
