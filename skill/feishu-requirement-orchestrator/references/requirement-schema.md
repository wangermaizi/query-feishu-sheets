# 需求与配置结构

## 目录

- [需求字段](#需求字段)
- [评估文件](#评估文件)
- [运行配置](#运行配置)

## 需求字段

通过 `orchestrator.json` 将实际飞书列名映射为以下逻辑字段：

| 逻辑字段 | 必需 | 说明 |
| --- | --- | --- |
| `id` | 是 | 稳定且唯一的需求 ID |
| `title` | 是 | 需求标题 |
| `description` | 是 | 完整需求描述 |
| `acceptance_criteria` | 是 | 可验证的验收标准 |
| `repository` | 条件必需 | 本地绝对路径；也可由配置提供默认值 |
| `priority` | 否 | P0、P1、P2、P3；缺失时由 Agent 评估 |
| `deadline` | 否 | 用于紧急度评估 |
| `status` | 否 | profile 可预先过滤不可执行状态 |
| `references` | 否 | 附件、截图或链接 |

缺失 `id`、`title`、`description`、`acceptance_criteria` 或有效仓库路径时设为 `eligible: false`。

## 评估文件

```json
{
  "requirements": [
    {
      "id": "REQ-1024",
      "title": "示例需求",
      "priority": "P1",
      "impact": 4,
      "urgency": 3,
      "ease": 4,
      "risk": 2,
      "eligible": true,
      "blocked_reasons": [],
      "selection_reason": "高优先级且依赖明确",
      "source": {}
    }
  ]
}
```

`impact`、`urgency`、`ease`、`risk` 均为 1 到 5 的整数。排序首先使用 P0 至 P3，其次依次考虑可实现容易度、影响、紧急度和风险。原始飞书记录放在 `source`，不得丢失空字段。

排序后的候选在代码只读核验阶段生成必要性结果：

```json
{
  "status": "partially_done",
  "reason": "接口已经支持查询，但缺少状态去重",
  "evidence": ["src/service.py:120", "tests/test_service.py:45"],
  "completed_criteria": ["可以读取需求列表"],
  "remaining_criteria": ["已处理需求不得重复执行"]
}
```

`status` 只能为 `not_started`、`partially_done`、`completed`、`obsolete`、`duplicate` 或 `needs_confirmation`。证据不足时使用 `needs_confirmation`，不要猜测。

## 运行配置

`orchestrator.json` 示例：

```json
{
  "profile": "requirements",
  "field_mapping": {
    "id": "需求ID",
    "title": "需求标题",
    "description": "需求描述",
    "acceptance_criteria": "验收标准",
    "repository": "代码目录",
    "priority": "优先级",
    "deadline": "期望时间",
    "status": "状态",
    "references": "附件"
  },
  "default_repository": null,
  "selection": {"max_items": 1},
  "runtime": {
    "model": "gpt-5.6",
    "reasoning_effort": "ultra",
    "fail_on_unsupported": true
  },
  "delivery": {
    "credential": "requirement-bot",
    "chat_id": "oc_xxx",
    "chat_name": "需求确认群",
    "auto_publish": true
  }
}
```

`chat_id` 和 `auto_publish` 必须由用户明确确认后保存。配置不保存 App Secret；密钥只存在于同目录的 `credentials.json`。

每个保存的 profile 应设置唯一、清楚的显示名，并可增加别名和用途描述，帮助解析用户口语中的表名：

```json
{
  "profile_id": "product-requirements",
  "display_name": "产品研发需求表",
  "aliases": ["研发需求", "产品需求", "研发表"],
  "description": "产品和研发团队待开发的软件需求",
  "credential": "requirement-bot",
  "document_url": "https://example.feishu.cn/base/token",
  "default_table": "需求池",
  "filters": [],
  "output_columns": ["需求ID", "需求标题", "需求描述", "验收标准"]
}
```

`aliases` 不能替代唯一 `profile_id`；不同 profile 可以出现语义相近别名，此时必须由用户选择。
