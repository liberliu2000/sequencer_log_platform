from __future__ import annotations

import io
import json
import os
import textwrap
import time
from typing import Any

from app.core.bootstrap import bootstrap_for_local_run

bootstrap_for_local_run()

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import yaml

st.set_page_config(page_title="测序仪日志整理及问题反馈系统", layout="wide")

DEFAULT_API_BASE = os.getenv("STREAMLIT_API_BASE", "http://127.0.0.1:8000/api/v1")
DURATION_UNITS = {"毫秒(ms)": "ms", "秒(s)": "s", "分钟(min)": "min", "小时(h)": "h"}
CHART_HEIGHT = 400


def inject_layout_guard_css() -> None:
    st.markdown(
        """
<style>
.block-container {
  padding-top: 1rem;
  padding-bottom: 2rem;
}
.element-container {
  margin-bottom: 0.75rem;
}
[data-testid="column"] {
  overflow: visible !important;
}
[data-testid="stPlotlyChart"] {
  width: 100% !important;
  min-height: 380px !important;
  position: relative !important;
  isolation: isolate !important;
  overflow: hidden !important;
}
[data-testid="stPlotlyChart"] > div,
.js-plotly-plot,
.plot-container,
.svg-container {
  width: 100% !important;
}
.js-plotly-plot .plotly .modebar {
  z-index: 20 !important;
}
[data-testid="stDataFrame"],
[data-testid="stTable"] {
  width: 100% !important;
}
div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stPlotlyChart"]) {
  width: 100% !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _safe_cell(value: Any):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, dict)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
    if hasattr(value, "_repr_html_"):
        return str(value)
    return str(value)


def coerce_df(data: Any):
    try:
        df = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data).copy()
    except Exception:
        return data
    for col in df.columns:
        try:
            df[col] = df[col].map(_safe_cell)
        except Exception:
            df[col] = df[col].astype(str)
    return df


def safe_dataframe(data=None, *, use_container_width=True, height=None):
    df = coerce_df(data)
    if isinstance(df, pd.DataFrame):
        st.dataframe(df, use_container_width=use_container_width, height=height)
    else:
        st.code(str(df))


def safe_json(data=None):
    def convert(obj):
        if isinstance(obj, dict):
            return {str(k): convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(v) for v in obj]
        return _safe_cell(obj)

    try:
        st.json(convert(data))
    except Exception:
        st.code(str(data))


def safe_text_block(data, *, language=None):
    if isinstance(data, (dict, list)):
        try:
            st.code(json.dumps(data, ensure_ascii=False, indent=2, default=str), language=language)
            return
        except Exception:
            pass
    st.code(str(data), language=language)


def chart_container(title: str | None = None, caption: str | None = None):
    container = st.container(border=True)
    with container:
        if title:
            st.markdown(f"#### {title}")
        if caption:
            st.caption(caption)
    return container


def render_fig(fig, *, key: str, height: int = CHART_HEIGHT, title: str | None = None, caption: str | None = None):
    fig.update_layout(
        height=height,
        autosize=True,
        margin=dict(l=10, r=10, t=60, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        uirevision=key,
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    with chart_container(title=title, caption=caption):
        st.plotly_chart(
            fig,
            use_container_width=True,
            key=key,
            config={
                "responsive": True,
                "displayModeBar": True,
                "displaylogo": False,
                "scrollZoom": False,
                "modeBarButtonsToAdd": ["autoScale2d", "resetScale2d"],
                "toImageButtonOptions": {"format": "png", "filename": key},
            },
        )




def safe_to_datetime(series):
    """兼容混合 ISO8601/毫秒/斜杠格式时间。"""
    try:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    except TypeError:
        return pd.to_datetime(series, errors="coerce", infer_datetime_format=True)

def _short_label(s: str, width: int = 28) -> str:
    if not s:
        return s
    return textwrap.shorten(str(s), width=width, placeholder="…")


def _safe_iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def api_get(path: str, **params):
    try:
        resp = requests.get(f"{API_BASE}{path}", params=params, timeout=60)
        resp.raise_for_status()
        return True, resp.json()
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text
        return False, f"GET {path} 失败: HTTP {exc.response.status_code} | {detail}"
    except Exception as exc:
        return False, f"GET {path} 失败: {exc}"


def api_post(path: str, **kwargs):
    try:
        resp = requests.post(f"{API_BASE}{path}", timeout=300, **kwargs)
        resp.raise_for_status()
        return True, resp.json()
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text
        return False, f"POST {path} 失败: HTTP {exc.response.status_code} | {detail}"
    except Exception as exc:
        return False, f"POST {path} 失败: {exc}"


def api_put(path: str, payload: dict):
    try:
        resp = requests.put(f"{API_BASE}{path}", json=payload, timeout=60)
        resp.raise_for_status()
        return True, resp.json()
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text
        return False, f"PUT {path} 失败: HTTP {exc.response.status_code} | {detail}"
    except Exception as exc:
        return False, f"PUT {path} 失败: {exc}"


def api_delete(path: str):
    try:
        resp = requests.delete(f"{API_BASE}{path}", timeout=60)
        resp.raise_for_status()
        return True, resp.json() if resp.text else {"success": True}
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json()
        except Exception:
            detail = exc.response.text
        return False, f"DELETE {path} 失败: HTTP {exc.response.status_code} | {detail}"
    except Exception as exc:
        return False, f"DELETE {path} 失败: {exc}"


def show_api_error(msg: str):
    st.error(msg)
    st.caption("请确认 FastAPI 已启动、端口地址正确，且数据库已初始化。")


def check_api_health() -> tuple[bool, str]:
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=5)
        resp.raise_for_status()
        return True, resp.json().get("status", "ok")
    except Exception as exc:
        return False, str(exc)


def _prepare_step_frames(step_rows: list[dict], cycle_rows: list[dict]):
    steps_df = pd.DataFrame(step_rows)
    cycles_df = pd.DataFrame(cycle_rows)
    for df, col in [(steps_df, "duration_ms"), (cycles_df, "total_duration_ms"), (cycles_df, "total_duration_value")]:
        if not df.empty and col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return steps_df, cycles_df


def load_tasks() -> list[dict]:
    ok, tasks = api_get("/tasks")
    return tasks if ok else []


def load_overview() -> dict:
    ok, data = api_get("/tasks/overview")
    return data if ok else {}


def load_cycles(task_uuid: str) -> list[int]:
    ok, cycles = api_get(f"/tasks/{task_uuid}/cycles")
    return cycles if ok else []


def _selected_cycle(task_uuid: str, key: str) -> int | None:
    cycles = load_cycles(task_uuid)
    options = ["全程"] + [str(c) for c in cycles]
    sel = st.selectbox("选择 Cycle", options, key=key)
    return None if sel == "全程" else int(sel)


def _history_task_options(tasks: list[dict]) -> tuple[dict[str, str], list[str]]:
    label_to_uuid: dict[str, str] = {}
    for t in tasks:
        created = _safe_iso(t.get("created_at"))
        task_id = str(t.get("task_uuid", ""))
        label = f"{created} | {task_id[:8]} | {t.get('status', '')} | {t.get('filename', '')}"
        label_to_uuid[label] = task_id
    labels = ["(不选择历史任务)"] + list(label_to_uuid.keys())
    return label_to_uuid, labels


inject_layout_guard_css()
st.title("测序仪日志整理及问题反馈系统")
API_BASE = st.sidebar.text_input("FastAPI 地址", value=st.session_state.get("api_base", DEFAULT_API_BASE))
st.session_state["api_base"] = API_BASE
api_ok, api_msg = check_api_health()
if api_ok:
    st.sidebar.success(f"API 连接正常: {api_msg}")
else:
    st.sidebar.error("API 未连通，请先启动 FastAPI。")
    st.sidebar.caption(api_msg)

tasks = load_tasks() if api_ok else []
label_to_uuid, labels = _history_task_options(tasks)
default_uuid = st.session_state.get("latest_task_uuid", "")
default_label = next((label for label, uuid in label_to_uuid.items() if uuid == default_uuid), labels[0])
selected_label = st.sidebar.selectbox("历史任务", labels, index=labels.index(default_label) if default_label in labels else 0)
if selected_label != labels[0]:
    st.session_state["latest_task_uuid"] = label_to_uuid[selected_label]
manual_uuid = st.sidebar.text_input("任务 UUID", value=st.session_state.get("latest_task_uuid", ""))
if manual_uuid:
    st.session_state["latest_task_uuid"] = manual_uuid.strip()

task_uuid = st.session_state.get("latest_task_uuid", "")

with st.sidebar.expander("项目管理", expanded=False):
    st.caption("可在此删除当前选中的历史项目。删除后相关事件、错误簇、LLM 结果与导出数据将一并移除。")
    if task_uuid:
        st.code(str(task_uuid))
        if st.checkbox("我确认删除该历史项目", key="confirm_delete_task"):
            if st.button("删除当前项目", type="secondary"):
                ok_del, resp_del = api_delete(f"/tasks/{task_uuid}")
                if ok_del:
                    st.session_state["latest_task_uuid"] = ""
                    st.success("项目已删除")
                    st.rerun()
                else:
                    show_api_error(resp_del)
    else:
        st.info("当前未选择历史项目。")

page = st.sidebar.radio(
    "导航",
    ["首页 / 仪表盘", "文件上传", "统一事件流", "耗时分析", "事件流时间轴", "错误分析", "LLM 诊断", "原始文件预览", "配置页面", "导出"],
)

if page == "文件上传":
    st.subheader("文件上传")
    uploaded = st.file_uploader("支持多文件与压缩包（zip / 7z / tar）", accept_multiple_files=True)
    if uploaded and st.button("开始批量上传并分析"):
        files_payload = [("files", (f.name, f.getvalue(), f.type or "application/octet-stream")) for f in uploaded]
        ok, result = api_post("/tasks/upload", files=files_payload)
        if ok:
            st.success("任务已提交，后端正在后台处理中")
            st.session_state["latest_task_uuid"] = result["task_uuid"]
            task_uuid = result["task_uuid"]
            safe_json(result)
        else:
            show_api_error(result)

    auto_refresh = st.checkbox("处理期间自动刷新进度", value=True)
    if task_uuid:
        ok, status = api_get(f"/tasks/{task_uuid}/status")
        if ok:
            st.markdown("### 当前任务进度")
            st.progress(int(status.get("progress_percent", 0)))
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("状态", status.get("status", "-"))
            c2.metric("进度", f"{status.get('progress_percent', 0)}%")
            c3.metric("识别文件数", status.get("file_count", 0))
            c4.metric("队列位置", status.get("queue_position") or 0)
            st.info(status.get("current_stage") or "-")
            if status.get("message"):
                st.caption(status["message"])
            refresh_col1, refresh_col2 = st.columns([1, 5])
            with refresh_col1:
                if st.button("刷新进度"):
                    st.rerun()
            with refresh_col2:
                st.caption("自动刷新只在当前上传页生效，以减少全页面高频重绘。")
            if auto_refresh and status.get("status") in {"queued", "processing"}:
                time.sleep(4)
                st.rerun()
        else:
            show_api_error(status)

    st.markdown("### 历史任务")
    if tasks:
        safe_dataframe(pd.DataFrame(tasks), use_container_width=True, height=320)
    else:
        st.info("暂无历史任务。")

elif page == "首页 / 仪表盘":
    overview = load_overview() if api_ok else {}
    st.markdown("### 项目总览")
    ov1, ov2, ov3, ov4 = st.columns(4)
    ov1.metric("项目总数", overview.get("total_projects", 0))
    ov2.metric("处理中项目", overview.get("processing_projects", 0))
    ov3.metric("已完成项目", overview.get("completed_projects", 0))
    ov4.metric("失败项目", overview.get("failed_projects", 0))

    processing_df = pd.DataFrame(overview.get("processing_details", []))
    latest_df = pd.DataFrame(overview.get("latest_projects", []))

    summary_tab, active_tab, history_tab = st.tabs(["当前摘要", "正在处理的项目", "最近历史项目"])
    with active_tab:
        if processing_df.empty:
            st.info("当前没有正在处理的项目。")
        else:
            cols = [c for c in ["task_uuid", "filename", "status", "progress_percent", "current_stage", "updated_at"] if c in processing_df.columns]
            safe_dataframe(processing_df[cols], use_container_width=True, height=280)
    with history_tab:
        if latest_df.empty:
            st.info("暂无历史项目。")
        else:
            cols = [c for c in ["task_uuid", "filename", "status", "file_count", "total_errors", "created_at"] if c in latest_df.columns]
            safe_dataframe(latest_df[cols], use_container_width=True, height=280)
            select_options = {f"{_safe_iso(r.get('created_at'))} | {r.get('status', '')} | {r.get('filename', '')}": r.get("task_uuid", "") for _, r in latest_df.iterrows()}
            selected_recent = st.selectbox("从历史项目中切换查看", ["(不切换)"] + list(select_options.keys()))
            if selected_recent != "(不切换)" and st.button("打开该历史项目"):
                st.session_state["latest_task_uuid"] = select_options[selected_recent]
                st.rerun()

    with summary_tab:
        if not task_uuid:
            st.info("请先在左侧选择一个任务 UUID 查看详细仪表盘。")
        else:
            st.markdown(f"### 当前查看项目：`{task_uuid}`")
            unit_label = st.selectbox("Cycle 总耗时单位", list(DURATION_UNITS.keys()), key="dash_unit")
            unit = DURATION_UNITS[unit_label]
            ok, data = api_get(f"/tasks/{task_uuid}/dashboard")
            ok2, cycles = api_get(f"/tasks/{task_uuid}/cycle-summary", unit=unit)
            ok3, ops = api_get(f"/tasks/{task_uuid}/operational-metrics")
            ok4, status = api_get(f"/tasks/{task_uuid}/status")
            if not ok:
                show_api_error(data)
            else:
                if ok4:
                    s1, s2, s3, s4 = st.columns(4)
                    s1.metric("任务状态", status.get("status", "-"))
                    s2.metric("处理进度", f"{status.get('progress_percent', 0)}%")
                    s3.metric("识别文件数", status.get("file_count", 0))
                    s4.metric("当前阶段", status.get("current_stage") or "-")
                    st.progress(int(status.get("progress_percent", 0)))
                    if status.get("message"):
                        st.caption(status.get("message"))
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("文件数", data.get("file_count", 0))
                c2.metric("总事件数", data.get("total_events", 0))
                c3.metric("总错误数", data.get("total_errors", 0))
                c4.metric("唯一错误数", data.get("unique_error_count", 0))

                top_df = pd.DataFrame(data.get("top_errors", []))
                comp_df = pd.DataFrame(data.get("component_distribution", []))
                chart_tabs = st.tabs(["高频问题", "部件分布", "周期趋势", "cPAS 预吸液"])
                with chart_tabs[0]:
                    if not top_df.empty:
                        plot_df = top_df.copy()
                        plot_df["label"] = plot_df["display_signature"].map(_short_label)
                        fig = px.bar(plot_df, x="label", y="count", color="error_family", hover_data=["display_signature", "component"])
                        fig.update_xaxes(tickangle=-25)
                        render_fig(fig, key="dash_top", title="近期高频问题 Top N", caption="改为单图容器展示，避免与相邻图表在窄窗口下互相覆盖。")
                    else:
                        st.info("当前任务暂无错误簇。")
                with chart_tabs[1]:
                    if not comp_df.empty:
                        render_fig(px.pie(comp_df, names="component", values="count"), key="dash_pie", title="各部件错误分布")
                    else:
                        st.info("当前任务暂无错误部件分布。")
                with chart_tabs[2]:
                    if ok2:
                        cycle_df = pd.DataFrame(cycles)
                        if not cycle_df.empty:
                            render_fig(
                                px.line(cycle_df, x="cycle_no", y="total_duration_value", color="chip_name", markers=True, hover_data=["started_at_text", "ended_at_text"]),
                                key="dash_cycle",
                                title=f"周期总耗时趋势({unit})",
                            )
                            with st.expander("查看周期总耗时明细", expanded=False):
                                safe_dataframe(cycle_df, use_container_width=True)
                        else:
                            st.info("暂无周期总耗时数据。")
                with chart_tabs[3]:
                    if ok3:
                        prim_df = pd.DataFrame(ops.get("cpas_priming_summary", []))
                        if not prim_df.empty:
                            safe_dataframe(prim_df, use_container_width=True, height=260)
                        else:
                            st.info("暂无 cPAS 预吸液摘要。")

                st.markdown("### 历史项目列表")
                if latest_df.empty:
                    st.info("暂无历史项目。")
                else:
                    hist_df = latest_df.copy()
                    hist_df["is_current"] = hist_df["task_uuid"].eq(task_uuid).map({True: "当前项目", False: "历史项目"})
                    cols = [c for c in ["is_current", "task_uuid", "filename", "status", "file_count", "total_events", "total_errors", "created_at", "updated_at"] if c in hist_df.columns]
                    safe_dataframe(hist_df[cols], use_container_width=True, height=320)

                ok_audit, audit_rows = api_get(f"/tasks/{task_uuid}/audit-logs")
                if ok_audit and audit_rows:
                    st.markdown("### 任务级审计日志")
                    safe_dataframe(pd.DataFrame(audit_rows), use_container_width=True, height=240)

elif page == "统一事件流":
    if not task_uuid:
        st.info("请先选择任务 UUID。")
    else:
        col1, col2, col3, col4, col5 = st.columns(5)
        component = col1.text_input("部件过滤")
        level = col2.selectbox("级别", ["", "INFO", "WARN", "ERROR", "FATAL"])
        cycle_no = col3.text_input("Cycle")
        chip_name = col4.text_input("芯片名")
        search = col5.text_input("关键字")
        ok, rows = api_get(
            f"/tasks/{task_uuid}/events",
            component=component or None,
            level=level or None,
            cycle_no=int(cycle_no) if cycle_no.strip() else None,
            chip_name=chip_name or None,
            search=search or None,
            limit=2000,
        )
        if ok:
            safe_dataframe(pd.DataFrame(rows), use_container_width=True, height=620)
        else:
            show_api_error(rows)

elif page == "耗时分析":
    if not task_uuid:
        st.info("请先选择任务 UUID。")
    else:
        unit = DURATION_UNITS[st.selectbox("Cycle 总耗时单位", list(DURATION_UNITS.keys()), key="ana_unit")]
        cycle_sel = _selected_cycle(task_uuid, "ana_cycle_pick")
        ok, step_rows = api_get(f"/tasks/{task_uuid}/steps", cycle_no=cycle_sel)
        ok2, cycle_rows = api_get(f"/tasks/{task_uuid}/cycle-summary", unit=unit)
        ok3, ops = api_get(f"/tasks/{task_uuid}/operational-metrics", cycle_no=cycle_sel)
        if ok and ok2:
            df, cycle_df = _prepare_step_frames(step_rows, cycle_rows)
            if cycle_sel is not None and not cycle_df.empty:
                cycle_df = cycle_df[cycle_df["cycle_no"] == cycle_sel]

            data_tab, trend_tab, photo_tab, extra_tab = st.tabs(["表格", "趋势图", "拍照/成像", "机械臂/cPAS/温控"])
            with data_tab:
                st.markdown("### 周期总耗时表")
                safe_dataframe(cycle_df, use_container_width=True, height=220)
                st.markdown("### Sub-step 耗时表")
                safe_dataframe(df, use_container_width=True, height=320)
                if not df.empty:
                    over_df = df[df.get("is_over_threshold") == True] if "is_over_threshold" in df.columns else pd.DataFrame()
                    st.markdown("### 超阈值告警")
                    safe_dataframe(over_df, use_container_width=True, height=220)
            with trend_tab:
                if not cycle_df.empty:
                    render_fig(
                        px.line(cycle_df, x="cycle_no", y="total_duration_value", color="chip_name", markers=True, hover_data=["started_at_text", "ended_at_text"]),
                        key="ana_cycle",
                        title=f"Cycle 总耗时趋势({unit})",
                    )
                if not df.empty:
                    trend_df = df.dropna(subset=["duration_ms", "cycle_no"]).copy()
                    if not trend_df.empty:
                        top_steps = trend_df.groupby("sub_step", as_index=False)["duration_ms"].mean().sort_values("duration_ms", ascending=False).head(12)
                        top_steps["label"] = top_steps["sub_step"].map(_short_label)
                        fig = px.bar(top_steps, x="label", y="duration_ms", hover_data=["sub_step"])
                        fig.update_xaxes(tickangle=-25)
                        render_fig(fig, key="ana_steps", title="步骤平均耗时(ms)")
            if ok3:
                with photo_tab:
                    st.markdown("### 拍照时间")
                    photo_df = pd.DataFrame(ops.get("photo_summary", []))
                    safe_dataframe(photo_df, use_container_width=True, height=240)
                    metric_df = pd.DataFrame(ops.get("metric_stage_avg", []))
                    if not metric_df.empty:
                        fig = px.bar(metric_df, x="metric_stage", y="avg_duration_ms", color="cycle_no", hover_data=["row_count", "chip_name"])
                        fig.update_xaxes(tickangle=-25)
                        render_fig(fig, key="metric_avg", title="metrics 文件每 cycle 行扫阶段平均时间(ms)")
                        safe_dataframe(metric_df, use_container_width=True, height=300)
                with extra_tab:
                    transfer_df = pd.DataFrame(ops.get("transfer_summary", []))
                    prim_df = pd.DataFrame(ops.get("cpas_priming_summary", []))
                    temp_df = pd.DataFrame(ops.get("temperature_times", []))
                    if not transfer_df.empty:
                        st.markdown("### 机械臂转移时间")
                        safe_dataframe(transfer_df, use_container_width=True, height=220)
                    if not prim_df.empty:
                        st.markdown("### cPAS 预吸液时间")
                        safe_dataframe(prim_df, use_container_width=True, height=220)
                    if not temp_df.empty:
                        render_fig(
                            px.bar(temp_df, x="temperature_phase", y="duration_ms", color="cycle_no", barmode="group", hover_data=["slide", "target_temperature", "chip_name"]),
                            key="temp_phases",
                            title="温控时间(ms)",
                        )
                        safe_dataframe(temp_df, use_container_width=True, height=260)
        else:
            show_api_error(step_rows if not ok else cycle_rows)

elif page == "事件流时间轴":
    if not task_uuid:
        st.info("请先选择任务 UUID。")
    else:
        cycle_sel = _selected_cycle(task_uuid, "timeline_cycle_pick")
        ok, rows = api_get(f"/tasks/{task_uuid}/movement-timeline", cycle_no=cycle_sel)
        if ok:
            df = pd.DataFrame(rows)
            if not df.empty:
                df["start"] = safe_to_datetime(df["start"])
                df["end"] = safe_to_datetime(df["end"])
                df = df.dropna(subset=["start", "end"]).copy()
                render_fig(
                    px.timeline(df, x_start="start", x_end="end", y="track", color="sub_step", hover_data=["component", "cycle_no", "chip_name", "duration_ms", "start_time_sec", "end_time_sec"]),
                    key="timeline",
                    height=480,
                    title="按 Cycle / 全程 的各部件运动时间轴",
                )
                cols = [c for c in ["cycle_no", "chip_name", "component", "sub_step", "duration_ms", "start_time_sec", "end_time_sec"] if c in df.columns]
                safe_dataframe(df[cols], use_container_width=True, height=320)
            else:
                st.info("当前筛选条件下暂无可成对展示的运动时间轴。")
        else:
            show_api_error(rows)

elif page == "错误分析":
    if not task_uuid:
        st.info("请先选择任务 UUID。")
    else:
        ok, rows = api_get(f"/tasks/{task_uuid}/errors")
        if ok:
            df = pd.DataFrame(rows)
            safe_dataframe(df, use_container_width=True, height=320)
            if not df.empty:
                chart_tab1, chart_tab2, chart_tab3 = st.tabs(["错误簇 Top N", "错误家族分布", "回归趋势"])
                with chart_tab1:
                    plot_df = df.head(20).copy()
                    plot_df["label"] = plot_df["display_signature"].map(_short_label)
                    fig1 = px.bar(plot_df, x="label", y="count", color="severity", hover_data=["display_signature", "component", "error_family"])
                    fig1.update_xaxes(tickangle=-25)
                    render_fig(fig1, key="err_top", title="Top 错误簇")
                with chart_tab2:
                    family_df = df.groupby("error_family", as_index=False)["count"].sum().sort_values("count", ascending=False)
                    family_df["error_family"] = family_df["error_family"].fillna("未知")
                    render_fig(px.pie(family_df, names="error_family", values="count"), key="err_family", title="错误家族分布")
                with chart_tab3:
                    trend_bucket = st.selectbox("错误回归趋势粒度", ["day", "week"], index=0)
                    selected_sig = st.selectbox(
                        "回归趋势错误簇",
                        df["normalized_signature"].tolist(),
                        format_func=lambda x: _short_label(df[df["normalized_signature"] == x]["display_signature"].iloc[0], 60),
                    )
                    ok_t, trend_rows = api_get(f"/tasks/{task_uuid}/errors/trend", signature=selected_sig, bucket=trend_bucket)
                    if ok_t and trend_rows:
                        trend_df = pd.DataFrame(trend_rows)
                        render_fig(px.line(trend_df, x="bucket", y="count", markers=True), key="err_trend", title=f"错误簇回归趋势({trend_bucket})")
        else:
            show_api_error(rows)

elif page == "LLM 诊断":
    if not task_uuid:
        st.info("请先选择任务 UUID。")
    else:
        ok, rows = api_get(f"/tasks/{task_uuid}/errors")
        ok_hist, hist_rows = api_get(f"/tasks/{task_uuid}/llm-results")
        if ok_hist and hist_rows:
            hist_df = pd.DataFrame(hist_rows)
            with st.expander("历史 LLM 诊断结果", expanded=False):
                show_cols = [c for c in ["normalized_signature", "model_name", "analysis_stage", "created_at", "chinese_summary"] if c in hist_df.columns]
                safe_dataframe(hist_df[show_cols], use_container_width=True, height=260)
        if ok:
            df = pd.DataFrame(rows)
            if df.empty:
                st.info("当前任务没有错误簇。")
            else:
                options = {f"{_short_label(r['display_signature'], 60)} ({r['count']})": r["normalized_signature"] for _, r in df.iterrows()}
                selected = st.selectbox("选择错误簇", list(options.keys()))
                force = st.checkbox("忽略缓存，重新调用 LLM", value=False)
                if st.button("开始诊断"):
                    ok2, result = api_post(f"/tasks/{task_uuid}/errors/{options[selected]}/analyze?force={'true' if force else 'false'}")
                    if ok2:
                        if result.get("from_cache"):
                            st.info("已返回历史诊断结果。")
                        st.markdown("### 中文摘要")
                        st.text(str(result.get("chinese_summary", "")))
                        ctx = result.get("context_summary", {})
                        if ctx:
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("压缩前日志条数", ctx.get("raw_line_count", 0))
                            c2.metric("压缩后日志条数", ctx.get("compressed_line_count", 0))
                            c3.metric("估算 Token", ctx.get("compressed_estimated_tokens", 0))
                            c4.metric("压缩比例", f"{round((1 - float(ctx.get('token_compression_ratio', 1.0))) * 100, 1)}%")
                            st.caption(f"分析阶段：{result.get('analysis_stage', 'light')} | Token 预算：{ctx.get('token_budget', 0)}")
                        req = result.get("request_payload", {})
                        preview = req.get("compressed_context_preview", [])
                        with st.expander("最小必要上下文预览", expanded=False):
                            if preview:
                                safe_dataframe(pd.DataFrame(preview), use_container_width=True, height=260)
                            else:
                                st.info("当前没有可展示的上下文预览。")
                        st.caption(f"Prompt 模板版本：{result.get('prompt_version', '-')}")
                        st.markdown("### 结构化 JSON")
                        safe_json(result.get("structured_result", {}))
                    else:
                        show_api_error(result)
        else:
            show_api_error(rows)

elif page == "原始文件预览":
    if not task_uuid:
        st.info("请先选择任务 UUID。")
    else:
        ok, files = api_get(f"/tasks/{task_uuid}/files")
        if ok and files:
            files_df = pd.DataFrame(files)
            selected_file = st.selectbox("选择原始文件", files_df["relative_path"].tolist())
            max_lines = st.slider("预览行数", 20, 500, 120, 20)
            if st.button("加载原始文件预览"):
                ok2, preview = api_get(f"/tasks/{task_uuid}/files/preview", relative_path=selected_file, max_lines=max_lines)
                if ok2:
                    st.caption(
                        f"文件: {preview.get('relative_path')} | 类型: {preview.get('mime_type', 'unknown')} | 编码: {preview.get('encoding', 'unknown')} | 预览行数: {preview.get('line_count')}"
                    )
                    safe_text_block("\n".join(preview.get("preview", [])))
                else:
                    show_api_error(preview)
            safe_dataframe(files_df, use_container_width=True, height=260)
        else:
            st.info("当前任务暂无可预览原始文件。")

elif page == "配置页面":
    ok, data = api_get("/config")
    if ok:
        st.markdown("### LLM 配置")
        safe_json(data.get("llm", {}))
        thresholds = data.get("thresholds", {})
        llm_context_cfg = thresholds.get("llm_context", {})
        with st.expander("LLM 最小必要上下文参数", expanded=True):
            lc1, lc2, lc3, lc4 = st.columns(4)
            llm_pre = lc1.number_input("前文条数", min_value=0, value=int(llm_context_cfg.get("pre_lines", 8)), step=1)
            llm_post = lc2.number_input("后文条数", min_value=0, value=int(llm_context_cfg.get("post_lines", 8)), step=1)
            llm_window = lc3.number_input("时间窗口(秒)", min_value=10, value=int(llm_context_cfg.get("time_window_seconds", 90)), step=10)
            llm_stack = lc4.number_input("最大堆栈帧数", min_value=1, value=int(llm_context_cfg.get("max_stack_frames", 8)), step=1)
            lc5, lc6, lc7, lc8 = st.columns(4)
            llm_comp = lc5.number_input("同组件相关日志上限", min_value=1, value=int(llm_context_cfg.get("related_component_limit", 30)), step=1)
            llm_cycle = lc6.number_input("同 Cycle 相关日志上限", min_value=1, value=int(llm_context_cfg.get("related_cycle_limit", 30)), step=1)
            llm_stage1 = lc7.number_input("轻量分析 Token 预算", min_value=200, value=int(llm_context_cfg.get("stage1_token_budget", 1200)), step=100)
            llm_budget = lc8.number_input("最大 Token 预算", min_value=500, value=int(llm_context_cfg.get("max_token_budget", 2200)), step=100)
        prompt_templates = data.get("prompt_templates", {})
        versions = list((prompt_templates.get("templates") or {}).keys())
        if versions:
            st.markdown("### LLM Prompt 模板版本管理")
            current_ver = prompt_templates.get("active_version")
            new_ver = st.selectbox("当前 Prompt 版本", versions, index=versions.index(current_ver) if current_ver in versions else 0)
            if st.button("切换 Prompt 版本"):
                okp, respp = api_put("/config/prompt-templates/active", {"version": new_ver})
                if okp:
                    st.success("Prompt 版本已切换")
                else:
                    show_api_error(respp)
        st.markdown("### 阈值输入框")
        default_threshold = st.number_input("默认阈值(ms)", min_value=0, value=int(thresholds.get("default_threshold_ms", 10000)), step=100)
        step_thresholds = thresholds.get("step_thresholds_ms", {})
        editable_keys = [
            "MoveStageFromLoadPosToFirstField",
            "CoarseThetaWithoutMoveStage",
            "FineAlign",
            "Row scan",
            "cPAS reagent priming",
            "升温时间 N",
            "升温时间 F",
            "降温时间 N",
            "降温时间 F",
        ]
        default_rules = step_thresholds.get("default", {})
        new_default_rules = dict(default_rules)
        cols = st.columns(2)
        for idx, threshold_key in enumerate(editable_keys):
            shown = cols[idx % 2].number_input(
                f"{threshold_key} 阈值(ms)",
                min_value=0,
                value=int(default_rules.get(threshold_key, default_threshold)),
                step=100,
            )
            new_default_rules[threshold_key] = shown
        thresholds_text = st.text_area("完整阈值 YAML", value=yaml.safe_dump(thresholds, allow_unicode=True, sort_keys=False), height=260)
        if st.button("保存阈值配置"):
            payload = yaml.safe_load(io.StringIO(thresholds_text)) or {}
            payload["default_threshold_ms"] = default_threshold
            payload.setdefault("step_thresholds_ms", {}).setdefault("default", {}).update(new_default_rules)
            payload["llm_context"] = {
                "pre_lines": int(llm_pre),
                "post_lines": int(llm_post),
                "time_window_seconds": int(llm_window),
                "related_component_limit": int(llm_comp),
                "related_cycle_limit": int(llm_cycle),
                "max_stack_frames": int(llm_stack),
                "max_token_budget": int(llm_budget),
                "stage1_token_budget": int(llm_stage1),
            }
            ok2, resp = api_put("/config/thresholds", payload)
            if ok2:
                st.success("阈值已保存")
            else:
                show_api_error(resp)
    else:
        show_api_error(data)

elif page == "导出":
    if task_uuid:
        st.markdown(f"[导出统一事件 CSV]({API_BASE}/tasks/{task_uuid}/export/events)")
        st.markdown(f"[导出错误分析 CSV]({API_BASE}/tasks/{task_uuid}/export/errors)")
        st.markdown(f"[导出 JSON 报告]({API_BASE}/tasks/{task_uuid}/export/report.json)")
        st.markdown(f"[导出 Excel 报告]({API_BASE}/tasks/{task_uuid}/export/report.xlsx)")
        st.markdown(f"[导出 PDF 报告]({API_BASE}/tasks/{task_uuid}/export/report.pdf)")
    else:
        st.info("请先选择任务 UUID。")
