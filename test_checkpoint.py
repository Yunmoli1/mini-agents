"""断点恢复的离线验证：中途崩溃 → 恢复续跑 → 已完成阶段零重复调用。

场景：
  A. 完整跑一遍流水线（假模型按 agent 名字出牌），记录总 LLM 调用数
  B. 注入崩溃（Writer 阶段抛异常）→ 此时黑板里已保存 Planner 阶段
  C. 从黑板上恢复续跑 → 断言 Planner/Researcher 零调用（不重复花钱），
     恢复跑调用数 == 完整跑 - 崩溃前已消耗

     python test_checkpoint.py
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from demo_research_team import research_pipeline
from mini_agents import Blackboard, TraceLogger


class ScriptedLLM:
    """按 agent 名字出牌的假模型；可注入"Writer 阶段中途崩溃"。

    calls     = 尝试次数（崩溃的那次也计入）
    completed = 成功完成的次数（崩溃的不算）——对账用它
    """

    def __init__(self, trace, crash_on_writer=False):
        self.trace = trace
        self.crash_on_writer = crash_on_writer
        self.calls = {}
        self.completed = {}

    def _done(self, agent, resp):
        self.completed[agent] = self.completed.get(agent, 0) + 1
        return resp

    async def chat(self, messages, tools=None, agent="?"):
        self.calls[agent] = self.calls.get(agent, 0) + 1
        self.trace.add_usage(agent, 0, 0)
        if agent.startswith("Planner"):
            if self.calls[agent] == 1:  # 第一轮：派 1 个调研员（经 research 工具）
                return self._done(agent, SimpleNamespace(
                    content=None, tool_calls=[SimpleNamespace(
                        id="t1", function=SimpleNamespace(
                            name="research",
                            arguments=json.dumps({"sub_question": "子问题A"})))]))
            return self._done(agent, SimpleNamespace(
                content="Planner 总结：调研已完成。", tool_calls=None))
        if agent.startswith("Researcher"):
            return self._done(agent, SimpleNamespace(
                content="要点：这是一条调研发现。", tool_calls=None))
        if agent.startswith("Writer"):
            if self.crash_on_writer:
                raise RuntimeError("模拟：Writer 阶段中途崩溃")
            return self._done(agent, SimpleNamespace(
                content="报告：依据黑板上的调研发现写成。", tool_calls=None))
        if agent.startswith("Reviewer"):
            return self._done(agent, SimpleNamespace(
                content='{"verdict": "pass", "issues": []}', tool_calls=None))
        return self._done(agent, SimpleNamespace(content="ok", tool_calls=None))


def total_calls(llm):
    return sum(llm.completed.values())


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    run_dir_b = Path("runs/checkpoint-test")
    run_dir_b.mkdir(parents=True, exist_ok=True)
    (run_dir_b / "blackboard.json").unlink(missing_ok=True)

    # ── 场景 A：完整跑（无崩溃），记录基准调用数 ─────────────────────
    trace_a = TraceLogger(run_dir_b / "trace-full.jsonl", echo=False)
    llm_a = ScriptedLLM(trace_a)
    res_a = await research_pipeline("测试主题", trace_a, llm=llm_a)
    assert "报告" in res_a.report
    assert res_a.board.read("review_round_1")["verdict"] == "pass"
    n_full = total_calls(llm_a)

    # ── 场景 B：Writer 阶段崩溃 ────────────────────────────────────
    trace_b1 = TraceLogger(run_dir_b / "trace.jsonl", echo=False)
    llm_b1 = ScriptedLLM(trace_b1, crash_on_writer=True)
    crashed = False
    try:
        await research_pipeline("测试主题", trace_b1, llm=llm_b1, run_dir=run_dir_b)
    except RuntimeError as exc:
        crashed = "崩溃" in str(exc)
    assert crashed, "崩溃注入未生效"
    pre_completed = total_calls(llm_b1)
    assert pre_completed == n_full - 2, (
        f"崩溃前应只完成 Planner(2)+Researcher(1)，实际 {pre_completed}/{n_full}")
    assert (run_dir_b / "blackboard.json").exists(), "崩溃前 checkpoint 未落盘"

    # ── 场景 C：从黑板恢复续跑 ─────────────────────────────────────
    board_b = Blackboard.load(run_dir_b / "blackboard.json")
    trace_b2 = TraceLogger(run_dir_b / "trace.jsonl", echo=False)
    llm_b2 = ScriptedLLM(trace_b2)
    res_b = await research_pipeline("测试主题", trace_b2, board=board_b,
                                    run_dir=run_dir_b, llm=llm_b2)

    # 关键断言 1：已完成阶段零调用（不重复花钱）
    assert "Planner" not in llm_b2.calls, "恢复后 Planner 被重复执行"
    assert not any(k.startswith("Researcher") for k in llm_b2.calls), (
        "恢复后 Researcher 被重复执行")
    # 关键断言 2：恢复跑调用数 == 完整跑 − 崩溃前已完成（不多不少）
    assert total_calls(llm_b2) == n_full - pre_completed, (
        f"恢复跑调用数 {total_calls(llm_b2)} != 预期 {n_full - pre_completed}")
    # 关键断言 3：最终状态正确且幂等
    assert res_b.board.read("review_round_1")["verdict"] == "pass"
    assert (res_b.board.read("finding_1")["finding"]
            == res_a.board.read("finding_1")["finding"]), "恢复后调研发现不一致"

    print("✓ 完整跑基准：全流程正常，总调用数", n_full)
    print("✓ 崩溃注入：Writer 阶段异常后，黑板 checkpoint 已落盘")
    print("✓ 恢复续跑：Planner/Researcher 零调用（不重复花钱）")
    print(f"✓ 调用守恒：恢复跑 {total_calls(llm_b2)} == 完整 {n_full} − 崩溃前 {pre_completed}")
    print("✓ 幂等一致：恢复后调研发现与完整跑完全相同")
    print("\n断点恢复离线验证全部通过 ✔")


if __name__ == "__main__":
    asyncio.run(main())
