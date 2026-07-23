# Lark Coding Agent Bridge 通道

仅当输入由 `lark-channel-bridge` 注入 `<bridge_context>` 时使用本协议。正常 Codex 对话和 `feishu-codex-gateway` 继续使用各自原有协议。

## 通道职责

- Bridge 负责飞书长连接、消息队列、附件、会话恢复、流式卡片、引用内容、按钮回调、停止与后台服务。
- 本 Skill 负责需求来源判断、需求表查询、项目和仓库语义、实现必要性、分支门禁、实施、Review 与结果规则。
- 不返回 `feishu-codex-gateway` 的结构化 JSON。直接输出给用户阅读的 Markdown；Bridge 会把输出渲染到当前飞书会话。
- 不调用 `publish_result.py` 或 `query_sheet.py delivery` 重复发送结果。

## 安全门禁

- 初始 profile 必须是 `read-only`，最大权限只能是 `workspace-write`；拒绝 `danger-full-access`。
- 分析阶段保持只读。展示完整分析、方案、当前分支和工作区后暂停，询问用户使用当前分支、创建新分支还是取消。
- 用户确认工作位置后，如果当前运行仍为只读，要求用户通过 Bridge 的 `/config` 把当前 profile 权限切换为工作区写入，再回复“继续”。权限切换完成前不得修改文件或创建分支。
- 延续 Skill 的 Git 边界：不得自动 add、commit、push、merge、发布或部署。
- 只允许使用已经在 orchestrator 配置中登记的代码仓库；用户要求 `/cd` 到其他目录时停止并要求先补充仓库配置。

## 消息与会话

- 群聊 session 按“群 + 发送者哈希”隔离；话题模式再叠加 thread。同一成员的引用回复恢复自己的 session，不同成员不得恢复、停止或重置他人的 session。
- 不可逆发送者哈希只用于内部 scope，不在回复中展示。不同成员在不同项目可以并行；同一仓库或 worktree 仍执行 Skill 的仓库级并发门禁。
- 引用回复时结合 `<quoted_message>` 与当前 user message 判断用户是在确认、修改、取消还是回答实施问题。
- Bridge 将运行期间的新消息排队到下一轮；不要在当前 turn 内等待终端输入。
- 需要用户决定时清楚列出可回复选项后结束当前 turn。

## 需求入口

- 输入包含 `source="bridge_preflight"` 的 `<sheet_query>` 时，查询已由 Bridge wrapper 在 Codex 沙箱外只读完成。直接分析其中结果，不得再次运行 `query_sheet.py`、`uv` 或自行访问需求表。
- 用户要求获取、读取或查询某张需求表时，使用飞书需求表模式。
- 用户直接描述新增、修复或优化内容时，默认作为新需求，不查询或匹配需求表具体记录；profile 只用于项目归属和仓库路由。
- 输入不唯一时先询问，不得猜测需求表或仓库。

## 结果输出

- 分析确认前一次性展示全部候选的原始需求、普通语言说明、验收标准和必要性结论。
- 已实现的需求明确说明 `completed` 及代码证据，不进入分支和实施。
- 实施完成后只展示项目、需求说明、修改内容和待确认事项；测试与 Review 明细保留在内部报告。
- 最终说明代码所在仓库和分支，以及尚未执行的 commit、push 或部署动作。
