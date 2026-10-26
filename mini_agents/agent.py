"""Agent 核心：系统提示 + 一组工具 + “请求 → 执行工具 → 再请求”的自主循环。

这段循环是所有 agent 框架（LangGraph / CrewAI / AutoGen …）共有的大心脏，
区别只在于外面包装了多少编排能力。值得逐行读懂它。
"""
import asyncio
import json

from .i18n import t

MAX_TOOL_RESULT_CHARS = 8000  # 单个工具结果塞进上下文的上限，防止一次搜索撑爆对话

# 工具失败约定：异常被 _execute 捕获后以这两个前缀开头；工具自身降级时返回含
# "error" 键的数据（见 web_search）。早停机制靠它识别"这轮一无所获"。
_FAILURE_PREFIXES = ("工具执行出错：", "错误：")


def looks_like_failure(text: str) -> bool:
    if isinstance(text, str) and text.startswith(_FAILURE_PREFIXES):
        return True
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    if isinstance(data, dict):
        return "error" in data
    if isinstance(data, list) and data:
        return all(isinstance(x, dict) and "error" in x for x in data)
    return False


class Agent:
    def __init__(self, name, system_prompt, tools=(), llm=None, max_turns=15,
                 parallel_tool_calls=True, fail_fast_turns=0):
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm
        self.max_turns = max_turns
        self.parallel_tool_calls = parallel_tool_calls
        # 连续 N 轮所有工具调用全部失败就提前止损（0 = 关闭）。
        # 默认关闭：早停是为"唯一工具持续不可用"的调研员场景设计的，
        # 一般 agent 偶尔失败后重试是正常行为，不该被掐断。
        self.fail_fast_turns = fail_fast_turns
        self.tools = {t.name: t for t in tools}
        self.trace = getattr(llm, "trace", None)

    def _schemas(self):
        return [t.schema() for t in self.tools.values()] or None

    async def run(self, task, context=""):
        """执行一个任务，返回 agent 的最终文字回答。

        每次调用都是全新对话（messages 从零开始）——这就是“上下文隔离”：
        子 Agent 只拿到派给它的任务文本，看不到主 Agent 的完整对话历史。
        """
        user_content = task if not context else f"{task}\n\n---\n以下是参考资料：\n{context}"
        messages = [{"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_content}]

        failed_turns = 0
        for _turn in range(1, self.max_turns + 1):
            msg = await self.llm.chat(messages, tools=self._schemas(), agent=self.name)

            if not msg.tool_calls:  # 不再请求工具 = 自认为任务完成
                return msg.content or ""

            # 协议要求：助手发起的工具调用必须先原样记回历史，再补执行结果
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [{"id": tc.id, "type": "function",
                                             "function": {"name": tc.function.name,
                                                          "arguments": tc.function.arguments}}
                                            for tc in msg.tool_calls]})

            # ★ 关键机制：模型在一条消息里发出的多个工具调用，可并发执行
            #   （demo 的“并行调研”靠它实现；parallel_tool_calls 开关用于评测对照实验）。
            if self.parallel_tool_calls:
                results = await asyncio.gather(*[self._execute(tc) for tc in msg.tool_calls])
            else:
                results = [await self._execute(tc) for tc in msg.tool_calls]
            for tc, output in zip(msg.tool_calls, results):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})

            # 提前止损：一轮里所有工具都失败 = 这一轮毫无收获；连续多轮如此，
            # 再跑下去只会烧满轮数上限（搜索服务持续限流时的真实教训）。
            # 只要有一轮工具成功就把计数清零——偶发失败后换关键词重试是正常行为。
            if self.fail_fast_turns:
                failed_turns = failed_turns + 1 if all(
                    looks_like_failure(r) for r in results) else 0
                if failed_turns >= self.fail_fast_turns:
                    if self.trace:
                        self.trace.log(self.name, "early_stop",
                                       failed_turns=failed_turns,
                                       max_turns=self.max_turns)
                    return t("a.early_stop", n=failed_turns)

        return t("a.max_turns")

    async def _execute(self, tool_call) -> str:
        """执行单个工具调用，任何异常都转成文字返回给模型（让它自己看到并纠错）。"""
        name = tool_call.function.name
        raw_args = tool_call.function.arguments or "{}"
        if self.trace:
            self.trace.log(self.name, "tool_call", name=name, arguments=raw_args)
        try:
            args = json.loads(raw_args)
            tool = self.tools.get(name)
            if tool is None:
                result = f"错误：没有名为 {name} 的工具。可用工具：{list(self.tools)}"
            else:
                result = await tool.call(args)
        except Exception as exc:
            result = f"工具执行出错：{exc}"

        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1)
        if len(text) > MAX_TOOL_RESULT_CHARS:
            text = text[:MAX_TOOL_RESULT_CHARS] + "\n…（结果过长已截断）"
        if self.trace:
            self.trace.log(self.name, "tool_result", name=name, preview=text[:120])
        return text
