"""MCP 离线测试：不花一分钱、不联网，走完整个 MCP 协议面。

覆盖：initialize 握手与版本协商 → 工具发现 → 工具调用（含中文读写、目录创建）→
沙箱越界拦截 → 未知工具错误透传 → McpTool 包装后与 Agent 循环集成。

    python test_mcp.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from mini_agents import Agent, TraceLogger
from mini_agents.mcp_client import McpStdioClient

SERVER = Path(__file__).parent / "examples" / "mcp_fileserver.py"


class FakeLLM:
    """第一次回复请求调用 MCP 工具 fs_read_file，第二次返回最终总结。"""

    def __init__(self, trace):
        self.trace = trace
        self.calls = 0

    async def chat(self, messages, tools=None, agent="?"):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(id="c1", function=SimpleNamespace(
                    name="fs_read_file",
                    arguments=json.dumps({"path": "notes.md"})))],
            )
        # 第二次调用时历史应为：system + user + assistant(工具调用) + tool 结果
        assert len(messages) == 4, f"消息协议不对：{[m['role'] for m in messages]}"
        return SimpleNamespace(
            content="周报要点：MCP 客户端已完成；下一步做 RAG 工具。",
            tool_calls=None)


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = Path(tempfile.mkdtemp(prefix="mini_mcp_"))
    (root / "notes.md").write_text("# 项目周报\n- 完成了 MCP 客户端\n- 下一步做 RAG 工具",
                                   encoding="utf-8")

    trace = TraceLogger("runs/mcp-test/trace.jsonl")
    client = McpStdioClient([sys.executable, str(SERVER), str(root)], trace=trace)
    await client.connect()

    # 1. 握手与元信息
    assert client.server_info["name"] == "mini-fs", client.server_info
    assert client.negotiated_version in ("2024-11-05", "2025-03-26", "2025-06-18")

    # 2. 工具发现 + 包装
    tools = await client.as_tools(prefix="fs")
    names = {t.name for t in tools}
    assert {"fs_list_dir", "fs_read_file", "fs_write_file"} <= names, names
    assert all(t.parameters.get("type") == "object" for t in tools)

    # 3. 工具调用：写（自动建父目录）→ 读回 → 列目录，含中文
    out = await client.call_tool("write_file",
                                 {"path": "out/a.txt", "content": "hello 中文"})
    assert "written" in out, out
    back = await client.call_tool("read_file", {"path": "out/a.txt"})
    assert back.strip() == "hello 中文", repr(back)
    listing = await client.call_tool("list_dir", {})
    assert "notes.md" in listing and "out" in listing, listing

    # 4. 错误通道：沙箱越界 / 未知工具，都应经 isError 透传而不是崩溃
    escape = await client.call_tool("read_file", {"path": "../escaped.txt"})
    assert escape.startswith("[MCP 工具报告出错]"), escape
    unknown = await client.call_tool("no_such_tool", {})
    assert unknown.startswith("[MCP 工具报告出错]"), unknown

    # 5. Agent 集成：McpTool 与本地工具在 agent 循环里行为完全一致
    agent = Agent(name="McpAgent", system_prompt="测试", tools=tools,
                  llm=FakeLLM(trace))
    answer = await agent.run("读取 notes.md 并总结")
    assert "RAG" in answer, answer

    await client.close()
    print("✓ 握手与版本协商正常")
    print(f"✓ 工具发现与包装正常（{sorted(names)}）")
    print("✓ 工具调用正常：写（自动建父目录）/ 读回 / 列目录，中文无乱码")
    print("✓ 错误通道正常：沙箱越界与未知工具均以 isError 透传")
    print("✓ Agent 集成正常：McpTool 在 agent 循环中与本地工具行为一致")
    print("\nMCP 离线测试全部通过 ✔")


if __name__ == "__main__":
    asyncio.run(main())
