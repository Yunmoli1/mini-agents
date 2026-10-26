# 评测报告：编排策略对比

- 时间：2026-10-26 00:40
- 框架：agents-sdk
- 模型：deepseek-v4.1-flash-1017
- 任务数：18（file 8 / knowledge 4 / math 6）｜ 重复 1 次
- 配置：single、orchestrated（四组共享同一提示词与工具集，仅执行器不同）

## 配置级汇总

| 配置 | 成功/总 | 成功率 | 平均耗时 | 平均 tokens | 平均请求数 | 多工具调用回合 |
|---|---|---|---|---|---|---|
| single | 17/18 | 94% | 13.8s | 1741 | 2.3 | 0 |
| orchestrated | 17/18 | 94% | 11.6s | 2480 | 2.7 | 0 |

## 逐任务结果

| 任务 | 类别 | single | orchestrated |
|---|---|---|---|
| m1 | math | ✓ | ✓ |
| m2 | math | ✓ | ✓ |
| m3 | math | ✓ | ✓ |
| m4 | math | ✓ | ✓ |
| m5 | math | ✓ | ✓ |
| m6 | math | ✓ | ✓ |
| k1 | knowledge | ✓ | ✓ |
| k2 | knowledge | ✓ | ✓ |
| k3 | knowledge | ✓ | ✓ |
| k4 | knowledge | ✓ | ✓ |
| f1 | file | ✓ | ✓ |
| f2 | file | ✓ | ✓ |
| f3 | file | ✓ | ✓ |
| f4 | file | ✗ | ✗ |
| f5 | file | ✓ | ✓ |
| f6 | file | ✓ | ✓ |
| f7 | file | ✓ | ✓ |
| f8 | file | ✓ | ✓ |

## 并行加速比

本轮没有出现同回合多工具调用，无法测加速比（可换支持并行工具调用的模型重试）。

## 失败明细

- [single] f4（r1）：result.txt 中期望出现 9
- [orchestrated] f4（r1）：result.txt 中期望出现 9
