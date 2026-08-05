"""Trang báo cáo bàn giao chứng từ — đúng hạn / quá hạn theo phòng nghiệp vụ"""
import asyncio
from datetime import date

from nicegui import ui

import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth,
    _handle_api_error,
)

_DEADLINE_NOTE = (
    "Đúng hạn = nộp trong 1 ngày làm việc sau ngày giao dịch "
    "(bỏ T7/CN, ngày lễ, ngày nghỉ phép của người nhận). "
    "Ngày nộp lấy từ lịch sử thao tác của chứng từ."
)


def _fmt(iso: str) -> str:
    """2026-07-02 → 02/07/2026"""
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso or ""


def _rate_style(rate):
    if rate is None:
        return "—", "bg-gray-100 text-gray-500"
    if rate >= 90:
        return f"{rate:.1f}%", "bg-green-100 text-green-700"
    if rate >= 70:
        return f"{rate:.1f}%", "bg-yellow-100 text-yellow-700"
    return f"{rate:.1f}%", "bg-red-100 text-red-700"


def _kpi_cards(overall: dict):
    rate = overall.get("rate")
    rate_str, _ = _rate_style(rate)
    cards = [
        ("Tổng chứng từ", str(overall.get("total", 0)), "description",   "bg-blue-50 border-blue-200",   "text-blue-700"),
        ("Nộp đúng hạn",  str(overall.get("on_time", 0)), "check_circle", "bg-green-50 border-green-200", "text-green-700"),
        ("Nộp quá hạn",   str(overall.get("late", 0)),    "error",        "bg-red-50 border-red-200",     "text-red-700"),
        ("Tỷ lệ đúng hạn", rate_str,                      "percent",      "bg-gray-50 border-gray-200",   "text-gray-700"),
    ]
    with ui.row().classes("w-full gap-4 flex-wrap"):
        for lbl, val, icon, box_cls, txt_cls in cards:
            with ui.card().classes(f"flex-1 min-w-[150px] p-4 rounded-xl border {box_cls} shadow-sm"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon(icon).classes(f"text-3xl {txt_cls}")
                    with ui.column().classes("gap-0"):
                        ui.label(val).classes(f"text-3xl font-bold {txt_cls}")
                        ui.label(lbl).classes("text-sm text-gray-500")


def _dept_table(by_dept: list):
    with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white"):
        ui.label("Thống kê theo phòng nghiệp vụ").classes("font-semibold text-red-900 mb-1")
        ui.label(_DEADLINE_NOTE).classes("text-xs text-gray-500 italic mb-3")

        if not by_dept:
            ui.label("Chưa có chứng từ nào trong kỳ này.").classes("text-gray-500 text-sm")
            return

        with ui.row().classes("w-full px-3 py-2 bg-red-50 text-xs font-semibold text-red-700 border-b border-red-100"):
            ui.label("Phòng").classes("flex-1")
            ui.label("Tổng").classes("w-20 text-center")
            ui.label("Đúng hạn").classes("w-24 text-center")
            ui.label("Quá hạn").classes("w-24 text-center")
            ui.label("Tỷ lệ").classes("w-24 text-center")

        for row in by_dept:
            r_str, r_cls = _rate_style(row.get("rate"))
            with ui.row().classes("w-full px-3 py-2 border-b border-gray-100 items-center"):
                ui.label(row.get("dept_name", "")).classes("flex-1 text-sm")
                ui.label(str(row.get("total", 0))).classes("w-20 text-center text-sm text-gray-700")
                ui.label(str(row.get("on_time", 0))).classes("w-24 text-center text-sm text-green-700 font-medium")
                ui.label(str(row.get("late", 0))).classes("w-24 text-center text-sm text-red-600 font-medium")
                ui.label(r_str).classes(f"w-24 text-center text-xs font-semibold px-2 py-0.5 rounded {r_cls}")


def _late_detail(late_entries: list):
    with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white"):
        ui.label("Chi tiết chứng từ nộp quá hạn").classes("font-semibold text-red-900 mb-1")
        ui.label("Nhấn vào tên phòng để xem danh sách.").classes("text-xs text-gray-500 italic mb-3")

        if not late_entries:
            with ui.row().classes("items-center gap-2 py-2"):
                ui.icon("check_circle", color="green").classes("text-xl")
                ui.label("Không có chứng từ nào nộp quá hạn trong kỳ này.").classes("text-sm text-green-700")
            return

        # Gom theo phòng — backend đã sort sẵn theo (phòng, số ngày chậm giảm dần)
        grouped: dict = {}
        for e in late_entries:
            grouped.setdefault(e["dept_name"], []).append(e)

        for dept_name, rows in grouped.items():
            with ui.expansion(f"{dept_name} — {len(rows)} chứng từ quá hạn").classes(
                "w-full border border-red-100 rounded-lg mb-2"
            ).props("dense header-class=text-red-800"):
                with ui.row().classes("w-full px-3 py-2 bg-red-50 text-xs font-semibold text-red-700"):
                    ui.label("Cán bộ").classes("flex-1")
                    ui.label("Mã IPCAS").classes("w-28 text-center")
                    ui.label("Ngày giao dịch").classes("w-32 text-center")
                    ui.label("Ngày nộp").classes("w-32 text-center")
                    ui.label("Số ngày chậm").classes("w-32 text-center")
                    ui.label("Số tờ").classes("w-20 text-center")

                for e in rows:
                    days = e["days_late"]
                    day_cls = "bg-red-100 text-red-700" if days > 2 else "bg-yellow-100 text-yellow-800"
                    with ui.row().classes("w-full px-3 py-2 border-b border-gray-100 items-center"):
                        ui.label(e["staff_name"]).classes("flex-1 text-sm text-gray-800")
                        ui.label(e["ipcas_code"] or "—").classes("w-28 text-center text-xs font-mono text-gray-600")
                        ui.label(_fmt(e["transaction_date"])).classes("w-32 text-center text-sm text-gray-700")
                        ui.label(_fmt(e["submitted_date"])).classes("w-32 text-center text-sm text-gray-700")
                        ui.label(f"{days} ngày").classes(
                            f"w-32 text-center text-xs font-semibold px-2 py-0.5 rounded {day_cls}"
                        )
                        ui.label(str(e["sheet_count"])).classes("w-20 text-center text-sm text-gray-600")


@ui.page("/handover_reports")
def handover_reports_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.handover_reports"):
        ui.navigate.to("/home")
        return

    today = date.today()

    with ui.row().classes("w-full"):
        _sidebar("handover_reports")
        with _content_area():
            _page_header(
                "Báo cáo bàn giao chứng từ",
                "Thống kê chứng từ nộp đúng hạn / quá hạn theo từng phòng nghiệp vụ",
            )

            # ── Bộ lọc kỳ báo cáo ──
            with ui.card().classes("w-full p-4 mb-5"):
                with ui.row().classes("items-end gap-4 flex-wrap"):
                    month_sel = ui.select(
                        {m: f"Tháng {m:02d}" for m in range(1, 13)},
                        value=today.month, label="Tháng",
                    ).classes("w-40")
                    year_sel = ui.select(
                        {y: str(y) for y in range(today.year - 4, today.year + 1)},
                        value=today.year, label="Năm",
                    ).classes("w-32")
                    load_btn = ui.button("Xem báo cáo", icon="search").classes("bg-red-800 text-white")
                    export_btn = ui.button("Xuất file Word", icon="description").classes(
                        "bg-blue-800 text-white"
                    )
                    export_btn.disable()

            result_area = ui.column().classes("w-full gap-5")

            # Kỳ ĐANG HIỂN THỊ — không lấy thẳng từ ô chọn: người dùng có thể đổi
            # tháng mà chưa bấm "Xem báo cáo", khi đó file xuất ra sẽ lệch với bảng
            # đang nhìn thấy.
            shown = {"year": None, "month": None}

            async def load():
                load_btn.props("loading")
                try:
                    data = await asyncio.to_thread(
                        api.get, "/api/handover-reports/summary",
                        {"year": year_sel.value, "month": month_sel.value},
                    )
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(str(e), type="negative")
                    return
                finally:
                    load_btn.props(remove="loading")

                shown["year"], shown["month"] = year_sel.value, month_sel.value
                export_btn.enable()

                result_area.clear()
                with result_area:
                    _kpi_cards(data.get("overall", {}))
                    _dept_table(data.get("by_dept", []))
                    _late_detail(data.get("late_entries", []))

                    skipped = data.get("no_submit_date", 0)
                    if skipped:
                        ui.label(
                            f"Ghi chú: {skipped} chứng từ trong kỳ không có dữ liệu ngày nộp "
                            f"(nhập trước khi hệ thống ghi lịch sử thao tác) — không đưa vào báo cáo."
                        ).classes("text-xs text-gray-500 italic")

            async def do_export():
                if shown["year"] is None:
                    ui.notify("Hãy xem báo cáo trước khi xuất file", type="warning")
                    return
                export_btn.props("loading")
                try:
                    content = await asyncio.to_thread(
                        api.download, "/api/handover-reports/export",
                        {"year": shown["year"], "month": shown["month"]},
                    )
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(str(e), type="negative")
                    return
                finally:
                    export_btn.props(remove="loading")

                ui.download(
                    content,
                    f"Bao_cao_ban_giao_chung_tu_T{shown['month']:02d}_{shown['year']}.docx",
                )
                ui.notify("Đã xuất báo cáo Word", type="positive")

            load_btn.on("click", load)
            export_btn.on("click", do_export)
            ui.timer(0.1, load, once=True)
