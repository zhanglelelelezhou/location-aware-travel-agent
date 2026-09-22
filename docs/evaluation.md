# 评测说明

## 为什么先建立规则基线

如果没有稳定基线，就无法判断 LLM 带来的语义泛化能力是否值得额外延迟、Token 成本和供应商依赖。规则 Planner 同时承担离线开发、CI 和模型服务故障降级的职责。

## 数据集

评测分为两组：

- `cases.jsonl`：20 条开发用例，参与过评分契约与提示词迭代，只用于回归和错误分析。
- `holdout_cases.jsonl`：20 条独立中英文留出用例，在首次真实模型运行前冻结；报告同时记录文件 SHA-256，防止结果与数据版本脱钩。

留出集 SHA-256 为 `9063598c67fa0547f1adaf42a0f9f49d2770636aef0c45816da1b0640cfa30fc`。首次运行后不根据失败样本调整 Prompt、策略或标注。当前规模仍不足以代表生产效果，扩充时必须避免只增加系统已经能够通过的同义用例。

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

## 确定性策略层

LLM 负责识别自然语言意图并生成候选计划；代码策略负责不可协商的产品不变量。当前策略包括：行程任务在已知位置时必须同时查询 POI 与天气、缺少位置时禁止执行工具，以及预订在用户确认前禁止执行工具。策略的每次补正都写入 `policy_adjustments`，而不是静默篡改模型输出。

这种分工避免为了确定性规则反复调 Prompt，也让审阅者可以从 trace 判断最终成功来自模型原生计划还是策略补正。

## DeepSeek 真实模型结果

使用 `deepseek-flash`、关闭思考模式和 JSON Output。开发集报告是在策略层加入后重新运行一次；留出集只运行一次：

| 指标 | 开发集规则 | 开发集 DeepSeek + 策略 | 留出集规则 | 留出集 DeepSeek + 策略 |
| --- | ---: | ---: | ---: | ---: |
| 完整任务通过率 | 55% | 95% | 50% | 85% |
| 意图准确率 | 55% | 100% | 60% | 90% |
| 工具集合准确率 | 80% | 95% | 55% | 95% |
| 约束准确率 | 95% | 95% | 90% | 95% |
| 端到端 P95 | 8 ms | 966 ms | 7 ms | 1,107 ms |

开发集使用 10,957 个输入 Token 和 939 个输出 Token，估算成本 0.004414 美元；策略补正 2 个样本，无格式修复和规则降级。留出集使用 11,687 个输入 Token 和 951 个输出 Token，估算成本 0.004647 美元；策略补正 1 个样本，发生 1 次格式修复，无规则降级。两组的原生 LLM 任务通过率分别为 95% 和 85%，这里的“原生”仅排除规则降级，并不排除确定性策略补正。

开发集唯一失败是把“问路的话”判定为缺少待翻译文本，从而阻止整个复合计划。留出集 3 个失败分别是两个次级意图集合不一致，以及同类翻译文本判定问题。它们被保留为后续实验假设，不在本轮用来调参。

## 评测校准记录

首次评分把所有餐饮请求都要求翻译、把上下文类别当成额外意图，并对互不依赖的工具顺序进行扣分，导致 DeepSeek 完整通过率只有 30%。这些规则来源于旧规则 Planner 的行为，而不是产品需求，属于实现污染标注。

修订后，意图按主任务集合评分，工具按集合评分，缺参数时禁止执行工具，并将 booking 的确认要求作为独立约束。初始预测保存在 `evals/results/deepseek-flash-initial.json`，最终报告由 `rescore_report.py` 在不重复调用 API 的情况下生成，保留了实验审计链路。

为防止降级结果掩盖模型问题，LLM 报告同时提供完整任务通过率、原生 LLM 通过率和 fallback_count。若模型输出失败后由规则版本答对，该样本不会计入原生 LLM 通过率。

独立留出集降低了在开发集上过拟合结论的风险，但单次运行仍不能衡量模型波动。下一阶段需要在不改变冻结集的前提下做多次重复评测，并增加工具参数准确率与真实结果质量评价。

## 端到端系统验收

语义 Planner 和知识检索之外，项目还有一组 30 条完全离线的系统契约集，覆盖单轮工具参数、多轮记忆、一次性确认、SSE 生命周期与有界恢复。首次冻结运行是 90%（27/30）；错误分类发现 3 个规则意图消歧缺陷。保持数据集与评分器不变并修复通用实现后，回归结果为 100%（30/30），并作为 CI 硬门禁。

修复后结果属于已消费数据上的回归证明，不能替代新的留出集。数据哈希、两份报告、错误分类和适用边界见[端到端系统验收](final-evaluation.md)。

## 知识检索基线

旅行安全知识使用独立的 `knowledge_cases.jsonl`，不与 Planner 的意图/工具评测混在一起。12 条中英文查询覆盖食物过敏、紧急电话、地震、证件遗失和就医；指标包括 Hit@1、Hit@K、真实 Recall@K 和 MRR@K。

```bash
python evals/run_knowledge_eval.py \
  --top-k 3 \
  --output evals/results/knowledge-bm25-baseline.json
```

当前 BM25 基线为 Hit@1 100%、Hit@3 100%、Recall@3 95.8%、MRR@3 100%；6 条库外查询的拒答准确率为 100%。正例集 SHA-256 为 `3823d6656c7957a610c186969725f9cc93792e0808ecf601507fabce91e36bb8`，拒答集 SHA-256 为 `570d848b8e48d8693eb3eccaa14de4895ca8d67a5d4020cd05bb6600da631506`，语料 SHA-256 为 `eb14d9f3ebd73012ba2c475b39c1cd0ed3a47eddef36af76a49d698fac89f10e`。

由于查询集规模小且与语料同时设计，拒答阈值也根据当前分数间隔选择，这组高分只表示基线实现和引用链路稳定。不能据此宣称开放域检索已经解决；混合检索实验需要增加独立语义改写与难负例，并报告相对 BM25 的增益和新增延迟。

### 稠密与混合检索盲测

在实现 FastEmbed adapter 前，先冻结 12 条语义改写正例和 8 条难负例。向量阈值只在上述开发集扫描：0.45 保持 Recall@3 100%，但拒答准确率为 83.3%；0.60 可让 RRF 混合模式在开发集同时达到 Hit@3、Recall@3 和拒答准确率 100%，因此在查看盲测结果前锁定为 0.60。

锁定参数后的首次冻结结果为：BM25 的 Hit@1 58.3%、Hit@3 66.7%、拒答 62.5%；dense 为 25.0%、25.0%、87.5%；RRF hybrid 为 66.7%、66.7%、62.5%。之后只为增加后端版本字段用相同参数重生成 JSON，准确率指标不变。最终报告中的查询 P50 从 BM25 的 0.121 ms 增至 hybrid 的 19.724 ms；延迟是单机小样本观测，不是稳定 benchmark。混合方案没有提升召回或拒答，所以没有替换默认 BM25。

对应报告为 `knowledge-bm25-blind.json`、`knowledge-dense-blind.json` 和 `knowledge-hybrid-blind.json`。这组结果不再用于调模型、调阈值或改写盲测用例；下一轮必须新建开发/测试数据。

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

python evals/run_eval.py \
  --planner llm \
  --cases evals/holdout_cases.jsonl \
  --output evals/results/llm-holdout.json
```

`LLM_JSON_MODE=false` 仅用于不支持 `response_format=json_object` 的兼容服务。对 DeepSeek 的短规划任务默认关闭思考模式，以减少延迟和 Token；如需实验思考模式，可将 `LLM_THINKING_MODE` 改为 `enabled`。价格字段只用于本地估算，应填写所用服务实际价格；为零时报告仍记录 Token，但估算成本为零。
