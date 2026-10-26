"""views 共享工具：语言选择器等跨页面复用的小部件。

语言选择器必须由**页面内部**调用（st.sidebar.selectbox 写进侧边栏）——
st.navigation 应用的主脚本中创建的 st.sidebar 组件会被 Streamlit 静默丢弃
（实测 1.66），所以它不能放在路由脚本里。
"""
import os

import streamlit as st

from mini_agents.i18n import set_lang

_LABELS = {"中文": "zh", "English": "en"}


def render_lang_switcher():
    """在侧边栏渲染语言选择器，并把选择写回 session / query 参数 / i18n。

    query 参数让刷新浏览器后语言不丢；session 让同会话内跨页保持一致。
    """
    if "lang" not in st.session_state:
        st.session_state["lang"] = (st.query_params.get("lang")
                                    or os.getenv("MINI_LANG", "zh"))

    current = "中文" if st.session_state["lang"] == "zh" else "English"
    choice = st.sidebar.selectbox("Language / 语言", list(_LABELS),
                                  index=list(_LABELS).index(current),
                                  key="lang_switcher")
    lang = _LABELS[choice]
    if lang != st.session_state["lang"]:
        st.session_state["lang"] = lang
        st.query_params["lang"] = lang
        set_lang(lang)
    return lang
