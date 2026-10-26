"""Trace 日志：把多 Agent 协作的每一步都记成一个 JSONL 文件。

一次完整运行 = 一个 trace.jsonl。它同时做两件事：
1. 落盘：事后用 view_trace.py 回放整个协作过程（谁在什么时候调了什么工具）
2. 终端实时打印一行摘要，跑 demo 时能"看见"多个 Agent 在协作

每条事件形如：
    {"ts": 1761300000.1, "agent": "Researcher-1", "type": "tool_call", "name": "web_search", ...}
"""
import json
import time
from datetime import datetime
from pathlib import Path

_DIM, _RESET, _CYAN = "\033[2m", "\033[0m", "\033[36m"


def _short(text, n=90):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe_event(agent, type, p):
    """把一条事件转成一行人话（终端摘要和回放器共用）。p 是该事件的其余字段。"""
    if type == "stage":
        return f"{_CYAN}═══ {p.get('title', '')} ═══{_RESET}"
    if type == "llm_request":
        last = p.get("last_message") or {}
        detail = last.get("content") or f"（工具结果回合，共 {p.get('message_count')} 条消息）"
        return f"[{agent}] → LLM: {_short(detail)}"
    if type == "llm_response":
        calls = p.get("tool_calls") or []
        if calls:
            return f"[{agent}] ← 请求调用工具: {', '.join(c['name'] for c in calls)}"
        return f"[{agent}] ← 回复: {_short(p.get('content') or '')}"
    if type == "tool_call":
        return f"[{agent}] ⚙ {p.get('name')}({_short(p.get('arguments', ''), 60)})"
    if type == "tool_result":
        return f"[{agent}] ✔ {p.get('name')} → {_short(p.get('preview', ''), 70)}"
    if type == "blackboard_write":
        return f"[黑板] ✍ 写入 {p.get('key')}: {_short(p.get('preview', ''), 70)}"
    if type == "mcp_event":
        return f"[{agent}] MCP: {p.get('detail', '')}"
    if type == "llm_retry":
        return f"[{agent}] ⏳ 429 限流，{p.get('delay')}s 后做第 {p.get('attempt')} 次重试"
    return f"[{agent}] {type}"


class TraceLogger:
    def __init__(self, path, echo=True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self.usage = {}  # agent 名 -> {"requests": n, "prompt_tokens": n, "completion_tokens": n}

    def log(self, agent, type, **payload):
        event = {"ts": time.time(), "agent": agent, "type": type, **payload}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        if self.echo:
            line = describe_event(agent, type, payload)
            clock = datetime.fromtimestamp(event["ts"]).strftime("%H:%M:%S")
            print(f"{_DIM}[{clock}] {line}{_RESET}")

    def add_usage(self, agent, prompt_tokens, completion_tokens, requests=1):
        u = self.usage.setdefault(agent, {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0})
        u["requests"] += requests or 1
        u["prompt_tokens"] += prompt_tokens or 0
        u["completion_tokens"] += completion_tokens or 0

    def print_usage_report(self):
        total_in = total_out = total_req = 0
        print("\n─── Token 用量（按 Agent）──────────")
        for name, u in self.usage.items():
            print(f"  {name:<14} {u['requests']:>3} 次请求   "
                  f"{u['prompt_tokens']:>7} 入 + {u['completion_tokens']:>6} 出 tokens")
            total_req += u["requests"]
            total_in += u["prompt_tokens"]
            total_out += u["completion_tokens"]
        print(f"  {'合计':<13}  {total_req:>3} 次请求   {total_in:>7} 入 + {total_out:>6} 出 tokens")
