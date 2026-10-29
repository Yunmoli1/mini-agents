"""mini-agents 控制台：Streamlit 多页应用。

    streamlit run app.py

三个页面（左侧导航切换）：
    🎯 深度调研小组 —— 实时协作时间线 + 报告 + Token 用量（支持断点恢复）
    📊 评测看板     —— evals/results/ 的交互式跨框架对比
    💬 助手对话     —— 普通聊天 + 上传文档本地问答（BM25 RAG）

语言选择器与「模型设置」（平台预设 + API Key，写回 .env）位于各页面内的侧边栏，
选择通过 session 与 URL 参数持久化，刷新后不丢失。
注意：st.navigation 应用中，主脚本里的 st.sidebar 组件会被 Streamlit 静默
丢弃（1.66 实测），因此侧边栏组件必须放在页面内部——见 views/_shared.py。
"""
import os
from pathlib import Path

import streamlit as st

# 启动即把 .env 装进进程环境：侧边栏「模型设置」要显示当前生效的 Key/网关/模型
# （LLM 层也有同样的加载，这里提前到入口，保证 UI 与实际配置一致）
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env", encoding="utf-8-sig")
except ImportError:
    pass

from mini_agents.i18n import init_from_env, t

init_from_env()
st.set_page_config(page_title="mini-agents 控制台", page_icon="🕸️", layout="wide")

if "lang" not in st.session_state:
    # 刷新后 session 会重置——优先取 URL 参数，其次 .env 的 MINI_LANG
    st.session_state["lang"] = (st.query_params.get("lang")
                                or os.getenv("MINI_LANG", "zh"))
if st.session_state["lang"]:
    from mini_agents.i18n import set_lang
    set_lang(st.session_state["lang"])

research_page = st.Page("views/research.py", title=t("page.research"),
                        icon="🎯", default=True)
dashboard_page = st.Page("views/evals_dashboard.py", title=t("page.dashboard"),
                         icon="📊")
assistant_page = st.Page("views/assistant.py", title=t("page.assistant"),
                         icon="💬")

page = st.navigation([research_page, dashboard_page, assistant_page])
page.run()
