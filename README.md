# Feishu Requirement Orchestrator

该仓库构建一个 Codex Skill：从飞书读取软件需求，分析并选择一条需求，在用户确认工作分支后实施修改和测试，组织三个只读 Reviewer，并把最终结果自动发送到预授权飞书群。

候选需求进入代码修改前，Skill 会只读核验目标仓库，判断需求是尚未实现、部分实现、已经完成、已经失效、与其他需求重复，还是证据不足需要人工确认。只有尚未实现或部分实现且仍有必要的需求才会进入分支选择和实施阶段。

飞书最终结果卡片使用 `【项目名｜需求ID】需求标题` 作为标题。项目名来自需求字段或已确认的 `default_project_name`；无法确定时必须询问用户，不能只显示需求标题或根据仓库路径猜测。

每轮会先完成全部候选需求的分析，再把排序、建议结论、证据和建议动作作为一个批次交给用户统一确认。用户可以一次确认全部，也可以按需求 ID 批量修正；确认前不会写入最终分类或修改代码。确认后仍按排序每轮最多实施一条需求。

配置多个需求表后，可以使用不完全一致的表名切换。Skill 会结合 profile ID、显示名、别名和用途描述做语义判断；只有一个可信候选时采用该表，存在多个合理候选时必须让用户选择，确认具体 profile 前不会查询需求或继续执行。

首次配置需求表时，Skill 必须在检查真实字段后询问默认筛选列、操作符和值，并展示试查结果供用户确认。默认禁止空筛选；只有用户明确确认读取整张表后才能设置 `allow_unfiltered: true`。

## 安全边界

- 修改代码前必须询问使用当前分支还是创建独立分支。
- 不自动 add、commit、push、merge、发布或部署。
- 飞书需求表只读；本地状态文件防止重复处理。
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

标签工作流成功后，可从项目的 [GitHub Releases](https://github.com/wangermaizi/query-feishu-sheets/releases) 下载离线安装包及 SHA-256 文件。普通 push 和 Pull Request 只生成 Actions 临时产物，不创建 Release。

## 使用发布 Skill

仓库包含 `.agents\skills\release-query-feishu-sheets`。在本仓库中对 Codex 说“部署”“发布”“发版”或显式调用以下提示词时，会触发完整发布流程：

```text
使用 $release-query-feishu-sheets 部署当前改动。
```

发布 Skill 会：

1. 检查分支、远程仓库、GitHub 登录状态和待提交文件；
2. 根据改动选择下一个语义化版本，首次发布使用 `v0.1.0`；
3. 更新 `pyproject.toml`、`uv.lock` 和中文 `CHANGELOG.md`；
4. 运行测试、Skill 校验和本地打包；
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

当用户描述与 Skill 的 `description` 匹配时，Codex 也可以自动选择该 Skill；涉及自动执行时建议显式写出 `$feishu-requirement-orchestrator`，避免触发意图不清晰。

执行到代码修改阶段时，Skill 必须暂停并询问使用当前分支、创建独立分支还是取消。用户回复前不会修改目标仓库。完成修改、测试和三路 Review 后，结果会发送到预先授权的固定飞书群。

Codex Skill 的发现位置和调用方式以 [OpenAI Codex Skills 文档](https://learn.chatgpt.com/docs/build-skills) 为准。

## 让 Codex 完成首次配置

可以把业务配置信息告诉 Codex，由 Codex 检查飞书表结构、生成并试查 profile、配置字段映射、选择固定群以及创建每日自动任务。

需要提供：

- 飞书 `/sheets/` 或 `/base/` 直接链接；
- 工作表或数据表名称；
- 需求 ID、标题、描述、验收标准、仓库路径、优先级等字段的实际列名；
- 默认代码仓库路径（飞书表没有仓库字段时）；
- 要查询的需求状态，例如“待处理”；
- 飞书应用凭证名称；
- 固定群的 `chat_id`，不知道时可让 Codex 列出机器人所在群后再选择；
- 每日执行时间；
- 模型和推理强度要求，以及不支持时是否停止。

可直接使用以下提示词：

```text
使用 $feishu-requirement-orchestrator 帮我完成首次配置。

需求表链接：
工作表/数据表：
默认代码仓库：
待处理状态：

字段映射：
需求ID =
需求标题 =
需求描述 =
验收标准 =
代码目录 =
优先级 =
期望时间 =
状态 =
附件 =

飞书凭证名称：
目标群 chat_id：
每天执行时间：工作日 09:00
运行模型：gpt-5.6
推理强度：ultra
模型不支持时停止，不要降级。

请先 inspect 表结构并生成配置预览，试查成功后让我确认，再保存 profile 和运行配置。最后配置每日自动任务。
```

不要在对话中直接发送 App Secret。应先把密钥放入本地受保护的凭证草稿或环境变量，再让 Codex 测试并保存；Codex 不应在回复中显示密钥、access token 或 Authorization 请求头。

Codex 必须在以下节点暂停并获得确认：

- 保存或覆盖飞书凭证；
- 保存或覆盖查询 profile；
- 授权固定 `chat_id` 自动接收结果；
- 创建每日自动任务。

`gpt-5.6` 和 `ultra` 属于 Codex 运行环境能力。Skill 只能声明并检查要求，不能自行安装或模拟模型。运行环境不支持且配置要求禁止降级时，任务必须停止并明确报告。
