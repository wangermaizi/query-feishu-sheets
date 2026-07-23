import assert from "node:assert/strict";
import test from "node:test";

import {
  repositoryCandidates,
  resolveProfileReply,
  resolveRepositoryReply,
  resolveSourceModeReply,
  routeCandidates,
  sourceModeCandidate,
} from "../src/routing.js";

const routes = [
  {
    profile_id: "product",
    display_name: "产品需求表",
    aliases: ["产品需求"],
    description: "产品研发",
  },
  {
    profile_id: "support",
    display_name: "客服需求表",
    aliases: ["客服需求"],
    description: "客户支持",
  },
];

function config(overrides = {}) {
  return { routes, chatDefaults: {}, ...overrides };
}

test("explicit table name overrides the chat default", () => {
  const result = routeCandidates(
    "请处理客服需求表里的导出问题",
    "oc_chat",
    config({ chatDefaults: { oc_chat: "product" } }),
  );
  assert.equal(result.route.profile_id, "support");
  assert.equal(result.reason, "explicit_name");
});

test("requires semantic routing when multiple profiles remain", () => {
  const result = routeCandidates("导出报表失败", "oc_chat", config());
  assert.equal(result.decision, "semantic_required");
  assert.equal(result.candidates.length, 2);
});

test("profile reply accepts sequence number or alias", () => {
  assert.equal(resolveProfileReply("2", routes).profile_id, "support");
  assert.equal(resolveProfileReply("产品需求", routes).profile_id, "product");
  assert.equal(resolveProfileReply("需求", routes), null);
});

test("routes one requirement table to one of several repositories", () => {
  const repositories = [
    {
      repository_id: "oas",
      display_name: "OAS",
      aliases: ["后台"],
      description: "入职管理后台",
    },
    {
      repository_id: "preboard",
      display_name: "Preboard",
      aliases: ["入职端"],
      description: "新员工入职端",
    },
  ];
  assert.equal(
    repositoryCandidates("Preboard 增加入职提醒", repositories).repository.repository_id,
    "preboard",
  );
  assert.equal(repositoryCandidates("优化入职流程", repositories).decision, "semantic_required");
  assert.equal(resolveRepositoryReply("1", repositories).repository_id, "oas");
});

test("distinguishes sheet queries from directly described requirements", () => {
  assert.deepEqual(sourceModeCandidate("帮我获取新应收的需求"), {
    decision: "selected",
    source_mode: "sheet",
  });
  assert.deepEqual(sourceModeCandidate("优化新入职工作经历同步逻辑"), {
    decision: "selected",
    source_mode: "manual",
  });
  assert.equal(sourceModeCandidate("看一下这个事情").decision, "semantic_required");
  assert.equal(resolveSourceModeReply("1"), "sheet");
  assert.equal(resolveSourceModeReply("处理当前描述"), "manual");
});

test("manual requirements use semantic profile routing instead of the chat default", () => {
  const result = routeCandidates(
    "导出报表失败",
    "oc_chat",
    config({ chatDefaults: { oc_chat: "product" } }),
    { preferSemantic: true },
  );
  assert.equal(result.decision, "semantic_required");
});
