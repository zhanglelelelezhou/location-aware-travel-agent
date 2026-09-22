# MCP Server

## 目标

MCP 层把已有能力标准化暴露给外部 Agent Host，也允许本项目的 LangGraph Agent 作为 Client 消费同一协议，不重新实现业务逻辑：

```text
MCP Client / Host
  -> MCP schema validation and tool metadata
  -> get_weather / search_poi protocol wrappers
  -> shared Open-Meteo / Overpass adapters
  -> typed WeatherObservation / PoiSearchResult
```

LangGraph Agent 可以直连 adapter，也可以通过 `MCPToolRegistry` 走 `tools/call`。MCP Server 继续复用相同 adapter 与 Pydantic 输出模型，因此修复位置消歧、偏好证据或供应商错误时只需要修改一处。

## 工具

| MCP 工具 | 副作用 | 外部数据 | 关键约束 |
| --- | --- | --- | --- |
| `get_weather` | 无 | Open-Meteo | 经纬度必须成对出现并满足范围 |
| `search_poi` | 无 | OpenStreetMap Overpass | 必须有可信坐标；类别、半径和结果数有白名单/上限 |

两者都声明 `readOnlyHint=true`、`destructiveHint=false`、`idempotentHint=true` 和 `openWorldHint=true`。这些是客户端规划提示，不替代服务端校验。

## 运行方式

本地 Host 通常使用 stdio：

```bash
travel-agent-mcp
```

加上 `--provider mock` 可以在不访问外部网络的情况下验证完整协议链路。

需要通过网络连接时使用 Streamable HTTP：

```bash
travel-agent-mcp --transport streamable-http --host 127.0.0.1 --port 8001
```

在另一个终端探测协议版本与工具列表：

```bash
python scripts/mcp_probe.py http://127.0.0.1:8001/mcp
```

本地验证结果协商到协议版本 `2026-07-28`，并发现 `get_weather` 与 `search_poi`。

默认只监听回环地址。当前 HTTP 模式未配置认证，不应直接暴露到公网；生产部署需要 TLS、OAuth/令牌验证、反向代理、主机白名单、速率限制和供应商配额治理。

## 让 Agent 通过 MCP 执行

默认自动启动 bundled stdio server，并使用真实开放数据 adapter：

```bash
travel-agent "东京现在天气如何" \
  --location 东京 \
  --latitude 35.6895 \
  --longitude 139.6917 \
  --tools mcp
```

相关环境变量：

- `MCP_SERVER_PROVIDER=open-data|mock`：自动启动 stdio server 时选择 adapter；
- `MCP_SERVER_URL=http://127.0.0.1:8001/mcp`：改为连接现有 Streamable HTTP server；
- `MCP_TIMEOUT_SECONDS=20`：Client 读取超时。

执行节点把一份计划中的 MCP 工具调用放在同一个 Client session 中，协议错误、连接错误和缺失结构化输出统一转成可写入 Agent trace 的工具错误。纯本地计划不会建立 MCP 连接；远端会话失败也不会阻止同一计划中的本地工具执行。翻译与旅行知识目前仍在本地执行。

## 测试策略

- 内存 MCP Client：完成协议协商、工具发现、Schema 检查和结构化调用，不启动端口。
- stdio 子进程：使用真实 Python 子进程验证 Host 能发现工具。
- Agent Client：验证计划经 `tools/call` 返回结果，同一多工具计划只创建一个 MCP 会话。
- Mock adapter：协议测试不访问外部网络，保持 CI 稳定。
- adapter 契约测试：分别验证真实供应商响应解析、证据过滤和错误归一化。

这种分层避免把“包装函数能调用”误当成 MCP 已可用；测试必须经过 `tools/list` 和 `tools/call` 协议路径。
