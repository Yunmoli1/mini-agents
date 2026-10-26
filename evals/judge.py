"""LLM 评委（LLM-as-judge）：给每个回答打 0~10 的质量分，补上程序化判分缺的"质量"轴。

为什么需要它：18 个任务的判分全是确定性的（正则/文件比对），只能回答"对没对"，
回答不出"答得有多好"。成本路由的帕累托曲线（成本 ⇄ 质量）需要后者。

口径（DECISIONS #22）：
- **盲评**：评委只看任务与回答，不给程序判分的期望值——期望值一给，评委就退化成
  复读程序判分，质量轴失去信息量
- 评分 rubric：正确性 0~5、指令遵循 0~3、完整清晰 0~2（提示词中文冻结，DECISIONS #20）
- 评委自身是模型调用：trace 与 token 单独计量，绝不混入被测配置的成本
"""
import json
import re

JUDGE_SYSTEM = (
    "你是严格而公正的回答质量评委。对照任务要求，从三个维度给回答打分：\n"
    "1. 正确性（0~5 分）：事实与计算是否正确，错误重扣；\n"
    "2. 指令遵循（0~3 分）：是否按任务要求的格式、范围与载体作答；\n"
    "3. 完整清晰（0~2 分）：表达是否完整清晰、有无编造。\n"
    '只输出一个 JSON 对象：{"score": 0到10的整数总分, "reason": "一句话理由"}。'
)


def parse_judge(raw):
    """从评委输出里提取分数与理由；解析不了返回 (None, 原因)，绝不猜分。"""
    m = re.search(r"\{.*\}", raw or "", re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            score = int(round(float(data["score"])))
            return max(0, min(10, score)), str(data.get("reason", ""))[:200]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    return None, f"评委输出不可解析：{(raw or '')[:120]}"


async def judge_answer(judge_llm, task_prompt, answer):
    """评委打分：返回 (score 0~10 或 None, reason)。异常交给调用方按"未评"处理。"""
    msg = await judge_llm.chat(
        [{"role": "system", "content": JUDGE_SYSTEM},
         {"role": "user", "content": f"任务：{task_prompt}\n\n回答：{answer}\n\n请评分。"}],
        agent="Judge")
    return parse_judge(msg.content or "")
