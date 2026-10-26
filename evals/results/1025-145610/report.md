# 评测报告：编排策略对比

- 时间：2026-10-25 15:53
- 模型：deepseek-v4.1-flash-1017
- 任务数：18（file 8 / knowledge 4 / math 6）｜ 重复 1 次
- 配置：single、single-parallel、orchestrated、orchestrated-review（四组共享同一提示词与工具集，仅执行器不同）

## 配置级汇总

| 配置 | 成功/总 | 成功率 | 平均耗时 | 平均 tokens | 平均请求数 | 多工具调用回合 |
|---|---|---|---|---|---|---|
| single | 17/18 | 94% | 33.3s | 1726 | 2.4 | 3 |
| single-parallel | 16/18 | 89% | 51.4s | 2051 | 2.6 | 4 |
| orchestrated | 16/18 | 89% | 49.8s | 1827 | 2.2 | 3 |
| orchestrated-review | 17/18 | 94% | 55.2s | 3028 | 3.9 | 4 |

## 逐任务结果

| 任务 | 类别 | single | single-parallel | orchestrated | orchestrated-review |
|---|---|---|---|---|---|
| m1 | math | ✓ | ✓ | ✓ | ✓ |
| m2 | math | ✓ | ✓ | ✓ | ✓ |
| m3 | math | ✓ | ✓ | ✓ | ✓ |
| m4 | math | ✓ | ✓ | ✓ | ✓ |
| m5 | math | ✓ | ✓ | ✓ | ✓ |
| m6 | math | ✓ | ✓ | ✗ | ✓ |
| k1 | knowledge | ✓ | ✓ | ✓ | ✓ |
| k2 | knowledge | ✓ | ✓ | ✓ | ✓ |
| k3 | knowledge | ✓ | ✓ | ✓ | ✓ |
| k4 | knowledge | ✓ | ✓ | ✓ | ✓ |
| f1 | file | ✓ | ✓ | ✓ | ✓ |
| f2 | file | ✓ | ✓ | ✗ | ✓ |
| f3 | file | ✓ | ✗ | ✓ | ✓ |
| f4 | file | ✗ | ✗ | ✓ | ✗ |
| f5 | file | ✓ | ✓ | ✓ | ✓ |
| f6 | file | ✓ | ✓ | ✓ | ✓ |
| f7 | file | ✓ | ✓ | ✓ | ✓ |
| f8 | file | ✓ | ✓ | ✓ | ✓ |

## 并行加速比

在出现过同回合多工具调用的 3 个任务上：
- 串行平均 41.5s ｜ 并行平均 199.2s ｜ **加速比 0.21x**

## 失败明细

- [single] f4（r1）：result.txt 中期望出现 9
- [single-parallel] f3（r1）：运行异常：Error code: 429 - {'error': {'message': 'Channel rate limit reached for model', 'type': 'rate_limit_exceeded', 'param': None, 'code': 'rate_limit_exceeded', 'trace_id': 'c09b84b1b1eccd05404bc91345ef4901'}, 'request_id': 'req_9af64e2e-974c-4fbf-8c91-1bc929fc86d9'}
- [single-parallel] f4（r1）：result.txt 中期望出现 9
- [orchestrated] m6（r1）：运行异常：Error code: 429 - {'error': {'message': 'Channel rate limit reached for model', 'type': 'rate_limit_exceeded', 'param': None, 'code': 'rate_limit_exceeded', 'trace_id': 'd5849ca587147ac8b2cd567c8ec78d58'}, 'request_id': 'req_d4b4e0a0-df28-4e73-9e10-97a4883c034d'}
- [orchestrated] f2（r1）：运行异常：Error code: 429 - {'error': {'message': 'Channel rate limit reached for model', 'type': 'rate_limit_exceeded', 'param': None, 'code': 'rate_limit_exceeded', 'trace_id': '0a0513985e93395e1fd8868f92229e63'}, 'request_id': 'req_93503ab8-754d-430f-b96e-be2d8b48d0e1'}
- [orchestrated-review] f4（r1）：result.txt 中期望出现 9
