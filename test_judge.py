"""LLM 评委离线测试：零成本验证评分解析、越界截断与报告渲染。

    python test_judge.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from mini_agents.i18n import set_lang

from evals import runner as R
from evals.judge import judge_answer, parse_judge


class FakeJudgeLLM:
    def __init__(self, reply):
        self.reply = reply

    async def chat(self, messages, tools=None, agent="?"):
        assert "请评分" in messages[-1]["content"], "评委提示词应落在 user 消息里"
        return SimpleNamespace(content=self.reply, tool_calls=None)


def row(config, task_id, category, quality=None, judge_tokens=0):
    return R.TaskResult(config=config, task_id=task_id, category=category,
                        repeat=1, success=True, detail="ok", seconds=1.0,
                        tokens=100, requests=2, tool_calls=1, multi_call_turns=1,
                        model="fake", quality=quality, judge_tokens=judge_tokens,
                        judge_reason="r")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    set_lang("zh")

    # 1. 解析：干净 JSON / 带前后废话的 JSON
    assert parse_judge('{"score": 8, "reason": "正确"}') == (8, "正确")
    score, reason = parse_judge('好的。{"score": 7, "reason": "基本正确"} 祝好')
    assert score == 7 and "基本正确" in reason

    # 2. 越界截断与取整：超界夹回 0~10，小数四舍五入
    assert parse_judge('{"score": 15, "reason": "x"}')[0] == 10
    assert parse_judge('{"score": -3, "reason": "x"}')[0] == 0
    assert parse_judge('{"score": 7.6, "reason": "x"}')[0] == 8

    # 3. 解析不了绝不猜分：返回 None
    assert parse_judge("我觉得挺好的")[0] is None
    assert parse_judge('{"reason": "缺 score"}')[0] is None
    assert parse_judge("")[0] is None

    # 4. 端到端：评委 LLM 一问一答
    score, _ = asyncio.run(judge_answer(FakeJudgeLLM('{"score": 9, "reason": "好"}'),
                                        "1+1=?", "2"))
    assert score == 9

    # 5. 聚合与报告：质量列进配置表，评委专节齐全
    results = [row("single", "m1", "math", quality=8, judge_tokens=50),
               row("single", "m2", "math", quality=6, judge_tokens=60),
               row("single", "k1", "knowledge", quality=None)]  # 评委失败的一条
    agg = R._aggregate(results, "single")
    assert agg["quality"] == 7.0 and agg["judge_tokens"] == 110

    out_dir = Path(tempfile.mkdtemp(prefix="mini_judge_"))
    tasks = [t for t in R.TASKS if t.id in ("m1", "m2", "k1")]
    R.write_report(out_dir, results, ["single"], "fake", 1, False, tasks,
                   judged=True)
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "| 平均质量 |" in report, "配置表缺质量列"
    assert "| 7.0 |" in report, "配置表质量均值不对"
    assert "## 回答质量（LLM 评委）" in report, "缺评委专节"
    assert "110 tokens" in report, "评委成本未单独呈现"
    assert "| m1 | math | 8 |" in report and "| k1 | knowledge | - |" in report, \
        "逐任务质量矩阵渲染不对（未解析的应为 -）"

    # 6. 没开评委的报告：无评委专节，质量列显示 -
    R.write_report(out_dir, [row("single", "m1", "math")], ["single"], "fake",
                   1, False, tasks[:1])
    report2 = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "## 回答质量" not in report2 and "| - |" in report2

    print("✓ 评分解析：干净/带废话 JSON 均可提取；越界夹回 0~10；解析失败返回 None 不猜分")
    print("✓ 端到端：评委 LLM 单次调用返回分数")
    print("✓ 报告渲染：质量列、评委专节、评委 token 单独计量、逐任务矩阵（未解析为 -）")
    print("✓ 未启用评委的报告保持原样（无评委专节，质量列 -）")
    print("\nLLM 评委离线测试全部通过 ✔")


if __name__ == "__main__":
    main()
