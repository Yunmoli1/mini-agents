"""子 Agent 委派工具：把"派活"变成一个普通工具，模型由此获得自主编排多 Agent 的能力。

用法：把 build_delegate_tool(...) 的返回值加进编排者的工具表即可。
模型在同一条消息里发出多个 delegate 调用时，它们会被 Agent 循环并发执行——
这就是"可并行的多 Agent 编排"，与 demo_research_team 里的思路一致，但决定权在模型。
"""
from .agent import Agent
from .tools import tool


def build_delegate_tool(llm, worker_system_prompt, tools, trace=None,
                        worker_name="Worker", max_turns=10):
    """构造一个 delegate 工具：每次调用现场创建一名全新子 Agent（上下文隔离）。"""
    counter = {"n": 0}

    @tool(description="把一个独立子任务委派给一个全新的子 Agent 执行，返回其最终回答。"
                     "多个相互独立的子任务应在同一条消息里多次调用本工具，它们将被并行执行。")
    async def delegate(sub_task: str) -> str:
        i = counter["n"] + 1
        counter["n"] = i  # 先占号再 await，并发下编号不重复
        worker = Agent(name=f"{worker_name}-{i}", system_prompt=worker_system_prompt,
                       tools=tools, llm=llm, max_turns=max_turns)
        return await worker.run(sub_task)

    return delegate
