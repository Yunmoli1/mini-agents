"""深度调研小组 —— 覆盖四大核心机制的最小多 Agent demo：

    阶段1  Planner   拆解任务，并用"并发工具调用"同时派出多名调研员（拆解 + 并行）
    阶段2  Writer    读黑板上的调研发现，汇总成报告初稿（共享黑板）
    阶段3  Reviewer  审查初稿，不通过就打回重写（批评循环，最多 MAX_REVISIONS 轮）

运行方式：
    命令行：  python demo_research_team.py "你想调研的问题"
    断点恢复：python demo_research_team.py --resume runs/<时间戳>   （v1.2）
    网页版：  streamlit run app.py   （实时观看协作过程）
产出：  runs/<时间戳>/ 下的 report.md、blackboard.json、trace.jsonl
回放：  python view_trace.py runs/<时间戳>/trace.jsonl

v1.2 断点恢复：每个阶段完成即把黑板落盘（checkpoint）；流水线按黑板进度幂等
续跑——已完成的阶段直接跳过，崩溃只损失当前阶段（test_checkpoint.py 有零成本
验证）。
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from mini_agents import Agent, Blackboard, LLM, TraceLogger
from mini_agents.i18n import init_from_env, t
from mini_agents.tools import tool, web_search

MAX_REVISIONS = 2  # 审查打回重写的上限，防止"写↔审"循环停不下来


def build_research_tool(board, llm):
    """构造 research 工具：每次被调用，就现场创建一名全新的调研员 Agent。

    注意两点：
    - 每名调研员都是新 Agent 实例、全新对话 → 上下文互相隔离，互不污染
    - Planner 在同一条消息里调用多次 research 时，它们会真正并发执行
    """
    counter = {"done": 0}

    @tool(description="派出一名调研员去调研一个子问题，返回要点式调研发现。"
                     "请在同一条消息里多次调用本工具以并行调研。")
    async def research(sub_question: str) -> str:
        i = counter["done"] + 1
        counter["done"] = i  # 先占号再 await，保证并发调用时编号不重复
        researcher = Agent(
            name=f"Researcher-{i}",
            system_prompt=("你是一名严谨的调研员。围绕给定子问题，用 web_search 搜索 2~3 次"
                           "（第一次结果不理想就换关键词），然后输出要点式调研发现，"
                           "每条要点尽量附来源链接。只做调研，不写长文。"),
            tools=[web_search],
            llm=llm,
            fail_fast_turns=3,  # 搜索服务持续限流时止损，别烧满 15 轮（DECISIONS #21）
        )
        finding = await researcher.run(f"请调研这个子问题：{sub_question}")
        board.write(f"finding_{i}", {"sub_question": sub_question, "finding": finding})
        return finding

    return research


def parse_review(raw):
    """从审查员回复里提取 JSON 结论；解析失败也按"打回"处理（轮数有上限，不怕循环）。"""
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            verdict = str(data.get("verdict", "revise")).lower()
            return ("pass", []) if verdict == "pass" else ("revise", list(data.get("issues", [])))
        except (json.JSONDecodeError, AttributeError):
            pass
    return "revise", [f"审查输出无法解析为 JSON，原始输出：{raw[:200]}"]


async def research_pipeline(topic, trace, max_revisions=MAX_REVISIONS,
                            board=None, run_dir=None, llm=None,
                            researcher_llm=None):
    """跑完整条"调研小组"流水线，返回 SimpleNamespace(report=报告文本, board=黑板)。

    命令行 demo 与 Streamlit 网页版共用这一条路径（单一事实源）。
    LLM 未配置时抛 RuntimeError，由调用方决定如何呈现；llm 参数供离线测试注入。

    v1.2 断点恢复：传入恢复的 board 即幂等续跑——黑板上已完成的阶段
    （planner_summary / draft_v1 / review_round_N / draft_vN）直接跳过；
    每完成一个阶段调用 checkpoint() 落盘。阶段内崩溃则该阶段整体重跑
    （阶段级粒度：够用、可讲清，步级恢复留给生产级实现）。

    v1.2 多模型成本路由：researcher_llm 可单独指定调研员的模型——调研员是
    token 大头，路由到便宜模型、规划与写审保留强模型（见 demo_cost_routing.py）。
    """
    board = board if board is not None else Blackboard(trace)
    if board.read("task") is None:
        board.write("task", topic)
    llm = llm or LLM(trace=trace)
    researcher_llm = researcher_llm or llm

    def checkpoint():
        if run_dir is not None:
            board.save(Path(run_dir) / "blackboard.json")

    # ── 阶段 1：Planner 拆解 + 并行派活（已有产出则跳过）────────────
    if board.read("planner_summary") is None:
        trace.log("driver", "stage", title=t("dt.stage_task", topic=topic))
        planner = Agent(
            name="Planner",
            system_prompt=("你是调研项目负责人。把总任务拆成 2~4 个互相独立、合起来能覆盖全面的子问题，"
                           "然后在同一条消息里调用多次 research 工具并行派活，"
                           "最后用三五句话向驱动方汇报收到的发现。"),
            tools=[build_research_tool(board, researcher_llm)],
            llm=llm,
        )
        board.write("planner_summary", await planner.run(f"总任务：{topic}"))
        checkpoint()
    else:
        trace.log("driver", "stage", title=t("dt.stage_skip_planner"))

    # ── 阶段 2：Writer 读黑板，汇总成稿（已有初稿则跳过）────────────
    writer = Agent(
        name="Writer",
        system_prompt=("你是报告撰写人。只依据黑板上「调研发现」部分的内容写一份中文 Markdown 报告："
                       "带小标题和要点，重要结论附来源链接，600~1200 字。"
                       "不得编造调研发现里没有的信息；发现之间有矛盾就如实指出。"),
        tools=[],
        llm=llm,
    )
    if board.read("draft_v1") is None:
        trace.log("driver", "stage", title=t("dt.stage_writer"))
        board.write("draft_v1",
                    await writer.run("请根据黑板上的任务和调研发现，撰写报告。",
                                     context=board.as_markdown()))
        checkpoint()
    else:
        trace.log("driver", "stage", title=t("dt.stage_skip_writer"))
    report = board.read("draft_v1")

    # ── 阶段 3：Reviewer 审查 ⇄ Writer 修订（按黑板进度续跑的批评循环）──
    reviewer = Agent(
        name="Reviewer",
        system_prompt=("你是苛刻的事实审查员。对照黑板上的总任务和调研发现检查报告："
                       "是否跑题、结构是否完整、有无与调研发现矛盾或无中生有的内容。"
                       '只输出一个 JSON 对象，格式：{"verdict": "pass 或 revise", "issues": ["问题1", "问题2"]}。'
                       " issues 为空当且仅当 verdict 为 pass。"),
        tools=[],
        llm=llm,
    )
    round_no = 1
    while round_no <= max_revisions:
        review = board.read(f"review_round_{round_no}")
        if review is None:
            trace.log("driver", "stage", title=t("dt.stage_review", round=round_no))
            raw = await reviewer.run("请审查当前报告：",
                                     context=f"总任务：{topic}\n\n报告全文：\n{report}\n\n{board.as_markdown()}")
            verdict, issues = parse_review(raw)
            review = {"verdict": verdict, "issues": issues}
            board.write(f"review_round_{round_no}", review)
            checkpoint()
        if review["verdict"] == "pass":
            trace.log("driver", "stage", title=t("dt.stage_pass"))
            return SimpleNamespace(report=report, board=board)
        trace.log("driver", "stage", title=t("dt.stage_revise", n=len(review["issues"])))
        next_key = f"draft_v{round_no + 1}"
        revised = board.read(next_key)
        if revised is None:
            report = await writer.run("审查员打回了报告，请逐条修订下面的问题，输出完整新版报告：\n- "
                                      + "\n- ".join(review["issues"]),
                                      context=board.as_markdown())
            board.write(next_key, report)
            checkpoint()
        else:
            report = revised
            trace.log("driver", "stage", title=t("dt.stage_skip_revision", key=next_key))
        round_no += 1
    trace.log("driver", "stage", title=t("dt.stage_max", n=max_revisions))
    return SimpleNamespace(report=report, board=board)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    init_from_env()

    parser = argparse.ArgumentParser(description=t("dt.description"))
    parser.add_argument("topic", nargs="*", default=[], help=t("dt.help_topic"))
    parser.add_argument("--resume", metavar="RUN_DIR",
                        help=t("dt.help_resume"))
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if args.resume:
        run_dir = Path(args.resume)
        board = Blackboard.load(run_dir / "blackboard.json", trace=None)
        topic = board.read("task")
        # trace 追加写：恢复后的记录接在原日志后面，回放可看完整历史
        trace = TraceLogger(run_dir / "trace.jsonl")
        print(t("dt.resumed", dir=run_dir))
    else:
        topic = " ".join(args.topic).strip() or "2026 年主流开源多 Agent 框架的选型对比与发展趋势"
        run_dir = Path("runs") / datetime.now().strftime("%m%d-%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        board = None
        trace = TraceLogger(run_dir / "trace.jsonl")

    try:
        result = asyncio.run(research_pipeline(topic, trace,
                                               board=board, run_dir=run_dir))
    except RuntimeError as e:
        print(e)
        return

    (run_dir / "report.md").write_text(result.report, encoding="utf-8")
    result.board.save(run_dir / "blackboard.json")
    trace.print_usage_report()
    print(t("dt.done_report", path=run_dir / "report.md"))
    print(t("dt.done_blackboard", path=run_dir / "blackboard.json"))
    print(t("dt.done_trace", path=run_dir / "trace.jsonl"))


if __name__ == "__main__":
    main()
