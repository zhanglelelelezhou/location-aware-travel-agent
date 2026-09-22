# 会话记忆与人工确认

## 目标与边界

这个模块解决两个不同问题：跨轮请求需要复用用户显式提供的位置与偏好；有副作用的 booking 请求必须等待用户在独立步骤中确认。两者都由确定性服务层处理，不要求 LLM 从长聊天历史中自行回忆，也不让模型声称“用户已经确认”。

请求没有 `session_id` 时保持无状态，原有 CLI、测试和单轮 API 不受影响。当前实现是单进程内存版本，用于项目演示和契约验证，不宣称具备生产持久化能力。

## 记忆模型

每个会话最多保存：

- 用户显式提供的地点；
- 与该地点一起提供的可信经纬度；
- 去重后的偏好列表；
- turn 计数；
- 最多一个待确认操作。

系统不保存完整消息历史、LLM 思维过程或历史工具输出。新请求显式提供的位置永远覆盖旧位置；如果新位置没有坐标，旧地点的坐标会同时删除，防止把东京坐标错误注入大阪请求。偏好只从请求字段写入，不从模型回答或外部文档推断。

默认最多保存 1,000 个会话，LRU 超限淘汰；会话 TTL 为 1,800 秒，pending action TTL 为 900 秒。三个值可通过 `SESSION_MAX_SESSIONS`、`SESSION_TTL_SECONDS` 和 `PENDING_ACTION_TTL_SECONDS` 配置。`DELETE /v1/sessions/{session_id}` 可主动清除。

## 人工确认流程

```text
Booking request
  -> Planner detects booking
  -> Policy forces needs_confirmation=true and blocks tool calls
  -> Service stores one PendingAction with random action_id + TTL
  -> Response returns confirmation_status=awaiting
  -> POST /v1/sessions/{session_id}/confirm
       |-- reject  -> consume token, no gateway call
       |-- approve -> consume token before gateway call
       `-- invalid / expired / replay -> no gateway call
```

令牌必须同时匹配会话与 action ID。批准时先从 Store 原子移除 pending action，再调用 gateway，因此相同令牌最多执行一次。这个选择优先防止重复副作用：如果 gateway 在提交途中失败，令牌不会自动重试，生产系统应依靠供应商幂等键和对账任务恢复不确定状态。

默认 `DryRunBookingGateway` 返回 `external_request_sent=false`，让任何人都能完整演示确认链路，但不会伪装成真实预订。批准、拒绝、失败、过期和重放状态都进入 trace；实际 gateway 结果写入 `confirmation_result` 和 `trace.executions`。

## 安全与生产差距

- `session_id` 只是关联键，不是身份认证。生产环境必须将会话绑定到已认证用户，不能依赖难猜 ID。
- 当前 Store 是进程内内存，重启会丢失，多 worker 之间也不共享。生产应换成支持原子 compare-and-set、TTL 和持久化幂等记录的 Redis/PostgreSQL。
- 当前同一会话的 read-run-write 不是跨进程事务；真实 booking 接入前需要会话版本号或乐观锁。
- 默认 gateway 永远是 dry-run。只有配置了真实供应商、认证、审计与对账后才能声明完成真实预订。
- 记忆召回字段和更新字段显式写入 trace，便于发现陈旧信息或错误复用。

## 测试覆盖

测试验证了会话内召回、会话隔离、显式新位置覆盖旧坐标、TTL 过期、批准前零 gateway 调用、拒绝零调用、跨会话令牌失败以及批准令牌最多执行一次。API 集成测试还覆盖完整的两轮记忆与 dry-run 确认流程。
