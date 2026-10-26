"""mini-agents 控制台：Streamlit 多页应用。

    streamlit run app.py

两个页面（左侧导航切换）：
    🎯 深度调研小组 —— 实时协作时间线 + 报告 + Token 用量（支持断点恢复）
    📊 评测看板     —— evals/results/ 的交互式跨框架对比

语言选择器位于各页面内的侧边栏（中文 / English），选择通过 session 与
URL 参数持久化，刷新后不丢失。
注意：st.navigation 应用中，主脚本里的 st.sidebar 组件会被 Streamlit 静默
丢弃（1.66 实测），因此语言选择器必须放在页面内部——见 views/_shared.py。
"""
import os

import streamlit as st

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

page = st.navigation([research_page, dashboard_page])
page.run()
