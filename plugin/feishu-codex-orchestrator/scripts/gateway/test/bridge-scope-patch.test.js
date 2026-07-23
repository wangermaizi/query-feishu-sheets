import assert from "node:assert/strict";
import test from "node:test";

import { patchBridgeSource } from "../../bridge/patch-user-scope.mjs";

const scopeFixture = `async function resolveScope(deps) {
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
}
  const scope = chatMode === "topic" && threadId ? \`\${msg.chatId}:\${threadId}\` : msg.chatId;`;
const stopFixture = [
  "  if (targetScope) {",
  "    await reply(",
  "      ctx,",
  "      ok ? `\\u5DF2\\u8BF7\\u6C42\\u505C\\u6B62 \\`${scope}\\`\\u3002` : `\\u672A\\u627E\\u5230\\u6B63\\u5728\\u8FD0\\u884C\\u7684\\u4EFB\\u52A1\\uFF1A\\`${scope}\\`\\u3002`",
  "    );",
  "  }",
].join("\n");
const fixture = `${scopeFixture}\n${stopFixture}`;

test("patch isolates group sessions by a non-reversible sender hash", () => {
  const result = patchBridgeSource(fixture);
  assert.equal(result.changed, true);
  assert.match(result.source, /senderScopedBridgeScope/u);
  assert.match(result.source, /digestCanonical\(\{ senderId:/u);
  assert.match(result.source, /baseScope, chatMode, msg\.senderId/u);
  assert.doesNotMatch(result.source, /user:\$\{senderId\}/u);
});

test("patch makes an untargeted stop command answer when nothing is running", () => {
  const result = patchBridgeSource(fixture);
  assert.match(result.source, /\\u5F53\\u524D\\u6CA1\\u6709/u);
});

test("patch is idempotent", () => {
  const first = patchBridgeSource(fixture);
  const second = patchBridgeSource(first.source);
  assert.equal(second.changed, false);
  assert.equal(second.source, first.source);
});
