# 评测说明

## 为什么先建立规则基线

如果没有稳定基线，就无法判断 LLM 带来的语义泛化能力是否值得额外延迟、Token 成本和供应商依赖。规则 Planner 同时承担离线开发、CI 和模型服务故障降级的职责。

## 数据集

当前评测集包含 20 条人工编写的中英文旅行请求，覆盖餐饮、行程、翻译、食物安全、天气、预订确认、缺失位置、Prompt injection、未支持能力和语义改写。

当前规模只适合开发期回归测试，不能作为生产效果结论。扩充时必须避免只增加系统已经能够通过的同义用例。

## 指标定义

- 意图准确率：预测意图列表与标注完全一致的比例。
- 工具路径准确率：工具名称及顺序与标注完全一致的比例。
- 约束准确率：缺失字段和是否需要确认均正确的比例。
- 完整任务通过率：以上三项全部正确的比例。

## 规则基线结果

生成命令：

```bash
python evals/run_eval.py --planner rule --output evals/results/rule-baseline.json
```

结果：完整任务通过率 75%（15/20），意图准确率 75%，工具路径准确率 75%，约束准确率 100%。

失败集中在五条没有显式关键词的语义改写：隐式餐饮需求、半日游规划、当地语言表达、身体不适风险和英文降雨询问。这些失败构成 LLM Planner 的主要验证目标。

## 尚未完成

LLM Planner 已完成接口、结构化输出校验、一次修复和规则降级测试，但尚未使用真实模型跑完 20 条评测，因此当前不能宣称 LLM 已提高准确率。接入真实 Provider 后，需要同时报告成功率、P50/P95 延迟、Token 用量和调用成本。

为防止降级结果掩盖模型问题，LLM 报告同时提供完整任务通过率、原生 LLM 通过率和 fallback_count。若模型输出失败后由规则版本答对，该样本不会计入原生 LLM 通过率。

## 真实模型评测

在项目根目录创建不提交 Git 的 `.env`：

```dotenv
AGENT_PLANNER=llm
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-secret
LLM_MODEL=your-model
LLM_JSON_MODE=true
LLM_INPUT_COST_PER_MILLION=0
LLM_OUTPUT_COST_PER_MILLION=0
```

然后运行：

```bash
python evals/run_eval.py --planner llm --output evals/results/llm-candidate.json
python evals/compare_reports.py evals/results/rule-baseline.json evals/results/llm-candidate.json
```

`LLM_JSON_MODE=false` 仅用于不支持 `response_format=json_object` 的兼容服务。价格字段只用于本地估算，应填写所用服务实际价格；为零时报告仍记录 Token，但估算成本为零。
