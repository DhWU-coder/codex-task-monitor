# 陈旧运行状态对账设计

## 1. 问题与证据

任务“你有pdf工具么”的本地会话文件最后写入了 `task_started`，但没有写入 `task_complete`、失败或中断事件，因此会话观察器保留了 `running`。

同一线程的 App Server 权威详情显示：

- 线程列表状态为 `notLoaded`；
- 最新 Turn ID 与本地会话一致；
- 最新 Turn 实际状态为 `interrupted`；
- 现有 `map_thread()` 已能把详情正确映射成 `interrupted`。

故障发生在运行时对账条件：`refresh_once()` 目前只在列表快照已经是运行或等待状态时调用 `thread/read`。`notLoaded` 被映射为 `unknown`，不会触发详情读取；聚合器又会保留已有的活动状态，避免把数据缺失误判为完成，最终形成永久的陈旧 `running`。

## 2. 目标行为

- 当聚合器已有同一线程的 `running`、`waiting_input` 或 `waiting_approval` 状态，而 App Server 列表快照为 `unknown` 时，补充调用一次 `thread/read`。
- 如果详情中的最新 Turn 是 `completed`、`failed` 或 `interrupted`，使用该权威终态更新任务。
- 如果详情仍是活动状态，正常刷新活动任务信息。
- 如果详情读取失败、返回缺失数据或仍无法确定状态，继续保留原活动状态，不误报完成。
- 普通的历史 `unknown/notLoaded` 线程如果聚合器中没有活动状态，不额外读取详情。
- 不根据文件年龄、更新时间或固定超时推断任务已经结束。

## 3. 实现方案

在 `RuntimeService.refresh_once()` 处理每个 App Server 列表快照时，先读取聚合器中的现有快照，并通过一个小型判定函数决定是否需要详情：

1. 列表快照本身处于活动状态时，维持现有行为，调用 `thread/read`。
2. 列表快照为 `unknown`，且聚合器中同一线程仍处于活动状态时，也调用 `thread/read`。
3. 其他状态直接使用列表快照。

详情仍由现有 `_read_active_thread()` 获取和映射，读取异常时返回列表快照。终态优先级和通知幂等继续由现有聚合器及监控服务处理，不修改状态优先级规则。

判定逻辑放在运行时模块的独立纯函数中，使边界明确并便于单元测试；活动状态集合提取为模块级常量，避免条件在多个位置漂移。

## 4. 通知与安全

- 该修复只纠正状态来源，不改变“只有用户预先启用监控才发送通知”的规则。
- 对未监控的陈旧任务只更新 UI，不发送飞书消息。
- 对已监控任务，权威终态仍按既有幂等键最多通知一次。
- 详情读取失败不会生成终态，也不会停用监控。

## 5. 测试

新增运行时回归测试，构造以下真实故障链：

1. 本地会话事件先把任务标记为 `running`。
2. App Server `thread/list` 返回同一线程的 `notLoaded` 和空 Turn 列表。
3. App Server `thread/read` 返回最新 Turn 为 `interrupted`。
4. 执行一次 `refresh_once()` 后，断言任务变为 `interrupted`，并确认确实调用了 `thread/read`。

另加边界测试：

- 聚合器中没有活动状态的普通 `notLoaded` 线程不调用 `thread/read`。
- `thread/read` 失败时保留已有 `running`，不误判终态。

最后运行完整 Python、前端、静态检查和构建验证。当前正在运行的监控器不自动重启。

## 6. 非目标

- 不用“长时间无更新”直接判定任务完成。
- 不修改 Codex 会话文件或 App Server 数据。
- 不清理或隐藏其他历史任务。
- 不在本次修复中处理缺失 `completedAt` 时的时长展示。
