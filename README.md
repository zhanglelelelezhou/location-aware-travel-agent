# Location-Aware Travel Agent

一个面向跨境旅行场景的位置感知智能体。它把用户当前位置、偏好和旅行知识转化为可审计的工具调用，并生成带依据的行动建议。

> 当前状态：Phase 2，已具备规则基线、结构化 LLM Planner、确定性策略层、真实天气工具、格式修复、规则降级和冻结留出集。仓库是基于真实实习场景进行的个人重构，不包含原公司的代码、数据或商业机密。默认规则模式不需要付费 API。

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

服务模式可在 `.env` 中设置 `AGENT_PROVIDER=open-meteo`。当前只有天气为真实服务，POI、翻译和知识工具仍使用 Mock；文本地名仅作为回退，候选不唯一时会明确失败并要求坐标。

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
  -> Execute tools (Mock or Open-Meteo weather)
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
- [ ] MCP Server：POI、天气、翻译
- [ ] 混合 RAG、Rerank 和引用溯源
- [ ] SSE 流式响应、会话记忆和人工确认
- [ ] 多次重复评测、参数准确率与 50+ 条评测集
- [ ] Docker Compose、CI 和在线演示

## 文档

- [架构与边界](docs/architecture.md)
- [工具契约](docs/tool-contracts.md)
- [项目故事](docs/project-story.md)
- [面试问题库](docs/interview-guide.md)
- [评测说明](docs/evaluation.md)
- [迭代计划](docs/roadmap.md)

## 真实性原则

- 不把规则路由包装成大模型自主规划；每一阶段都会明确能力边界。
- README 中只展示由评测脚本实际生成的指标。
- 第三方服务不可用时提供 fixture，确保面试官能够复现核心链路。
- 所有技术选型都要能回答“为什么”，而不是为了堆砌框架。
