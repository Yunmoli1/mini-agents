"""深度调研小组页面：输入问题，实时观看多 Agent 协作过程。

实现要点：流水线在后台线程里跑自己的事件循环，TraceLogger 的每条事件同时
推入线程安全队列；主线程轮询队列、增量渲染时间线——"实时"的全部原理就这么简单。
"""
import asyncio
import html
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from demo_research_team import MAX_REVISIONS, research_pipeline
from mini_agents import Blackboard, TraceLogger, describe_event
from mini_agents.i18n import t
from views._shared import render_lang_switcher

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_AGENT_STYLES = [
    ("Planner", "#58a6ff"), ("Researcher", "#7ee787"), ("Writer", "#f2cc60"),
    ("Reviewer", "#d2a8ff"), ("黑板", "#8b949e"), ("driver", "#ff7b72"),
    ("MCP", "#79c0ff"),
]


def agent_color(agent: str) -> str:
    for prefix, color in _AGENT_STYLES:
        if agent.startswith(prefix):
            return color
    return "#c9d1d9"


class LiveTraceLogger(TraceLogger):
    """JSONL 落盘照旧，每条事件额外推入线程安全队列供主线程增量渲染。"""

    def __init__(self, path, event_queue: queue.Queue):
        super().__init__(path, echo=False)
        self.event_queue = event_queue

    def log(self, agent, type, **payload):
        super().log(agent, type, **payload)
        line = ANSI_RE.sub("", describe_event(agent, type, payload))
        self.event_queue.put((agent, line))


def spawn_pipeline(topic: str, trace_path: Path, result: dict, event_queue: queue.Queue,
                   board=None):
    """在后台线程里跑整条流水线（线程内有独立事件循环）。board 传入即为断点恢复。"""

    def worker():
        try:
            trace = LiveTraceLogger(trace_path, event_queue)
            pipeline = asyncio.run(research_pipeline(
                topic, trace, MAX_REVISIONS, board=board, run_dir=trace_path.parent))
            result["report"] = pipeline.report
            result["usage"] = dict(trace.usage)
            result["trace_path"] = str(trace.path)
        except Exception as exc:  # 未配 API Key（RuntimeError）等全部在此呈现
            result["error"] = str(exc)
        finally:
            result["done"] = True
            event_queue.put(None)  # 哨兵：通知主线程收工

    threading.Thread(target=worker, daemon=True).start()


def render_timeline_html(lines):
    parts = []
    for agent, text in lines[-300:]:  # 只渲染最近 300 条，防止页面越来越卡
        color = agent_color(agent)
        parts.append(
            f'<div style="font-family:Consolas,monospace;font-size:0.82rem;line-height:1.55">'
            f'<span style="color:{color}">{html.escape(agent)}</span> '
            f'<span style="color:#c9d1d9">{html.escape(text)}</span></div>')
    return "".join(parts) or f"<i>{t('res.waiting')}</i>"


def render_usage(usage):
    if not usage:
        return
    st.subheader(t("res.usage_header"))
    st.table([{t("res.col_agent"): name, t("res.col_req"): u["requests"],
               t("res.col_in"): u["prompt_tokens"],
               t("res.col_out"): u["completion_tokens"]}
              for name, u in usage.items()])


def main():
    render_lang_switcher()
    st.title(t("res.title"))
    st.caption(t("res.caption"))

    mode = st.radio(t("res.mode"), [t("res.mode_new"), t("res.mode_resume")],
                    horizontal=True)

    board, topic, trace_path = None, "", None
    if mode == t("res.mode_new"):
        topic = st.text_input(t("res.topic"),
                              value="2026 年主流开源多 Agent 框架的选型对比与发展趋势")
        if not st.button(t("res.start"), type="primary", use_container_width=True):
            return
        if not topic.strip():
            st.warning(t("res.warn_topic"))
            return
        trace_path = Path("runs") / f"app-{datetime.now().strftime('%m%d-%H%M%S')}" / "trace.jsonl"
        topic = topic.strip()
    else:
        resume_text = st.text_input(t("res.resume_dir"), value="runs/")
        if not st.button(t("res.resume_btn"), type="primary", use_container_width=True):
            return
        resume_dir = Path(resume_text.strip())
        board_file = resume_dir / "blackboard.json"
        if not board_file.exists():
            st.error(t("res.resume_missing", path=board_file))
            return
        board = Blackboard.load(board_file)
        topic = board.read("task") or "（恢复的任务）"
        trace_path = resume_dir / "trace.jsonl"  # 追加写，回放可看完整历史
        st.info(t("res.resume_info", dir=resume_dir))

    event_queue: queue.Queue = queue.Queue()
    result: dict = {}
    spawn_pipeline(topic, trace_path, result, event_queue, board=board)

    status = st.status("协作进行中…", expanded=True)
    # 单一空槽位 + 重复 .markdown() 原地替换。不要用 container.empty()+with 重绘：
    # 那会让前端持续累积 DOM（实测 10 分钟涨到 5.6MB/5.8 万节点，页面僵死）。
    timeline_slot = status.empty()
    lines, done = [], False
    while not done:
        got_any = False
        while True:  # 排空队列再渲染一次，避免高频重绘
            try:
                item = event_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                done = True
                break
            lines.append(item)
            got_any = True
        if got_any:
            timeline_slot.markdown(render_timeline_html(lines), unsafe_allow_html=True)
        if not done:
            time.sleep(0.3)

    ok = "error" not in result
    status.update(label=t("res.done") if ok else t("res.error_state"),
                  state="complete" if ok else "error")
    if not ok:
        st.error(result["error"])
        return

    st.subheader(t("res.report_header"))
    st.markdown(result["report"])
    render_usage(result["usage"])
    st.download_button(t("res.download"), result["report"], file_name="report.md")
    st.caption(t("res.trace_caption", path=result["trace_path"]))


main()
