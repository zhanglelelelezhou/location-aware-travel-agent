# Location-Aware Travel Agent

一个面向跨境旅行场景的位置感知智能体。它把用户当前位置、偏好和旅行知识转化为可审计的工具调用，并生成带依据的行动建议。

> 当前状态：Phase 3，已具备规则基线、结构化 LLM Planner、确定性策略层、真实天气与 POI、带官方引用的旅行安全知识检索、MCP Server/Client 执行链路、规则降级和冻结评测集。知识检索已完成 BM25、稠密向量和 RRF 混合召回的盲测消融；由于混合方案增益有限且拒答未改善，默认仍使用 BM25。仓库是基于真实实习场景进行的个人重构，不包含原公司的代码、数据或商业机密。默认规则模式不需要付费 API。

## 为什么它是 Agent，而不是聊天壳

当前工作流显式执行以下闭环：

1. 理解用户意图与约束；
2. 生成工具计划；
3. 调用位置、天气、翻译或知识工具；
4. 校验工具执行结果并进行一次受控恢复；
5. 返回答案以及可审计的执行轨迹。

规则 Planner 保证任何人都能本地复现；LLM Planner 通过同一接口接入任意 OpenAI-compatible 服务。模型输出必须通过 Pydantic Schema 和工具白名单校验，首次失败会要求模型修复，第二次失败则降级到规则 Planner。合法计划还会经过确定性策略层：例如行程任务必须同时包含 POI 与天气工具，预订任务在确认前不能执行工具。所有自动补正均写入 trace。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
uvicorn travel_agent.api:app --reload
```

调用示例：

```bash
curl -X POST http://127.0.0.1:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "我在大阪站附近，找一家支持素食的餐厅，并生成一句日语询问语",
    "location": "大阪站",
    "preferences": ["素食"]
  }'
```

也可以直接使用 CLI：

```bash
travel-agent "我在大阪站附近，找一家支持素食的餐厅，并生成一句日语询问语" --location 大阪站 --preference 素食
```

调用真实天气工具（Open-Meteo 无需 API Key）。位置感知设备应优先传经纬度，避免同名地点误解析：

```bash
travel-agent "东京现在天气怎么样" \
  --location 东京 \
  --latitude 35.6895 \
  --longitude 139.6917 \
  --tools open-meteo
```

服务模式可在 `.env` 中设置 `AGENT_PROVIDER=open-meteo`。该模式使用真实天气、官方来源知识快照以及 Mock POI/翻译；文本地名仅作为回退，候选不唯一时会明确失败并要求坐标。

同时启用真实天气和 POI 搜索：

```bash
travel-agent "东京站附近有什么餐厅" \
  --location 东京站 \
  --latitude 35.6812 \
  --longitude 139.7671 \
  --tools open-data
```

`open-data` 模式使用 OpenStreetMap Overpass 搜索附近地点，结果携带距离、标签证据、OSM 来源链接和署名。真实 POI 必须提供可信坐标；公共 Overpass 实例仅用于低频作品集演示，生产部署需要缓存、限流并自建或更换供应商。

## MCP Server

天气和 POI adapter 同时通过 MCP 暴露，供任意兼容 Host 发现和调用。默认使用本地 stdio：

```bash
travel-agent-mcp
```

也可以启动本地 Streamable HTTP：

```bash
travel-agent-mcp --transport streamable-http --host 127.0.0.1 --port 8001
# MCP endpoint: http://127.0.0.1:8001/mcp
```

服务启动后可在另一个终端验证协议协商与工具发现：

```bash
python scripts/mcp_probe.py http://127.0.0.1:8001/mcp
```

两个 MCP 工具都声明为只读、非破坏、幂等且访问外部数据。输入 JSON Schema 直接来自类型注解和 Pydantic 约束，非法类别、坐标、半径和结果数量会在调用 adapter 前被协议层拒绝。详见 [MCP Server 说明](docs/mcp-server.md)。

LangGraph Agent 也可以作为 MCP Client 执行自己的工具计划。未设置远程地址时会自动启动 bundled stdio server；同一计划中的多个 MCP 工具复用一个会话：

```bash
travel-agent "帮我安排东京半日景点行程" \
  --location 东京 \
  --latitude 35.6895 \
  --longitude 139.6917 \
  --tools mcp
```

完全离线验证可设置 `MCP_SERVER_PROVIDER=mock`。连接已启动的 Streamable HTTP server 时设置 `MCP_SERVER_URL=http://127.0.0.1:8001/mcp`。当前只有天气与 POI 经过 MCP；翻译在本地使用 Mock，旅行知识在本地使用官方来源快照。

## 带引用的旅行知识检索

真实工具模式包含一个可复现的中英文 BM25 基线，语料是对日本消费者厅和日本政府观光局页面的短摘要，每个 passage 保留发布机构、原始 URL、主题和快照日期。安全问题的回答会直接附上来源链接：

```bash
travel-agent "我对花生严重过敏，在日本餐厅点餐要注意什么" --tools open-data
```

运行独立检索评测：

```bash
python evals/run_knowledge_eval.py \
  --output evals/results/knowledge-bm25-baseline.json
```

当前 12 条中英文小型基线为 Hit@1 100%、Hit@3 100%、Recall@3 95.8%、MRR@3 100%；另有 6 条库外查询，拒答准确率 100%。语料与两组查询集都记录 SHA-256；这些数字只用于后续稠密检索和 Rerank 的同集对照，不代表开放域泛化能力。详见[知识检索设计](docs/knowledge-retrieval.md)。

可选安装 FastEmbed 并运行稠密/混合检索：

```bash
python -m pip install -e ".[dev,rag]"
python evals/run_knowledge_eval.py \
  --cases evals/knowledge_blind_cases.jsonl \
  --rejection-cases evals/knowledge_blind_rejection_cases.jsonl \
  --retrieval-method hybrid \
  --dense-min-score 0.60
```

冻结盲测揭示了更真实的上限：BM25 的 Hit@1/Hit@3 为 58.3%/66.7%，稠密检索为 25.0%/25.0%，RRF 混合为 66.7%/66.7%；三者的库外拒答准确率分别为 62.5%、87.5%、62.5%。因此线上默认没有切换到混合检索。模型缓存位于 Git 忽略的 `.cache/fastembed`，可通过 `KNOWLEDGE_RETRIEVAL=dense|hybrid` 显式启用实验方案。

启用真实 LLM Planner。复制 `.env.example` 为 `.env`，填写服务地址、模型名和密钥；`.env` 已被 Git 忽略：

```bash
travel-agent "肚子饿了，周围有无不含肉的店" --location 难波 --planner llm
```

运行规则基线评测：

```bash
python evals/run_eval.py --planner rule
```

运行冻结留出集：

```bash
python evals/run_eval.py \
  --planner llm \
  --cases evals/holdout_cases.jsonl \
  --output evals/results/deepseek-flash-holdout.json
```

生成真实 LLM 报告并与规则基线比较：

```bash
python evals/run_eval.py --planner llm --output evals/results/llm-candidate.json
python evals/compare_reports.py \
  evals/results/rule-baseline.json \
  evals/results/llm-candidate.json
```

报告会记录数据集路径与 SHA-256、原生 LLM 通过率、策略补正、规则降级、格式修复、Planner 与端到端 P50/P95 延迟、Token 用量及估算成本。报告不会保存 API Key。

## 当前可复现实验结果

20 条开发集与 20 条冻结留出集上的单次对照：

| 数据集 | 规则 Planner | DeepSeek + 策略层 | 变化 |
| --- | ---: | ---: | ---: |
| 开发集完整任务通过率 | 55% | 95% | +40 pp |
| 留出集完整任务通过率 | 50% | 85% | +35 pp |
| 留出集意图准确率 | 60% | 90% | +30 pp |
| 留出集工具集合准确率 | 55% | 95% | +40 pp |
| 留出集约束准确率 | 90% | 95% | +5 pp |

开发集中的策略层补正了 2 个不完整行程计划，完整任务通过率由此前纯 LLM 的 85% 提升到 95%。冻结留出集在首次且唯一一次运行中达到 85%（17/20），无规则降级；使用 11,687 个输入 Token、951 个输出 Token，估算成本 0.004647 美元，端到端 P95 为 1,107 ms。留出集 SHA-256 为 `9063598c67fa0547f1adaf42a0f9f49d2770636aef0c45816da1b0640cfa30fc`，首次运行后没有据其结果修改 Prompt、策略或标注。详见[评测说明](docs/evaluation.md)、[开发集报告](evals/results/deepseek-flash-policy-dev.json)和[留出集报告](evals/results/deepseek-flash-holdout.json)。

## 当前架构

```text
Request
  -> Understand
  -> Plan (semantic LLM / rule fallback)
  -> Enforce deterministic policy
  -> Execute tools (Mock / Open-Meteo / OpenStreetMap / cited knowledge / MCP)
  -> Verify -- failed once --> Recover -> Execute
       |
       +-- success / retry exhausted --> Respond
```

核心接口与工具实现解耦，因此 Mock、真实 HTTP API 和 MCP 工具可以复用同一工作流。

## 项目路线图

- [x] 可运行的 LangGraph 状态机
- [x] Mock POI、天气、翻译和旅行知识工具
- [x] 执行轨迹、一次重试和基础测试
- [x] 项目故事与首批面试问题
- [x] LLM Provider 抽象与结构化输出
- [x] 一次格式修复、工具白名单与规则降级
- [x] 20 条规则/LLM 共用评测集
- [x] DeepSeek 真实调用、成本与延迟对照
- [x] 确定性业务策略层与可审计补正
- [x] 20 条冻结留出集与数据集哈希
- [x] Open-Meteo 真实天气适配器与 Mock 共用输出契约
- [x] 设备坐标优先、地名歧义拒绝与供应商错误归一化
- [x] OpenStreetMap 真实 POI、距离排序与偏好证据过滤
- [x] MCP Server：天气与 POI、stdio 与 Streamable HTTP
- [x] MCP Client：Agent 工具执行、会话复用与错误归一化
- [x] 官方来源知识快照、BM25 基线、引用输出与检索评测
- [ ] MCP Server：翻译与旅行知识
- [x] 多语稠密检索与 RRF 混合召回盲测消融（负结果如实保留）
- [ ] Rerank、按主题校准拒答和更大规模盲测
- [ ] SSE 流式响应、会话记忆和人工确认
- [ ] 多次重复评测、参数准确率与 50+ 条评测集
- [ ] Docker Compose、CI 和在线演示

## 文档

- [架构与边界](docs/architecture.md)
- [工具契约](docs/tool-contracts.md)
- [知识检索设计](docs/knowledge-retrieval.md)
- [MCP Server](docs/mcp-server.md)
- [项目故事](docs/project-story.md)
- [面试问题库](docs/interview-guide.md)
- [评测说明](docs/evaluation.md)
- [迭代计划](docs/roadmap.md)

## 真实性原则

- 不把规则路由包装成大模型自主规划；每一阶段都会明确能力边界。
- README 中只展示由评测脚本实际生成的指标。
- 第三方服务不可用时提供 fixture，确保面试官能够复现核心链路。
- 所有技术选型都要能回答“为什么”，而不是为了堆砌框架。
