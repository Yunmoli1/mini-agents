"""早停机制离线测试：零成本验证"连续失败止损"与工具失败约定的识别逻辑。

    python test_early_stop.py

背景：搜索服务持续限流时，调研员会一轮轮换关键词重试直到烧满 15 轮上限，
token 全部打水漂。fail_fast_turns 让"连续 N 轮一无所获"提前止损。
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from mini_agents import Agent, TraceLogger
from mini_agents.agent import looks_like_failure
from mini_agents.tools import tool


class ScriptedLLM:
    """按剧本回复：每次 chat 依序弹出下一条消息，并记录被调用的次数。"""

    def __init__(self, script, trace):
        self.script = list(script)
        self.trace = trace
        self.calls = 0

    async def chat(self, messages, tools=None, agent="?"):
        self.calls += 1
        return self.script.pop(0)


def tool_msg(*names):
    """构造一条"模型请求调用工具"的消息（结构对齐 OpenAI 协议的最小面）。"""
    return SimpleNamespace(
        content=None,
        tool_calls=[SimpleNamespace(id=f"c{i}", type="function",
                                    function=SimpleNamespace(name=n, arguments="{}"))
                    for i, n in enumerate(names)])


DONE = SimpleNamespace(content="完成", tool_calls=None)


@tool(description="永远失败的工具（模拟服务不可用）")
async def always_fails():
    raise RuntimeError("网络不可用")


@tool(description="正常的工具")
async def echo(text: str = "ok"):
    return text


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    trace = TraceLogger(Path(tempfile.mkdtemp(prefix="mini_early_")) / "t.jsonl",
                        echo=False)

    # 1. 失败约定：异常前缀 / error 键（dict 或 list 项）算失败；正常数据、空列表、混合列表不算
    for text in ("工具执行出错：网络炸了", "错误：没有名为 x 的工具",
                 '{"error": "搜索不可用"}', '[{"error": "ddgs 未安装"}]'):
        assert looks_like_failure(text), text
    for text in ('[{"title": "t", "url": "u", "snippet": "s"}]', "42",
                 "这是一段普通文字", "[]", '[{"error": "x"}, {"title": "t"}]'):
        assert not looks_like_failure(text), text

    # 2. 连续失败止损：fail_fast_turns=2，模型铁了心调失败工具 → 第 2 轮就停，不等 15 轮
    llm = ScriptedLLM([tool_msg("always_fails")] * 15, trace)
    agent = Agent("R", "s", [always_fails], llm, max_turns=15, fail_fast_turns=2)
    out = asyncio.run(agent.run("任务"))
    assert llm.calls == 2, f"期望 2 轮止损，实际调了 {llm.calls} 次模型"
    assert "提前止损" in out, out
    events = [json.loads(line) for line in trace.path.read_text(encoding="utf-8")
              .splitlines() if line.strip()]
    stops = [e for e in events if e["type"] == "early_stop"]
    assert len(stops) == 1 and stops[0]["failed_turns"] == 2, stops

    # 3. 中间成功一次即清零：失败→成功→失败→完成，不触发早停
    llm2 = ScriptedLLM([tool_msg("always_fails"), tool_msg("echo"),
                        tool_msg("always_fails"), DONE], trace)
    agent2 = Agent("R2", "s", [always_fails, echo], llm2, max_turns=15,
                   fail_fast_turns=2)
    assert asyncio.run(agent2.run("任务")) == "完成" and llm2.calls == 4

    # 4. 混合轮（一个失败一个成功）不算失败轮
    llm3 = ScriptedLLM([tool_msg("always_fails", "echo"),
                        tool_msg("always_fails", "echo"), DONE], trace)
    agent3 = Agent("R3", "s", [always_fails, echo], llm3, max_turns=15,
                   fail_fast_turns=2)
    assert asyncio.run(agent3.run("任务")) == "完成" and llm3.calls == 3

    # 5. 默认关闭（fail_fast_turns=0）：同样的连续失败照常跑满 max_turns
    llm4 = ScriptedLLM([tool_msg("always_fails")] * 15, trace)
    agent4 = Agent("R4", "s", [always_fails], llm4, max_turns=15)
    out4 = asyncio.run(agent4.run("任务"))
    assert llm4.calls == 15 and "最大轮数" in out4

    print("✓ 失败约定识别正确：异常前缀/error 键算失败，正常数据/空列表/混合列表不算")
    print("✓ 连续失败止损：2 轮全失败即停（模型仅被调 2 次），trace 有 early_stop 事件")
    print("✓ 计数清零正确：中间成功一轮即复位；混合轮不算失败轮")
    print("✓ 默认关闭：不开 fail_fast_turns 时行为与原来完全一致")
    print("\n早停机制离线测试全部通过 ✔")


if __name__ == "__main__":
    main()
