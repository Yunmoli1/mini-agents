"""通用对话助手：普通聊天与文档问答共用一条 Agent 路径（网页控制台的引擎）。

设计：
- 无知识库 → 不带工具的普通对话；有知识库 → 带 knowledge_search 工具，
  回答优先依据检索结果并附 [来源 文件名#段落]，文档没有的才用自身知识并注明
- 多轮记忆：Agent.run 每次都是全新对话，历史由 format_history 压成文本
  作为 context 注入，只带最近 MAX_HISTORY_MESSAGES 条控制 token 上限
- 提示词中文冻结（DECISIONS #20 的既有口径）
"""
from .agent import Agent
from .rag import make_knowledge_tool

MAX_HISTORY_MESSAGES = 12

CHAT_PLAIN_PROMPT = ("你是 mini-agents 控制台的通用助手。回答准确、简洁，"
                     "适合列表的内容就用列表；不知道就直说，不要编造。")
CHAT_DOC_PROMPT = ("你是 mini-agents 控制台的文档助手。用户上传的文档已建成检索知识库，"
                   "你有一个 knowledge_search 工具可以检索文档片段。"
                   "回答用户问题前先用它检索（必要时换关键词多检索几次）；"
                   "依据检索结果作答，引用处标注 [来源 文件名#段落号]；"
                   "文档里没有的内容可以用你自己的知识补充，"
                   "但必须注明「以下为模型自身知识，非文档内容」。")


def format_history(history) -> str:
    """把 [{"role", "content"}] 压成文本；只保留最近 N 条。"""
    lines = []
    for m in list(history)[-MAX_HISTORY_MESSAGES:]:
        who = "用户" if m.get("role") == "user" else "助手"
        lines.append(f"{who}：{m.get('content', '')}")
    return "\n\n".join(lines)


def build_chat_agent(llm, kb=None) -> Agent:
    """有知识库给检索工具，没有就纯对话——同一个循环，两种模式。"""
    if kb:
        return Agent("助手", CHAT_DOC_PROMPT, [make_knowledge_tool(kb)], llm)
    return Agent("助手", CHAT_PLAIN_PROMPT, [], llm)


async def chat_reply(prompt, llm, kb=None, history=()) -> str:
    """一条用户消息 → 助手回复。history 是本次消息之前的对话（role/content 列表）。"""
    agent = build_chat_agent(llm, kb)
    context = ""
    if kb:
        sources = "、".join(kb.sources()) or "（无文件名）"
        context = f"用户上传的文档已入库：{sources}，共 {len(kb.chunks)} 个片段。"
    if history:
        history_text = format_history(history)
        if history_text:
            context += (("\n\n" if context else "")
                        + "以下是此前的对话记录，供衔接上下文：\n" + history_text)
    return await agent.run(prompt, context=context)
