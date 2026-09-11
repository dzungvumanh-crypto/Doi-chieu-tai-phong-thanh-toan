"""Thống kê kết quả khảo sát — tổng hợp theo câu, từng câu trả lời, tiến độ người nhận.

Biểu đồ: câu chọn đáp án / thang đo là so sánh ĐỘ LỚN giữa các lựa chọn của
MỘT chuỗi dữ liệu → cột một màu, nhãn số ở đầu cột, không legend. Không dùng
biểu đồ tròn: 5-10 lát gần bằng nhau thì mắt không so được lát nào lớn hơn.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from nicegui import ui

import frontend.api_client as api
import frontend.ui_kit as ui_kit
from frontend.shared import (_sidebar, _content_area, _page_header, _require_auth,
                             _handle_api_error, _query_params, _qp_int)
from frontend.survey_common import QTYPE_ICONS, fmt_dt, state_chip

_BAR = "#B91C1C"          # đỏ Agribank — một chuỗi dữ liệu nên một màu
_AXIS = "#6B7280"
_GRID = "#E5E7EB"
_VN = timezone(timedelta(hours=7))


def _tile(label: str, value: str, sub: str = ""):
    with ui.card().classes("flex-1 min-w-[10rem] rounded-xl shadow-sm p-4 gap-0 border border-gray-200"):
        ui.label(label).classes("text-xs text-gray-500")
        ui.label(value).classes("text-2xl font-bold text-gray-900")
        if sub:
            ui.label(sub).classes("text-xs text-gray-500")


def _con_lai(deadline: str | None) -> str:
    if not deadline:
        return ""
    try:
        # Giờ VN, cùng quy ước với _vn_now() phía backend — không lấy giờ của máy
        d = datetime.fromisoformat(deadline) - datetime.now(_VN).replace(tzinfo=None)
    except ValueError:
        return ""
    if d.total_seconds() <= 0:
        return "đã hết hạn"
    h = int(d.total_seconds() // 3600)
    return f"còn {h // 24} ngày {h % 24} giờ" if h >= 24 else f"còn {h} giờ"


def _bar_ngang(items: list[dict]):
    """Cột ngang cho câu lựa chọn — nhãn lựa chọn dài đọc được trọn vẹn."""
    ui.echart({
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} người"},
        "grid": {"left": 8, "right": 72, "top": 4, "bottom": 4, "containLabel": True},
        "xAxis": {"type": "value", "minInterval": 1, "splitLine": {"lineStyle": {"color": _GRID}},
                  "axisLabel": {"color": _AXIS, "fontSize": 11}},
        "yAxis": {"type": "category", "inverse": True, "data": [o["label"] for o in items],
                  "axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": _GRID}},
                  "axisLabel": {"color": "#374151", "fontSize": 12, "width": 220, "overflow": "break"}},
        "series": [{
            "type": "bar", "barMaxWidth": 22,
            "itemStyle": {"color": _BAR, "borderRadius": [0, 4, 4, 0]},
            "data": [{"value": o["count"],
                      "label": {"show": True, "position": "right", "color": "#374151", "fontSize": 12,
                                "formatter": f"{o['count']} ({o['pct']}%)"}} for o in items],
        }],
    }).classes("w-full").style(f"height: {max(90, 38 * len(items) + 24)}px")


def _cot_doc(items: list[dict]):
    """Cột đứng cho thang đo — trục ngang là điểm số có thứ tự."""
    ui.echart({
        "tooltip": {"trigger": "item", "formatter": "Điểm {b}: {c} người"},
        "grid": {"left": 8, "right": 8, "top": 26, "bottom": 4, "containLabel": True},
        "xAxis": {"type": "category", "data": [o["label"] for o in items], "axisTick": {"show": False},
                  "axisLine": {"lineStyle": {"color": _GRID}}, "axisLabel": {"color": "#374151"}},
        "yAxis": {"type": "value", "minInterval": 1, "splitLine": {"lineStyle": {"color": _GRID}},
                  "axisLabel": {"color": _AXIS, "fontSize": 11}},
        "series": [{
            "type": "bar", "barMaxWidth": 40,
            "itemStyle": {"color": _BAR, "borderRadius": [4, 4, 0, 0]},
            "data": [{"value": o["count"],
                      "label": {"show": o["count"] > 0, "position": "top", "color": "#374151",
                                "fontSize": 12, "formatter": f"{o['count']}"}} for o in items],
        }],
    }).classes("w-full").style("height: 220px")


def _stat_card(i: int, st: dict):
    with ui.card().classes("w-full rounded-xl shadow-sm p-5 gap-2 border border-gray-200"):
        with ui.row().classes("w-full items-start no-wrap gap-2"):
            ui.icon(QTYPE_ICONS.get(st["qtype"], "help")).classes("text-red-800 text-lg mt-0.5")
            ui.label(f"{i}. {st['title']}").classes("font-semibold text-gray-900 flex-1")
            ui.label(f"{st['answered']}/{st['total']} người trả lời").classes(
                "text-xs text-gray-500 whitespace-nowrap")
        if st["answered"] == 0:
            ui.label("Chưa có câu trả lời").classes("text-sm text-gray-400 italic")
            return
        if st["qtype"] == "scale":
            with ui.row().classes("items-baseline gap-2"):
                ui.label(f"{st['average']}").classes("text-3xl font-bold text-gray-900")
                ui.label(f"điểm trung bình / {st['options'][-1]['label']}").classes("text-sm text-gray-500")
            _cot_doc(st["options"])
            lo, hi = st.get("scale_min_label"), st.get("scale_max_label")
            if lo or hi:
                with ui.row().classes("w-full justify-between text-xs text-gray-500"):
                    ui.label(f"{st['options'][0]['label']} = {lo or ''}")
                    ui.label(f"{st['options'][-1]['label']} = {hi or ''}")
        elif "options" in st:
            if st["qtype"] == "multi":
                ui.label("Chọn nhiều — tổng % có thể vượt 100%").classes("text-xs text-gray-500")
            _bar_ngang(st["options"])
        else:
            with ui.column().classes("w-full gap-1 max-h-80 overflow-y-auto"):
                for t in st["texts"]:
                    with ui.element("div").classes("w-full bg-gray-50 rounded-lg px-3 py-2"):
                        ui.label(t["text"]).classes("text-sm text-gray-800 whitespace-pre-line")
                        if t.get("staff_name"):
                            ui.label(t["staff_name"]).classes("text-xs text-gray-500")


@ui.page("/surveys/results")
async def survey_results_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.surveys"):
        ui.navigate.to("/home")
        return
    sid = _qp_int(_query_params(), "id")
    if not sid:
        ui.navigate.to("/surveys")
        return

    await _sidebar("surveys")
    with _content_area():
        _page_header("Kết quả khảo sát", "Thống kê cập nhật theo thời gian thực mỗi lần mở trang")
        body = ui.column().classes("w-full max-w-5xl gap-4")
        with body:
            ui_kit.skeleton_cards(4)

    try:
        res = await asyncio.to_thread(api.get, f"/api/surveys/{sid}/results")
    except Exception as e:
        body.clear()
        with body:
            if not _handle_api_error(e):
                ui.label("Không tải được kết quả.").classes("text-red-600")
        return

    s = res["survey"]
    anon = s["is_anonymous"]

    async def export():
        try:
            content = await asyncio.to_thread(api.download, f"/api/surveys/{sid}/export")
        except Exception as e:
            _handle_api_error(e)
            return
        ui.download(content, f"Ket_qua_khao_sat_{sid}.xlsx")

    body.clear()
    with body:
        # ── Tiêu đề + thao tác ──
        with ui.row().classes("w-full items-center gap-3"):
            ui.label(s["title"]).classes("text-xl font-bold text-gray-900")
            state_chip(s["state"])
            if anon:
                ui.label("Ẩn danh").classes("text-xs px-2 py-0.5 rounded border bg-green-50 "
                                            "text-green-700 border-green-300")
            ui.space()
            ui.button("Xuất Excel", icon="download", on_click=export).props(
                "outline no-caps color=red-8")
            ui.button("Quay lại", icon="arrow_back", on_click=lambda: ui.navigate.to("/surveys")
                      ).props("flat no-caps").classes("text-gray-600")

        # ── Số liệu chính: số, không phải biểu đồ ──
        with ui.row().classes("w-full gap-3 flex-wrap"):
            _tile("Người nhận", str(res["recipient_count"]))
            _tile("Đã trả lời", str(res["responded_recipients"]),
                  f"chưa trả lời {res['recipient_count'] - res['responded_recipients']}")
            _tile("Tỷ lệ phản hồi", f"{res['response_rate']}%")
            _tile("Hạn chót", fmt_dt(s["deadline"]),
                  _con_lai(s["deadline"]) if s["state"] == "open" else "")

        with ui.tabs().classes("text-red-800").props("align=left no-caps dense") as tabs:
            t1 = ui.tab("sum", "Tổng hợp", icon="insights")
            t2 = ui.tab("rows", f"Từng câu trả lời ({res['response_count']})", icon="table_rows")
            t3 = ui.tab("prog", "Tiến độ", icon="groups")
        with ui.tab_panels(tabs, value=t1).classes("w-full bg-transparent"):
            with ui.tab_panel(t1).classes("p-0 pt-2 gap-3"):
                if res["response_count"] == 0:
                    ui_kit.empty_state("Chưa có ai trả lời", "hourglass_empty")
                for i, st in enumerate(res["stats"], start=1):
                    _stat_card(i, st)

            with ui.tab_panel(t2).classes("p-0 pt-2"):
                if not res["rows"]:
                    ui_kit.empty_state("Chưa có câu trả lời", "table_rows")
                else:
                    cols = [] if anon else [
                        {"name": "n", "label": "Người trả lời", "field": "n", "align": "left", "sortable": True},
                        {"name": "d", "label": "Phòng", "field": "d", "align": "left", "sortable": True},
                        {"name": "t", "label": "Thời điểm nộp", "field": "t", "align": "left", "sortable": True},
                    ]
                    cols += [{"name": f"q{j}", "label": q["title"], "field": f"q{j}", "align": "left"}
                             for j, q in enumerate(res["questions"])]
                    rows = []
                    for k, r in enumerate(res["rows"]):
                        d = {"_k": k, "n": r["staff_name"], "d": r["dept_name"] or "",
                             "t": fmt_dt(r["updated_at"] or r["submitted_at"])}
                        d.update({f"q{j}": a for j, a in enumerate(r["answers"])})
                        rows.append(d)
                    if anon:
                        ui.label("Khảo sát ẩn danh — không hiện tên, giờ nộp; dòng xếp theo nội dung "
                                 "câu trả lời, không theo thứ tự nộp.").classes("text-xs text-gray-500 mb-1")
                    ui.table(columns=cols, rows=rows, row_key="_k",
                             pagination={"rowsPerPage": 20}).props(
                        "flat bordered dense wrap-cells").classes("w-full")

            with ui.tab_panel(t3).classes("p-0 pt-2"):
                chua = [r for r in res["recipients"] if not r["responded"]]
                roi = [r for r in res["recipients"] if r["responded"]]
                with ui.row().classes("w-full gap-4 items-start flex-wrap"):
                    for title, lst, icon, color in (
                            (f"Chưa trả lời ({len(chua)})", chua, "pending", "text-orange-700"),
                            (f"Đã trả lời ({len(roi)})", roi, "check_circle", "text-green-700")):
                        with ui.card().classes("flex-1 min-w-[18rem] rounded-xl shadow-sm p-0 "
                                               "border border-gray-200 overflow-hidden"):
                            with ui.row().classes("w-full bg-red-50 px-4 py-2 border-b border-red-100 "
                                                  "items-center gap-2"):
                                ui.icon(icon).classes(color)
                                ui.label(title).classes("font-semibold text-red-900")
                            with ui.column().classes("w-full gap-0 max-h-[28rem] overflow-y-auto"):
                                if not lst:
                                    ui.label("—").classes("px-4 py-3 text-gray-400")
                                for r in lst:
                                    with ui.row().classes("w-full px-4 py-2 border-b border-gray-100 "
                                                          "items-center justify-between no-wrap"):
                                        with ui.column().classes("gap-0"):
                                            ui.label(r["staff_name"]).classes("text-sm text-gray-900")
                                            ui.label(r["dept_name"] or "").classes("text-xs text-gray-500")
                                        if r.get("submitted_at"):
                                            ui.label(fmt_dt(r["submitted_at"])).classes(
                                                "text-xs text-gray-500 whitespace-nowrap")
