"""评测 runner：一键跑配置矩阵，产出成功率 / token 成本 / 时延 / 并行加速比。

对照实验设计（控制变量）：四个配置共享同一 system prompt 与工具集，
只切换"执行器"——并行或串行执行工具调用、有无 delegate 编排、有无审查循环。
因此配置间的差异可归因于执行策略，而不是提示词或工具差异。
"""
import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from mini_agents import Agent, LLM, TraceLogger
from mini_agents.delegation import build_delegate_tool
from mini_agents.i18n import init_from_env, t
from mini_agents.mcp_client import McpStdioClient
from mini_agents.tools import calculator

from .tasks import TASKS

SERVER = Path(__file__).parent.parent / "examples" / "mcp_fileserver.py"

# 四个配置共享的提示词（控制变量的关键：提示词不随配置变化）
BASE_PROMPT = ("你是一个严谨的任务执行者，优先用提供的工具完成任务，不要编造结果；"
               "无需工具的常识问题直接准确回答。若多个工具调用相互独立，"
               "尽量在同一条消息中一次性发出。完成后用一句话给出任务要求的最终结果。")
ORCH_PROMPT = BASE_PROMPT + (" 你可以把相互独立的子任务通过 delegate 工具派给子 Agent，"
                             "多个独立的 delegate 调用应放在同一条消息里并行执行。")
REVIEWER_PROMPT = ('你是苛刻的审查员。对照任务要求检查回答是否完整、正确。'
                   '只输出 JSON：{"verdict": "pass 或 revise", "issues": ["问题"]}，'
                   'issues 为空当且仅当 pass。')

CONFIGS = {
    "single":              dict(parallel=False, delegate=False, review=False),
    "single-parallel":     dict(parallel=True,  delegate=False, review=False),
    "orchestrated":        dict(parallel=True,  delegate=True,  review=False),
    "orchestrated-review": dict(parallel=True,  delegate=True,  review=True),
}


class OfflineLLM:
    """离线自检用假模型：第一次调用直接执行任务的正确行为（task.solve），
    之后一律返回 pass。它验证的是评测管线与判分逻辑，不代表任何模型能力。"""

    def __init__(self, trace, solve=None):
        self.trace = trace
        self.solve = solve
        self.sandbox = None
        self.calls = 0

    async def chat(self, messages, tools=None, agent="?"):
        self.calls += 1
        self.trace.add_usage(agent, 0, 0)
        self.trace.log(agent, "llm_response", content="(offline)", tool_calls=[])
        if self.calls == 1 and self.solve:
            return SimpleNamespace(content=self.solve(self.sandbox), tool_calls=None)
        return SimpleNamespace(content='{"verdict": "pass", "issues": []}', tool_calls=None)


@dataclass
class TaskResult:
    config: str
    task_id: str
    category: str
    repeat: int
    success: bool
    detail: str
    seconds: float
    tokens: int
    requests: int
    tool_calls: int
    multi_call_turns: int
    model: str


def _trace_stats(path: Path):
    if not path.exists():
        return 0, 0
    tool_calls = multi = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "tool_call":
            tool_calls += 1
        elif e.get("type") == "llm_response" and len(e.get("tool_calls") or []) >= 2:
            multi += 1
    return tool_calls, multi


def _usage_total(trace):
    usage = trace.usage
    return (sum(u["prompt_tokens"] + u["completion_tokens"] for u in usage.values()),
            sum(u["requests"] for u in usage.values()))


def parse_review(raw):
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            return (str(data.get("verdict", "revise")).lower() == "pass",
                    list(data.get("issues", [])))
        except json.JSONDecodeError:
            pass
    return False, [f"审查输出不可解析：{raw[:100]}"]


async def run_task(config, task, repeat, llm_maker, out_dir, model_name,
                   framework="mini-agents"):
    cfg = CONFIGS[config]
    sandbox = Path(tempfile.mkdtemp(prefix=f"eval_{task.id}_"))
    if task.prepare:
        task.prepare(sandbox)
    trace = TraceLogger(out_dir / f"{config}--{task.id}--r{repeat}.trace.jsonl", echo=False)
    t0 = time.perf_counter()
    try:
        async with McpStdioClient([sys.executable, str(SERVER), str(sandbox)],
                                  trace=trace) as client:
            tools = [calculator, *await client.as_tools()]
            if framework == "langgraph":
                from .langgraph_adapter import (LangGraphAgent, make_delegate_tool,
                                                to_langchain_tool)
                lc_tools = [to_langchain_tool(t) for t in tools]
                if cfg["delegate"]:
                    agent = LangGraphAgent(
                        "Orchestrator", ORCH_PROMPT, lc_tools, trace,
                        delegate_tool=make_delegate_tool(lc_tools, BASE_PROMPT, trace))
                else:
                    agent = LangGraphAgent("Solver", BASE_PROMPT, lc_tools, trace)
            elif framework == "agents-sdk":
                from .agents_sdk_adapter import (AgentsSDKAgent, make_agent,
                                                 make_delegate_tool, to_function_tool)
                sdk_tools = [to_function_tool(t, trace) for t in tools]
                if cfg["delegate"]:
                    sdk_agent = make_agent(
                        "Orchestrator", ORCH_PROMPT, sdk_tools, trace,
                        delegate_tool=make_delegate_tool(sdk_tools, BASE_PROMPT, trace))
                else:
                    sdk_agent = make_agent("Solver", BASE_PROMPT, sdk_tools, trace)
                agent = AgentsSDKAgent("Orchestrator" if cfg["delegate"] else "Solver",
                                       sdk_agent, trace)
            else:
                llm = llm_maker(trace, task, sandbox)
                if cfg["delegate"]:
                    all_tools = [*tools,
                                 build_delegate_tool(llm, BASE_PROMPT, tools, trace)]
                    agent = Agent("Orchestrator", ORCH_PROMPT, all_tools, llm,
                                  parallel_tool_calls=cfg["parallel"])
                else:
                    agent = Agent("Solver", BASE_PROMPT, tools, llm,
                                  parallel_tool_calls=cfg["parallel"])
            answer = await agent.run(task.prompt)

            if cfg["review"]:
                if framework == "langgraph":
                    reviewer = LangGraphAgent("Reviewer", REVIEWER_PROMPT, [], trace)
                elif framework == "agents-sdk":
                    reviewer = AgentsSDKAgent(
                        "Reviewer",
                        make_agent("Reviewer", REVIEWER_PROMPT, [], trace), trace)
                else:
                    reviewer = Agent("Reviewer", REVIEWER_PROMPT, [],
                                     llm_maker(trace, task, sandbox, role="reviewer"))
                for _round in (1, 2):
                    ok, issues = parse_review(await reviewer.run(
                        "请审查：", context=f"任务：{task.prompt}\n\n回答：{answer}"))
                    if ok:
                        break
                    answer = await agent.run(
                        "审查员打回了你的回答，请修正后重新给出最终答案：\n- "
                        + "\n- ".join(issues))
    except Exception as exc:
        seconds = time.perf_counter() - t0
        tokens, requests = _usage_total(trace)
        tc, mc = _trace_stats(trace.path)
        return TaskResult(config, task.id, task.category, repeat, False,
                          f"运行异常：{exc}", seconds, tokens, requests, tc, mc,
                          model_name)

    seconds = time.perf_counter() - t0
    tokens, requests = _usage_total(trace)
    tc, mc = _trace_stats(trace.path)
    ok, detail = task.verify(SimpleNamespace(answer=answer, sandbox=sandbox))
    return TaskResult(config, task.id, task.category, repeat, ok, detail,
                      seconds, tokens, requests, tc, mc, model_name)


def _aggregate(results, config):
    rs = [r for r in results if r.config == config]
    n = len(rs)
    if not n:
        return None
    return {
        "n": n,
        "success": sum(r.success for r in rs),
        "avg_seconds": sum(r.seconds for r in rs) / n,
        "avg_tokens": sum(r.tokens for r in rs) / n,
        "avg_requests": sum(r.requests for r in rs) / n,
        "multi_call_turns": sum(r.multi_call_turns for r in rs),
    }


def _speedup(results):
    """在真正出现过"同回合多工具调用"的任务上，比较串行 vs 并行的平均耗时。"""
    parallel_by_task = {r.task_id: r for r in results
                        if r.config == "single-parallel"}
    hot = [t for t, r in parallel_by_task.items() if r.multi_call_turns > 0]
    if not hot:
        return None
    def avg(cfg, ids):
        rs = [r for r in results if r.config == cfg and r.task_id in ids]
        return sum(r.seconds for r in rs) / len(rs) if rs else 0.0
    return {"tasks": hot, "serial": avg("single", hot),
            "parallel": avg("single-parallel", hot)}


def write_chart(out_dir: Path, results, configs, framework="mini-agents"):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("（未安装 matplotlib，跳过图表生成）")
        return
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    agg = [(c, _aggregate(results, c)) for c in configs]
    agg = [(c, a) for c, a in agg if a]
    names = [c for c, _ in agg]
    metrics = [("任务成功率", [a["success"] / a["n"] for _, a in agg], ""),
               ("平均 tokens", [a["avg_tokens"] for _, a in agg], ""),
               ("平均耗时 (s)", [a["avg_seconds"] for _, a in agg], "")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for ax, (title, values, _) in zip(axes, metrics):
        ax.bar(names, values, color="#4c72b0")
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=20)
    fig.suptitle(f"{framework} 编排策略对比", y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "chart.png", dpi=120, bbox_inches="tight")


def write_report(out_dir: Path, results, configs, model_name, repeats, offline, tasks,
                 framework="mini-agents"):
    counts = {}
    for task in tasks:
        counts[task.category] = counts.get(task.category, 0) + 1
    breakdown = " / ".join(f"{k} {n}" for k, n in sorted(counts.items()))
    lines = [t("r.report_title"), "",
             t("r.time", time=f"{datetime.now():%Y-%m-%d %H:%M}"),
             t("r.framework", framework=framework),
             t("r.model", model=model_name)
             + (t("r.offline_note") if offline else ""),
             t("r.task_count", n=len(tasks), breakdown=breakdown, repeats=repeats),
             t("r.configs", configs="、".join(configs)), "",
             t("r.cfg_summary"), "", t("r.cfg_cols"),
             "|---|---|---|---|---|---|---|"]
    for c in configs:
        a = _aggregate(results, c)
        if not a:
            continue
        lines.append(t("r.cfg_row", config=c, success=a["success"], total=a["n"],
                       rate=a["success"] / a["n"], seconds=a["avg_seconds"],
                       tokens=a["avg_tokens"], requests=a["avg_requests"],
                       multi=a["multi_call_turns"]))

    lines += ["", t("r.matrix_title"), ""]
    lines.append(t("r.matrix_cols", configs=" | ".join(configs)))
    lines.append("|" + "---|" * (len(configs) + 2))
    for task in tasks:
        cells = []
        for c in configs:
            rs = [r for r in results if r.config == c and r.task_id == task.id]
            if not rs:
                cells.append("-")
            elif repeats == 1:
                cells.append("✓" if rs[0].success else "✗")
            else:
                cells.append(f"{sum(r.success for r in rs)}/{len(rs)}")
        lines.append(f"| {task.id} | {task.category} | " + " | ".join(cells) + " |")

    sp = _speedup(results)
    lines += ["", t("r.speedup_title"), ""]
    if sp:
        gain = sp["serial"] / sp["parallel"] if sp["parallel"] else float("inf")
        lines += [t("r.speedup_on", n=len(sp["tasks"])),
                  t("r.speedup_pair", serial=sp["serial"], parallel=sp["parallel"],
                    gain=gain)]
    elif "single-parallel" not in configs:
        lines.append(t("r.speedup_no_config"))
    else:
        lines.append(t("r.speedup_no_events"))

    failures = [r for r in results if not r.success]
    lines += ["", t("r.failures_title"), ""]
    if failures:
        for r in failures:
            lines.append(t("r.fail_line", config=r.config, task=r.task_id,
                           repeat=r.repeat, detail=r.detail))
    else:
        lines.append(t("r.no_failures"))

    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def amain(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    init_from_env()
    args = parse_args(argv)
    configs = (args.configs.split(",") if args.configs else list(CONFIGS))
    for c in configs:
        if c not in CONFIGS:
            sys.exit(t("r.unknown_config", config=c, choices=", ".join(CONFIGS)))

    stamp = datetime.now().strftime("%m%d-%H%M%S")
    suffix = ("-offline" if args.offline else ""
              ) + ("" if args.framework == "mini-agents" else f"-{args.framework}")
    out_dir = Path("evals/results") / (stamp + suffix)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.offline:
        model_name = "offline-selfcheck"

        def llm_maker(trace, task, sandbox, role="solver"):
            # reviewer 不能带 solve 脚本：否则它的首轮回复不是审查结论，
            # 会错误触发"打回重写"分支
            llm = OfflineLLM(trace, task.solve if role == "solver" else None)
            llm.sandbox = sandbox
            return llm
    else:
        def llm_maker(trace, task, sandbox, role="solver"):
            return LLM(trace=trace)
        LLM(trace=None)  # 触发 .env 加载，使报告里的模型名反映 .env 的真实配置
        model_name = os.getenv("LLM_MODEL", "未知")

    tasks = TASKS if not args.limit else TASKS[: args.limit]
    print(t("r.eval_start", framework=args.framework,
            configs=",".join(configs), repeats=args.repeats,
            tasks=len(tasks), model=model_name, dir=out_dir))
    results = []
    for config in configs:
        for task in tasks:
            for repeat in range(1, args.repeats + 1):
                res = await run_task(config, task, repeat, llm_maker, out_dir,
                                     model_name, args.framework)
                results.append(res)
                mark = "✓" if res.success else "✗"
                line = t("r.task_line", config=config, task=task.id, mark=mark,
                         seconds=res.seconds, tokens=res.tokens)
                if not res.success:
                    line += t("r.task_fail_suffix", detail=res.detail)
                print(line, flush=True)

    (out_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in results) + "\n",
        encoding="utf-8")
    write_report(out_dir, results, configs, model_name, args.repeats, args.offline,
                 tasks, args.framework)
    write_chart(out_dir, results, configs, args.framework)

    print(t("r.summary"))
    for c in configs:
        a = _aggregate(results, c)
        if a:
            print(t("r.summary_line", config=c, success=a["success"], n=a["n"],
                    seconds=a["avg_seconds"], tokens=a["avg_tokens"]))
    print(t("r.out_report", path=out_dir / "report.md"))
    print(t("r.out_data", path=out_dir / "results.jsonl"))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=t("r.help_description"))
    parser.add_argument("--offline", action="store_true",
                        help=t("r.help_offline"))
    parser.add_argument("--configs", default=None,
                        help=t("r.help_configs", choices=", ".join(CONFIGS)))
    parser.add_argument("--repeats", type=int, default=1,
                        help=t("r.help_repeats"))
    parser.add_argument("--limit", type=int, default=None,
                        help=t("r.help_limit"))
    parser.add_argument("--framework", default="mini-agents",
                        choices=["mini-agents", "langgraph", "agents-sdk"],
                        help=t("r.help_framework"))
    return parser.parse_args(argv)
