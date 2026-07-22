# 分级 Review 标准

所有 Reviewer 必须只读审查，并按严重度从高到低返回发现。每条发现包含严重度、文件、行号、触发条件、实际影响和建议。不要只给风格偏好。

Reviewer 只能在 `review_gate.py start` 成功后启动。审查对象必须是主 Agent 已完成全部验收项并通过初测后的同一份完整候选 diff。禁止实现前的 Design Review，禁止按文件或局部改动反复 Review。Reviewer 运行期间主 Agent 不得修改候选文件。

## Fast 综合 Reviewer

由一个 Reviewer 在一次审查中合并检查下列“需求与功能”“测试与回归”“质量与安全”三部分。不要为了形式拆成三个 Agent。发现高严重度问题或实际改动超出 fast 范围时，通知主 Agent 重新分级。

## Reviewer 1：需求与功能

- 对照原始需求和每条验收标准检查行为。
- 检查遗漏场景、错误分支、边界值和兼容性。
- 确认改动没有实现未经要求的额外行为。

## Reviewer 2：测试与回归

- 判断测试是否真正覆盖新增或修改行为。
- 检查异常路径、状态转换、并发、重试及幂等风险。
- 识别可能受影响但未验证的调用方和平台。

## Reviewer 3：质量与安全

- 检查敏感信息、权限、输入校验、命令执行和外部副作用。
- 检查是否破坏仓库既有架构、公共接口或数据格式。
- 检查可维护性问题，但只报告有明确后果的事项。

## 输出

有问题时输出结构化 findings；没有问题时明确写 `findings: []`，并列出残余风险和未运行的检查。Reviewer 不得修改代码、创建分支、提交或发送飞书消息。

主 Agent 必须等待本轮所有 Reviewer 返回后一次性生成：

```json
{
  "reviews": [
    {"role": "functionality", "findings": []},
    {"role": "testing", "findings": []},
    {"role": "quality-security", "findings": []}
  ]
}
```

首轮 `fast` 必须收齐 1 个综合结果，`standard` 和 `strict` 必须收齐 3 个独立结果。`collect` 成功前不得修复任何发现；成功后集中修复，不按 Reviewer 返回顺序边审边改。

`standard` 和 `strict` 使用三个独立 Reviewer。`standard` 默认一轮；`strict` 最多两轮，第二轮只复核高严重度修复及直接受影响范围，不重新做无差别全仓审查。

## 超时与替换

- `fast` 每次 Reviewer 尝试最多 10 分钟，`standard` 最多 15 分钟，`strict` 最多 20 分钟。
- 主 Agent 监控每个角色。超时、失败或异常退出时，只中断受影响角色，并在门禁登记 `retry`；已完成及正常运行的 Reviewer 保持不变。
- 替换 Reviewer 必须使用同一角色和完全相同的候选输入与快照。每个角色仅允许替换一次，替换尝试重新获得该等级的完整时限。
- 替换仍超时、失败或退出时，运行 `block` 进入 `review_blocked`，停止等待并向用户报告缺失角色。不得由主 Agent 自审补位，不得用其他角色结果替代。
