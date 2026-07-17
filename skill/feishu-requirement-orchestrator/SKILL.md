---
name: feishu-requirement-orchestrator
description: Read software requirements from a configured Feishu Sheet or Bitable, assess and rank them, verify from repository evidence whether each leading candidate is already implemented or still necessary, implement the highest-ranked necessary item after an explicit branch-choice checkpoint, coordinate one primary implementation agent and three independent review agents, and automatically post the final reviewed result to a pre-authorized Feishu group. Use for scheduled daily requirement processing or when the user asks to analyze, execute, review, or report requirements stored in Feishu.
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

### 首次配置筛选条件

运行 `inspect` 取得真实表头后，必须暂停并明确询问用户“应该通过哪些条件过滤出待处理需求”，不得自行推断后直接保存。展示可用字段，并逐项确认：

- 筛选列；
- 操作符：`equals`、`contains`、`in`、`not_empty`、`date_between` 或 `natural_week`；
- 筛选值，以及日期条件是否使用当前自然周或固定范围；
- 多个条件是否符合预期。当前脚本对多个条件使用 AND，必须告知用户；
- 输出字段。

根据回答生成 profile 草稿并执行试查，完整展示实际生效的 `filters`、命中数量和样例结果。只有用户确认筛选条件与试查结果后才能保存 profile。

默认禁止无筛选查询。用户明确要求读取整张表时，警告可能读取大量或已处理需求，并单独确认；确认后在 profile 中设置 `"allow_unfiltered": true`。不得把空 `filters` 当成用户同意。定时任务没有默认筛选且没有该显式授权时必须停止。

## 查询与选择

1. 运行 `credential list` 和 `profile list`，不要读取凭证文件。
2. 按“解析需求表名称”规则确定唯一 profile，再查询需求。链接为 `/sheets/` 或 `/base/` 时自动分流；`/wiki/` 要求直接链接。
3. 排除 `state.json` 中 `awaiting_analysis_confirmation`、`awaiting_branch_choice`、`needs_confirmation`、`in_progress`、`reported`、`completed`、`obsolete`、`duplicate` 或 `skipped` 的需求。已有 `approved` 需求时优先处理，不重复加入新分析批次。
4. 对每条候选生成结构化评估：业务优先级、影响、紧急度、实现容易度、风险、阻塞项和信息完整性。
5. 运行 `rank_requirements.py` 校验评估并生成候选队列。没有可执行项时输出队列摘要并结束，不调用代码执行或群发布。

```powershell
uv run <skill-dir>\scripts\query_sheet.py query --profile "requirements"
uv run <skill-dir>\scripts\rank_requirements.py --input "评估JSON绝对路径"
```

## 解析需求表名称

用户提供需求表名称、要求切换需求表，或当前配置包含多个 profile 时，先运行：

```powershell
uv run <skill-dir>\scripts\profile_selector.py resolve --name "用户说的表名"
```

结合全部 profile 的 `profile_id`、`display_name`、`aliases` 和 `description` 按以下顺序判断：

1. 精确匹配 `profile_id`。
2. 精确或规范化匹配 `display_name`、`aliases`，忽略大小写、空白、标点和“需求表/表格/表”等通用后缀。
3. 判断名称包含关系、关键词和业务语义是否指向同一张表。不要只按字符串相似度决定。

只有一个可信候选时，明确告知用户“已解析为 `display_name`（`profile_id`）”并使用该 profile。存在两个或更多文本或语义都合理的候选时，展示每个候选的 `display_name`、`profile_id`、别名、用途和默认工作表/数据表，暂停让用户选择。没有可信候选时列出全部可用 profile 并询问。确认唯一 profile 前不得查询需求、修改默认 profile 或继续后续流程。

用户说“本次使用”时只在当前调用传递 `--profile`。用户说“切换到”“以后使用”或“设为默认”时，在唯一解析后执行：

```powershell
uv run <skill-dir>\scripts\profile_selector.py switch --profile-id "profile-id"
```

不要根据相似群名、飞书工作表标签或 URL 猜 profile；需求表配置名与 profile 内部的 `default_sheet` / `default_table` 是不同概念。

## 实现状态与必要性核验

对候选队列中的所有需求完成只读核验后再询问用户，不要在分析第一条后暂停。查看相关代码、测试、配置、文档和 `git log`，逐条对照验收标准，并给出以下唯一建议结论之一：

- `not_started`：没有实现证据，且需求仍适用；建议批准实施。
- `partially_done`：已有部分实现；列出已完成和剩余验收项，建议只实施剩余范围。
- `completed`：所有验收项已有实现与验证证据；建议标记已完成。
- `obsolete`：需求前提已经消失或当前产品行为使其无必要；建议标记失效。
- `duplicate`：与已有实现或另一需求重复；建议标记重复。
- `needs_confirmation`：证据冲突或不足；要求用户在批量确认时给出判断或选择暂缓。

每个结论必须提供具体证据，例如文件与行号、测试名称、提交、配置或明确的飞书业务状态。不要仅凭搜索不到关键词判定 `not_started`，也不要仅凭存在相似代码判定 `completed`。`completed` 必须逐项覆盖验收标准；`obsolete` 和 `duplicate` 必须说明依据。

完成全部核验后，为本批次生成唯一 `batch_id`，按排序为每条需求写入待确认状态：

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --status awaiting_analysis_confirmation --batch-id "20260717-001" --rank 1 --proposed-status partially_done --reason "已有查询，缺少去重" --evidence "src/example.ts:42" --remaining-criterion "已处理需求不得重复执行"
```

向用户一次性展示整个批次，至少包含：排序、需求 ID、标题、优先级、建议结论、理由、证据、剩余验收项和建议动作。明确提供“全部确认”以及“按需求 ID 批量修改结论”两种回复方式。不得逐条弹出确认，也不得在用户回复前写入最终结论、选择分支或修改代码。

用户批量确认后统一落盘：

- `completed`、`obsolete`、`duplicate`：写入对应终态。
- `not_started`、`partially_done`：写入 `approved`；部分完成项保留剩余验收范围。
- `needs_confirmation`：用户已给出结论则写入修正后的状态；仍无法判断则保留 `needs_confirmation`，但不阻塞同批其他已批准需求。

从全部 `approved` 需求中选择排序最高的一条进入分支确认，本轮仍最多实施一条。其余 `approved` 项保留到后续轮次；实施前重新核对证据，若仓库变化导致结论变化，必须放入新的批次再次统一确认。候选全部无需实施时，在批量确认落盘后结束，不询问分支、不修改代码、不发最终实施报告。

## 分支选择检查点

选择需求后只读检查目标仓库，展示：

- 需求 ID、标题、验收标准和选择原因
- 必要性结论、证据，以及 `partially_done` 时的剩余验收项
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
