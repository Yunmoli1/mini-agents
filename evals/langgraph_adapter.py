"""LangGraph 适配器：让同一个评测 harness 以相同口径评测 LangGraph。

公平性三原则（与 mini-agents 完全一致，见 runner.py）：
- 同一份任务集与程序化判分器（evals/tasks.py，零改动）
- 同一份提示词（runner 的 BASE_PROMPT / ORCH_PROMPT / REVIEWER_PROMPT）
- 同一套工具（calculator + MCP 文件沙箱，仅做 LangChain "方言转换"）

因此配置间的差异可归因于框架实现本身：agent 循环、并行执行、编排方式。
用量统计走与 mini-agents 相同的 TraceLogger 通道，保证报告口径一致。
"""
import json
import os
from typing import Optional

from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent
from pydantic import create_model

from mini_agents.tracing import TraceLogger

_TYPE_MAP = {"string": str, "integer": int, "number": float,
             "boolean": bool, "array": list, "object": dict}


def _schema_to_pydantic(schema: dict, model_name: str):
    """把 JSON Schema 转成 pydantic 模型（LangChain 工具的 args_schema 要求）。"""
    fields = {}
    required = set(schema.get("required", []))
    for prop, spec in schema.get("properties", {}).items():
        ann = _TYPE_MAP.get(spec.get("type", "string"), str)
        fields[prop] = (ann, ...) if prop in required else (Optional[ann], None)
    return create_model(model_name, **fields)


def to_langchain_tool(tool):
    """mini_agents 的 Tool（含 MCP 远程工具）→ LangChain StructuredTool。"""
    async def _call(**kwargs):
        result = await tool.call(kwargs)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

    return StructuredTool(
        name=tool.name,
        description=tool.description or tool.name,
        args_schema=_schema_to_pydantic(tool.parameters, f"{tool.name}_args"),
        coroutine=_call,
    )


def make_model():
    from langchain_core.rate_limiters import InMemoryRateLimiter
    from langchain_openai import ChatOpenAI

    # 共享限流通道的基础设施对齐（DECISIONS.md #14）：LangGraph 侧用官方 rate_limiter
    # 主动限速（25s/请求，防并发突发 429）+ SDK 重试；mini-agents 用自研 429 长退避。
    # 两者地位等同，策略差异如实写进对比报告。
    limiter = InMemoryRateLimiter(requests_per_second=0.04, max_bucket_size=1)
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "glm-4-flash"),
        base_url=os.getenv("LLM_BASE_URL"),
        api_key=os.getenv("LLM_API_KEY"),
        timeout=600,       # 与 mini-agents 的 openai SDK 默认超时对齐
        max_retries=10,
        rate_limiter=limiter,
    )


def _content_to_str(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # 某些模型返回内容块列表
        return "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content or "")


class LangGraphAgent:
    """统一 run(task, context="") 接口 + 用量写回 TraceLogger，对 runner 完全透明。"""

    def __init__(self, name, system_prompt, tools, trace: TraceLogger,
                 model=None, delegate_tool=None):
        self.name = name
        self.system_prompt = system_prompt
        self.trace = trace
        self.model = model or make_model()
        all_tools = list(tools) + ([delegate_tool] if delegate_tool else [])
        self.graph = (create_react_agent(self.model, all_tools, prompt=system_prompt)
                      if all_tools else None)  # 无工具（如 Reviewer）直接走模型调用

    async def run(self, task, context="") -> str:
        user_content = task if not context else f"{task}\n\n---\n以下是参考资料：\n{context}"
        if self.graph is None:
            resp = await self.model.ainvoke([("system", self.system_prompt),
                                             ("user", user_content)])
            self._account([resp])
            return _content_to_str(resp.content)

        state = await self.graph.ainvoke({"messages": [("user", user_content)]})
        messages = state.get("messages", [])
        self._account(messages)
        return _content_to_str(messages[-1].content) if messages else ""

    def _account(self, messages):
        """把本轮的 token/请求/工具调用统计写进 trace——与 mini-agents 同口径。"""
        for msg in messages:
            if getattr(msg, "type", "") != "ai":
                continue
            usage = getattr(msg, "usage_metadata", None) or {}
            self.trace.add_usage(self.name,
                                 usage.get("input_tokens", 0),
                                 usage.get("output_tokens", 0))
            calls = [{"name": tc.get("name", ""), "arguments": str(tc.get("args", ""))[:120]}
                     for tc in (msg.tool_calls or [])]
            self.trace.log(self.name, "llm_response",
                           content=_content_to_str(msg.content)[:160],
                           tool_calls=calls)
            for tc in (msg.tool_calls or []):
                self.trace.log(self.name, "tool_call",
                               name=tc.get("name", ""),
                               arguments=json.dumps(tc.get("args", {}), ensure_ascii=False)[:120])


_DELEGATE_SCHEMA = {"type": "object",
                    "properties": {"sub_task": {"type": "string",
                                                "description": "派给子 Agent 的独立子任务"}},
                    "required": ["sub_task"]}


def make_delegate_tool(tools, worker_system_prompt, trace: TraceLogger):
    """LangGraph 版的 delegate：每次调用现场创建全新 worker ReAct agent（上下文隔离，
    与 mini-agents 的 delegate 设计一致）。"""
    model = make_model()
    counter = {"n": 0}

    async def delegate(sub_task: str) -> str:
        i = counter["n"] + 1
        counter["n"] = i
        worker = LangGraphAgent(f"Worker-{i}", worker_system_prompt, tools, trace,
                                model=model)
        return await worker.run(sub_task)

    return StructuredTool(
        name="delegate",
        description=("把一个独立子任务委派给一个全新的子 Agent 执行，返回其最终回答。"
                     "多个相互独立的子任务应在同一条消息里多次调用本工具，它们将被并行执行。"),
        args_schema=_schema_to_pydantic(_DELEGATE_SCHEMA, "delegate_args"),
        coroutine=delegate,
    )
