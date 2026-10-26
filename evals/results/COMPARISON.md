# 跨框架对比（自动生成）

- 生成时间：2026-10-26 02:21
- 口径：每框架取任务数最多的最新全量运行；三列共享同一任务集、提示词、工具与判分器

- **mini-agents**：deepseek-v4.1-flash-1017（1025-145610，72 条结果）
- **langgraph**：deepseek-v4.1-flash-1017（1025-231621-langgraph，36 条结果）
- **agents-sdk**：deepseek-v4.1-flash-1017（1026-003312-agents-sdk，36 条结果）

| 配置 | 指标 | mini-agents | langgraph | agents-sdk |
|---|---|---|---|---|
| single | 成功率 | 94% | 100% | 94% |
| single | 平均 tokens | 1726 | 2453 | 1741 |
| single | 平均耗时 | 33.3s | 92.7s | 13.8s |
| single-parallel | 成功率 | 89% | - | - |
| single-parallel | 平均 tokens | 2051 | - | - |
| single-parallel | 平均耗时 | 51.4s | - | - |
| orchestrated | 成功率 | 89% | 94% | 94% |
| orchestrated | 平均 tokens | 1827 | 3242 | 2480 |
| orchestrated | 平均耗时 | 49.8s | 91.5s | 11.6s |
| orchestrated-review | 成功率 | 94% | - | - |
| orchestrated-review | 平均 tokens | 3028 | - | - |
| orchestrated-review | 平均耗时 | 55.2s | - | - |
| **编排开销** | tokens | **+6%** | **+32%** | **+42%** |

> 自动生成：`python -m evals.compare`。延迟列不可跨框架直接对比，限流对齐策略与运行时段不同（详见各 report.md）。
