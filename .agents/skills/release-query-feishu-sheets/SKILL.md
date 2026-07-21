---
name: release-query-feishu-sheets
description: Release the query-feishu-sheets repository to GitHub by analyzing current changes, generating a Chinese user-facing changelog that becomes the GitHub Release body, choosing and creating the next semantic version tag, committing and pushing main, pushing the tag, and confirming that the Build Skill GitHub Actions workflow has started without waiting for its result. Use when the user says 部署、发布、发版、上线新版本, or asks to tag and ship this repository.
---

# 发布 query-feishu-sheets

将用户的部署指令视为对本仓库以下操作的明确授权：更新版本与日志、运行检查、提交当前发布范围内的改动、推送 `main`、创建并推送 tag。不得扩展为修改 GitHub 设置、删除远程引用或等待流水线结果。

## 终止条件

推送 tag 后，只确认 `.github/workflows/build-skill.yml` 已产生该 tag 对应的运行记录。看到记录后立即结束并返回 tag、commit、Actions URL 和记录当时的状态；不要等待完成，不要判断成功或失败。

## 1. 发布前检查

1. 确认当前仓库根目录为 `query-feishu-sheets`，当前分支为 `main`，远程 `origin` 指向 GitHub。
2. 优先运行 `gh auth status`。未安装 GitHub CLI 时，确认仓库公开可读并允许检测脚本使用 GitHub REST API；私有仓库没有 `GH_TOKEN` 或 `GITHUB_TOKEN` 时停止。
3. 确认 `.github/workflows/build-skill.yml` 存在且监听 `v*` tag。
4. 读取 `git status --short`、已跟踪和未跟踪改动、最近提交及已有 tag。
5. 运行 `git fetch origin main --tags`。若本地 `main` 落后或与 `origin/main` 分叉，停止并说明，不自动 rebase、merge 或强推。
6. 检查待提交文件。发现凭证、token、App Secret、运行配置、构建产物或明显无关改动时停止并询问。不要读取或显示密钥内容。
7. 没有可发布改动时停止，不创建空版本。

保留用户的全部相关改动，不还原、不覆盖。任何检查失败都在 commit 和 tag 之前停止。

## 2. 先生成更新日志

在修改版本号、提交或创建 tag 前，先由 AI 完整分析 `git diff`、未跟踪文件和自上一 tag 以来的提交，生成本次面向使用者的中文更新日志草稿。不得只依赖提交标题或 GitHub 自动生成说明。

更新日志必须描述用户实际获得的新能力、行为变化和修复，不写提交哈希、内部推理、机械文件列表或“Full Changelog”链接。先确定内容属于新增、改进或修复，再进入版本选择。

## 3. 选择版本

使用现有最高 `vX.Y.Z` tag 计算下一个版本；没有 tag 时使用 `v0.1.0`。

- 存在破坏性兼容变更：major + 1，minor 和 patch 归零。
- 存在用户可见的新功能：minor + 1，patch 归零。
- 只有修复、文档、测试、构建或内部调整：patch + 1。
- 用户明确指定版本时优先使用，但必须符合 `vX.Y.Z`、高于已有版本且尚不存在。

同时把 `pyproject.toml` 的 `project.version` 更新为不带 `v` 的版本号，并运行 `uv lock` 更新锁文件。

## 4. 写入并验证更新日志

把已生成的更新日志写入仓库根目录 `CHANGELOG.md`。使用中文、面向使用者描述实际行为，不把提交哈希、内部推理或无意义文件列表当作更新内容。

在文件顶部加入：

```markdown
## [vX.Y.Z] - YYYY-MM-DD

### 新增

- ...

### 改进

- ...

### 修复

- ...
```

只保留实际需要的分类。不要修改历史版本内容。首次发布时总结当前项目的主要能力。

当前版本章节是 GitHub Release 正文的唯一来源。写入后必须运行提取脚本并阅读输出，确认内容非空、版本正确且与本次改动一致：

```powershell
uv run <skill-dir>\scripts\extract_release_notes.py --tag "vX.Y.Z" --changelog "CHANGELOG.md" --output "dist\release-notes.md"
Get-Content "dist\release-notes.md" -Encoding UTF8
```

提取失败、输出包含错误版本或内容与实际改动不符时，必须在提交和 tag 前停止并修正。GitHub Actions 会使用同一脚本提取 tag 对应章节，并通过 `--notes-file` 创建或更新 GitHub Release；不得改回 `--generate-notes`。

## 5. 验证并提交

1. 运行 `uv sync --frozen` 和 `.\scripts\build.ps1`。
2. 确认测试、所有仓库 Skill 校验、ZIP、SHA-256 和当前版本 Release notes 提取均成功。
3. 再次检查 `git diff` 和 `git status --short`，确认没有 `dist/`、凭证或运行状态进入提交。
4. 使用 `git add --all` 暂存已经检查过的发布范围。
5. 检查 `git diff --cached` 后提交：`chore(release): vX.Y.Z`。

检查失败时不要提交、打 tag 或推送。提交失败时不要继续。

## 6. 推送并启动流水线

按顺序执行：

```powershell
git push origin main
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

不要并行推送 main 和 tag。只有 main 推送成功后才创建 tag；只有 tag 创建成功后才推送 tag。禁止使用 `--force`。

tag 推送成功后运行：

```powershell
& <skill-dir>\scripts\wait_for_workflow.ps1 -Tag "vX.Y.Z"
```

脚本发现运行记录即成功，不关心记录是 `queued`、`in_progress` 还是已经快速结束。若 60 秒内未发现记录，报告“代码和 tag 已推送，但无法确认流水线已启动”，不得删除 tag、重复推送或创建另一个版本。

## 7. 返回结果

简要返回：

- 新版本 tag；
- release commit；
- `main` 和 tag 已推送；
- GitHub Actions 运行 URL 及发现时状态。

明确说明没有等待流水线运行结果。不要继续调用 `gh run watch`、轮询 conclusion 或检查 GitHub Release 产物。
