"""评测看板页面：交互式浏览 evals/results/ 下的跨框架对比数据。

数据函数直接复用 evals/compare.py（同一套口径：每框架取任务数最多的最新
全量运行），保证看板与 COMPARISON.md / README 永远同源。
"""
import pandas as pd
import streamlit as st

from evals.compare import CONFIG_ORDER, aggregate, load_runs, pick_best

st.title("📊 评测看板")
st.caption("数据源：evals/results/*/results.jsonl（每框架取任务数最多的最新全量运行）；"
           "三列共享同一任务集、提示词、工具与判分器。刷新浏览器即重新读取最新数据。")

runs = load_runs()
if not runs:
    st.warning("没有找到评测结果——先跑一次 `python -m evals`（或 `--framework langgraph` 等）。")
    st.stop()

frameworks = list(dict.fromkeys(r["framework"] for r in runs))
selected = st.multiselect("框架", frameworks, default=frameworks)
picks = {fw: pick_best(runs, fw) for fw in selected}
picks = {fw: run for fw, run in picks.items() if run}

if not picks:
    st.info("所选框架没有可展示的运行。")
    st.stop()

st.caption("　|　".join(f"**{fw}**：{run['rows'][0].get('model', '?')}"
                        f"（{run['dir']}，{len(run['rows'])} 条）"
                        for fw, run in picks.items()))

configs = [c for c in CONFIG_ORDER
           if any(aggregate(run["rows"], c) for run in picks.values())]
if not configs:
    st.info("所选运行里没有任务结果。")
    st.stop()
config = st.selectbox("配置", configs)

# ── 指标表 ──────────────────────────────────────────────────────
rows = []
chart_rows = []
for fw, run in picks.items():
    a = aggregate(run["rows"], config)
    if not a:
        continue
    rows.append({"框架": fw, "模型": run["rows"][0].get("model", "?"),
                 "成功率": f"{a['success'] / a['n']:.0%}",
                 "成功/总数": f"{a['success']}/{a['n']}",
                 "平均 tokens": int(a["tokens"]),
                 "平均耗时 (s)": round(a["seconds"], 1)})
    chart_rows.append({"框架": fw,
                       "成功率 (%)": a["success"] / a["n"] * 100,
                       "平均 tokens": a["tokens"],
                       "平均耗时 (s)": a["seconds"]})

st.dataframe(rows, hide_index=True, use_container_width=True)

# ── 柱状图 ──────────────────────────────────────────────────────
metric = st.radio("图表指标", ["成功率 (%)", "平均 tokens", "平均耗时 (s)"],
                  horizontal=True)
chart_df = pd.DataFrame(chart_rows).set_index("框架")
st.bar_chart(chart_df[[metric]])

# ── 逐任务矩阵 ──────────────────────────────────────────────────
st.subheader("逐任务结果")
task_ids = sorted({r["task_id"] for run in picks.values() for r in run["rows"]})
matrix = []
for tid in task_ids:
    row = {"任务": tid}
    for fw, run in picks.items():
        rs = [r for r in run["rows"] if r["task_id"] == tid and r["config"] == config]
        row[fw] = "✓" if rs and rs[0]["success"] else ("✗" if rs else "-")
    matrix.append(row)
st.dataframe(matrix, hide_index=True, use_container_width=True)

# ── 失败明细 ────────────────────────────────────────────────────
st.subheader("失败明细")
for fw, run in picks.items():
    failures = [r for r in run["rows"] if not r["success"]]
    with st.expander(f"{fw}：{len(failures)} 个失败"):
        for f in failures:
            st.markdown(f"- **{f['task_id']}**（{f['config']}）：{f['detail']}")
