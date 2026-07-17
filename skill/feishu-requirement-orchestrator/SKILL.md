---
name: feishu-requirement-orchestrator
description: Read software requirements from a configured Feishu Sheet or Bitable, assess and rank them, implement the highest-ranked eligible item after an explicit branch-choice checkpoint, coordinate one primary implementation agent and three independent review agents, and automatically post the final reviewed result to a pre-authorized Feishu group. Use for scheduled daily requirement processing or when the user asks to analyze, execute, review, or report requirements stored in Feishu.
---

# 飞书需求自动执行

使用内置脚本读取飞书需求并管理结果发布。先读 [workflow.md](references/workflow.md)；处理字段映射时读 [requirement-schema.md](references/requirement-schema.md)；开始 Review 前读 [review-rubrics.md](references/review-rubrics.md)。始终通过 `uv run` 执行 Python 脚本。

## 强制边界

- 每轮最多选择一条可执行需求。
- 查询和分析阶段保持目标代码仓库只读。
- 在修改文件、安装依赖或创建分支前暂停，向用户展示需求、方案、当前分支和工作区状态，并询问：使用当前分支、创建独立分支，还是取消。
- 用户未回复时停止。不得替用户选择分支，也不得提前创建分支。
- 保留已有未提交修改。发现与需求相关的未提交修改时明确告知用户并等待决定。
- 可以修改代码和运行测试；不得自动 `git add`、commit、push、merge、发布或部署。
- 三个 Review 子 Agent 只读审查，不得修改文件。由主 Agent 统一修复。
- 飞书需求源保持只读，不回写状态。
- 只向设置中已明确授权且 `auto_publish: true` 的固定 `chat_id` 自动发送最终结果。发送失败后不得自动重试。
- 不输出 App Secret、access token 或 Authorization 请求头。

## 配置

默认运行目录为 `%USERPROFILE%\.codex\feishu-requirement-orchestrator`。可用 `FEISHU_ORCHESTRATOR_CONFIG_DIR` 覆盖。运行目录包含：

- `credentials.json`：飞书应用凭证，禁止读取或输出其内容。
- `profiles.json`：飞书查询 profile。
- `orchestrator.json`：字段映射、目标仓库默认值、模型要求及固定群授权。
- `state.json`：本地处理状态，用于防止定时任务重复执行同一需求。

首次使用时根据 [requirement-schema.md](references/requirement-schema.md) 创建配置草稿，隐藏密钥后展示非敏感配置，获得用户确认再保存。覆盖现有配置前再次确认。

## 查询与选择

1. 运行 `credential list` 和 `profile list`，不要读取凭证文件。
2. 使用已配置 profile 查询需求。链接为 `/sheets/` 或 `/base/` 时自动分流；`/wiki/` 要求直接链接。
3. 排除 `state.json` 中 `awaiting_branch_choice`、`in_progress` 或 `reported` 的需求。
4. 对每条候选生成结构化评估：业务优先级、影响、紧急度、实现容易度、风险、阻塞项和信息完整性。
5. 运行 `rank_requirements.py` 校验评估并选择一条需求。没有可执行项时输出队列摘要并结束，不调用代码执行或群发布。

```powershell
uv run <skill-dir>\scripts\query_sheet.py query --profile "requirements"
uv run <skill-dir>\scripts\rank_requirements.py --input "评估JSON绝对路径"
```

## 分支选择检查点

选择需求后只读检查目标仓库，展示：

- 需求 ID、标题、验收标准和选择原因
- 实施步骤、预计文件和验证命令
- 当前分支及 `git status --short`
- 使用当前分支、创建 `codex/<slug>` 分支或取消三个选项

将需求状态标记为 `awaiting_branch_choice`，随后暂停。用户选择当前分支后直接继续；只有用户明确选择新分支时才创建。用户取消时标记为 `skipped`。

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --title "需求标题" --status awaiting_branch_choice
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --status skipped
```

## 实施与 Review

实施前将状态改为 `in_progress`：

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --status in_progress
```

先阅读目标仓库的 `AGENTS.md` 和相关代码，做范围最小的修改并运行与风险匹配的检查。

主 Agent 完成初次实现后，同时启动三个子 Agent，分别使用 [review-rubrics.md](references/review-rubrics.md) 的三个角色。只传递需求、验收标准、目标仓库路径、当前 diff 和测试结果，不传递预期结论。要求 Reviewer 返回带文件和行号的发现；没有问题时明确说明残余测试风险。

主 Agent核实每条发现，修复成立的问题并重新运行相关检查。不得用 Reviewer 的结论替代实际验证。

## 发布最终结果

生成符合 [result-schema.md](references/result-schema.md) 的 JSON 报告。先预览并保留哈希，再立即向预授权群发布同一报告；这是用户对固定群的持续授权，不需要每次再次询问。报告变化导致哈希不一致时重新生成预览，禁止绕过检查。

```powershell
uv run <skill-dir>\scripts\publish_result.py preview --report "报告绝对路径"
uv run <skill-dir>\scripts\publish_result.py publish --report "报告绝对路径" --expected-hash "预览哈希" --confirm
```

发送成功后将需求标记为 `reported` 并返回消息 ID。发送失败时标记为 `report_failed`，报告错误并停止；不得重试：

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --status reported
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --status report_failed
```

代码结果即使未发送也必须保留，不得回滚用户或主 Agent 的修改。

## 模型与调度

Skill 不能自行定时唤醒。每日运行由 Codex Automation 或外部调度器调用本 Skill；手动调用执行同一状态机。

检查运行环境能否满足 `orchestrator.json` 中的模型与推理强度要求。默认要求 `gpt-5.6` 和 `ultra`；环境无法确认或不支持时明确报告并停止，不静默降级。模型选择属于运行器配置，不写入业务脚本。

## 飞书脚本

内置 `query_sheet.py` 支持 `inspect`、`query`、`chat`、`delivery`、`profile` 和 `credential`。管理及错误处理规则沿用飞书表格查询流程：保存、覆盖和删除配置必须确认；群名不唯一时使用 `chat_id`；任何命令失败时只转述脱敏错误。
