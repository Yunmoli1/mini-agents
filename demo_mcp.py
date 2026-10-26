"""demo：Agent 通过手写 MCP 客户端操作一个文件沙箱（需 .env 中的 API Key）。

运行：python demo_mcp.py
内容：启动参考 MCP server（examples/mcp_fileserver.py），Agent 只靠 MCP 工具
完成"盘点沙箱文件 → 逐个读取 → 汇总写入 summary.md"的任务。
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from mini_agents import Agent, LLM, TraceLogger
from mini_agents.i18n import init_from_env, t
from mini_agents.mcp_client import McpStdioClient

SERVER = Path(__file__).parent / "examples" / "mcp_fileserver.py"

SEEDS = {
    "notes/meeting.md": "# 周会纪要\n- 多 Agent 框架通过离线测试\n- 本周接入 MCP 协议",
    "notes/todo.md": "- [x] 并行工具调用\n- [ ] RAG 工具\n- [ ] 评测 harness",
    "readme.txt": "这是一个 MCP 文件沙箱演示目录，里面是某项目的零散笔记。",
}


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    init_from_env()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    run_dir = Path("runs") / datetime.now().strftime("mcp-%m%d-%H%M%S")
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    for rel, content in SEEDS.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    trace = TraceLogger(run_dir / "trace.jsonl")
    try:
        llm = LLM(trace=trace)
    except RuntimeError as e:
        print(e)
        return

    async with McpStdioClient([sys.executable, str(SERVER), str(workspace)],
                              trace=trace) as client:
        trace.log("driver", "stage",
                  title=t("dm.ready", name=client.server_info.get("name"),
                          dir=workspace))
        tools = await client.as_tools()
        agent = Agent(
            name="FileAgent",
            system_prompt=("你是文件管理员。你的所有工具都来自一个 MCP 文件服务器。"
                           "流程：先 list_dir 盘点目录结构，再逐个读取所有文本文件，"
                           "最后把要点汇总成一篇 summary.md 写回沙箱根目录。全程用中文。"),
            tools=tools,
            llm=llm,
        )
        answer = await agent.run(
            f"请盘点并汇总当前沙箱（沙箱根目录即你的工作根目录，一律用相对路径）中的文件。")

    trace.log("driver", "stage", title=t("dm.done"))
    summary = workspace / "summary.md"
    trace.print_usage_report()
    print(t("dm.answer", answer=answer[:500]))
    print(t("dm.summary", path=summary,
            state=t("dm.generated") if summary.exists() else t("dm.missing")))
    print(t("dm.trace_line", path=trace.path))


if __name__ == "__main__":
    asyncio.run(main())
