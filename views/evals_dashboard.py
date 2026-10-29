"""评测看板页面：交互式浏览 evals/results/ 下的跨框架对比数据。

数据函数直接复用 evals/compare.py（同一套口径：每框架取任务数最多的最新
全量运行），保证看板与 COMPARISON.md / README 永远同源。
"""
import pandas as pd
import streamlit as st

from evals.compare import CONFIG_ORDER, aggregate, load_runs, pick_best
from mini_agents.i18n import t
from views._shared import render_lang_switcher, render_model_settings

render_lang_switcher()
render_model_settings()
st.title(t("dash.title"))
st.caption(t("dash.caption"))

runs = load_runs()
if not runs:
    st.warning(t("dash.warn_no_runs"))
    st.stop()

frameworks = list(dict.fromkeys(r["framework"] for r in runs))
selected = st.multiselect(t("dash.frameworks"), frameworks, default=frameworks)
picks = {fw: pick_best(runs, fw) for fw in selected}
picks = {fw: run for fw, run in picks.items() if run}

if not picks:
    st.info(t("dash.info_none"))
    st.stop()

st.caption("　|　".join(t("dash.fw_line", fw=f"**{fw}**",
                          model=run["rows"][0].get("model", "?"),
                          dir=run["dir"], n=len(run["rows"]))
                        for fw, run in picks.items()))

configs = [c for c in CONFIG_ORDER
           if any(aggregate(run["rows"], c) for run in picks.values())]
if not configs:
    st.info(t("dash.info_no_tasks"))
    st.stop()
config = st.selectbox(t("dash.config"), configs)

# ── 指标表 ──────────────────────────────────────────────────────
rows = []
chart_rows = []
for fw, run in picks.items():
    a = aggregate(run["rows"], config)
    if not a:
        continue
    rows.append({t("dash.col_fw"): fw, t("dash.col_model"): run["rows"][0].get("model", "?"),
                 t("dash.col_success"): f"{a['success'] / a['n']:.0%}",
                 t("dash.col_sn"): f"{a['success']}/{a['n']}",
                 t("dash.col_tokens"): int(a["tokens"]),
                 t("dash.col_seconds"): round(a["seconds"], 1)})
    chart_rows.append({t("dash.col_fw"): fw,
                       t("dash.metric_success"): a["success"] / a["n"] * 100,
                       t("dash.metric_tokens"): a["tokens"],
                       t("dash.metric_seconds"): a["seconds"]})

st.dataframe(rows, hide_index=True, use_container_width=True)

# ── 柱状图 ──────────────────────────────────────────────────────
metric = st.radio(t("dash.metric"),
                  [t("dash.metric_success"), t("dash.metric_tokens"),
                   t("dash.metric_seconds")], horizontal=True)
chart_df = pd.DataFrame(chart_rows).set_index(t("dash.col_fw"))
st.bar_chart(chart_df[[metric]])

# ── 逐任务矩阵 ──────────────────────────────────────────────────
st.subheader(t("dash.matrix_header"))
task_ids = sorted({r["task_id"] for run in picks.values() for r in run["rows"]})
matrix = []
for tid in task_ids:
    row = {t("dash.col_task"): tid}
    for fw, run in picks.items():
        rs = [r for r in run["rows"] if r["task_id"] == tid and r["config"] == config]
        row[fw] = "✓" if rs and rs[0]["success"] else ("✗" if rs else "-")
    matrix.append(row)
st.dataframe(matrix, hide_index=True, use_container_width=True)

# ── 失败明细 ────────────────────────────────────────────────────
st.subheader(t("dash.failures_header"))
for fw, run in picks.items():
    failures = [r for r in run["rows"] if not r["success"]]
    with st.expander(t("dash.fail_count", fw=fw, n=len(failures))):
        for f in failures:
            st.markdown(f"- **{f['task_id']}**（{f['config']}）：{f['detail']}")
