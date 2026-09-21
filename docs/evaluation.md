# 评测说明

## 为什么先建立规则基线

如果没有稳定基线，就无法判断 LLM 带来的语义泛化能力是否值得额外延迟、Token 成本和供应商依赖。规则 Planner 同时承担离线开发、CI 和模型服务故障降级的职责。

## 数据集

当前评测集包含 20 条人工编写的中英文旅行请求，覆盖餐饮、行程、翻译、食物安全、天气、预订确认、缺失位置、Prompt injection、未支持能力和语义改写。

当前规模只适合开发期回归测试，不能作为生产效果结论。扩充时必须避免只增加系统已经能够通过的同义用例。

## 指标定义

- 意图准确率：预测意图集合与标注集合完全一致的比例。
- 工具集合准确率：工具集合与标注集合完全一致的比例；当前工具彼此独立，因此不因调用顺序不同扣分。
- 约束准确率：缺失字段和是否需要确认均正确的比例。
- 完整任务通过率：以上三项全部正确的比例。

## 规则基线结果

生成命令：

```bash
python evals/run_eval.py --planner rule --output evals/results/rule-baseline.json
```

最终评分策略下，完整任务通过率 55%（11/20），意图准确率 55%，工具集合准确率 80%，约束准确率 95%。

规则版本的主要问题是关键词匹配无法稳定区分主任务意图，也不能处理隐式餐饮、半日游、当地语言表达、身体不适和英文降雨等语义改写。

## DeepSeek 真实模型结果

使用 `deepseek-flash`、关闭思考模式、JSON Output，对同一批 20 条用例进行一次真实评测：

| 指标 | 规则 Planner | DeepSeek | 变化 |
| --- | ---: | ---: | ---: |
| 完整任务通过率 | 55% | 85% | +30 pp |
| 意图准确率 | 55% | 100% | +45 pp |
| 工具集合准确率 | 80% | 85% | +5 pp |
| 约束准确率 | 95% | 100% | +5 pp |
| 端到端 P95 | 7 ms | 949 ms | +942 ms |

DeepSeek 使用 10,957 个输入 Token 和 996 个输出 Token，按 `.env` 中配置的保守价格估算约 0.004482 美元。没有发生格式修复或规则降级，因此 85% 同时也是原生 LLM 通过率。

剩余三条失败都属于 itinerary 工具完整性：模型正确识别了行程意图，但漏掉 `search_poi` 或 `get_weather`。这说明语义理解适合交给 LLM，而“行程必须同时检查地点和天气”更适合由确定性策略层强制保证。

## 评测校准记录

首次评分把所有餐饮请求都要求翻译、把上下文类别当成额外意图，并对互不依赖的工具顺序进行扣分，导致 DeepSeek 完整通过率只有 30%。这些规则来源于旧规则 Planner 的行为，而不是产品需求，属于实现污染标注。

修订后，意图按主任务集合评分，工具按集合评分，缺参数时禁止执行工具，并将 booking 的确认要求作为独立约束。初始预测保存在 `evals/results/deepseek-flash-initial.json`，最终报告由 `rescore_report.py` 在不重复调用 API 的情况下生成，保留了实验审计链路。

为防止降级结果掩盖模型问题，LLM 报告同时提供完整任务通过率、原生 LLM 通过率和 fallback_count。若模型输出失败后由规则版本答对，该样本不会计入原生 LLM 通过率。

当前 20 条数据已经参与规则与提示词迭代，因此只能视为开发集。下一阶段必须增加独立留出集并进行多次重复评测，才能评价稳定性和泛化能力。

## 真实模型评测

在项目根目录创建不提交 Git 的 `.env`：

```dotenv
AGENT_PLANNER=llm
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-secret
LLM_MODEL=your-model
LLM_JSON_MODE=true
LLM_THINKING_MODE=disabled
LLM_MAX_TOKENS=1500
LLM_INPUT_COST_PER_MILLION=0
LLM_OUTPUT_COST_PER_MILLION=0
```

然后运行：

```bash
python evals/run_eval.py --planner llm --output evals/results/llm-candidate.json
python evals/compare_reports.py evals/results/rule-baseline.json evals/results/llm-candidate.json
```

`LLM_JSON_MODE=false` 仅用于不支持 `response_format=json_object` 的兼容服务。对 DeepSeek 的短规划任务默认关闭思考模式，以减少延迟和 Token；如需实验思考模式，可将 `LLM_THINKING_MODE` 改为 `enabled`。价格字段只用于本地估算，应填写所用服务实际价格；为零时报告仍记录 Token，但估算成本为零。
