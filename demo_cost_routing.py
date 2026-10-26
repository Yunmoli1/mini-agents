"""多模型成本路由 demo（v1.2）：强模型做规划/写作/审查，便宜模型跑调研。

    python demo_cost_routing.py "调研问题"

原理：调研员是流水线的 token 大头，把路由到便宜模型、主链路保留强模型，
就能在质量敏感的环节不降级的情况下压缩成本。跑完后按角色输出 token 分布，
并用价格场景表估算"全强模型" vs "路由"两种策略的成本差。

配置（.env 可选）：
    LLM_MODEL_STRONG   主链路模型（默认取 LLM_MODEL）
    LLM_MODEL_CHEAP    调研员模型（默认取 LLM_MODEL——即不路由）
"""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from mini_agents import Agent, Blackboard, LLM, TraceLogger
from demo_research_team import build_research_tool
from mini_agents.tools import tool, web_search

MAX_REVISIONS = 2


def _price(tier: str, direction: str, default: str) -> float:
    """价格可从环境变量覆盖：PRICE_STRONG_IN / PRICE_STRONG_OUT /
    PRICE_CHEAP_IN / PRICE_CHEAP_OUT（元 / 百万 tokens）。"""
    return float(os.getenv(f"PRICE_{tier.upper()}_{direction.upper()}", default))


# 价格场景表：元 / 百万 tokens（示例假设值，可用环境变量覆盖，或按实际账单修改）
PRICE = {
    "strong": {"input": _price("strong", "in", "2.0"),
               "output": _price("strong", "out", "8.0")},
    "cheap": {"input": _price("cheap", "in", "0.2"),
              "output": _price("cheap", "out", "0.8")},
}


def cost_of(usage: dict, tier: str) -> float:
    return (usage["prompt_tokens"] / 1e6 * PRICE[tier]["input"]
            + usage["completion_tokens"] / 1e6 * PRICE[tier]["output"])


async def routed_pipeline(topic, trace, strong_llm, cheap_llm):
    """与 demo_research_team 同构的流水线，仅调研员路由到便宜模型。"""
    board = Blackboard(trace)
    board.write("task", topic)

    def checkpoint():
        pass  # 成本路由 demo 聚焦 token 分布，checkpoint 见 demo_research_team

    planner = Agent(
        name="Planner",
        system_prompt=("你是调研项目负责人。把总任务拆成 2 个互相独立的子问题，"
                       "在同一条消息里调用多次 research 工具并行派活，"
                       "最后用三五句话汇报收到的发现。"),
        tools=[build_research_tool(board, cheap_llm)],
        llm=strong_llm,
    )
    board.write("planner_summary", await planner.run(f"总任务：{topic}"))

    writer = Agent(
        name="Writer",
        system_prompt=("你是报告撰写人。只依据黑板上的调研发现写一份中文 Markdown 报告，"
                       "带小标题和要点，400~800 字。"),
        tools=[],
        llm=strong_llm,
    )
    report = await writer.run("请根据黑板上的任务和调研发现，撰写报告。",
                              context=board.as_markdown())
    board.write("draft_v1", report)
    return report


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    import os

    strong_name = os.getenv("LLM_MODEL_STRONG", os.getenv("LLM_MODEL", "glm-4-flash"))
    cheap_name = os.getenv("LLM_MODEL_CHEAP", os.getenv("LLM_MODEL", "glm-4-flash"))
    topic = " ".join(sys.argv[1:]).strip() or "轻量级 RAG 方案在本地知识库问答中的效果"

    run_dir = Path("runs") / datetime.now().strftime("cost-routing-%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    trace = TraceLogger(run_dir / "trace.jsonl")

    try:
        strong_llm = LLM(trace=trace, model=strong_name)
        cheap_llm = LLM(trace=trace, model=cheap_name)
    except RuntimeError as e:
        print(e)
        return

    print(f"路由策略：主链路 = {strong_name} ｜ 调研员 = {cheap_name}")
    report = await routed_pipeline(topic, trace, strong_llm, cheap_llm)

    # ── 成本核算：同一份 token 分布 × 两种价格策略 ────────────────────
    usage = trace.usage
    rows, cost_strong_all, cost_routed = [], 0.0, 0.0
    for name, u in usage.items():
        tier = "cheap" if name.startswith("Researcher") else "strong"
        actual = cost_of(u, tier)
        all_strong = cost_of(u, "strong")
        cost_routed += actual
        cost_strong_all += all_strong
        rows.append((name, u["requests"], u["prompt_tokens"],
                     u["completion_tokens"], tier, actual, all_strong))

    trace.print_usage_report()
    print("\n─── 成本场景对比（价格表为示例假设，按实际账单修改 PRICE）───")
    print(f"  {'角色':<14} {'tier':<7} {'实际成本':>10} {'若全强模型':>10}")
    for name, req, pt, ct, tier, actual, all_strong in rows:
        print(f"  {name:<14} {tier:<7} {actual:>10.4f} {all_strong:>10.4f}")
    print(f"  {'合计':<24} {cost_routed:>10.4f} {cost_strong_all:>10.4f}")
    if cost_strong_all > 0:
        print(f"  路由节省：{(1 - cost_routed / cost_strong_all):.0%}"
              + ("（当前 STRONG==CHEAP，未发生真实路由）" if strong_name == cheap_name else ""))

    (run_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"\n报告：{run_dir / 'report.md'} ｜ trace：{run_dir / 'trace.jsonl'}")
    print("提示：把 LLM_MODEL_CHEAP 设成更便宜的模型即可看到真实节省比例。")


if __name__ == "__main__":
    asyncio.run(main())
