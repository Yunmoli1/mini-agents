"""mini_agents —— 从零手写的多 Agent 协作框架（学习用）。

模块导读（建议按此顺序阅读）：
    llm.py        最底层的模型调用（薄封装，OpenAI 兼容接口通用）
    tools.py      把 Python 函数变成 Agent 可调用的工具
    agent.py      Agent 核心：请求 → 执行工具 → 再请求 的自主循环
    blackboard.py 共享黑板：Agent 之间用结构化数据交换产出，而不是闲聊
    mcp_client.py 手写的 MCP 客户端：把任意 MCP server 的工具动态接入框架
    rag.py        BM25 本地知识库 + knowledge_search 工具（v1.2）
    delegation.py delegate 工具：把"派子 Agent"变成一个普通工具（v1.2）
    tracing.py    全程 JSONL 日志 + 终端实时摘要（用 view_trace.py 可回放）
"""
from .agent import Agent
from .blackboard import Blackboard
from .llm import LLM
from .mcp_client import MCPError, McpStdioClient, McpTool
from .rag import KnowledgeBase, make_knowledge_tool
from .tracing import TraceLogger, describe_event

__all__ = ["Agent", "Blackboard", "KnowledgeBase", "LLM", "MCPError",
           "McpStdioClient", "McpTool", "TraceLogger", "describe_event",
           "make_knowledge_tool"]
