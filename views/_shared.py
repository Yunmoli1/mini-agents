"""views 共享工具：语言选择器、模型设置面板等跨页面复用的小部件。

语言选择器必须由**页面内部**调用（st.sidebar.selectbox 写进侧边栏）——
st.navigation 应用的主脚本中创建的 st.sidebar 组件会被 Streamlit 静默丢弃
（实测 1.66），所以它们不能放在路由脚本里。
"""
import os
from pathlib import Path

import streamlit as st

from mini_agents.envtools import update_env_file
from mini_agents.i18n import set_lang, t

_LABELS = {"中文": "zh", "English": "en"}

_ROOT = Path(__file__).resolve().parent.parent

# 常用 OpenAI 兼容平台的预设：选中即自动填 base_url 与建议模型（均可改）
_PRESETS = {
    "智谱 BigModel（GLM）": {"base_url": "https://open.bigmodel.cn/api/paas/v4/",
                            "model": "glm-4-flash"},
    "DeepSeek 官方": {"base_url": "https://api.deepseek.com/v1",
                     "model": "deepseek-chat"},
    "月之暗面 Kimi": {"base_url": "https://api.moonshot.cn/v1",
                     "model": "moonshot-v1-8k"},
    "阿里云百炼（Qwen）": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                          "model": "qwen-plus"},
    "OpenAI": {"base_url": "https://api.openai.com/v1",
               "model": "gpt-4o-mini"},
    "OpenRouter": {"base_url": "https://openrouter.ai/api/v1",
                   "model": "openrouter/auto"},
    "自定义 / 不更换平台": None,
}


def _apply_preset():
    """平台预设下拉框的回调：把预设的 base_url / 模型填进输入框（可在保存前手改）。"""
    preset = _PRESETS.get(st.session_state.get("cfg_preset"))
    if preset:
        st.session_state["cfg_base_url"] = preset["base_url"]
        st.session_state["cfg_model"] = preset["model"]


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


def render_model_settings():
    """侧边栏「模型设置」：平台预设 + base_url + API Key + 模型名，保存写回 .env。

    保存后同步 os.environ——LLM 层的 load_dotenv 不覆盖已有变量，
    只写文件的话本进程要到重启才会生效。Key 输入框留空 = 不修改。
    """
    with st.sidebar.expander(t("cfg.title"), expanded=not os.getenv("LLM_API_KEY")):
        if "cfg_base_url" not in st.session_state:
            st.session_state["cfg_base_url"] = os.getenv(
                "LLM_BASE_URL", _PRESETS["智谱 BigModel（GLM）"]["base_url"])
        if "cfg_model" not in st.session_state:
            st.session_state["cfg_model"] = os.getenv("LLM_MODEL", "glm-4-flash")

        st.selectbox(t("cfg.preset"), list(_PRESETS),
                     index=len(_PRESETS) - 1, key="cfg_preset",
                     on_change=_apply_preset, help=t("cfg.preset_help"))
        st.text_input(t("cfg.base_url"), key="cfg_base_url")
        api_key = st.text_input(t("cfg.api_key"), type="password",
                                placeholder=("****" + os.getenv("LLM_API_KEY", "")[-4:])
                                if os.getenv("LLM_API_KEY") else t("cfg.no_key"))
        st.text_input(t("cfg.model"), key="cfg_model")

        if st.button(t("cfg.save"), type="primary", use_container_width=True):
            updates = {"LLM_BASE_URL": st.session_state["cfg_base_url"].strip(),
                       "LLM_MODEL": st.session_state["cfg_model"].strip()}
            if api_key.strip():
                updates["LLM_API_KEY"] = api_key.strip()
            update_env_file(_ROOT / ".env", updates)
            for key, value in updates.items():  # 进程内即时生效
                os.environ[key] = value
            st.toast(t("cfg.saved"))
            st.rerun()

        st.caption(t("cfg.current", model=os.getenv("LLM_MODEL", "?"),
                    url=os.getenv("LLM_BASE_URL", "?")))
