# Location-Aware Travel Agent

一个面向跨境旅行场景的位置感知智能体。它把用户当前位置、偏好和旅行知识转化为可审计的工具调用，并生成带依据的行动建议。

> 当前状态：Phase 1，可运行的 Mock 垂直切片。仓库是基于真实实习场景进行的个人重构，不包含原公司的代码、数据或商业机密。Mock 模式不需要付费 API。

## 为什么它是 Agent，而不是聊天壳

当前工作流显式执行以下闭环：

1. 理解用户意图与约束；
2. 生成工具计划；
3. 调用位置、天气、翻译或知识工具；
4. 校验工具执行结果并进行一次受控恢复；
5. 返回答案以及可审计的执行轨迹。

Phase 1 使用确定性策略，保证任何人都能本地复现。Phase 2 将在同一接口下接入真实 LLM、MCP Server、混合 RAG 和流式输出，并用固定评测集比较升级前后的收益。

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

## 当前架构

```text
Request
  -> Understand
  -> Plan
  -> Execute tools
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
- [ ] LLM Provider 抽象与结构化输出
- [ ] MCP Server：POI、天气、翻译
- [ ] 混合 RAG、Rerank 和引用溯源
- [ ] SSE 流式响应、会话记忆和人工确认
- [ ] 50+ 条 Agent 评测集与指标看板
- [ ] Docker Compose、CI 和在线演示

## 文档

- [架构与边界](docs/architecture.md)
- [项目故事](docs/project-story.md)
- [面试问题库](docs/interview-guide.md)
- [迭代计划](docs/roadmap.md)

## 真实性原则

- 不把规则路由包装成大模型自主规划；每一阶段都会明确能力边界。
- README 中只展示由评测脚本实际生成的指标。
- 第三方服务不可用时提供 fixture，确保面试官能够复现核心链路。
- 所有技术选型都要能回答“为什么”，而不是为了堆砌框架。

