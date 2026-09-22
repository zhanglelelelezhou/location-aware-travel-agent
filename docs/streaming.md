# SSE Agent 事件协议

## 为什么流式传状态而不是逐字输出

Agent 的等待时间主要来自 Planner 和外部工具，逐字输出只能让最终回答看起来在流动，不能说明系统正在做什么。这个接口把真实生命周期转成事件：前端可以展示“正在规划”“正在查询天气”“工具失败，进行一次恢复”“等待确认”，面试官也能从事件与最终 trace 对照执行路径。

同步 `/v1/chat` 与流式 `/v1/chat/stream` 共用同一个 `ConversationService`、LangGraph、策略层和工具注册表。事件通过可选 observer 从真实节点旁路发出，没有复制第二套 Agent 逻辑。

## 传输格式

响应类型为 `text/event-stream`，同时设置 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。每个 frame 包含 SSE `id`、具名 `event` 和 JSON `data`：

```text
id: 4
event: tool.started
data: {"schema_version":"1.0","sequence":4,"type":"tool.started","data":{"name":"get_weather","arguments":{"location":"大阪"}}}

```

`sequence` 从 1 开始，在单次流内单调递增；`schema_version` 当前为 `1.0`。连接超过 15 秒没有事件时发送 SSE comment `: keepalive`，客户端应忽略 comment。最后一个正常业务事件是 `response.completed`，其中包含与同步接口相同的完整 `AgentResponse`。

## 事件类型

| 事件 | 含义 |
| --- | --- |
| `request.accepted` | 请求进入 ConversationService，标明是否启用 session |
| `memory.recalled` | 只列出本轮召回的结构化字段，不发送完整历史 |
| `planning.started` | Planner 开始工作 |
| `planning.completed` | 返回结构化计划、Planner 类型、修复与策略补正 |
| `tool.started` | 某个计划工具开始执行 |
| `tool.completed` | 返回该工具的结构化执行结果或错误 |
| `verification.completed` | 本轮工具结果校验成功或失败 |
| `recovery.started` | 进入一次有界恢复 |
| `memory.updated` | 只列出从显式请求写入的字段 |
| `confirmation.awaiting` | booking pending action 已保存，等待独立确认 |
| `response.completed` | 最终完整响应 |
| `stream.error` | Worker 在最终响应前发生未处理异常；对客户端隐藏内部错误详情 |

booking 在确认前不会发出 `tool.started`。失败工具会经历 `tool.completed(error) → verification.completed(success=false) → recovery.started`，最多重试一次。

## 实现与背压边界

当前 LangGraph 和外部 adapter 是同步实现。流式端点为每个连接启动一个 daemon worker，通过有界生命周期的线程安全 Queue 把事件交给 StreamingResponse；SSE 消费与 Agent 执行因此可以同时进行。事件生产本身不会改变图状态或工具参数。

当前尚未实现客户端断连后的任务取消，daemon worker 会把这一轮有界 Agent 执行完成；也没有每用户连接上限。生产版本应改为 async tool adapter、AnyIO memory stream、断连取消、队列上限、速率限制和反向代理 idle timeout 配置。`tool.completed` 与最终 trace 可能包含用户请求和供应商数据，生产日志与前端展示需要字段分级和脱敏。

## 测试

协议测试验证：SSE frame 格式、事件/ID 与 JSON 一致、序号连续、正常工具生命周期、记忆召回、booking 等待确认、工具失败后的单次恢复，以及最终事件包含完整响应。API 测试验证 Content-Type、缓存头和真实 HTTP 响应内容。
