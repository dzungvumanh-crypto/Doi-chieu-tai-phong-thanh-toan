"""Trang chủ — Dashboard KPI."""
import asyncio
from datetime import date as _date
from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error



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

        _today = _date.today()
        try:
            results = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/staff/"),
                asyncio.to_thread(api.get, "/api/departments/"),
                asyncio.to_thread(api.get, "/api/dashboard/summary"),
                asyncio.to_thread(api.get, "/api/dashboard/pending-counts"),
                asyncio.to_thread(api.get, "/api/leaves/today"),
                return_exceptions=True,
            )
        except Exception as e:
            if isinstance(e, api.SessionExpiredError):
                ui.notify(str(e), type="warning")
                ui.navigate.to("/login")
                return
            results = [[], [], {}, {}, {}]

        staff_list, depts, summary, pending, today_leaves = results
        for r in results:
            if isinstance(r, api.SessionExpiredError):
                ui.notify(str(r), type="warning")
                ui.navigate.to("/login")
                return
        staff_list = staff_list if isinstance(staff_list, list) else []
        depts      = depts      if isinstance(depts, list)      else []
        summary    = summary    if isinstance(summary, dict)    else {}
        pending    = pending    if isinstance(pending, dict)    else {}
        today_leaves   = today_leaves if isinstance(today_leaves, dict) else {}
        leave_total    = today_leaves.get("total", 0)
        leave_by_dept  = today_leaves.get("by_dept", [])

        loading_row.set_visibility(False)

        for _bkey in ("leaves", "handovers"):
            _cnt = pending.get(_bkey, 0)
            if _bkey in badge_refs and isinstance(_cnt, int) and _cnt > 0:
                badge_refs[_bkey].set_text(str(_cnt))
                badge_refs[_bkey].set_visibility(True)

        # Số người dùng không tính quản trị viên (admin)
        n_users = len([s for s in staff_list if s.get("role") != "admin"])
        stats = [
            ("Người dùng",      n_users,                                           "people",   "bg-red-50 border-red-200"),
            ("Phòng nghiệp vụ", len([d for d in depts if d.get("code") != "BGD"]), "business", "bg-blue-50 border-blue-200"),
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

            # ── Nghỉ phép hôm nay ─────────────────────────────────────────────
            with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white border-2 border-red-400"):
                ui.label(f"Nghỉ phép hôm nay ({_today.strftime('%d/%m/%Y')})").classes("font-semibold text-red-900 mb-3")
                _by_dept_map = {d.get("dept_name", ""): d.get("count", 0) for d in leave_by_dept}
                # Thứ tự: BGD → Phòng Thanh toán → Phòng Tổng hợp → còn lại alpha
                _DEPT_PRI = {"Phòng Thanh toán": 1, "Phòng Tổng hợp": 2}
                _sorted_depts = sorted(depts, key=lambda d: (
                    0 if d.get("code") == "BGD" else 1,
                    _DEPT_PRI.get(d.get("name", ""), 99),
                    d.get("name", ""),
                ))
                _CELL_COLORS = [
                    "bg-red-50 border-red-200",
                    "bg-blue-50 border-blue-200",
                    "bg-green-50 border-green-200",
                    "bg-purple-50 border-purple-200",
                    "bg-yellow-50 border-yellow-200",
                    "bg-orange-50 border-orange-200",
                    "bg-teal-50 border-teal-200",
                    "bg-pink-50 border-pink-200",
                ]
                with ui.row().classes("w-full gap-2 flex-nowrap"):
                    # Ô tổng toàn trung tâm
                    _color0 = _CELL_COLORS[0]
                    _tc_num = "text-red-700 font-bold" if leave_total else "text-gray-400"
                    with ui.element("div").classes(f"flex-1 min-w-0 p-2 rounded-xl border {_color0} flex flex-col items-center justify-center").style("min-height:80px"):
                        ui.label(str(leave_total)).classes(f"text-2xl {_tc_num}")
                        ui.label("Toàn trung tâm").classes("text-xs font-semibold text-gray-600 mt-1 leading-tight text-center")
                    # Ô từng phòng ban
                    for _di, _dept in enumerate(_sorted_depts):
                        _dname   = _dept.get("name", "")
                        _cnt     = _by_dept_map.get(_dname, 0)
                        _color   = _CELL_COLORS[(_di + 1) % len(_CELL_COLORS)]
                        _num_cls = "text-red-700 font-bold" if _cnt else "text-gray-400"
                        with ui.element("div").classes(f"flex-1 min-w-0 p-2 rounded-xl border {_color} flex flex-col items-center justify-center").style("min-height:80px"):
                            ui.label(str(_cnt)).classes(f"text-2xl {_num_cls}")
                            ui.label(_dname).classes("text-xs text-gray-600 mt-1 leading-tight text-center")

            # ── Biểu đồ nộp chứng từ đúng hạn — chọn Tháng/Năm để xem ──
            dept_slots = [
                ("PAYMENT", "Phòng Thanh toán"),
                ("ACCT",    "Phòng Kế toán"),
                ("SWIFT",   "Phòng Swift"),
                ("NOSTRO",  "Phòng QLTK Nostro, Vostro"),
            ]
            _today = _date.today()
            _year_opts  = list(range(_today.year, 2023, -1))
            _month_opts = {m: f"Tháng {m:02d}" for m in range(1, 13)}

            with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white"):
                with ui.row().classes("w-full justify-between items-center mb-1 flex-wrap gap-2"):
                    ui.label("Tỷ lệ nộp chứng từ đúng hạn").classes("font-semibold text-red-900")
                    with ui.row().classes("items-center gap-2"):
                        month_sel = ui.select(_month_opts, value=_today.month
                                              ).props("dense outlined").classes("w-32")
                        year_sel  = ui.select(_year_opts, value=_today.year
                                              ).props("dense outlined").classes("w-28")

                ui.label("Đúng hạn = nộp trong 1 ngày làm việc sau ngày giao dịch "
                         "(bỏ T7/CN, ngày lễ, ngày nghỉ phép của người nhận)"
                         ).classes("text-xs text-gray-400 italic")

                chart_box = ui.column().classes("w-full gap-0")

                def _render_chart(sm: dict):
                    # Vẽ lại toàn bộ vùng biểu đồ theo dữ liệu kỳ đã chọn
                    chart_box.clear()
                    ov  = sm.get("overall", {})
                    ot  = ov.get("on_time", 0)
                    lt  = ov.get("late", 0)
                    tot = ov.get("total", 0)
                    bd  = sm.get("by_dept", [])
                    by_code = {(r.get("dept_code") or "").upper(): r for r in bd}
                    labels  = [lbl for _, lbl in dept_slots]
                    ot_vals = [(by_code.get(c) or {}).get("on_time", 0) for c, _ in dept_slots]
                    lt_vals = [(by_code.get(c) or {}).get("late", 0)    for c, _ in dept_slots]
                    with chart_box:
                        if tot:
                            ui.label(f"Tổng {tot} chứng từ · {ot} đúng hạn · {lt} muộn"
                                     ).classes("text-xs text-gray-500 mb-1")
                        _skipped = sm.get("no_submit_date", 0)
                        if _skipped:
                            ui.label(
                                f"Không tính {_skipped} chứng từ cũ chưa có dữ liệu ngày nộp. "
                                f"Xem chi tiết tại Báo cáo bàn giao chứng từ."
                            ).classes("text-xs text-gray-400 italic mb-1")
                        if not bd:
                            ui.label("Chưa có dữ liệu bàn giao trong kỳ này."
                                     ).classes("text-gray-400 text-sm mt-1")
                        else:
                            ui.echart({
                                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                                "legend": {"data": ["Đúng hạn", "Nộp muộn"], "bottom": 0},
                                "grid": {"left": "3%", "right": "4%", "top": "8%", "bottom": "12%", "containLabel": True},
                                "xAxis": {"type": "category", "data": labels,
                                          "axisLabel": {"interval": 0, "fontSize": 11}},
                                "yAxis": {"type": "value", "minInterval": 1},
                                "series": [
                                    {"name": "Đúng hạn", "type": "bar", "barGap": "10%", "data": ot_vals,
                                     "itemStyle": {"color": "#16a34a"},
                                     "label": {"show": True, "position": "top"}},
                                    {"name": "Nộp muộn", "type": "bar", "data": lt_vals,
                                     "itemStyle": {"color": "#dc2626"},
                                     "label": {"show": True, "position": "top"}},
                                ],
                            }).classes("w-full").style("height: 340px")

                _render_chart(summary)  # kỳ mặc định (tháng hiện tại) — dùng lại data đã tải

                async def _reload_chart():
                    chart_box.clear()
                    with chart_box:
                        ui.spinner(size="1.5em", color="red").classes("my-6")
                    try:
                        sm = await asyncio.to_thread(
                            api.get, "/api/dashboard/summary",
                            {"year": year_sel.value, "month": month_sel.value},
                        )
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        sm = {}
                    _render_chart(sm if isinstance(sm, dict) else {})

                month_sel.on_value_change(_reload_chart)
                year_sel.on_value_change(_reload_chart)
