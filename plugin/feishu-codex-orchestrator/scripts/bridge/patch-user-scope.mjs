#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const PATCH_MARKER = "feishu-orchestrator-sender-scope-v1";

const ORIGINAL_SCOPE_RESOLVER = `async function resolveScope(deps) {
  const chatId = deps.evt.chatId;
  const mode = await deps.chatModeCache.resolve(deps.channel, chatId);
  if (mode !== "topic") {
    return { scope: chatId, threadId: void 0, mode };
  }
  const threadId = await lookupMessageThreadId(deps.channel, deps.evt.messageId);
  if (!threadId) {
    return { scope: chatId, threadId: void 0, mode };
  }
  return { scope: \`\${chatId}:\${threadId}\`, threadId, mode };
}`;

const PATCHED_SCOPE_RESOLVER = `// ${PATCH_MARKER}
function senderScopedBridgeScope(baseScope, mode, senderId) {
  if (mode === "p2p") return baseScope;
  const senderHash = digestCanonical({ senderId: String(senderId || "") }).slice(0, 16);
  return \`\${baseScope}:user:\${senderHash}\`;
}
async function resolveScope(deps) {
  const chatId = deps.evt.chatId;
  const mode = await deps.chatModeCache.resolve(deps.channel, chatId);
  if (mode !== "topic") {
    return {
      scope: senderScopedBridgeScope(chatId, mode, deps.evt.operator.openId),
      threadId: void 0,
      mode
    };
  }
  const threadId = await lookupMessageThreadId(deps.channel, deps.evt.messageId);
  const baseScope = threadId ? \`\${chatId}:\${threadId}\` : chatId;
  return {
    scope: senderScopedBridgeScope(baseScope, mode, deps.evt.operator.openId),
    threadId: threadId || void 0,
    mode
  };
}`;

const ORIGINAL_INTAKE_SCOPE =
  '  const scope = chatMode === "topic" && threadId ? `${msg.chatId}:${threadId}` : msg.chatId;';
const PATCHED_INTAKE_SCOPE = `  const baseScope = chatMode === "topic" && threadId ? \`\${msg.chatId}:\${threadId}\` : msg.chatId;
  const scope = senderScopedBridgeScope(baseScope, chatMode, msg.senderId);`;

const ORIGINAL_STOP_REPLY = [
  "  if (targetScope) {",
  "    await reply(",
  "      ctx,",
  "      ok ? `\\u5DF2\\u8BF7\\u6C42\\u505C\\u6B62 \\`${scope}\\`\\u3002` : `\\u672A\\u627E\\u5230\\u6B63\\u5728\\u8FD0\\u884C\\u7684\\u4EFB\\u52A1\\uFF1A\\`${scope}\\`\\u3002`",
  "    );",
  "  }",
].join("\n");
const PATCHED_STOP_REPLY = [
  "  await reply(",
  "    ctx,",
  "    targetScope",
  "      ? ok",
  "        ? `\\u5DF2\\u8BF7\\u6C42\\u505C\\u6B62 \\`${scope}\\`\\u3002`",
  "        : `\\u672A\\u627E\\u5230\\u6B63\\u5728\\u8FD0\\u884C\\u7684\\u4EFB\\u52A1\\uFF1A\\`${scope}\\`\\u3002`",
  "      : ok",
  '        ? "\\u5DF2\\u8BF7\\u6C42\\u505C\\u6B62\\u5F53\\u524D\\u4EFB\\u52A1\\u3002"',
  '        : "\\u5F53\\u524D\\u6CA1\\u6709\\u8FD0\\u884C\\u4E2D\\u7684\\u4EFB\\u52A1\\u3002"',
  "  );",
].join("\n");

function replaceExactlyOnce(source, before, after, label) {
  const first = source.indexOf(before);
  if (first < 0) throw new Error(`找不到 Bridge ${label} 补丁锚点`);
  if (source.indexOf(before, first + before.length) >= 0) {
    throw new Error(`Bridge ${label} 补丁锚点不唯一`);
  }
  return source.slice(0, first) + after + source.slice(first + before.length);
}

export function patchBridgeSource(source) {
  if (source.includes(PATCH_MARKER)) return { source, changed: false };
  let patched = replaceExactlyOnce(
    source,
    ORIGINAL_SCOPE_RESOLVER,
    PATCHED_SCOPE_RESOLVER,
    "callback scope",
  );
  patched = replaceExactlyOnce(
    patched,
    ORIGINAL_INTAKE_SCOPE,
    PATCHED_INTAKE_SCOPE,
    "message scope",
  );
  patched = replaceExactlyOnce(
    patched,
    ORIGINAL_STOP_REPLY,
    PATCHED_STOP_REPLY,
    "stop reply",
  );
  return { source: patched, changed: true };
}

export function patchBridgeFile(target) {
  const absolute = path.resolve(target);
  const original = fs.readFileSync(absolute, "utf8");
  const result = patchBridgeSource(original);
  if (!result.changed) return { target: absolute, changed: false, backup: null };
  const timestamp = new Date().toISOString().replace(/[-:TZ.]/gu, "").slice(0, 14);
  const backup = `${absolute}.backup-${timestamp}`;
  const temporary = `${absolute}.${process.pid}.tmp`;
  fs.copyFileSync(absolute, backup);
  fs.writeFileSync(temporary, result.source, "utf8");
  fs.renameSync(temporary, absolute);
  return { target: absolute, changed: true, backup };
}

const invokedDirectly =
  process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (invokedDirectly) {
  const target = process.argv[2];
  if (!target) {
    process.stderr.write("Usage: patch-user-scope.mjs <lark-channel-bridge dist/cli.js>\n");
    process.exitCode = 2;
  } else {
    try {
      process.stdout.write(`${JSON.stringify(patchBridgeFile(target))}\n`);
    } catch (error) {
      process.stderr.write(`${error.message}\n`);
      process.exitCode = 1;
    }
  }
}
