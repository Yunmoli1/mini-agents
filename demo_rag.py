"""RAG demo（v1.2 / 原 M2）：BM25 本地知识库 + knowledge_search 工具。

    python demo_rag.py "你的问题"

流程：播种一个示例知识库（3 个 md 文件）→ BM25 建索引 → Agent 挂
knowledge_search 工具回答问题（回答必须基于检索结果）。检索本身零 API 成本，
已在 test_rag.py 离线验证命中正确性。
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from mini_agents import Agent, LLM, TraceLogger
from mini_agents.rag import KnowledgeBase, make_knowledge_tool

SEEDS = {
    "framework.md": ("# mini-agents 框架笔记\n\n"
                     "框架核心约 700 行 Python，不依赖任何 agent 框架，只用 openai SDK 发请求。\n\n"
                     "Agent 自主循环：请求模型 → 执行工具 → 回填结果 → 再请求，直到模型不再要工具。\n\n"
                     "并行调度：模型在一条消息里发出的多个工具调用由 asyncio.gather 并发执行。\n\n"
                     "共享黑板：Agent 之间用结构化数据交换产出，不闲聊；黑板同时充当检查点容器。\n"),
    "evals.md": ("# 评测体系笔记\n\n"
                 "评测 harness 包含 18 个任务，判分全部程序化：数学对数字、文件产物精确比对、"
                 "知识题判关键词。\n\n"
                 "四个配置共享同一提示词与工具集，只切换执行器：串行、并行、编排、编排加审查。\n\n"
                 "跨框架对比结论：编排 token 开销 mini-agents +6%，LangGraph +32%，"
                 "Agents SDK +42%。\n"),
    "routing.md": ("# 成本路由笔记\n\n"
                   "多模型成本路由：调研员是流水线的 token 大头，路由到便宜模型，"
                   "规划与写作保留强模型。\n\n"
                   "429 长退避序列是 15/30/60/120 秒，实战中 95 次退避把任务完成率"
                   "从 11% 拉回 96%。\n"),
}


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    run_dir = Path("runs") / datetime.now().strftime("rag-%m%d-%H%M%S")
    knowledge_dir = run_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    for name, text in SEEDS.items():
        (knowledge_dir / name).write_text(text, encoding="utf-8")

    kb = KnowledgeBase()
    n_chunks = kb.ingest(knowledge_dir)
    trace = TraceLogger(run_dir / "trace.jsonl")

    try:
        llm = LLM(trace=trace)
    except RuntimeError as e:
        print(e)
        return

    print(f"知识库就绪：{len(SEEDS)} 个文件 → {n_chunks} 块（BM25 索引，纯本地）")
    question = " ".join(sys.argv[1:]).strip() or "这个框架的编排 token 开销比 LangGraph 好多少？"
    trace.log("driver", "stage", title=f"问题：{question}")

    agent = Agent(
        name="Librarian",
        system_prompt=("你是知识库问答助手。回答前必须先用 knowledge_search 工具检索，"
                       "只依据检索到的内容回答，并注明每条信息的来源标记。"
                       "检索不到就说检索不到，不许编造。"),
        tools=[make_knowledge_tool(kb)],
        llm=llm,
    )
    answer = await agent.run(question)

    trace.print_usage_report()
    print(f"\n问题：{question}\n\n回答：{answer}")
    print(f"\n知识库与日志：{run_dir}")


if __name__ == "__main__":
    asyncio.run(main())
