"""mini-agents 控制台：Streamlit 多页应用。

    streamlit run app.py

两个页面（左侧导航切换）：
    🎯 深度调研小组 —— 实时协作时间线 + 报告 + Token 用量（支持断点恢复）
    📊 评测看板     —— evals/results/ 的交互式跨框架对比
"""
import streamlit as st

st.set_page_config(page_title="mini-agents 控制台", page_icon="🕸️", layout="wide")

research_page = st.Page("views/research.py", title="深度调研小组",
                        icon="🎯", default=True)
dashboard_page = st.Page("views/evals_dashboard.py", title="评测看板", icon="📊")

page = st.navigation([research_page, dashboard_page])
page.run()
