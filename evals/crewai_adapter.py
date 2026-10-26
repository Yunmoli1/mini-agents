"""CrewAI 适配器：与 langgraph_adapter 同构，延续公平性三原则。

与另外两个框架保持**同一编排架构模式**（delegate 即工具、每次调用现场建全新
worker），而不是各框架的惯用模式——变量隔离优先（DECISIONS.md #15）。

已知口径差异（报告中如实注明）：token 计量来自 crew.usage_metrics
（litellm tokenizer 口径），与 mini-agents / LangGraph 的 API 返回 usage
略有出入；CrewAI 会注入 role/goal/expected_output 脚手架，计入框架开销。
"""
import asyncio
import concurrent.futures
import json
import os

from crewai import Agent as CrewAgent, Crew, Task
from crewai.llm import LLM as CrewLLM
from crewai.tools import BaseTool
from pydantic import create_model

from mini_agents.tracing import TraceLogger

from .langgraph_adapter import _DELEGATE_SCHEMA, _schema_to_pydantic


def make_llm():
    return CrewLLM(
        model=f"openai/{os.getenv('LLM_MODEL', 'glm-4-flash')}",
        base_url=os.getenv("LLM_BASE_URL"),
        api_key=os.getenv("LLM_API_KEY"),
        num_retries=10,  # 与另外两侧的限流对齐策略地位等同（DECISIONS.md #14/#15）
    )


def _run_coro_sync(coro):
    """在 CrewAI 的同步执行上下文里驱动我们的异步工具：
    本线程无事件循环就直接跑；有（CrewAI 内部起的 loop）就丢到独立线程。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, coro).result()


def to_crewai_tool(tool, trace: TraceLogger):
    """mini_agents 的 Tool（含 MCP 远程工具）→ CrewAI BaseTool。"""
    args_model = _schema_to_pydantic(tool.parameters, f"{tool.name}_args")

    class _Tool(BaseTool):
        name: str = tool.name
        description: str = tool.description or tool.name
        args_schema: type = args_model

        def _run(self, **kwargs) -> str:
            trace.log(tool.name, "tool_call", name=tool.name,
                      arguments=json.dumps(kwargs, ensure_ascii=False)[:120])
            result = _run_coro_sync(tool.call(kwargs))
            result = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            trace.log(tool.name, "tool_result", name=tool.name, preview=str(result)[:120])
            return result

    return _Tool()


class CrewAIAgent:
    """统一 run(task, context="") 接口；每次 run 构建全新 Crew（上下文隔离）。"""

    def __init__(self, name, system_prompt, tools, trace: TraceLogger,
                 delegate_tool_factory=None):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = list(tools)
        self.trace = trace
        self.delegate_tool_factory = delegate_tool_factory
        self.llm = make_llm()
        self.counter = [0]

    async def run(self, task, context="") -> str:
        user_content = task if not context else f"{task}\n\n---\n以下是参考资料：\n{context}"
        return await asyncio.to_thread(self._kickoff, user_content)

    def _kickoff(self, user_content: str) -> str:
        tools = list(self.tools)
        if self.delegate_tool_factory:
            tools.append(self.delegate_tool_factory())
        agent = CrewAgent(
            role="任务执行者",
            goal=self.system_prompt,       # 完整提示词放在 goal，与另两侧口径对齐
            backstory="严格按指令完成任务，只依据给定信息，不编造。",
            llm=self.llm,
            tools=tools,
            allow_delegation=False,        # 编排走我们的 delegate 工具，不用内置委派
            verbose=False,
        )
        crew_task = Task(description=user_content,
                         expected_output="按任务要求给出最终结果。",
                         agent=agent)
        crew = Crew(agents=[agent], tasks=[crew_task], verbose=False)
        result = crew.kickoff()

        metrics = getattr(crew, "usage_metrics", None)
        if metrics is not None:
            self.trace.add_usage(self.name,
                                 getattr(metrics, "prompt_tokens", 0) or 0,
                                 getattr(metrics, "completion_tokens", 0) or 0)
        self.trace.log(self.name, "llm_response",
                       content=str(result)[:160], tool_calls=[])
        return str(result)


def make_delegate_tool(base_tools, worker_system_prompt, trace: TraceLogger):
    """CrewAI 版 delegate：每次调用现场创建一个单 Agent 内部 Crew（上下文隔离，
    与 mini-agents / LangGraph 的 delegate 设计一致）。"""
    counter = [0]

    def _factory():
        class _Delegate(BaseTool):
            name: str = "delegate"
            description: str = ("把一个独立子任务委派给一个全新的子 Agent 执行，返回其最终回答。"
                                "多个相互独立的子任务应在同一条消息里多次调用本工具，"
                                "它们将被并行执行。")
            args_schema: type = _schema_to_pydantic(_DELEGATE_SCHEMA, "delegate_args")

            def _run(self, sub_task: str) -> str:
                counter[0] += 1
                worker = CrewAIAgent(f"Worker-{counter[0]}", worker_system_prompt,
                                     base_tools, trace)
                return _run_coro_sync(worker.run(sub_task))

        return _Delegate()

    return _factory
