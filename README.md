# Feishu Codex Orchestrator

该仓库构建一个 Codex Plugin，并继续提供兼容的独立 Skill。Plugin 通过登录后自动运行的本地网关维持飞书长连接：用户在授权群中 @机器人描述需求，网关识别对应需求表和本地仓库，创建独立 Codex thread，把分析结果作为卡片回复；用户继续引用回复卡片即可确认、修改、选择分支或取消，后续始终恢复同一需求和同一 Codex thread。

网关连接的是本机 Codex 运行时，不要求 Codex 桌面窗口保持打开。电脑必须保持登录、开机、联网且不休眠；注销、关机或休眠期间不会接收或执行需求。Plugin 不把本地方案描述为云端 7×24 小时服务。

候选需求进入代码修改前，Skill 会只读核验目标仓库，判断需求是尚未实现、部分实现、已经完成、已经失效、与其他需求重复，还是证据不足需要人工确认。只有尚未实现或部分实现且仍有必要的需求才会进入分支选择和实施阶段。

飞书最终结果卡片使用 `【项目名】需求标题` 作为标题，不显示需求 ID。项目名来自需求字段或已确认的 `default_project_name`；无法确定时必须询问用户，不能只显示需求标题或根据仓库路径猜测。

群卡片保持简洁，只显示执行信息、普通语言需求说明、修改内容和待确认事项。选择原因、复杂度策略、必要性证据、测试明细、Review 结果和残余风险仍保留在内部报告中用于校验，但不推送到群里。

每轮会先完成全部候选需求的分析，再把结果作为一个批次交给用户统一确认。每条需求会同时显示原始内容、普通人能看懂的需求说明和技术分析；需求说明会讲清当前情况、用户影响、期望结果，并在复杂场景下给出简单例子。用户无需再单独要求 Codex 二次梳理。用户可以一次确认全部，也可以按需求 ID 批量修正；确认前不会写入最终分类或修改代码。确认后仍按排序每轮最多实施一条需求。

配置多个需求表后，可以使用不完全一致的表名切换。Skill 会结合 profile ID、显示名、别名和用途描述做语义判断；只有一个可信候选时采用该表，存在多个合理候选时必须让用户选择，确认具体 profile 前不会查询需求或继续执行。

首次配置需求表时，Skill 必须在检查真实字段后询问默认筛选列、操作符和值，并展示试查结果供用户确认。默认禁止空筛选；只有用户明确确认读取整张表后才能设置 `allow_unfiltered: true`。

没有需求表时可以直接在调用 Skill 的消息中描述一条或多条需求。Skill 会整理标题和验收标准草稿，补问无法确定的项目名与仓库，生成 `MANUAL-YYYYMMDD-序号` 本地 ID，并继续使用相同的普通语言说明、必要性核验、统一确认、分支选择、开发、测试、分级 Review 和群推送流程。手动需求不会创建或回写飞书记录。

选定要实施的需求后，主 Agent 会在分支确认前分为 `fast`、`standard` 或 `strict`。最多两个文件、局部且无高风险信号的需求使用快速流程：定向测试和一个综合 Review；3 到 8 个文件的普通范围使用三路并行 Review 一轮；超过 8 个文件或涉及数据库、权限、安全、公开接口、跨模块等高风险修改才使用严格流程和最多两轮复审。分级结果和理由会在实施前展示，避免小需求承担完整重流程。

Review 使用强制阶段门禁。主 Agent 必须先独立完成所有验收项、相关代码和初步测试，形成完整候选 diff，之后才能启动 Reviewer；禁止实现前的 Design Review，也禁止改一个文件就审一次。门禁记录候选文件快照，确保 Reviewer 审查同一版本；全部返回后主 Agent 才集中修复。普通问题不会触发新一轮完整 Review，只有高严重度、公共契约变化或范围升级才允许严格档进行一次定向复审。

Reviewer 不会被无限等待：`fast`、`standard`、`strict` 的单次等待上限分别为 10、15、20 分钟。某个角色超时、失败或异常退出时，只替换该角色，已完成或正常运行的 Reviewer 不受影响；替换者审查同一候选快照，每个角色最多自动替换一次。替换仍失败时门禁进入 `review_blocked`，立即停止等待并向用户报告缺失角色，主 Agent 不会用自审结果补位，也不会把不完整 Review 当作成功结果发布。

处理状态按 Git 仓库和 worktree 隔离，而不是使用全局单任务锁。另一个项目存在 `in_progress` 时当前项目可以继续；同一工作目录仍会被保护。相同仓库的不同 worktree 可以在用户确认后并行。旧版没有仓库信息的活动记录会要求关联一次仓库，不会要求将旧需求改为 `skipped`。内部状态键包含仓库范围，因此两个项目都存在“需求 31”时也不会互相覆盖；并行写状态由进程锁保护。

## Plugin 架构

```text
飞书长连接
  -> 本地 FeishuCodexGateway 后台任务
  -> 消息 ID / 需求 ID / Codex thread ID 持久化
  -> Codex SDK 创建或恢复本地线程
  -> feishu-requirement-orchestrator Skill
  -> 飞书引用回复卡片
```

- Plugin：提供 Skill、只读状态 MCP、网关运行时和安装脚本。
- 后台网关：接收飞书事件、校验群与操作者、去重、串联回复、调用 Codex。
- 双入口：识别“查询需求表”和“直接描述需求”。查询入口按 profile 的已确认筛选条件只读拉取候选；手动入口不查询飞书。
- Codex thread：每条需求独立保存；引用回复恢复原线程，不靠文本猜测需求。
- `gateway-state.json`：保存事件去重、任务和消息关联；不进入构建产物。
- 需求表：保持只读。机器人收到的新需求只进入本地状态，不自动新增或修改飞书记录。

## Lark Coding Agent Bridge 测试模式

Plugin 提供可选的 Bridge 验证模式，用开源 [Lark Coding Agent Bridge](https://github.com/zarazhangrui/lark-coding-agent-bridge) 承担飞书长连接、消息队列、附件、流式卡片、会话恢复和后台服务，现有 Skill 继续负责需求表、仓库路由、分析门禁、实施与 Review。项目只有生产环境时允许直接复用生产机器人，但 `FeishuCodexGateway` 与 Bridge 不能同时运行，任意时刻只能保留一个消息消费者。

先安装固定版本：

```powershell
& "$plugin\scripts\Install-Lark-Bridge-Poc.ps1"
```

复用生产机器人时，先停止旧网关，再在可见终端中启动首次初始化并扫码；这段时间机器人会短暂不可用：

```powershell
Stop-ScheduledTask -TaskName "FeishuCodexGateway"
lark-channel-bridge run --profile requirement-poc --agent codex
```

扫码时选择现有生产机器人。完成绑定后停止前台进程，从 orchestrator 已登记仓库中选择默认工作区，再配置安全 wrapper：

```powershell
& "$plugin\scripts\Configure-Lark-Bridge-Poc.ps1" `
  -ProfileName "requirement-poc" `
  -DefaultWorkspace "D:\workspace\已登记仓库" `
  -AllowProductionBot `
  -Confirm
```

`-AllowProductionBot` 是复用生产 App ID 的显式确认；未提供时配置脚本仍会拒绝生产 App ID。脚本始终拒绝未登记仓库，并固定以下边界：

- `codex.ignoreRules=false`，不允许 Bridge 忽略仓库规则；
- 默认 `read-only`，最大 `workspace-write`；
- wrapper 拒绝 `danger-full-access`；
- wrapper 使用 orchestrator 的模型和推理强度；
- 每条消息强制进入 `feishu-requirement-orchestrator` 与 Bridge 专用通道协议。

前台验证通过后注册 Bridge 后台服务。启动前再次确认旧网关处于停止状态：

```powershell
Stop-ScheduledTask -TaskName "FeishuCodexGateway"
lark-channel-bridge start --profile requirement-poc
lark-channel-bridge status --profile requirement-poc
```

Bridge 验证阶段限定单个默认仓库。切换工作区只能使用 orchestrator 已登记的仓库；多需求表自动选择不同仓库仍由现有专用网关负责。需要回退时先执行 `lark-channel-bridge unregister --profile requirement-poc`，确认 Bridge 已停止后再执行 `Start-ScheduledTask -TaskName "FeishuCodexGateway"`，不得让两个消费者重叠运行。

## 飞书应用要求

在飞书开放平台为自建应用启用机器人能力，并完成以下配置：

1. 事件订阅选择“使用长连接接收事件”，订阅“接收消息 v2.0（`im.message.receive_v1`）”。
2. 开通机器人发送消息、获取群内 @机器人消息的权限。
3. 为了让用户引用回复卡片时不必再次 @机器人，还需要开通“获取群组中所有消息”权限；这是敏感权限，应只把机器人加入明确授权的需求群。
4. 发布应用版本并把机器人加入 `gateway.allowed_chat_ids` 对应的群。

长连接不需要公网 webhook、端口映射或反向代理。

## 网关配置

网关继续使用 `%USERPROFILE%\.codex\feishu-requirement-orchestrator` 下已有的 `credentials.json`、`profiles.json` 和 `orchestrator.json`。不要在对话、日志或仓库中保存 App Secret。

在 `orchestrator.json` 中增加经过用户确认的 `gateway`：

```json
{
  "runtime": {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "ultra",
    "fail_on_unsupported": true
  },
  "gateway": {
    "enabled": true,
    "credential": "requirement-bot",
    "allowed_chat_ids": ["oc_xxx"],
    "admin_open_ids": ["ou_admin"],
    "require_group_mention": true,
    "turn_timeout_minutes": 180,
    "network_access": false,
    "chat_default_profiles": {},
    "profile_routes": {
      "product-requirements": {
        "repositories": [
          {
            "id": "product-api",
            "display_name": "产品后台",
            "aliases": ["后台", "API"],
            "description": "产品接口和管理后台",
            "project_name": "产品平台",
            "path": "D:\\workspace\\product-api"
          },
          {
            "id": "product-web",
            "display_name": "产品前端",
            "aliases": ["前端", "Web"],
            "description": "用户端网页",
            "project_name": "产品平台",
            "path": "D:\\workspace\\product-web"
          }
        ]
      }
    }
  }
}
```

新需求由发起人控制；`admin_open_ids` 中的管理员也可以控制。其他群成员引用回复时会被拒绝。网关先选择需求表，再选择该表下的代码仓库。两层路由都优先使用正文中的明确名称或别名，其次使用默认值或唯一候选，最后使用 Codex 语义判断；多个候选都合理时机器人必须让用户选择。一张需求表可以配置多个仓库。只有一个仓库时也可继续使用 profile 的 `default_repository` 和 `default_project_name`。

## 安全边界

- 修改代码前必须询问使用当前分支还是创建独立分支。
- 新分支使用 `<type>/<YYYYMMDD>/<summary>` 格式，例如 `feature/20260717/新增超额支付预警`；类型为 `feature`、`fix` 或 `refactor`，创建前必须确认。
- 不自动 add、commit、push、merge、发布或部署。
- 飞书需求表只读；本地状态文件防止重复处理。
- 不同代码仓库允许由不同 Codex 任务并行处理；同一 worktree 禁止并行，同一仓库不同 worktree 需用户明确确认。
- 只向明确配置 `auto_publish: true` 的固定 `chat_id` 发送一次，失败不重试。
- 网关只处理 `allowed_chat_ids` 中的群；只有需求发起人和配置管理员能推进任务。
- 后台 Codex 使用 `read-only` 或 `workspace-write`，不使用 `danger-full-access`；非交互运行不依赖本地审批弹窗。
- 凭证和运行配置位于 `%USERPROFILE%\.codex\feishu-requirement-orchestrator`，不进入构建产物。

## 开发

```powershell
uv sync
uv run pytest
.\scripts\build.ps1
```

构建结果位于 `dist\feishu-requirement-orchestrator\` 和 `dist\feishu-requirement-orchestrator.zip`。

Plugin 产物位于 `dist\feishu-codex-orchestrator\` 和 `dist\feishu-codex-orchestrator.zip`。Plugin 包含 Windows 网关运行依赖，但复用安装机器现有的 `codex.exe`，不会重复打包完整 Codex 平台二进制。

构建脚本运行 Python 与 Node 测试、依赖安全审计、Skill 和 Plugin 校验，并生成两个 ZIP 对应的 SHA-256 文件。

## GitHub Actions 自动打包

工作流文件位于 `.github\workflows\build-skill.yml`，使用 GitHub 托管的 Windows runner 执行与本地相同的 `scripts\build.ps1`。

触发规则：

- 向 `main` 分支 push：运行测试、校验并打包；
- 向 `main` 创建或更新 Pull Request：运行同样的构建检查；
- 在 GitHub Actions 页面手动运行 `Build Plugin and Skill`；
- 推送 `v*` 标签：构建产物并自动创建或更新对应的 GitHub Release。

每次成功构建都会在 GitHub Actions 的运行详情中保存 30 天产物，包含：

```text
feishu-requirement-orchestrator.zip
feishu-requirement-orchestrator.sha256
feishu-codex-orchestrator.zip
feishu-codex-orchestrator.sha256
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
6. 确认 GitHub Actions 已出现该 tag 对应的 `Build Plugin and Skill` 运行记录。

发现流水线运行记录后任务立即结束，不等待流水线成功或失败，也不检查 GitHub Release 产物。部署过程禁止强推；如果本地分支落后、存在疑似凭证或检查失败，会在 commit 和 tag 前停止。

## 安装 Plugin 和后台网关

Plugin 需要 Windows、Node.js 22 或更高版本、`uv`，以及已经登录并可运行的本机 Codex。`uv` 用于在网关进程中执行内置的只读需求表查询脚本；特殊安装位置可配置 `gateway.uv_path`。将 `feishu-codex-orchestrator.zip` 解压到稳定目录，例如：

```powershell
$pluginRoot = Join-Path $HOME "plugins"
New-Item -ItemType Directory -Force $pluginRoot | Out-Null
Expand-Archive `
  -LiteralPath "D:\path\to\feishu-codex-orchestrator.zip" `
  -DestinationPath $pluginRoot `
  -Force
```

使用个人 Codex marketplace 安装或更新该目录中的 `feishu-codex-orchestrator`。Plugin 启用后会提供 `feishu-requirement-orchestrator` Skill 以及 `gateway_config`、`gateway_status`、`gateway_tasks` 三个只读 MCP 工具。

先让 Codex 根据“网关配置”一节检查并补充 `orchestrator.json`；确认不包含密钥的配置预览后，再安装登录自启任务：

```powershell
$plugin = Join-Path $HOME "plugins\feishu-codex-orchestrator"
& "$plugin\scripts\Install-Gateway.ps1"
& "$plugin\scripts\Gateway-Status.ps1"
```

如果本机已经使用独立 `query-feishu-sheets` Skill 保存过需求表，初始化 Plugin 时不需要重新描述链接、筛选条件和输出字段。Codex 会读取旧 profile 的非敏感参数，并在存在旧 `projects/*/orchestrator.json` 时同时读取其中的项目名和仓库路由，运行 `legacy_profile_draft.py` 生成新 `profiles.json`、`profile_routes` 与顶层项目路由草稿，只询问旧配置中没有的映射。旧目录不会直接覆盖新运行目录，所有同名冲突和最终保存仍需用户确认；App Secret 不会出现在草稿或对话中。

Bridge 收到明确命名的需求表查询时，安全 wrapper 会在启动 Codex 前以固定 profile 参数执行沙箱外只读查询，再把结果作为 `<sheet_query>` 注入只读分析会话。这样 `uv` 的临时文件和缓存不会被目标仓库的只读沙箱拦截；Codex 不得重复查询。名称不唯一时 wrapper 不查询，由 Skill 先让用户选择。

固定的 Bridge `0.6.0` 安装后会应用版本校验补丁：普通群 session 使用“群 + 发送者不可逆哈希”，话题模式再叠加 thread。不同成员可以在同群维护独立会话，`/new`、`/stop` 和卡片回调只影响自己的 scope；管理员仍可使用 Bridge 的定向管理命令。补丁拒绝未知 Bridge 版本，重新安装 Bridge 时由 `Install-Lark-Bridge-Poc.ps1` 自动重放。授权群和管理员从 orchestrator 的 `allowed_chat_ids` 与 `admin_open_ids` 同步。

该任务使用当前 Windows 用户的非交互式 S4U 会话，以受限权限在登录后后台启动，不显示控制台窗口，也不保存 Windows 密码。它可以访问当前用户的 Codex 登录、`CODEX_HOME` 和本地仓库；电脑锁屏不影响运行，注销、休眠或关机会停止。S4U 不适合依赖网络共享盘或 EFS 加密文件的仓库。

卸载后台任务不会删除凭证、profile、任务状态或 Plugin 文件：

```powershell
& "$plugin\scripts\Uninstall-Gateway.ps1"
```

安装脚本执行 `npm ci --omit=optional` 并验证配置，不会安装第二份 Codex。网关要求能找到 `codex.exe` 和 `uv.exe`；特殊安装位置可分别在 `gateway.codex_path`、`gateway.uv_path` 中配置绝对路径。

群里 @机器人后有两种行为：

- “获取新应收的需求”：解析唯一 profile，按其固定筛选条件只读查询，把全部候选交给 Codex 整理和核验，再通过卡片统一确认。
- “导出页面增加按客户筛选”：把正文作为一项新需求，在全部已配置 profile 和仓库之间按名称、别名与业务语义判断项目归属和目标代码库，再通过卡片确认；不查询需求表，也不匹配表内已有记录。

意图、需求表或仓库不唯一时，机器人会发送选择卡片。分析确认后仍会单独确认当前分支或新分支；获得工作位置授权后，执行中出现产品问题会继续通过引用回复卡片询问，用户回复后恢复同一个 Codex thread 和写入权限，直至发送最终结果。需求表始终只读，网关不会自动 add、commit、push、merge、发布或部署。

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

`gpt-5.6-sol` 和 `ultra` 属于 Codex 运行环境能力。Sol 是当前 GPT-5.6 系列中适合复杂、开放式任务的推荐型号。Skill 只能声明并检查要求，不能自行安装或模拟模型；运行环境不支持且配置要求禁止降级时必须停止并明确报告。
