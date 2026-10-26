"""OpenAI Agents SDK 适配器：与 langgraph / crewai 适配器同构，公平性三原则一致。

选择它作为第三框架的原因：CrewAI 全版本钉死 Requires-Python <3.14（本机 3.14.6
无法安装，用户拍板换用，见 DECISIONS.md #15 修订）；Agents SDK 纯 Python、
官方出品、2026 年最热的新贵框架，对比叙事反而更有时效性。

接入要点：自定义 OpenAI 兼容网关必须走 chat_completions API 并禁用 tracing
（否则会向 OpenAI 平台导出 trace）。
"""
import json
import os

from mini_agents.tracing import TraceLogger

from .langgraph_adapter import _DELEGATE_SCHEMA, _schema_to_pydantic

_initialized = False


def _init_sdk():
    """初始化 SDK 全局配置：自定义网关 + chat_completions + 禁 tracing。"""
    global _initialized
    if _initialized:
        return
    from agents import (set_default_openai_api, set_default_openai_client,
                        set_tracing_disabled)
    from openai import AsyncOpenAI

    set_default_openai_client(AsyncOpenAI(
        base_url=os.getenv("LLM_BASE_URL"),
        api_key=os.getenv("LLM_API_KEY"),
        timeout=600,
        max_retries=10,  # 与另两侧的限流对齐策略地位等同（DECISIONS.md #14）
    ))
    set_default_openai_api("chat_completions")  # 自定义网关不支持 Responses API
    set_tracing_disabled(True)
    _initialized = True


def make_agent(name, system_prompt, tools, trace: TraceLogger,
               delegate_tool=None):
    """构建 Agents SDK 的 Agent；tools 为已转换的 FunctionTool 列表。"""
    _init_sdk()
    from agents import Agent

    all_tools = list(tools) + ([delegate_tool] if delegate_tool else [])
    return Agent(name=name, instructions=system_prompt,
                 tools=all_tools, model=os.getenv("LLM_MODEL", "glm-4-flash"))


def to_function_tool(tool, trace: TraceLogger):
    """mini_agents 的 Tool（含 MCP 远程工具）→ Agents SDK FunctionTool。"""
    from agents import FunctionTool

    async def on_invoke(ctx, args_json: str) -> str:
        args = json.loads(args_json or "{}")
        trace.log(tool.name, "tool_call", name=tool.name,
                  arguments=json.dumps(args, ensure_ascii=False)[:120])
        result = await tool.call(args)
        result = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        trace.log(tool.name, "tool_result", name=tool.name, preview=str(result)[:120])
        return result

    # strict_json_schema=False：我们的工具 schema 非 strict 子集（网关也不要求）
    return FunctionTool(name=tool.name, description=tool.description or tool.name,
                        params_json_schema=tool.parameters, on_invoke_tool=on_invoke,
                        strict_json_schema=False)


class AgentsSDKAgent:
    """统一 run(task, context="") 接口 + 用量写回 TraceLogger，对 runner 透明。"""

    def __init__(self, name, agent, trace: TraceLogger):
        self.name = name
        self.agent = agent
        self.trace = trace

    async def run(self, task, context="") -> str:
        from agents import Runner

        user_content = task if not context else f"{task}\n\n---\n以下是参考资料：\n{context}"
        result = await Runner.run(self.agent, user_content, max_turns=15)
        self._account(result)
        return str(result.final_output or "")

    def _account(self, result):
        usage = result.context_wrapper.usage
        self.trace.add_usage(self.name,
                             getattr(usage, "input_tokens", 0) or 0,
                             getattr(usage, "output_tokens", 0) or 0,
                             requests=max(1, getattr(usage, "requests", 1) or 1))
        # 用 raw_responses 统计每轮的工具调用：chat_completions 模式下
        # MessageOutputItem.raw_item 没有 tool_calls 字段（那属于 chat completion
        # message），SDK 已把工具调用统一转换成 Response.output 里的 function_call 项。
        # 直接遍历 raw_responses 才能数准 multi_call_turns（自检发现的原统计缺陷）。
        responses = getattr(result, "raw_responses", None) or []
        for resp in responses:
            output = getattr(resp, "output", None) or []
            calls, text_parts = [], []
            for out_item in output:
                out_type = getattr(out_item, "type", "")
                if out_type == "function_call":
                    calls.append({"name": getattr(out_item, "name", ""),
                                  "arguments": str(getattr(out_item, "arguments", ""))[:120]})
                elif out_type == "message":
                    for part in (getattr(out_item, "content", None) or []):
                        text_parts.append(str(getattr(part, "text", "")))
            self.trace.log(self.name, "llm_response",
                           content=" ".join(text_parts)[:160],
                           tool_calls=calls)
        if not responses:  # 兜底：SDK 版本差异导致拿不到 raw_responses 时至少留痕
            self.trace.log(self.name, "llm_response", content="", tool_calls=[])


_DELEGATE_SCHEMA_ARGS = _schema_to_pydantic(_DELEGATE_SCHEMA, "delegate_args")


def make_delegate_tool(base_tools, worker_system_prompt, trace: TraceLogger):
    """Agents SDK 版 delegate：每次调用现场创建全新 worker Agent（上下文隔离，
    与另外两个框架的 delegate 设计一致）。"""
    from agents import FunctionTool, Runner

    counter = [0]

    async def on_invoke(ctx, args_json: str) -> str:
        counter[0] += 1
        args = json.loads(args_json or "{}")
        worker_agent = make_agent(f"Worker-{counter[0]}", worker_system_prompt,
                                  base_tools, trace)
        result = await Runner.run(worker_agent, str(args.get("sub_task", "")),
                                  max_turns=15)
        worker_view = AgentsSDKAgent(f"Worker-{counter[0]}", worker_agent, trace)
        worker_view._account(result)  # worker 用量也计入同一 trace，口径一致
        return str(result.final_output or "")

    return FunctionTool(name="delegate",
                        description=("把一个独立子任务委派给一个全新的子 Agent 执行，"
                                     "返回其最终回答。多个相互独立的子任务应在同一条消息里"
                                     "多次调用本工具，它们将被并行执行。"),
                        params_json_schema=_DELEGATE_SCHEMA,
                        on_invoke_tool=on_invoke,
                        strict_json_schema=False)
