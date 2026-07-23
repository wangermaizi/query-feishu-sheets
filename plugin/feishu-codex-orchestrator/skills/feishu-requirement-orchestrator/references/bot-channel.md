# 飞书机器人通道

仅当输入明确来自 `feishu-codex-gateway` 时使用本协议。正常 Codex 对话继续使用原有展示和暂停方式。

## 通道边界

- 按网关任务中的 `source_mode` 处理来源。`manual` 把用户正文视为手动需求；`sheet` 使用网关提供的 `sheet_query` 作为只读需求表查询结果，不得再次查询或回写飞书。
- `manual` 默认是一项新需求。profile 只表示项目归属，仓库候选只用于代码路由；不得读取需求表、匹配表内相似记录或绑定已有需求 ID。只有用户明确要求查询需求表时才进入 `sheet`。
- `sheet` 模式对查询结果中的全部候选生成普通语言说明和必要性分析，再一次性交给用户确认；不得把“获取某需求表的需求”误建为一条手动需求。
- 所有需要用户决定的节点都结束当前 turn，由网关发送卡片。不得等待终端输入或自行假设用户选择。
- 不直接调用 `publish_result.py`、`query_sheet.py delivery` 或其他飞书发送命令；网关负责发送并绑定消息。
- 分析确认前保持仓库只读。只有用户先确认分析，再明确选择当前分支或确认新分支名称后，才允许修改代码。
- 延续现有边界：可以修改和测试，但不得自动 add、commit、push、merge、发布或部署。

## 结构化响应

每个 turn 返回网关要求的 JSON 字段：

- `status`：`awaiting_user`、`completed`、`blocked` 或 `failed`。
- `stage`：`analysis_confirmation`、`branch_choice`、`implementation`、`review`、`question`、`final` 或 `blocked`。
- `card_title`：包含项目名和当前动作的简短标题，不显示内部状态 ID。
- `card_markdown`：给普通用户阅读的完整内容。分析阶段同时包含原始需求、普通语言说明、验收标准草稿、必要性结论和证据。
- `next_action`：用户可以直接引用回复的明确选项；完成时说明代码当前所在位置及尚未执行的提交、推送或发布动作。
- `write_authorized`：只有用户已经明确选择当前分支或确认新分支名称时为 `true`。分析确认、来源选择和仓库选择阶段为 `false`；一旦授权，执行中的追问及其后续回复保持 `true`。

不得把内部推理、凭证、访问令牌、完整环境变量或不必要的代码日志放进卡片。

## 状态映射

1. 网关先区分需求表查询和手动需求；无法唯一判断时先由网关卡片询问，不启动代码分析。
2. 首次分析完成：返回 `awaiting_user / analysis_confirmation`，让用户确认、修改或取消，并返回 `write_authorized: false`。
3. 用户确认分析：完成复杂度分级和只读方案，返回 `awaiting_user / branch_choice`，展示当前分支与完整候选分支名，仍返回 `write_authorized: false`。
4. 用户确认工作位置：返回 `write_authorized: true`，执行完整实现、测试和分级 Review。只有遇到真实阻塞或需要额外产品决定时才返回 `awaiting_user / question`；后续问答保持写入授权，否则处理到最终结果。
5. 成功完成：返回 `completed / final`。Review 阻塞或外部条件不足：返回 `blocked / blocked`。
