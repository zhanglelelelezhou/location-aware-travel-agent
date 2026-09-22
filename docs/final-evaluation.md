# 端到端系统验收

## 这组评测回答什么问题

Planner 评测衡量自然语言到结构化计划的语义能力，知识检索评测衡量召回与拒答；本评测单独验证完整系统契约是否稳定：工具与参数、缺失约束、会话记忆、一次性确认、SSE 生命周期和一次有界恢复。

评测固定使用 `RulePlanner + Mock tools + Dry-run booking gateway`，不访问网络，也不读取 `.env`。因此结果可以进入 CI，但不能代表 DeepSeek 的语义泛化、真实 POI/天气质量或开放域答案正确率。

## 冻结数据集与指标

`evals/system_cases.jsonl` 共 30 条：16 条单轮、5 条多轮会话、5 条确认安全、4 条流式生命周期。文件 SHA-256 为：

```text
ad50e28be5c002baafee1c8385bd3d918ce221713198d0c7cae4db67ff1bd0c3
```

每条样本必须通过所有适用检查才算成功。报告分别统计完整任务通过率、维度准确率、类别通过率、P50/P95 和以下错误分类：

- `intent_mismatch`
- `tool_mismatch`
- `constraint_mismatch`
- `answer_evidence_missing`
- `memory_mismatch`
- `confirmation_mismatch`
- `lifecycle_mismatch`
- `recovery_mismatch`
- `runtime_error`

运行命令：

```bash
python evals/run_system_eval.py \
  --output evals/results/system-acceptance.json
```

CLI 默认要求 100% 任务通过率，低于门槛时退出非零；`--min-pass-rate` 可用于独立实验，但 CI 不降低默认门槛。

## 可审计的修复记录

冻结集首次运行结果为 27/30（90%）。工具、参数、约束、记忆、确认、安全、生命周期和恢复全部通过，3 个失败均为 `intent_mismatch`：安全问答中的“点餐”被额外标成 dining，中英文订位请求中的“餐位/table”也被额外标成 dining。

没有修改样本或评分器。实现层加入两条通用消歧规则并增加反例测试：booking 压制冗余 dining；安全问答仅在没有场所发现表达时压制 dining，所以“推荐适合过敏者的餐厅”仍保留 dining+safety。相同数据哈希的回归结果为 30/30，各维度与各类别均为 100%。

| 报告 | 数据状态 | 任务通过率 | 意图准确率 | 失败 |
| --- | --- | ---: | ---: | --- |
| `system-acceptance-initial.json` | 首次冻结运行 | 90%（27/30） | 85.7% | 3 个意图消歧 |
| `system-acceptance.json` | 看过失败后的回归 | 100%（30/30） | 100% | 0 |

第二行是工程回归结果，不再是未消费留出成绩。对外描述时必须同时说明首次 90% 和修复后 100%，不能只展示后者来暗示未知分布上的泛化能力。

## 能证明与不能证明的内容

这组结果能证明当前提交满足已定义的确定性编排和安全契约，并且 CI 能阻止这些契约回退。它不能证明真实供应商稳定、回答主观质量、事实时效性、多进程状态一致性或模型在新表达上的鲁棒性。下一轮泛化验证需要新建未消费测试集，并对 DeepSeek Planner 做多次重复实验。
