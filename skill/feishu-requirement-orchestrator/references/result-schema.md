# 最终报告结构

`publish_result.py` 接受以下 JSON：

```json
{
  "requirement_id": "REQ-1024",
  "title": "示例需求",
  "status": "completed",
  "selection_reason": "高优先级且实现路径明确",
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

`status` 可为 `completed`、`blocked` 或 `failed`。不得包含密钥、access token、Authorization 请求头或完整凭证配置。报告应说明未 commit、未 push、未 merge、未发布。
