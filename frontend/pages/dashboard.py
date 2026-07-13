"""Trang chủ — Dashboard KPI."""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth


@ui.page("/home")
@ui.page("/")
async def dashboard_page():
    if not _require_auth():
        return
    # Chỉ redirect CV sang handovers nếu họ có quyền — tránh vòng lặp vô tận
    # khi CV thuộc phòng TH (handovers chặn TH → redirect về home → lại redirect sang handovers)
    _u = api.get_current_user()
    if _u and _u.get("role") == "chuyen_vien" and api.has_feature("menu.handovers"):
        ui.navigate.to("/handovers")
        return
    badge_refs = _sidebar("home")
    with _content_area():
        _page_header("Trang chủ", "Hệ thống Trung tâm Thanh toán")

        loading_row = ui.row().classes("w-full justify-center items-center py-10")
        with loading_row:
            ui.spinner(size="3em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-3 text-sm")
        content = ui.column().classes("w-full gap-6")

        try:
            await ui.context.client.connected()
        except Exception:
            pass

        try:
            results = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/staff/"),
                asyncio.to_thread(api.get, "/api/departments/"),
                asyncio.to_thread(api.get, "/api/bundles/groups"),
                asyncio.to_thread(api.get, "/api/dashboard/summary"),
                asyncio.to_thread(api.get, "/api/dashboard/pending-counts"),
                return_exceptions=True,
            )
        except Exception as e:
            if isinstance(e, api.SessionExpiredError):
                ui.notify(str(e), type="warning")
                ui.navigate.to("/login")
                return
            results = [[], [], [], {}, {}]

        staff_list, depts, groups, summary, pending = results
        for r in results:
            if isinstance(r, api.SessionExpiredError):
                ui.notify(str(r), type="warning")
                ui.navigate.to("/login")
                return
        staff_list = staff_list if isinstance(staff_list, list) else []
        depts      = depts      if isinstance(depts, list)      else []
        groups     = groups     if isinstance(groups, list)     else []
        summary    = summary    if isinstance(summary, dict)    else {}
        pending    = pending    if isinstance(pending, dict)    else {}

        loading_row.set_visibility(False)

        for _bkey in ("leaves", "handovers"):
            _cnt = pending.get(_bkey, 0)
            if _bkey in badge_refs and isinstance(_cnt, int) and _cnt > 0:
                badge_refs[_bkey].set_text(str(_cnt))
                badge_refs[_bkey].set_visibility(True)

        overall   = summary.get("overall", {})
        rate_val  = overall.get("rate")
        period    = summary.get("period", "")
        on_time   = overall.get("on_time", 0)
        late_cnt  = overall.get("late", 0)
        total_doc = overall.get("total", 0)

        if rate_val is None:
            rate_str, rate_icon = "—", "help_outline"
            rate_clr, rate_txt_clr = "bg-gray-50 border-gray-200", "text-gray-500"
        elif rate_val >= 90:
            rate_str, rate_icon = f"{rate_val:.1f}%", "check_circle"
            rate_clr, rate_txt_clr = "bg-green-50 border-green-200", "text-green-700"
        elif rate_val >= 70:
            rate_str, rate_icon = f"{rate_val:.1f}%", "warning"
            rate_clr, rate_txt_clr = "bg-yellow-50 border-yellow-200", "text-yellow-700"
        else:
            rate_str, rate_icon = f"{rate_val:.1f}%", "error"
            rate_clr, rate_txt_clr = "bg-red-50 border-red-200", "text-red-700"

        stats = [
            ("Người dùng",     len(staff_list),                               "people",     "bg-red-50 border-red-200"),
            ("Phòng nghiệp vụ", len([d for d in depts if d.get("code") != "BGD"]), "business",   "bg-blue-50 border-blue-200"),
            ("Nhóm tập",        len(groups),                                   "folder_zip", "bg-purple-50 border-purple-200"),
            ("Tập đã in",       sum(len(g.get("bundles", [])) for g in groups),"print",      "bg-orange-50 border-orange-200"),
        ]

        with content:
            with ui.row().classes("w-full gap-4 mb-2 flex-wrap"):
                for lbl, val, icon, colors in stats:
                    with ui.card().classes(f"flex-1 min-w-[120px] p-4 rounded-xl border {colors} shadow-sm"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon(icon).classes("text-3xl text-gray-500")
                            with ui.column().classes("gap-0"):
                                ui.label(str(val)).classes("text-3xl font-bold text-gray-800")
                                ui.label(lbl).classes("text-sm text-gray-500")

                period_vn = ""
                if period:
                    try:
                        y, m = period.split("-")
                        period_vn = f"Tháng {int(m):02d}/{y}"
                    except Exception:
                        period_vn = period
                with ui.card().classes(f"flex-1 min-w-[160px] p-4 rounded-xl border {rate_clr} shadow-sm"):
                    with ui.row().classes("items-center gap-3"):
                        ui.icon(rate_icon).classes(f"text-3xl {rate_txt_clr}")
                        with ui.column().classes("gap-0"):
                            ui.label(rate_str).classes(f"text-3xl font-bold {rate_txt_clr}")
                            ui.label("Đúng hạn").classes("text-sm text-gray-500")
                            if period_vn:
                                ui.label(period_vn).classes("text-xs text-gray-400")

            pend_leaves       = pending.get("leaves",          0)
            pend_handovers    = pending.get("handovers",       0)
            by_dept_handovers = pending.get("handovers_by_dept", [])
            if pend_leaves or pend_handovers:
                with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white border border-yellow-100"):
                    ui.label("Công việc đang chờ").classes("font-semibold text-red-900 mb-3")
                    if pend_handovers:
                        with ui.row().classes(
                            "w-full items-center gap-3 p-3 bg-orange-50 rounded-lg border border-orange-200 "
                            "cursor-pointer hover:bg-orange-100 mb-2"
                        ).on("click", lambda: ui.navigate.to("/handovers")):
                            ui.icon("receipt_long").classes("text-2xl text-orange-600")
                            with ui.column().classes("flex-1 gap-1"):
                                ui.label(f"{pend_handovers} chứng từ chờ xác nhận").classes("text-sm font-semibold text-orange-800")
                                if by_dept_handovers:
                                    for dept_item in by_dept_handovers:
                                        ui.label(
                                            f"• {dept_item['count']:02d} chứng từ — {dept_item['dept_name']}"
                                        ).classes("text-xs text-orange-700")
                                else:
                                    ui.label("Nhấn để đến Bàn giao chứng từ").classes("text-xs text-orange-500")
                            ui.icon("chevron_right").classes("text-orange-400")
                    if pend_leaves:
                        with ui.row().classes(
                            "w-full items-center gap-3 p-3 bg-blue-50 rounded-lg border border-blue-200 "
                            "cursor-pointer hover:bg-blue-100"
                        ).on("click", lambda: ui.navigate.to("/leaves")):
                            ui.icon("event_busy").classes("text-2xl text-blue-600")
                            with ui.column().classes("flex-1 gap-0"):
                                ui.label(f"{pend_leaves} đơn nghỉ phép chờ duyệt").classes("text-sm font-semibold text-blue-800")
                                ui.label("Nhấn để đến Nghỉ phép").classes("text-xs text-blue-500")
                            ui.icon("chevron_right").classes("text-blue-400")

            by_dept = summary.get("by_dept", [])
            with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white"):
                with ui.row().classes("w-full justify-between items-center mb-1"):
                    title_txt = f"Tỷ lệ nộp chứng từ đúng hạn — {period_vn}" if period_vn else "Tỷ lệ nộp chứng từ đúng hạn"
                    ui.label(title_txt).classes("font-semibold text-red-900")
                    if total_doc:
                        ui.label(f"Tổng {total_doc} chứng từ · {on_time} đúng hạn · {late_cnt} muộn").classes("text-xs text-gray-500")
                with ui.column().classes("gap-0 mb-3"):
                    ui.label("Đúng hạn = nộp trong 1 ngày làm việc sau ngày giao dịch (bỏ T7/CN, ngày lễ, ngày nghỉ phép của người nhận)").classes(
                        "text-xs text-gray-400 italic")
                    _skipped = summary.get("no_submit_date", 0)
                    if _skipped:
                        ui.label(
                            f"Không tính {_skipped} chứng từ cũ chưa có dữ liệu ngày nộp. "
                            f"Xem chi tiết tại Báo cáo bàn giao chứng từ."
                        ).classes("text-xs text-gray-400 italic")

                if not by_dept:
                    ui.label("Chưa có dữ liệu bàn giao trong tháng này.").classes("text-gray-400 text-sm mt-1")
                else:
                    with ui.row().classes("w-full px-3 py-2 bg-red-50 text-xs font-semibold text-red-700 border-b border-red-100"):
                        ui.label("Phòng").classes("flex-1")
                        ui.label("Đúng hạn").classes("w-20 text-center")
                        ui.label("Muộn").classes("w-16 text-center")
                        ui.label("Tỷ lệ").classes("w-20 text-center")
                    for row in by_dept:
                        r = row.get("rate")
                        if r is None:
                            r_str, r_cls = "—", "bg-gray-100 text-gray-500"
                        elif r >= 90:
                            r_str, r_cls = f"{r:.1f}%", "bg-green-100 text-green-700"
                        elif r >= 70:
                            r_str, r_cls = f"{r:.1f}%", "bg-yellow-100 text-yellow-700"
                        else:
                            r_str, r_cls = f"{r:.1f}%", "bg-red-100 text-red-700"
                        with ui.row().classes("w-full px-3 py-2 border-b border-gray-100 items-center"):
                            ui.label(row.get("dept_name", "")).classes("flex-1 text-sm")
                            ui.label(str(row.get("on_time", 0))).classes("w-20 text-center text-sm text-green-700 font-medium")
                            ui.label(str(row.get("late", 0))).classes("w-16 text-center text-sm text-red-600")
                            ui.label(r_str).classes(f"w-20 text-center text-xs font-semibold px-2 py-0.5 rounded {r_cls}")

            with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white"):
                with ui.row().classes("w-full justify-between items-center mb-3"):
                    ui.label("Các tập chứng từ gần đây").classes("font-semibold text-red-900")
                    ui.button("Xem tất cả", icon="arrow_forward",
                              on_click=lambda: ui.navigate.to("/bundles")
                              ).props("flat dense").classes("text-red-700 text-sm")
                if groups:
                    with ui.row().classes(
                        "w-full px-3 py-2 bg-red-50 text-xs font-semibold text-red-700"
                        " border-b border-red-100 rounded-t"
                    ):
                        ui.label("Tên bìa chứng từ").classes("flex-1")
                        ui.label("Số tập").classes("w-20 text-center")
                        ui.label("Ngày tạo").classes("w-28 text-center")
                    for g in groups[:10]:
                        dept       = g.get("department") or {}
                        dept_name  = dept.get("name", "N/A")
                        notes      = g.get("notes") or ""
                        bundle_lbl = f"{dept_name} – {notes}" if notes else dept_name
                        n_bundles  = g.get("total_bundles", 0)
                        date_str   = (g.get("created_at") or "")[:10]
                        with ui.row().classes(
                            "w-full px-3 py-2 border-b border-gray-100 items-center cursor-pointer hover:bg-red-50"
                        ).on("click", lambda: ui.navigate.to("/bundles")):
                            ui.label(bundle_lbl).classes("flex-1 text-sm text-gray-800")
                            ui.label(str(n_bundles)).classes("w-20 text-center text-sm font-semibold text-red-700")
                            ui.label(date_str).classes("w-28 text-center text-sm text-gray-500")
                else:
                    ui.label("Chưa có tập chứng từ nào").classes("text-gray-400 text-sm")
