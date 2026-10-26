"""多模型成本路由的离线验证：不花一分钱确认"角色 → 模型"的接线正确。

    python test_cost_routing.py
"""
import asyncio
import sys
from types import SimpleNamespace

from demo_research_team import research_pipeline
from mini_agents import TraceLogger


class FakeLLM:
    """按 agent 名字出牌的假模型，记录所有调用者。"""

    def __init__(self, label, trace):
        self.label = label
        self.trace = trace
        self.served = []
        self.step = 0

    async def chat(self, messages, tools=None, agent="?"):
        self.served.append(agent)
        self.step += 1
        self.trace.add_usage(agent, 0, 0)
        if agent.startswith("Planner") and self.step == 1:
            return SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id="t1", function=SimpleNamespace(name="research",
                arguments='{"sub_question": "子问题A"}'))])
        if agent.startswith("Reviewer"):
            return SimpleNamespace(content='{"verdict": "pass", "issues": []}',
                                   tool_calls=None)
        return SimpleNamespace(content=f"[{self.label}] 回答", tool_calls=None)


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    trace = TraceLogger("runs/cost-routing-test/trace.jsonl", echo=False)
    strong = FakeLLM("强模型", trace)
    cheap = FakeLLM("便宜模型", trace)

    # 路由：主链路（Planner/Writer/Reviewer）走强模型，调研员走便宜模型
    res = await research_pipeline("测试主题", trace, llm=strong,
                                  researcher_llm=cheap)

    assert "Planner" in strong.served and "Writer" in strong.served \
        and "Reviewer" in strong.served, f"主链路应走强模型：{strong.served}"
    assert not any(a.startswith("Researcher") for a in strong.served), (
        f"调研员不应走强模型：{strong.served}")
    assert any(a.startswith("Researcher") for a in cheap.served), (
        f"调研员应走便宜模型：{cheap.served}")
    assert not any(a.startswith(("Planner", "Writer", "Reviewer"))
                   for a in cheap.served), f"主链路不应走便宜模型：{cheap.served}"
    assert res.report and "回答" in res.report, f"产出异常：{res.report[:100]}"

    print("✓ 主链路（Planner/Writer/Reviewer）全部走强模型")
    print("✓ 调研员（Researcher-*）全部走便宜模型")
    print("✓ 路由下流水线产出正常")
    print("\n成本路由离线验证全部通过 ✔")


if __name__ == "__main__":
    asyncio.run(main())
