"""evals —— mini-agents 的评测 harness（M3）。

用法：
    python -m evals --offline                    # 离线自检：免费验证管线与判分
    python -m evals                              # 真实评测（需 .env 的 API Key）
    python -m evals --configs single,orchestrated --repeats 2

产出在 evals/results/<时间戳>/：report.md、results.jsonl、chart.png、逐任务 trace。
"""
