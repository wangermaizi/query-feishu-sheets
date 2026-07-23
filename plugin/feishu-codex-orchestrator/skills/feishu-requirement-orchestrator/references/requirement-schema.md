# 需求与配置结构

## 目录

- [需求字段](#需求字段)
- [手动需求输入](#手动需求输入)
- [评估文件](#评估文件)
- [运行配置](#运行配置)
- [从旧查询配置生成](#从旧查询配置生成)

## 需求字段

飞书模式通过 `orchestrator.json` 将实际列名映射为以下逻辑字段；手动模式把用户描述整理为相同结构：

| 逻辑字段 | 必需 | 说明 |
| --- | --- | --- |
| `id` | 是 | 稳定且唯一的需求 ID |
| `title` | 是 | 需求标题 |
| `description` | 是 | 完整需求描述 |
| `acceptance_criteria` | 是 | 可验证的验收标准 |
| `project_name` | 发布时必需 | 群消息中显示的业务项目名；也可由配置提供默认值 |
| `repository` | 条件必需 | 本地绝对路径；也可由配置提供默认值 |
| `priority` | 否 | P0、P1、P2、P3；缺失时由 Agent 评估 |
| `deadline` | 否 | 用于紧急度评估 |
| `status` | 否 | profile 可预先过滤不可执行状态 |
| `references` | 否 | 附件、截图或链接 |

缺失 `id`、`title`、`description`、`acceptance_criteria` 或有效仓库路径时设为 `eligible: false`。

## 从旧查询配置生成

用户已有 `query-feishu-sheets` 配置时，把旧配置作为新配置草稿的数据源，不做目录级迁移。自动复用 profile 中已经保存的 `document_url`、`credential`、`default_sheet` / `default_table`、`default_view`、`range`、`filters`、`output_columns`、`display_name`、`aliases`、`description` 和非敏感 `delivery` 字段。先运行 `legacy_profile_draft.py`，展示脱敏草稿和 `missing_fields`；只询问缺失内容。

旧 profile 通常没有代码仓库配置。不要因此重新询问表格链接、筛选条件或机器人名称，只补齐 `default_project_name` 或 `profile_routes.<profile_id>.repositories`。旧 credential 通过名称和 App ID 核对；用户确认复用后在不输出 App Secret 的情况下生成目标凭证配置。任何同名冲突都先展示非敏感差异并确认，不自动覆盖。

## 手动需求输入

`manual_requirement.py` 接受单条需求对象，或包含多条需求的 `requirements` 数组：

```json
{
  "requirements": [
    {
      "title": "回款金额异常提醒",
      "description": "回款金额超过最新应收金额时提醒用户",
      "acceptance_criteria": ["列表显示异常提醒", "用户可以定位错误记录"],
      "project_name": "应收系统",
      "repository": "D:\\workspace\\receivables",
      "priority": "P2",
      "references": []
    }
  ]
}
```

`title`、`description`、`acceptance_criteria`、`project_name` 和 `repository` 必填。`repository` 必须是已存在的绝对目录。输出补充 `id`、`source_type: manual`、`source_fingerprint` 和保留原始输入的 `source`。没有明确验收标准时由 Codex生成草稿，并在批量确认中明确标注供用户修正；脚本不接受空验收标准。

## 评估文件

```json
{
  "requirements": [
    {
      "id": "REQ-1024",
      "title": "示例需求",
      "plain_language_summary": "现状：系统会重复处理已完成需求。影响：用户可能看到重复结果。目标：已处理需求不再进入执行队列。示例：REQ-1024 完成后，第二天查询不会再次选中它。",
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

`impact`、`urgency`、`ease`、`risk` 均为 1 到 5 的整数。排序首先使用 P0 至 P3，其次依次考虑可实现容易度、影响、紧急度和风险。原始飞书记录或手动输入放在 `source`，不得丢失空字段。

`plain_language_summary` 是必填非空字符串。按“现状、问题或用户影响、期望结果”组织；复杂场景再提供一个简单例子。它用于帮助非技术用户理解需求，不替代 `source` 中的原始需求、后续技术证据或必要性结论。

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
    "project_name": "项目名称",
    "repository": "代码目录",
    "priority": "优先级",
    "deadline": "期望时间",
    "status": "状态",
    "references": "附件"
  },
  "default_repository": null,
  "default_project_name": "OA",
  "selection": {"max_items": 1},
  "runtime": {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "ultra",
    "fail_on_unsupported": true
  },
  "delivery": {
    "credential": "requirement-bot",
    "chat_id": "oc_xxx",
    "chat_name": "需求确认群",
    "auto_publish": true
  },
  "gateway": {
    "enabled": true,
    "credential": "requirement-bot",
    "allowed_chat_ids": ["oc_xxx"],
    "admin_open_ids": ["ou_admin"],
    "require_group_mention": true,
    "turn_timeout_minutes": 180,
    "network_access": false,
    "codex_path": "C:\\path\\to\\codex.exe",
    "uv_path": "C:\\path\\to\\uv.exe",
    "chat_default_profiles": {},
    "profile_routes": {
      "product-requirements": {
        "repositories": [
          {
            "id": "oas",
            "display_name": "OAS",
            "aliases": ["后台"],
            "description": "入职管理后台",
            "project_name": "入职管理",
            "path": "D:\\workspace\\oas"
          },
          {
            "id": "preboard",
            "display_name": "Preboard",
            "aliases": ["入职端"],
            "description": "新员工入职端",
            "project_name": "入职管理",
            "path": "D:\\workspace\\preboard"
          }
        ]
      }
    }
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
  "default_project_name": "OA",
  "default_repository": "D:\\workspace\\oas",
  "credential": "requirement-bot",
  "document_url": "https://example.feishu.cn/base/token",
  "default_table": "需求池",
  "filters": [
    {"column": "状态", "operator": "equals", "value": "待处理"}
  ],
  "output_columns": ["需求ID", "需求标题", "需求描述", "验收标准"]
}
```

`aliases` 不能替代唯一 `profile_id`；不同 profile 可以出现语义相近别名，此时必须由用户选择。

`gateway.allowed_chat_ids` 是机器人入站授权边界，不能因为机器人已加入其他群就自动扩大。新需求由发起人的飞书 `open_id` 控制，`admin_open_ids` 可增加管理员。一张需求表可在 `profile_routes.<profile_id>.repositories` 下配置多个仓库，网关先选择 profile，再根据仓库 ID、显示名、别名、用途和需求语义选择仓库；多候选合理时必须询问。只有一个仓库时可以继续使用 profile 自身的 `default_project_name` 和 `default_repository`。仍缺少有效路径时必须阻塞，不得根据目录名猜测。`chat_default_profiles` 只作为需求表查询模式的无明确表名回退；手动需求存在多个 profile 时先做语义匹配。`codex_path` 和 `uv_path` 可省略并由网关从 PATH 自动发现，只有特殊安装位置才需要配置绝对路径。

启用网关前必须确认飞书应用使用长连接订阅 `im.message.receive_v1`，具备接收 @机器人消息、接收群内引用回复和发送消息的权限。网关不更改需求表，所有 profile 保持只读。

`filters` 默认为必填且不能为空。所有条件按 AND 组合。只有用户在看过风险提示后明确要求读取整张表，才允许使用：

```json
{
  "filters": [],
  "allow_unfiltered": true
}
```

`allow_unfiltered` 是显式安全授权，不得由 Codex自行添加。后续重新加入筛选条件时删除该字段或设为 `false`。
