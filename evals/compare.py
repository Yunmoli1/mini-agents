"""跨框架对比表生成器：扫描 evals/results/，自动汇总各框架最新全量运行。

    python -m evals.compare

- 框架识别：目录名后缀（-langgraph / -agents-sdk …），无后缀为 mini-agents
- 同框架多个运行时，取任务数最多的一份（并列取最新）——冒烟小样自动被全量覆盖
- 输出：Markdown 对比表（stdout + evals/COMPARISON.md）

替代手工维护 README 对比表：每次跑完新框架，执行本脚本即可刷新。
"""
import json
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path("evals/results")
FRAMEWORK_SUFFIXES = ["langgraph", "agents-sdk", "crewai"]
CONFIG_ORDER = ["single", "single-parallel", "orchestrated", "orchestrated-review"]


def detect_framework(dirname: str) -> str | None:
    if dirname.endswith("-offline"):
        return None
    for fw in FRAMEWORK_SUFFIXES:
        if dirname.endswith(f"-{fw}"):
            return fw
    return "mini-agents"


def load_runs():
    runs = []
    for d in sorted(RESULTS_DIR.iterdir()):
        results_file = d / "results.jsonl"
        if not d.is_dir() or not results_file.exists():
            continue
        rows = [json.loads(line) for line in
                results_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            continue
        framework = detect_framework(d.name)
        if framework is None:
            continue
        runs.append({"framework": framework, "dir": d.name, "rows": rows})
    return runs


def pick_best(runs, framework):
    """同框架取任务数最多的运行（并列取目录名最新的）。"""
    same = [r for r in runs if r["framework"] == framework]
    if not same:
        return None
    return max(same, key=lambda r: (len(r["rows"]), r["dir"]))


def aggregate(rows, config):
    rs = [r for r in rows if r["config"] == config]
    if not rs:
        return None
    n = len(rs)
    return {"success": sum(r["success"] for r in rs), "n": n,
            "tokens": sum(r["tokens"] for r in rs) / n,
            "seconds": sum(r["seconds"] for r in rs) / n}


def main():
    if hasattr(__import__("sys").stdout, "reconfigure"):
        __import__("sys").stdout.reconfigure(encoding="utf-8", errors="replace")

    runs = load_runs()
    if not runs:
        print("没有找到任何评测结果（evals/results/*/results.jsonl）")
        return

    picks = {}
    for fw in dict.fromkeys([r["framework"] for r in runs]):  # 去重保序
        best = pick_best(runs, fw)
        if best:
            picks[fw] = best

    configs = [c for c in CONFIG_ORDER
               if any(aggregate(p["rows"], c) for p in picks.values())]

    lines = ["# 跨框架对比（自动生成）", "",
             f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
             "- 口径：每框架取任务数最多的最新全量运行；三列共享同一任务集、"
             "提示词、工具与判分器", ""]
    for fw, run in picks.items():
        model = run["rows"][0].get("model", "?")
        lines.append(f"- **{fw}**：{model}（{run['dir']}，{len(run['rows'])} 条结果）")
    lines += ["", "| 配置 | 指标 | " + " | ".join(picks) + " |",
              "|---|---|" + "---|" * len(picks)]

    for config in configs:
        aggs = {fw: aggregate(run["rows"], config) for fw, run in picks.items()}
        aggs = {fw: a for fw, a in aggs.items() if a}
        for metric, fmt in (("成功率", lambda a: f"{a['success'] / a['n']:.0%}"),
                            ("平均 tokens", lambda a: f"{a['tokens']:.0f}"),
                            ("平均耗时", lambda a: f"{a['seconds']:.1f}s")):
            cells = []
            for fw in picks:
                a = aggs.get(fw)
                cells.append(fmt(a) if a else "-")
            lines.append(f"| {config} | {metric} | " + " | ".join(cells) + " |")

    # 编排开销：同一框架内 orchestrated/single 的 tokens 比
    overhead = {}
    for fw, run in picks.items():
        single = aggregate(run["rows"], "single")
        orch = aggregate(run["rows"], "orchestrated")
        if single and orch and single["tokens"]:
            overhead[fw] = (orch["tokens"] / single["tokens"] - 1)
    if overhead:
        lines.append("| **编排开销** | tokens | "
                     + " | ".join(f"**{overhead.get(fw, float('nan')):+.0%}**"
                                  if fw in overhead else "-"
                                  for fw in picks) + " |")

    lines += ["", "> 自动生成：`python -m evals.compare`。延迟列不可跨框架直接对比，"
              "限流对齐策略与运行时段不同（详见各 report.md）。"]

    output = "\n".join(lines) + "\n"
    print(output)
    out_path = RESULTS_DIR / "COMPARISON.md"
    out_path.write_text(output, encoding="utf-8")
    print(f"已写入：{out_path}")


if __name__ == "__main__":
    main()
