# 迭代计划

## Phase 1：可信的可运行基线（当前）

- LangGraph 有界状态机
- Mock 工具与统一接口
- API、CLI、测试和最小评测集
- 项目故事、能力边界与面试问题

完成标准：新环境能够运行测试；三类核心场景拥有可审计 trace。

## Phase 2：真实推理与工具协议

- [x] Provider-agnostic LLM 接口和结构化规划
- [x] Schema 校验、一次修复与规则降级
- [x] 20 条规则/LLM 共用评测集
- [x] DeepSeek 真实评测、Token/成本/延迟报告与错误分析
- [x] 确定性业务策略层与独立留出评测集
- [x] Open-Meteo 真实天气 adapter 与契约测试
- [x] OpenStreetMap Overpass 真实 POI adapter、距离排序与证据过滤
- [x] POI 与天气 MCP Server（stdio、Streamable HTTP、协议级测试）
- [x] LangGraph MCP Client 执行路径、计划级会话复用与错误归一化
- 翻译与旅行知识 MCP Server
- 工具 schema 校验、超时、重试和降级
- SSE 流式事件

完成标准：真实与 Mock adapter 通过同一契约测试；LLM 版本在固定评测集上优于规则基线。

## Phase 3：知识、记忆与安全

- [x] 官方来源知识快照、BM25 基线、引用溯源与独立检索评测
- [ ] 稠密召回、RRF 混合检索、Rerank 和盲测语义改写集
- 会话摘要与用户偏好记忆
- Prompt injection 防护和有副作用操作的人工确认

完成标准：引用正确率和记忆相关任务有独立评测，不以单个 Demo 代替结论。

## Phase 4：作品集交付

- 50 条以上场景化评测集和错误分类
- OpenTelemetry/Langfuse 可观测性
- Docker Compose、GitHub Actions 和部署说明
- 架构图、90 秒演示视频、简历 bullet 和完整面试复盘

完成标准：面试官可以在十分钟内理解价值，在三条命令内运行项目，并从报告中看到真实指标与限制。
