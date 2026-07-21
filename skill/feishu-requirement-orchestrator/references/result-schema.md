# 最终报告结构

`publish_result.py` 接受以下 JSON：

```json
{
  "requirement_id": "REQ-1024",
  "project_name": "OA",
  "title": "示例需求",
  "status": "completed",
  "selection_reason": "高优先级且实现路径明确",
  "plain_language_summary": "现状：系统会重复处理已完成需求。影响：用户可能看到重复结果。目标：已处理需求不再进入执行队列。",
  "complexity_tier": "standard",
  "complexity_reason": "预计修改三个相关模块，范围明确但需要独立回归审查",
  "review_rounds": 1,
  "review_process": {
    "implementation_completed_at": "2026-07-16T17:00:00+08:00",
    "first_review_started_at": "2026-07-16T17:10:00+08:00",
    "complete_candidate_reviewed": true,
    "all_reviewers_collected_before_fixes": true
  },
  "necessity_assessment": {
    "status": "partially_done",
    "reason": "已有基础查询，仍缺少状态去重",
    "evidence": ["src/service.py:120"],
    "remaining_criteria": ["已处理需求不得重复执行"]
  },
  "repository": "D:\\workspace\\example",
  "branch": "main",
  "changes": ["修改内容摘要"],
  "tests": [{"command": "uv run pytest", "result": "passed"}],
  "reviews": [
    {"role": "functionality", "finding_count": 0, "summary": "未发现问题"},
    {"role": "testing", "finding_count": 0, "summary": "未发现问题"},
    {"role": "quality-security", "finding_count": 0, "summary": "未发现问题"}
  ],
  "residual_risks": [],
  "next_action": "请确认是否接受本次修改",
  "completed_at": "2026-07-16T18:00:00+08:00"
}
```

`status` 可为 `completed`、`blocked` 或 `failed`。`plain_language_summary` 必须为非空字符串，并覆盖现状、问题或用户影响和期望结果；复杂场景补充简单例子。不得包含密钥、access token、Authorization 请求头或完整凭证配置。报告应说明未 commit、未 push、未 merge、未发布。

`complexity_tier` 必须为 `fast`、`standard` 或 `strict`，并提供非空 `complexity_reason`。`fast` 的 `reviews` 必须只有一个综合 Reviewer；`standard` 和 `strict` 必须包含三个独立 Reviewer。`fast` 和 `standard` 的 `review_rounds` 必须为 1；`strict` 可以为 1 或 2。

`review_process` 必须来自 `review_gate.py status`。实现完成时间必须早于或等于首次 Review 开始时间，两个时间都必须包含时区；`complete_candidate_reviewed` 和 `all_reviewers_collected_before_fixes` 必须为 `true`。不满足时禁止发布成功报告。

`project_name` 必须是用户可识别的业务项目名。卡片标题生成格式为 `【project_name】title`，不显示需求 ID；不得只显示需求标题，也不得从目录名自行推断项目名。

群卡片只渲染执行信息、普通语言需求说明、修改内容和待确认事项。选择原因、复杂度、必要性核验、测试、Review 和残余风险仍为内部报告必填数据，用于安全校验和审计，但不渲染到群卡片。
