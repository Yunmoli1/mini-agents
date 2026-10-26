"""LLM 调用层：只负责“把对话历史发给模型，拿回下一条消息”。

刻意做得很薄：凡是 OpenAI 兼容接口（智谱 GLM / Z.ai / OpenAI / DeepSeek …）
都走同一个 chat.completions 协议，区别只在 base_url 和模型名。
"""
import asyncio
import os
from pathlib import Path

from .i18n import t

try:
    from openai import RateLimitError as _RateLimitError
except ImportError:          # 离线测试不装 openai，保留一个占位类型即可
    class _RateLimitError(Exception):
        pass

# SDK 自带的两次快速重试顶不住共享网关通道的限流，这里接手做长退避
_RETRY_DELAYS = (15, 30, 60, 120)

# 项目根目录 = mini_agents 包的上一级；.env 显式锚定在这里，行为与运行目录无关
_PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"


class LLM:
    def __init__(self, trace=None, model=None):
        try:
            from dotenv import load_dotenv
            load_dotenv(_PROJECT_ENV if _PROJECT_ENV.exists() else None,
                        encoding="utf-8-sig")
        except ImportError:
            pass
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
        # model 覆盖支持多模型成本路由：同一 client 配置下按角色换模型
        self.model = model or os.getenv("LLM_MODEL", "glm-4-flash")
        if not api_key or "粘贴" in api_key:
            raise RuntimeError(t("l.no_key"))
        from openai import AsyncOpenAI  # 延迟导入：离线测试时无需安装 openai

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.trace = trace

    async def chat(self, messages, tools=None, agent="?"):
        """发消息给模型，返回它的下一条消息：
        - 要么带 content（任务完成，是最终回答）
        - 要么带 tool_calls（模型想用工具，由 Agent 层执行后再发回来）
        """
        self.trace.log(agent, "llm_request",
                       message_count=len(messages), last_message=messages[-1])

        kwargs = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        attempt = 0
        while True:
            try:
                resp = await self.client.chat.completions.create(**kwargs)
                break
            except _RateLimitError as exc:
                # 限流是通道属性而不是任务失败：长退避错峰后重试，
                # 序列用尽才抛给上层按任务失败记录
                if attempt >= len(_RETRY_DELAYS):
                    raise
                delay = _RETRY_DELAYS[attempt]
                attempt += 1
                try:  # 网关明确给了 Retry-After 就听网关的（夹在 5~150s）
                    delay = max(5, min(150, int(exc.response.headers["retry-after"])))
                except Exception:
                    pass
                self.trace.log(agent, "llm_retry", attempt=attempt, delay=delay,
                               detail=str(exc)[:140])
                await asyncio.sleep(delay)

        msg = resp.choices[0].message
        usage = resp.usage
        self.trace.add_usage(
            agent,
            getattr(usage, "prompt_tokens", 0) if usage else 0,
            getattr(usage, "completion_tokens", 0) if usage else 0,
        )
        self.trace.log(agent, "llm_response", content=msg.content,
                       tool_calls=[{"name": tc.function.name, "arguments": tc.function.arguments}
                                   for tc in (msg.tool_calls or [])])
        return msg
