"""助手对话引擎离线测试：普通聊天 / 文档问答 / 历史裁剪 / .env 写回，零 API 成本。

    python test_assistant.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from mini_agents.agent import Agent
from mini_agents.assistant import (MAX_HISTORY_MESSAGES, build_chat_agent,
                                   chat_reply, format_history)
from mini_agents.envtools import update_env_file
from mini_agents.rag import KnowledgeBase
from mini_agents.tracing import TraceLogger

_DOCS = {"产品说明.txt": "mini-agents 是一个从零手写的多 Agent 框架。\n\n"
                        "它支持断点恢复与成本路由。\n\n"
                        "评测体系覆盖数学、知识与文件操作三类任务。",
         "架构笔记.txt": "Agent 循环负责请求与工具执行的往返。\n\n"
                        "黑板是多 Agent 之间的共享状态容器。",}


class ScriptedLLM:
    """按剧本出牌：依序弹出回复，并记录每次收到的 messages。"""

    def __init__(self, script, trace):
        self.script = list(script)
        self.trace = trace
        self.seen_messages = []

    async def chat(self, messages, tools=None, agent="?"):
        self.seen_messages.append(messages)
        return self.script.pop(0)


def tool_msg(name, arguments):
    return SimpleNamespace(
        content=None, tool_calls=[SimpleNamespace(
            id="c0", type="function",
            function=SimpleNamespace(name=name, arguments=arguments))])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    trace = TraceLogger(Path(tempfile.mkdtemp(prefix="mini_chat_")) / "t.jsonl",
                        echo=False)

    # 1. 普通对话：无工具，一次调用直接返回
    llm = ScriptedLLM([SimpleNamespace(content="你好，我是助手。", tool_calls=None)], trace)
    reply = asyncio.run(chat_reply("你好", llm))
    assert reply == "你好，我是助手。", reply
    assert llm.seen_messages[0][0]["role"] == "system"

    # 2. 多轮历史：format_history 只保留最近 N 条，且作为 context 注入
    history = [{"role": "user", "content": f"旧消息{i}"} for i in range(20)]
    trimmed = format_history(history)
    assert trimmed.count("用户：") == MAX_HISTORY_MESSAGES
    assert "旧消息19" in trimmed and "旧消息0" not in trimmed
    llm2 = ScriptedLLM([SimpleNamespace(content="记得。", tool_calls=None)], trace)
    asyncio.run(chat_reply("继续", llm2, history=history))
    assert "旧消息19" in llm2.seen_messages[0][1]["content"], "历史没有注入 user 消息"

    # 3. 文档问答：Agent 先调 knowledge_search 检索，再依据片段回答
    root = Path(tempfile.mkdtemp(prefix="mini_chat_kb_"))
    for name, text in _DOCS.items():
        (root / name).write_text(text, encoding="utf-8")
    kb = KnowledgeBase()
    kb.ingest(root)
    assert kb.sources() == ["产品说明.txt", "架构笔记.txt"]
    llm3 = ScriptedLLM([
        tool_msg("knowledge_search", '{"query": "支持什么功能"}'),
        SimpleNamespace(content="按文档：支持断点恢复与成本路由 [来源 产品说明.txt#p2]。",
                        tool_calls=None),
    ], trace)
    reply3 = asyncio.run(chat_reply("它支持哪些功能？", llm3, kb=kb))
    assert "断点恢复" in reply3, reply3
    tool_message = llm3.seen_messages[1][-1]  # 第二轮对话最后一条 = 工具结果
    assert tool_message["role"] == "tool" and "产品说明.txt" in tool_message["content"], \
        "检索结果（带来源）没有回填给模型"

    # 4. build_chat_agent：有无知识库决定工具与提示词
    assert len(build_chat_agent(llm=None).tools) == 0
    assert list(build_chat_agent(llm=None, kb=kb).tools) == ["knowledge_search"]

    # 5. .env 写回：替换已有键、跳过空值、保留注释与顺序、新键追加
    env = Path(tempfile.mkdtemp(prefix="mini_env_")) / ".env"
    env.write_text("# 注释要保留\nLLM_API_KEY=old-key\nLLM_MODEL=glm-4-flash\n\nLLM_BASE_URL=https://a\n",
                   encoding="utf-8")
    written = update_env_file(env, {"LLM_MODEL": "deepseek-chat",
                                    "LLM_API_KEY": "", "MINI_LANG": "zh"})
    assert written == ["LLM_MODEL", "MINI_LANG"], written  # 空值不写
    text = env.read_text(encoding="utf-8")
    assert text == ("# 注释要保留\nLLM_API_KEY=old-key\nLLM_MODEL=deepseek-chat\n\n"
                    "LLM_BASE_URL=https://a\nMINI_LANG=zh\n"), repr(text)

    print("✓ 普通对话：无工具单次调用直返；历史压缩为 context 注入")
    print("✓ 历史裁剪：只保留最近 12 条，旧消息不占 token")
    print("✓ 文档问答：先检索后回答，带来源的片段回填进模型上下文")
    print("✓ 有无知识库自动切换工具与提示词")
    print("✓ .env 写回：替换/跳过空值/保注释/追加，全部正确")
    print("\n助手对话引擎离线测试全部通过 ✔")


if __name__ == "__main__":
    main()
