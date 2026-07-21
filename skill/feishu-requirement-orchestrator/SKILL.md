---
name: feishu-requirement-orchestrator
description: Accept software requirements directly from the user's message or read them from a configured Feishu Sheet or Bitable, assess and rank them, verify from repository evidence whether they are already implemented or still necessary, classify implementation complexity, implement the highest-ranked necessary item after an explicit branch-choice checkpoint, apply complexity-proportional testing and review, and post the final reviewed result to a pre-authorized Feishu group. Use for directly described requirements, scheduled Feishu requirement processing, or when the user asks to analyze, execute, review, or report software requirements.
---

# 软件需求自动执行

接收用户直接描述的需求，或使用内置脚本读取飞书需求，并管理分析、实施与结果发布。先读 [workflow.md](references/workflow.md)；处理需求结构或字段映射时读 [requirement-schema.md](references/requirement-schema.md)；开始 Review 前读 [review-rubrics.md](references/review-rubrics.md)。始终通过 `uv run` 执行 Python 脚本。

## 强制边界

- 每个 Codex 任务每轮最多选择一条可执行需求；不同仓库可以由不同 Codex 任务并行处理。
- 查询和分析阶段保持目标代码仓库只读。
- 在修改文件、安装依赖或创建分支前暂停，向用户展示需求、方案、当前分支和工作区状态，并询问：使用当前分支、创建独立分支，还是取消。
- 用户未回复时停止。不得替用户选择分支，也不得提前创建分支。
- 保留已有未提交修改。发现与需求相关的未提交修改时明确告知用户并等待决定。
- 可以修改代码和运行测试；不得自动 `git add`、commit、push、merge、发布或部署。
- Review 子 Agent 只读审查，不得修改文件。数量和轮次由复杂度分级决定，由主 Agent 统一修复。
- 飞书需求源保持只读，不回写状态。
- 只向设置中已明确授权且 `auto_publish: true` 的固定 `chat_id` 自动发送最终结果。发送失败后不得自动重试。
- 不输出 App Secret、access token 或 Authorization 请求头。

## 配置

默认运行目录为 `%USERPROFILE%\.codex\feishu-requirement-orchestrator`。可用 `FEISHU_ORCHESTRATOR_CONFIG_DIR` 覆盖。运行目录包含：

- `credentials.json`：飞书应用凭证，禁止读取或输出其内容。
- `profiles.json`：飞书查询 profile。
- `orchestrator.json`：字段映射、目标仓库默认值、模型要求及固定群授权。
- `state.json`：带仓库与 worktree 范围的本地处理状态，用于防止重复处理和同目录并发冲突；脚本使用进程锁避免并行写入互相覆盖。

手动需求模式不要求配置飞书凭证或 profile，但仍使用 `orchestrator.json` 中已确认的模型、默认项目、默认仓库和群授权。缺少本次执行所必需的配置时只询问缺失项，不强迫用户初始化需求表。

首次使用时根据 [requirement-schema.md](references/requirement-schema.md) 创建配置草稿，隐藏密钥后展示非敏感配置，获得用户确认再保存。覆盖现有配置前再次确认。

同时确认用于群消息标题的项目名。优先映射需求表中的项目字段；同一 profile 固定属于一个项目时可设置 `default_project_name`。项目名不明确时必须询问用户，不得从仓库目录名、远程仓库名或需求标题猜测。

### 首次配置筛选条件

运行 `inspect` 取得真实表头后，必须暂停并明确询问用户“应该通过哪些条件过滤出待处理需求”，不得自行推断后直接保存。展示可用字段，并逐项确认：

- 筛选列；
- 操作符：`equals`、`contains`、`in`、`not_empty`、`date_between` 或 `natural_week`；
- 筛选值，以及日期条件是否使用当前自然周或固定范围；
- 多个条件是否符合预期。当前脚本对多个条件使用 AND，必须告知用户；
- 输出字段。

根据回答生成 profile 草稿并执行试查，完整展示实际生效的 `filters`、命中数量和样例结果。只有用户确认筛选条件与试查结果后才能保存 profile。

默认禁止无筛选查询。用户明确要求读取整张表时，警告可能读取大量或已处理需求，并单独确认；确认后在 profile 中设置 `"allow_unfiltered": true`。不得把空 `filters` 当成用户同意。定时任务没有默认筛选且没有该显式授权时必须停止。

## 确定需求入口

先判断本次需求来源，不要默认强迫用户使用飞书：

- 用户消息中已经直接描述要新增、修复或重构的具体内容时，使用手动需求模式。即使已配置 profile，也不得忽略用户正文改为查询需求表。
- 用户明确要求读取、切换或处理某张需求表，或只说“处理今天的需求”而没有提供需求正文时，使用飞书需求表模式。
- 两种来源同时出现且用户意图不明确时，暂停询问本次处理用户正文、需求表，还是两者一起进入同一分析批次。

### 手动需求模式

从用户消息提取一条或多条需求的标题、完整描述、验收标准、项目名、仓库、优先级和参考资料。标题可根据正文概括；用户没有明确写验收标准时，先生成可验证的验收标准草稿，并在统一批量确认中让用户一并确认。项目名和仓库优先使用用户本次明确提供的值，其次使用已确认的 `default_project_name` 和 `default_repository`；仍不唯一时必须询问，不得从目录名或需求标题猜测。

把草稿写入运行配置目录或系统临时目录，不得写入目标代码仓库。运行脚本校验并生成 `MANUAL-<YYYYMMDD>-<序号>` ID：

```powershell
uv run <skill-dir>\scripts\manual_requirement.py --input "手动需求JSON绝对路径"
```

脚本会校验项目名、已存在的绝对仓库路径和非空验收标准，并根据 Asia/Shanghai 当天日期及 `state.json` 生成递增 ID。内容指纹与已记录需求完全相同时，优先恢复或说明原需求状态，不得创建新需求；只有用户明确要求作为新需求再次处理时才使用 `--allow-duplicate`。

手动需求不查询或回写飞书，也不要求 profile、字段映射或筛选条件。生成 ID 后与飞书需求共用后续排序、普通语言说明、必要性核验、批量确认、复杂度分级、分支选择、实施、Review 和结果发布流程。写入待确认状态时必须保存原始描述和来源信息，保证恢复后内容完整：

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "MANUAL-20260721-001" --status awaiting_analysis_confirmation --title "回款金额异常提醒" --description "用户直接描述的原始需求" --acceptance-criterion "列表显示异常提醒" --project-name "应收系统" --repository "D:\workspace\receivables" --source-type manual --source-fingerprint "脚本输出的指纹" --batch-id "20260721-001" --rank 1 --proposed-status not_started --reason "尚无实现" --plain-language-summary "现状：...影响：...目标：..."
```

### 飞书需求表模式

1. 运行 `credential list` 和 `profile list`，不要读取凭证文件。
2. 按“解析需求表名称”规则确定唯一 profile，再查询需求。链接为 `/sheets/` 或 `/base/` 时自动分流；`/wiki/` 要求直接链接。
3. 按“仓库级并行隔离”读取 `state.json`。只排除当前需求自身已经处于 `awaiting_analysis_confirmation`、`awaiting_branch_choice`、`needs_confirmation`、`in_progress`、`reported`、`completed`、`obsolete`、`duplicate` 或 `skipped` 的记录。只优先处理当前目标仓库已有的 `approved` 需求；其他仓库的等待项和活动项不得阻塞或被当前任务接管。
4. 对每条候选生成结构化评估：业务优先级、影响、紧急度、实现容易度、风险、阻塞项、信息完整性和 `plain_language_summary`。说明必须使用非技术人员能理解的业务语言，依次讲清当前情况、问题或用户影响、期望结果；场景复杂时补一个具体例子。不得只改写标题，也不得用技术证据代替说明。
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

每条需求的技术结论之外，必须同时保留原始需求并输出 `plain_language_summary`。使用“现状、问题或影响、期望结果、示例（复杂场景时）”的顺序，让不了解代码和内部术语的人直接明白为什么要做、做完会怎样。普通语言说明是对技术分析的补充，不得替换建议结论、证据、验收项或原始内容。

完成全部核验后，为本批次生成唯一 `batch_id`，按排序为每条需求写入待确认状态：

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --repository "D:\workspace\example" --status awaiting_analysis_confirmation --batch-id "20260717-001" --rank 1 --proposed-status partially_done --reason "已有查询，缺少去重" --plain-language-summary "现状：系统能读取需求。影响：同一需求可能被重复处理。目标：已处理需求不再重复执行。" --evidence "src/example.ts:42" --remaining-criterion "已处理需求不得重复执行"
```

向用户一次性展示整个批次。每条需求必须把普通语言的“需求说明”和技术分析放在一起，至少包含：来源、排序、需求 ID、标题、原始需求、验收标准、优先级、需求说明、建议结论、理由、证据、剩余验收项和建议动作。手动生成的验收标准草稿必须明确标注。需求说明必须覆盖当前情况、问题或用户影响和期望结果，复杂场景补充简单例子。明确提供“全部确认”以及“按需求 ID 批量修改结论”两种回复方式。不得逐条弹出确认，也不得在用户回复前写入最终结论、选择分支或修改代码。

用户批量确认后统一落盘：

- `completed`、`obsolete`、`duplicate`：写入对应终态。
- `not_started`、`partially_done`：写入 `approved`；部分完成项保留剩余验收范围。
- `needs_confirmation`：用户已给出结论则写入修正后的状态；仍无法判断则保留 `needs_confirmation`，但不阻塞同批其他已批准需求。

从全部 `approved` 需求中选择排序最高的一条进入分支确认，本轮仍最多实施一条。其余 `approved` 项保留到后续轮次；实施前重新核对证据，若仓库变化导致结论变化，必须放入新的批次再次统一确认。候选全部无需实施时，在批量确认落盘后结束，不询问分支、不修改代码、不发最终实施报告。

## 复杂度分级

主 Agent 在选出本轮需求后、展示分支确认前，根据只读仓库证据评估预计修改文件、验收清晰度、跨模块范围和风险信号。不要让 Reviewer 代替主 Agent 分级，也不得为了省时隐瞒风险。把评估写入临时 JSON：

```json
{
  "estimated_files": ["src/view.ts", "tests/view.test.ts"],
  "acceptance_clear": true,
  "cross_module": false,
  "risk_flags": [],
  "reason": "局部行为修改，预计只影响实现和对应测试",
  "minimum_tier": "fast"
}
```

运行：

```powershell
uv run <skill-dir>\scripts\complexity_policy.py --input "复杂度评估JSON绝对路径"
```

分为三档：

- `fast`：预计最多修改 2 个文件、验收明确、局部变更、不跨模块且没有高风险信号。执行定向测试，启动 1 个综合只读 Reviewer，最多 1 轮。
- `standard`：预计修改 3 到 8 个文件且范围仍明确，或主 Agent 主动提高等级。执行相关模块测试，同时启动 3 个独立 Reviewer，默认只审 1 轮。
- `strict`：预计修改超过 8 个文件，或涉及架构、数据库迁移、数据丢失、权限、安全、公开 API、外部契约、依赖升级、部署、并发、跨模块或范围不确定。执行更广检查，启动 3 个独立 Reviewer，最多 2 轮。

`risk_flags` 使用 `architecture`、`auth_permissions`、`concurrency`、`data_loss`、`database_migration`、`dependency_upgrade`、`deployment`、`external_contract`、`public_api`、`scope_uncertain` 或 `security`。任一风险信号、跨模块或验收不清晰都会强制进入 `strict`。主 Agent 可以通过 `minimum_tier` 提高级别，不得降低脚本算出的级别。

向用户展示分级、理由、预计文件、风险信号、测试范围、Reviewer 数量和轮次上限，并与分支选择一起确认，不增加独立确认步骤。把分级写入 `state.json`。如果实施中发现范围或风险扩大，立即重新运行分级；升级到 `strict` 且需要扩大修改范围时暂停告知用户，未升级时继续执行。

## 仓库级并行隔离

在进入分支确认或恢复活动需求前，根据目标仓库检查活动范围：

```powershell
uv run <skill-dir>\scripts\run_state.py check-scope --repository "D:\workspace\example"
```

严格按 `decision` 处理：

- `clear`：继续。`other_repositories` 只用于提示其他项目正在运行，不得暂停当前项目，也不得建议把它们标记为 `skipped`。
- `blocked_same_worktree`：同一工作目录已有 `awaiting_branch_choice`、`in_progress` 或 `report_failed`，停止当前需求，避免分支和未提交修改互相覆盖。
- `parallel_worktree_confirmation_required`：同一 Git 仓库但不同 worktree。展示两个工作目录，用户明确同意并行后，用 `--allow-parallel-worktree` 重新检查，并在写入活动状态时同时传入该参数。
- `legacy_scope_confirmation_required`：旧活动记录没有仓库范围。询问旧需求所属仓库并执行 `attach-scope`，不得要求用户取消或跳过旧需求。关联一次后重新检查：

```powershell
uv run <skill-dir>\scripts\run_state.py attach-scope --id "31" --repository "D:\workspace\old-project"
```

脚本使用 Git common directory 识别同一仓库，使用 top-level path 区分 worktree；非 Git 目录使用绝对目录作为范围。内部状态键由仓库范围与需求 ID 共同生成，因此不同项目中相同的需求 ID 不会覆盖。所有后续 `mark` 命令都传入 `--repository`；需求 ID 在多个仓库重复且未传仓库时，脚本必须拒绝猜测。

## 分支选择检查点

选择需求后只读检查目标仓库，展示：

- 需求 ID、标题、验收标准和选择原因
- 必要性结论、证据，以及 `partially_done` 时的剩余验收项
- 复杂度分级、理由、预计文件、风险信号和对应验证策略
- 实施步骤、预计文件和验证命令
- 当前分支及 `git status --short`
- 使用当前分支、创建按下述规范生成的新分支或取消三个选项

将需求状态连同 `--complexity-tier` 和 `--complexity-reason` 标记为 `awaiting_branch_choice`，随后暂停。用户选择当前分支后直接继续；只有用户明确选择新分支时才创建。用户取消时标记为 `skipped`。

新分支必须使用 `<type>/<YYYYMMDD>/<summary>` 三段格式：

- `type`：新增需求或新增功能使用 `feature`；修复缺陷使用 `fix`；不改变外部行为的结构调整使用 `refactor`。类型不明确时先询问用户。
- `YYYYMMDD`：使用创建分支当日的 Asia/Shanghai 日期。
- `summary`：用简短中文或小写英文描述本次主要修改，去除空格和 Git 禁止字符，不得包含 `/`，不得使用“新需求”“修复问题”“代码调整”等无具体含义的名称。

先生成并校验建议名称：

```powershell
uv run <skill-dir>\scripts\branch_name.py propose --type feature --summary "新增超额支付预警"
git check-ref-format --branch "feature/20260717/新增超额支付预警"
```

向用户展示完整名称，并允许使用建议名称、修改名称或取消。用户确认后再检查本地和远程是否已有同名分支；存在时暂停让用户决定新名称，不得自动追加数字或随机后缀。创建分支不代表允许 push。

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --repository "D:\workspace\example" --title "需求标题" --status awaiting_branch_choice
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --repository "D:\workspace\example" --status skipped
```

## 实施与 Review

实施前将状态改为 `in_progress`：

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --repository "D:\workspace\example" --status in_progress
```

先阅读目标仓库的 `AGENTS.md` 和相关代码，做范围最小的修改并运行与风险匹配的检查。

主 Agent 必须先独立完成全部验收项的代码、测试和必要迁移，形成一份完整候选 diff。实现过程中可以运行定向测试，但不得启动任何名为 Design、功能、测试、质量、安全或其他用途的 Review 子 Agent；设计判断由主 Agent 在实施方案和编码阶段完成。不得按文件、模块或验收项边改边 Review。

完整实现和初测完成后，写入 Review 门禁。`--candidate-file` 必须覆盖本次完整候选 diff，不能只登记刚改的一部分：

```powershell
uv run <skill-dir>\scripts\review_gate.py prepare --id "REQ-1024" --repository "D:\workspace\example" --implementation-summary "全部验收项已实现" --test-result "定向测试通过" --candidate-file "src/service.py" --candidate-file "tests/test_service.py"
uv run <skill-dir>\scripts\review_gate.py start --id "REQ-1024" --repository "D:\workspace\example"
```

`prepare` 会记录候选文件内容快照；`start` 会在快照未变化时才放行。只有 `start` 成功并返回 `review_phase: reviewing` 后才允许创建 Reviewer。按复杂度策略和 [review-rubrics.md](references/review-rubrics.md)：`fast` 启动 1 个综合 Reviewer；`standard` 和 `strict` 同时启动 3 个独立 Reviewer。所有 Reviewer 必须审查同一份完整 diff，只传递需求、全部验收标准、候选文件、完整 diff 和测试结果，不传递预期结论。

Reviewer 运行期间主 Agent 不得修改文件。必须等待本轮全部 Reviewer 返回，把结果一次性写入同一个 JSON，再通过门禁收集：

```powershell
uv run <skill-dir>\scripts\review_gate.py collect --id "REQ-1024" --repository "D:\workspace\example" --results "本轮全部Review结果JSON绝对路径"
```

`collect` 会再次核对候选文件快照，文件变化时拒绝收集。`collect` 未成功前不得开始修复。收齐后由主 Agent 一次性核实所有发现，形成一份合并修复清单，集中完成全部成立问题，再统一运行受影响测试。不得在某个 Reviewer 返回后立即修改，再让其他 Reviewer 审查不同版本。

集中修复后关闭本轮：

```powershell
uv run <skill-dir>\scripts\review_gate.py complete --id "REQ-1024" --repository "D:\workspace\example" --resolution-summary "已集中处理全部成立问题" --test-result "受影响测试通过"
```

`fast` 和 `standard` 固定一轮。只有高严重度修复、公共契约变化或范围升级时，先重新分级为 `strict`，再用 `--request-rereview high_severity|public_contract|scope_upgrade` 申请第二轮；第二轮只邀请受影响 Reviewer，不重新全量审查。准备定向复审时再次运行 `prepare` 并传相同的 `--rereview-reason`。`strict` 最多两轮，达到上限后把未解决问题列为阻塞或残余风险。不得用 Reviewer 的结论替代实际验证。

## 发布最终结果

先运行 `review_gate.py status`。只有 `review_phase: review_complete` 才能生成符合 [result-schema.md](references/result-schema.md) 的 JSON 报告，并把门禁中的实现完成时间、首次 Review 开始时间和收齐状态写入 `review_process`。随后预览并保留哈希，再立即向预授权群发布同一报告；这是用户对固定群的持续授权，不需要每次再次询问。报告变化导致哈希不一致时重新生成预览，禁止绕过检查。

报告必须包含非空 `project_name`。飞书卡片标题固定使用 `【project_name】title`，不显示需求 ID，确保用户在消息列表中无需展开卡片即可识别项目和需求。项目名无法从已确认字段或 `default_project_name` 唯一确定时，发布前暂停询问用户。

群卡片只展示执行信息、选择原因、普通语言需求说明、修改内容和待确认事项。复杂度与验证策略、实施必要性核验、测试明细、Review 结果和残余风险继续保留在内部报告用于校验，但不得渲染到群卡片。

```powershell
uv run <skill-dir>\scripts\publish_result.py preview --report "报告绝对路径"
uv run <skill-dir>\scripts\publish_result.py publish --report "报告绝对路径" --expected-hash "预览哈希" --confirm
```

发送成功后将需求标记为 `reported` 并返回消息 ID。发送失败时标记为 `report_failed`，报告错误并停止；不得重试：

```powershell
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --repository "D:\workspace\example" --status reported
uv run <skill-dir>\scripts\run_state.py mark --id "REQ-1024" --repository "D:\workspace\example" --status report_failed
```

代码结果即使未发送也必须保留，不得回滚用户或主 Agent 的修改。

## 模型与调度

Skill 不能自行定时唤醒。每日运行由 Codex Automation 或外部调度器调用本 Skill；直接描述需求和手动调用执行同一状态机。

检查运行环境能否满足 `orchestrator.json` 中的模型与推理强度要求。默认要求 `gpt-5.6` 和 `ultra`；环境无法确认或不支持时明确报告并停止，不静默降级。模型选择属于运行器配置，不写入业务脚本。

## 飞书脚本

内置 `query_sheet.py` 支持 `inspect`、`query`、`chat`、`delivery`、`profile` 和 `credential`。管理及错误处理规则沿用飞书表格查询流程：保存、覆盖和删除配置必须确认；群名不唯一时使用 `chat_id`；任何命令失败时只转述脱敏错误。
