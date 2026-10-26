"""离线冒烟测试：不花一分钱、不联网，验证多 Agent 的全部机制性代码。

原理：Agent 只依赖 llm.chat() 这一个接口。把真模型换成按脚本出牌的
FakeLLM，就能离线验证：agent 循环、并行工具调用、消息协议、trace 日志。

    python test_offline.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from mini_agents.agent import Agent
from mini_agents.tools import tool
from mini_agents.tracing import TraceLogger

TOOL_LATENCY = 0.2   # 模拟每个工具调用的网络耗时
starts = []          # 记录每次工具调用的开始时刻，用来验证“真的在并行”


class FakeLLM:
    """按脚本出牌的假模型：第一次返回两个并行工具调用，第二次返回最终总结。"""

    def __init__(self, trace):
        self.trace = trace
        self.call_count = 0

    async def chat(self, messages, tools=None, agent="?"):
        self.call_count += 1
        if self.call_count == 1:
            return SimpleNamespace(
                content=None,
                tool_calls=[
                    SimpleNamespace(id="call_1", function=SimpleNamespace(
                        name="research", arguments=json.dumps({"sub_question": "子问题A"}))),
                    SimpleNamespace(id="call_2", function=SimpleNamespace(
                        name="research", arguments=json.dumps({"sub_question": "子问题B"}))),
                ],
            )
        # 第二次调用时，历史里应已包含：system + user + assistant(工具调用) + 2 条 tool 结果
        assert len(messages) == 5, f"消息协议不对，期望 5 条，实际 {len(messages)}：{messages}"
        return SimpleNamespace(content="最终总结：两个子问题均已调研完成。", tool_calls=None)


@tool(description="假调研工具，固定延时，用于验证并行执行。")
async def research(sub_question: str) -> str:
    starts.append(time.perf_counter())
    await asyncio.sleep(TOOL_LATENCY)
    return f"关于「{sub_question}」的调研结果"


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    trace_path = Path("runs/offline-test/trace.jsonl")
    trace_path.unlink(missing_ok=True)
    trace = TraceLogger(trace_path)

    agent = Agent(name="TestPlanner", system_prompt="测试用", tools=[research],
                  llm=FakeLLM(trace))
    answer = await agent.run("总任务：验证并行工具调用")

    assert "最终总结" in answer, "agent 没有正确返回最终回答"

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_calls) == 2, f"应有 2 次工具调用，实际 {len(tool_calls)}"

    spread = max(starts) - min(starts)
    assert spread < TOOL_LATENCY / 2, (
        f"两次工具调用间隔 {spread:.2f}s，疑似串行执行而非并行")

    print("✓ agent 循环正常（工具调用 → 回填结果 → 最终回答）")
    print("✓ 消息协议正确（5 条：system/user/assistant+tool_calls/tool×2）")
    print(f"✓ 两个工具调用确实并行执行（启动时间差 {spread * 1000:.0f}ms << 单次耗时 {TOOL_LATENCY * 1000:.0f}ms）")
    print("✓ trace 日志正常落盘：runs/offline-test/trace.jsonl")
    print("\n离线冒烟测试全部通过 ✔")


if __name__ == "__main__":
    asyncio.run(main())
