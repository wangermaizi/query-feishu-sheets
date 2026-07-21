# Feishu Requirement Orchestrator

该仓库构建一个 Codex Skill：接收用户直接描述的需求，或从飞书读取软件需求，分析并选择一条需求，由主 Agent 在实施前判断复杂度，在用户确认工作分支后按复杂度实施、测试和 Review，并把最终结果自动发送到预授权飞书群。

候选需求进入代码修改前，Skill 会只读核验目标仓库，判断需求是尚未实现、部分实现、已经完成、已经失效、与其他需求重复，还是证据不足需要人工确认。只有尚未实现或部分实现且仍有必要的需求才会进入分支选择和实施阶段。

飞书最终结果卡片使用 `【项目名】需求标题` 作为标题，不显示需求 ID。项目名来自需求字段或已确认的 `default_project_name`；无法确定时必须询问用户，不能只显示需求标题或根据仓库路径猜测。

群卡片保持简洁，只显示执行信息、选择原因、普通语言需求说明、修改内容和待确认事项。复杂度策略、必要性证据、测试明细、Review 结果和残余风险仍保留在内部报告中用于校验，但不推送到群里。

每轮会先完成全部候选需求的分析，再把结果作为一个批次交给用户统一确认。每条需求会同时显示原始内容、普通人能看懂的需求说明和技术分析；需求说明会讲清当前情况、用户影响、期望结果，并在复杂场景下给出简单例子。用户无需再单独要求 Codex 二次梳理。用户可以一次确认全部，也可以按需求 ID 批量修正；确认前不会写入最终分类或修改代码。确认后仍按排序每轮最多实施一条需求。

配置多个需求表后，可以使用不完全一致的表名切换。Skill 会结合 profile ID、显示名、别名和用途描述做语义判断；只有一个可信候选时采用该表，存在多个合理候选时必须让用户选择，确认具体 profile 前不会查询需求或继续执行。

首次配置需求表时，Skill 必须在检查真实字段后询问默认筛选列、操作符和值，并展示试查结果供用户确认。默认禁止空筛选；只有用户明确确认读取整张表后才能设置 `allow_unfiltered: true`。

没有需求表时可以直接在调用 Skill 的消息中描述一条或多条需求。Skill 会整理标题和验收标准草稿，补问无法确定的项目名与仓库，生成 `MANUAL-YYYYMMDD-序号` 本地 ID，并继续使用相同的普通语言说明、必要性核验、统一确认、分支选择、开发、测试、分级 Review 和群推送流程。手动需求不会创建或回写飞书记录。

选定要实施的需求后，主 Agent 会在分支确认前分为 `fast`、`standard` 或 `strict`。最多两个文件、局部且无高风险信号的需求使用快速流程：定向测试和一个综合 Review；3 到 8 个文件的普通范围使用三路并行 Review 一轮；超过 8 个文件或涉及数据库、权限、安全、公开接口、跨模块等高风险修改才使用严格流程和最多两轮复审。分级结果和理由会在实施前展示，避免小需求承担完整重流程。

Review 使用强制阶段门禁。主 Agent 必须先独立完成所有验收项、相关代码和初步测试，形成完整候选 diff，之后才能启动 Reviewer；禁止实现前的 Design Review，也禁止改一个文件就审一次。门禁记录候选文件快照，确保 Reviewer 审查同一版本；全部返回后主 Agent 才能集中修复。普通问题不会触发新一轮完整 Review，只有高严重度、公共契约变化或范围升级才允许严格档进行一次定向复审。

处理状态按 Git 仓库和 worktree 隔离，而不是使用全局单任务锁。另一个项目存在 `in_progress` 时当前项目可以继续；同一工作目录仍会被保护。相同仓库的不同 worktree 可以在用户确认后并行。旧版没有仓库信息的活动记录会要求关联一次仓库，不会要求将旧需求改为 `skipped`。内部状态键包含仓库范围，因此两个项目都存在“需求 31”时也不会互相覆盖；并行写状态由进程锁保护。

## 安全边界

- 修改代码前必须询问使用当前分支还是创建独立分支。
- 新分支使用 `<type>/<YYYYMMDD>/<summary>` 格式，例如 `feature/20260717/新增超额支付预警`；类型为 `feature`、`fix` 或 `refactor`，创建前必须确认。
- 不自动 add、commit、push、merge、发布或部署。
- 飞书需求表只读；本地状态文件防止重复处理。
- 不同代码仓库允许由不同 Codex 任务并行处理；同一 worktree 禁止并行，同一仓库不同 worktree 需用户明确确认。
- 只向明确配置 `auto_publish: true` 的固定 `chat_id` 发送一次，失败不重试。
- 凭证和运行配置位于 `%USERPROFILE%\.codex\feishu-requirement-orchestrator`，不进入构建产物。

## 开发

```powershell
uv sync
uv run pytest
.\scripts\build.ps1
```

构建结果位于 `dist\feishu-requirement-orchestrator\` 和 `dist\feishu-requirement-orchestrator.zip`。

构建脚本只依赖仓库内的校验器，不要求构建机器预先安装 `skill-creator`。同时会生成 `dist\feishu-requirement-orchestrator.sha256`，用于校验 ZIP 是否完整。

## GitHub Actions 自动打包

工作流文件位于 `.github\workflows\build-skill.yml`，使用 GitHub 托管的 Windows runner 执行与本地相同的 `scripts\build.ps1`。

触发规则：

- 向 `main` 分支 push：运行测试、校验并打包；
- 向 `main` 创建或更新 Pull Request：运行同样的构建检查；
- 在 GitHub Actions 页面手动运行 `Build Skill`；
- 推送 `v*` 标签：构建产物并自动创建或更新对应的 GitHub Release。

每次成功构建都会在 GitHub Actions 的运行详情中保存 30 天产物，包含：

```text
feishu-requirement-orchestrator.zip
feishu-requirement-orchestrator.sha256
```

发布正式版本时执行：

```powershell
git tag v0.1.0
git push origin v0.1.0
```

标签工作流成功后，可从项目的 [GitHub Releases](https://github.com/wangermaizi/query-feishu-sheets/releases) 查看 AI 根据实际改动生成的中文更新日志，并下载离线安装包及 SHA-256 文件。Release 正文直接使用 `CHANGELOG.md` 中当前 tag 对应的版本章节，不使用 GitHub 自动生成的 “Full Changelog” 作为发布说明。普通 push 和 Pull Request 只生成 Actions 临时产物，不创建 Release。

## 使用发布 Skill

仓库包含 `.agents\skills\release-query-feishu-sheets`。在本仓库中对 Codex 说“部署”“发布”“发版”或显式调用以下提示词时，会触发完整发布流程：

```text
使用 $release-query-feishu-sheets 部署当前改动。
```

发布 Skill 会：

1. 检查分支、远程仓库、GitHub 登录状态和待提交文件；
2. 根据改动选择下一个语义化版本，首次发布使用 `v0.1.0`；
3. 先根据实际改动生成面向使用者的中文更新日志，再更新 `pyproject.toml`、`uv.lock` 和 `CHANGELOG.md`；
4. 提取当前版本章节作为 GitHub Release 正文，并运行测试、Skill 校验和本地打包；
5. 提交改动并依次推送 `main` 和新 tag；
6. 确认 GitHub Actions 已出现该 tag 对应的 `Build Skill` 运行记录。

发现流水线运行记录后任务立即结束，不等待流水线成功或失败，也不检查 GitHub Release 产物。部署过程禁止强推；如果本地分支落后、存在疑似凭证或检查失败，会在 commit 和 tag 前停止。

## 离线安装 Skill

安装机器需要已有 Codex 桌面应用、Codex CLI 或 Codex IDE 扩展。把构建生成的 `feishu-requirement-orchestrator.zip` 复制到目标机器后，不需要从网络下载 Skill 依赖即可完成安装。

### 安装到当前用户

Codex 当前的用户级 Skill 目录是 `$HOME\.agents\skills`。在 PowerShell 中执行：

```powershell
$skillRoot = Join-Path $HOME ".agents\skills"
New-Item -ItemType Directory -Force $skillRoot | Out-Null
Expand-Archive `
  -LiteralPath "D:\path\to\feishu-requirement-orchestrator.zip" `
  -DestinationPath $skillRoot `
  -Force
```

安装后的文件应位于：

```text
%USERPROFILE%\.agents\skills\feishu-requirement-orchestrator\SKILL.md
```

### 只安装到某个仓库

如果 Skill 只供一个代码仓库使用，也可以解压到该仓库的 `.agents\skills`：

```powershell
$skillRoot = "D:\workspace\target-repository\.agents\skills"
New-Item -ItemType Directory -Force $skillRoot | Out-Null
Expand-Archive `
  -LiteralPath "D:\path\to\feishu-requirement-orchestrator.zip" `
  -DestinationPath $skillRoot `
  -Force
```

仓库级安装后的文件应位于：

```text
D:\workspace\target-repository\.agents\skills\feishu-requirement-orchestrator\SKILL.md
```

### 升级已有安装

先保留旧目录作为备份，再解压新包，避免新版删除的旧文件残留：

```powershell
$skillRoot = Join-Path $HOME ".agents\skills"
$installed = Join-Path $skillRoot "feishu-requirement-orchestrator"
$backup = "$installed.backup-$(Get-Date -Format yyyyMMddHHmmss)"

if (Test-Path -LiteralPath $installed) {
  Move-Item -LiteralPath $installed -Destination $backup
}

Expand-Archive `
  -LiteralPath "D:\path\to\feishu-requirement-orchestrator.zip" `
  -DestinationPath $skillRoot
```

确认新版本正常后再人工删除备份目录。Codex 通常会自动发现 Skill；如果 `/skills` 中没有出现，重启 Codex。

Skill 安装目录与运行配置目录不是同一个位置：Skill 安装在 `.agents\skills`，飞书凭证、profile 和处理状态默认保存在 `%USERPROFILE%\.codex\feishu-requirement-orchestrator`。

“离线安装”仅表示可以通过本地压缩包安装 Skill。实际执行时仍需连接 Codex 模型服务和飞书开放平台 API。

## 使用 Skill

在 Codex CLI 或 IDE 中运行 `/skills`，或者在输入框输入 `$`，确认列表中存在 `feishu-requirement-orchestrator`。

首次配置完成后，可以显式调用：

```text
使用 $feishu-requirement-orchestrator 读取今天的飞书需求，分析候选项并处理优先级最高的一条。
```

也可以指定只分析，不执行代码修改：

```text
使用 $feishu-requirement-orchestrator 查询并分析当前需求队列，只给出排序结果，不要修改代码或发送群消息。
```

没有需求表时可以直接提供需求：

```text
使用 $feishu-requirement-orchestrator 处理下面的需求：

回款金额超过最新应收金额时，在列表中显示异常提醒，
让用户可以及时定位并删除错误的回款记录。

项目名：应收系统
代码仓库：D:\workspace\receivables
```

用户没有单独列出验收标准时，Codex 会生成可验证的草稿，并与需求说明和技术分析一起放入同一批确认。手动模式不要求配置飞书凭证、需求表 profile、字段映射或筛选条件；模型要求、项目默认值、仓库默认值和固定群授权仍沿用运行配置。

当用户描述与 Skill 的 `description` 匹配时，Codex 也可以自动选择该 Skill；涉及自动执行时建议显式写出 `$feishu-requirement-orchestrator`，避免触发意图不清晰。

执行到代码修改阶段时，Skill 必须展示复杂度与验证策略，并暂停询问使用当前分支、创建独立分支还是取消。用户回复前不会修改目标仓库。完成分级要求的修改、测试和 Review 后，结果会发送到预先授权的固定飞书群。

Codex Skill 的发现位置和调用方式以 [OpenAI Codex Skills 文档](https://learn.chatgpt.com/docs/build-skills) 为准。

## 让 Codex 完成首次配置

可以只提供启动配置所需的最少信息，也可以一次性提供已经确定的全部业务信息。Codex 会先检查已有凭证和飞书表结构，自动推断字段映射，只询问无法确定或必须确认的内容。

### 最小配置

首次开始只需要提供：

- 飞书 `/sheets/` 或 `/base/` 直接链接；
- 一个便于以后切换的配置名称；
- 用自然语言描述的默认筛选要求。

```text
使用 $feishu-requirement-orchestrator 帮我完成首次配置。

需求表链接：
配置名称：产品需求表
筛选要求：状态等于待处理，并且负责人包含张三

请先 inspect 表结构，自动推断字段映射，只询问缺失信息。展示筛选条件、映射和试查结果，等我确认后再保存。
```

工作表或数据表、需求字段映射和飞书凭证名称通常不需要提前填写：存在多个候选时 Codex 才会让用户选择。筛选要求必须确认，但可以直接说业务语言，不需要自己编写 `equals`、`contains` 等内部格式。

### 一次性完整配置

已经知道更多信息时可以一次性提供，以减少后续问答：

```text
使用 $feishu-requirement-orchestrator 帮我完成首次配置。

需求表链接：
配置名称：产品需求表
筛选要求：状态等于待处理，并且负责人包含张三

默认项目名：OA
默认代码仓库：D:\workspace\oas
工作表/数据表：需求池

目标群：项目需求确认群
每天执行时间：工作日 09:00

请先 inspect 表结构并自动推断字段映射。目标群存在多个匹配时让我选择；展示配置和试查结果，等我确认后再保存 profile、群授权和自动任务。
```

这些信息按需提供：

- `默认项目名`：需求表没有项目字段时需要，用于群消息标题；
- `默认代码仓库`：需求表没有仓库字段时需要；
- `工作表/数据表`：链接包含多个候选且用户已经知道目标时可提供；
- `目标群`：启用群推送时提供群名即可，Codex 会解析并在重名时要求选择；
- `每天执行时间`：需要创建定时任务时提供。

不要求用户预先填写完整字段映射、`chat_id`、模型名称或推理强度。需要覆盖 Skill 默认模型要求时再单独说明。

不要在对话中直接发送 App Secret。应先把密钥放入本地受保护的凭证草稿或环境变量，再让 Codex 测试并保存；Codex 不应在回复中显示密钥、access token 或 Authorization 请求头。

Codex 必须在以下节点暂停并获得确认：

- 保存或覆盖飞书凭证；
- 保存或覆盖查询 profile；
- 授权固定 `chat_id` 自动接收结果；
- 创建每日自动任务。

`gpt-5.6` 和 `ultra` 属于 Codex 运行环境能力。Skill 只能声明并检查要求，不能自行安装或模拟模型。运行环境不支持且配置要求禁止降级时，任务必须停止并明确报告。
