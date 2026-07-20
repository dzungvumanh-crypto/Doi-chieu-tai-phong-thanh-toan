"""Trang bàn giao chứng từ."""
import asyncio
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error

# Màu ô theo entry_status
_CELL_STATUS_STYLE = {
    "pending_confirm": ("background:#FEF3C7", "2px solid #F59E0B"),  # vàng nhạt
    "borrowed":        ("background:#EDE9FE", "2px solid #7C3AED"),  # tím nhạt
    "confirmed":       ("background:#DCFCE7", "2px solid #16A34A"),  # xanh lá nhạt
    "rejected":        ("background:#FEE2E2", "2px solid #DC2626"),  # đỏ nhạt
}
_STATUS_DOT_COLOR = {
    "pending_confirm": "#D97706",
    "confirmed":       "#16A34A",
    "borrowed":        "#7C3AED",
    "rejected":        "#DC2626",
}
_STATUS_LABEL_MAP = {
    "pending_confirm": "Chờ xác nhận",
    "confirmed":       "Đã xác nhận",
    "borrowed":        "Đang mượn",
    "rejected":        "Bị từ chối",
}
_ACTION_COLOR_MAP = {
    "blue":   "#2563EB",
    "green":  "#16A34A",
    "orange": "#EA580C",
    "purple": "#7C3AED",
}

@ui.page("/handovers")
async def handovers_page():
    if not _require_auth():
        return
    user_data = api.get_current_user()
    user_role = user_data.get("role", "") if user_data else ""
    is_cv     = user_role == "chuyen_vien"
    if not api.has_feature("menu.handovers"):
        ui.navigate.to("/home")
        return

    badge_refs = _sidebar("handovers")

    # ── Right drawer panel ────────────────────────────────────────────────────
    with ui.right_drawer(value=False).props("width=360 overlay").classes(
        "bg-white shadow-2xl overflow-y-auto"
    ) as right_panel:
        panel_container = ui.column().classes("w-full gap-0")

    with _content_area():
        _page_header("Bàn giao chứng từ", "Nhập số chứng từ theo ngày và cán bộ")

        from datetime import date as _date
        today = _date.today()

        # ── Filter controls ───────────────────────────────────────────────────
        try:
            _all_depts_raw, _pending = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/departments/"),
                asyncio.to_thread(api.get, "/api/dashboard/pending-counts"),
                return_exceptions=True,
            )
        except Exception:
            _all_depts_raw, _pending = [], {}
        if not isinstance(_all_depts_raw, list):
            _all_depts_raw = []
        if isinstance(_pending, dict):
            _hcnt = _pending.get("handovers", 0)
            if "handovers" in badge_refs and _hcnt > 0:
                badge_refs["handovers"].set_text(str(_hcnt))
                badge_refs["handovers"].set_visibility(True)
        all_depts = [d for d in _all_depts_raw if d.get("is_source")]

        dept_opts  = {d["id"]: d["name"] for d in all_depts}
        year_opts  = {y: str(y) for y in range(2023, today.year + 3)}
        month_opts = {m: f"Tháng {m:02d}" for m in range(1, 13)}

        # Chuyên viên: tự động xác định phòng của mình
        cv_dept_id = user_data.get("department_id") if is_cv else None
        default_dept  = cv_dept_id if (is_cv and cv_dept_id) else (all_depts[0]["id"] if all_depts else None)
        default_year  = today.year
        default_month = today.month


        with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 mb-4"):
            with ui.row().classes("items-end gap-4 flex-wrap"):
                sel_dept = ui.select(dept_opts, label="Phòng", value=default_dept).classes("w-72")
                if is_cv:
                    sel_dept.props("disable")
                    sel_dept.tooltip("Phòng của bạn (không thể thay đổi)")
                sel_year  = ui.select(year_opts,  label="Năm",   value=default_year).classes("w-28")
                sel_month = ui.select(month_opts, label="Tháng", value=default_month).classes("w-36")
                ui.button("Tải dữ liệu", icon="search",
                          on_click=lambda: load_grid()
                          ).classes("bg-red-700 text-white px-4").tooltip("Tải dữ liệu")

        # Chú thích màu trạng thái
        with ui.row().classes("items-center gap-4 mb-2 flex-wrap"):
            for status_key, label in [
                ("confirmed",       "Đã xác nhận"),
                ("pending_confirm", "Chờ xác nhận"),
                ("borrowed",        "Đang mượn"),
                ("rejected",        "Bị từ chối"),
            ]:
                bg, border = _CELL_STATUS_STYLE[status_key]
                with ui.row().classes("items-center gap-1"):
                    ui.element("div").style(
                        f"width:14px;height:14px;border-radius:3px;{bg};border:{border}"
                    )
                    ui.label(label).classes("text-xs text-gray-600")

        async def save_pending():
            save_btn.props("loading")
            year  = int(sel_year.value)
            month = int(sel_month.value)
            # Collect all modified cells from the DOM (works even without prior blur)
            changes = await ui.run_javascript("""
                var r = [];
                document.querySelectorAll('.hv-inp').forEach(function(inp) {
                    var orig = parseInt(inp.dataset.orig || '0');
                    var curr = inp.value === '' ? 0 : (parseInt(inp.value) || 0);
                    if (curr !== orig) r.push({uid: parseInt(inp.dataset.uid), day: parseInt(inp.dataset.day), count: curr});
                });
                return r;
            """)
            changes = changes or []
            errors = []
            for item in changes:
                try:
                    date_str = f"{year}-{month:02d}-{item['day']:02d}"
                    await asyncio.to_thread(
                        api.put, "/api/handovers/entry-upsert",
                        {"staff_id": item["uid"], "date": date_str, "sheet_count": item["count"]},
                    )
                except Exception as ex:
                    if _handle_api_error(ex):
                        save_btn.props(remove="loading")
                        return
                    errors.append(str(ex))
            save_btn.props(remove="loading")
            if errors:
                ui.notify(f"Lỗi khi lưu: {'; '.join(errors[:3])}", type="negative")
            elif changes:
                ui.notify("Đã lưu", type="positive")
            else:
                ui.notify("Không có thay đổi nào", type="info")
            await load_grid()

        with ui.row().classes("gap-2 mb-2 items-center"):
            save_btn = ui.button("Lưu", icon="save",
                on_click=save_pending
            ).classes("bg-green-700 text-white px-4").tooltip("Lưu tất cả thay đổi")
            save_btn.set_visibility(api.has_feature("handovers.save_entry"))

            async def _export_handovers():
                try:
                    import calendar as _cal
                    y, m = sel_year.value, sel_month.value
                    last_day = _cal.monthrange(y, m)[1]
                    from_d = f"{y}-{m:02d}-01"
                    to_d   = f"{y}-{m:02d}-{last_day:02d}"
                    params = {"from_date": from_d, "to_date": to_d}
                    if sel_dept.value:
                        params["department_id"] = sel_dept.value
                    content = await asyncio.to_thread(
                        api.download, "/api/handovers/export",
                        params=params,
                    )
                    ui.download(content, f"chung_tu_{y}_{m:02d}.xlsx")
                except Exception as e:
                    _handle_api_error(e)

            ui.button("Xuất Excel", icon="download",
                      on_click=_export_handovers).classes("bg-blue-700 text-white px-4").tooltip("Tải file Excel")

        title_label    = ui.label("").classes("text-lg font-bold text-red-900 mb-3")
        loading_row    = ui.row().classes("w-full justify-center items-center py-10 hidden")
        with loading_row:
            ui.spinner(size="3em", color="red")
            ui.label("Đang tải dữ liệu...").classes("text-gray-500 ml-3 text-sm")
        grid_container = ui.column().classes("w-full")

        def _save_filter_state():
            app.storage.tab["hv_dept"]  = sel_dept.value
            app.storage.tab["hv_year"]  = sel_year.value
            app.storage.tab["hv_month"] = sel_month.value

        # ── Side panel renderer ───────────────────────────────────────────────
        async def open_entry_panel(entry_id: int, user_name: str):
            panel_container.clear()
            try:
                hist = await asyncio.to_thread(
                    api.get, f"/api/handovers/entries/{entry_id}/history"
                )
            except Exception as ex:
                with panel_container:
                    with ui.row().classes("w-full justify-between items-center px-4 py-3 bg-red-50 border-b border-red-100"):
                        ui.label("Lỗi").classes("font-bold text-red-900")
                        ui.button(icon="close", on_click=right_panel.hide).props("flat dense").classes("text-gray-400")
                    ui.label(str(ex)).classes("text-red-500 p-4 text-sm")
                right_panel.show()
                return

            current_status = hist.get("current_status", "confirmed")
            dot_color = _STATUS_DOT_COLOR.get(current_status, "#6B7280")
            status_label_text = _STATUS_LABEL_MAP.get(current_status, current_status)

            with panel_container:
                # Header
                with ui.column().classes("w-full bg-red-50 px-4 py-3 border-b border-red-100 gap-1"):
                    with ui.row().classes("w-full justify-between items-center"):
                        ui.label(hist.get("source_user_name", user_name)).classes("font-bold text-red-900 text-base")
                        ui.button(icon="close", on_click=right_panel.hide).props("flat dense").classes("text-gray-400")
                    _logs = hist.get("logs", [])
                    _last_ts = _logs[0].get("timestamp", "") if _logs else ""
                    _parts = _last_ts.split() if _last_ts else []
                    _disp_date = _parts[-1] if len(_parts) >= 2 else hist.get("transaction_date", "")
                    ui.label(
                        f"Ngày {_disp_date}  •  {hist.get('sheet_count', 0)} tờ"
                    ).classes("text-sm text-gray-600")
                    with ui.row().classes("items-center gap-1 mt-1"):
                        ui.element("div").style(
                            f"width:8px;height:8px;border-radius:50%;background:{dot_color}"
                        )
                        ui.label(status_label_text).classes("text-xs font-semibold").style(f"color:{dot_color}")
                    if hist.get("borrow_reason"):
                        ui.label(f"Lý do mượn: {hist['borrow_reason']}").classes("text-xs text-orange-700 italic")

                # Thao tác
                with ui.column().classes("w-full px-4 py-3 border-b border-gray-100 gap-2"):
                    ui.label("THAO TÁC").classes("text-xs font-bold text-gray-400 tracking-widest")
                    has_action = False

                    borrow_reason_val = hist.get("borrow_reason")

                    if user_role in ("admin", "hau_kiem_vien", "pho_phong", "truong_phong"):
                        if current_status == "pending_confirm":
                            _can_confirm = api.has_feature("handovers.confirm_entry")
                            _can_reject  = api.has_feature("handovers.reject_entry")
                            if _can_confirm or _can_reject:
                                has_action = True
                                btn_label = "✓  Xác nhận cho mượn" if borrow_reason_val else "✓  Xác nhận đã nhận"
                                async def _do_confirm(eid=entry_id, uname=user_name):
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/confirm-received", {})
                                        ui.notify("Đã xác nhận", type="positive")
                                        await open_entry_panel(eid, uname)
                                        await load_grid()
                                    except Exception as ex2:
                                        if _handle_api_error(ex2): return
                                with ui.row().classes("w-full gap-2"):
                                    if _can_confirm:
                                        ui.button(btn_label, on_click=_do_confirm).classes(
                                            "flex-1 bg-green-600 text-white rounded-lg text-sm font-semibold"
                                        )
                                    if _can_reject:
                                        with ui.dialog() as reject_dialog, ui.card().classes("w-96"):
                                            ui.label("Từ chối chứng từ").classes("font-bold text-lg mb-2 text-red-700")
                                            reject_reason_inp = ui.input("Lý do từ chối *").classes("w-full")
                                            with ui.row().classes("justify-end gap-2 mt-3"):
                                                ui.button("Huỷ", on_click=reject_dialog.close).props("flat")
                                                async def _do_reject_submit(eid=entry_id, uname=user_name):
                                                    reason = reject_reason_inp.value.strip()
                                                    if not reason:
                                                        ui.notify("Vui lòng nhập lý do từ chối", type="warning")
                                                        return
                                                    try:
                                                        await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/reject", {"reason": reason})
                                                        reject_dialog.close()
                                                        ui.notify("Đã từ chối chứng từ", type="warning")
                                                        right_panel.hide()
                                                        await load_grid()
                                                    except Exception as ex2:
                                                        if _handle_api_error(ex2): return
                                                ui.button("Từ chối", on_click=_do_reject_submit).classes("bg-red-600 text-white")
                                        ui.button("✗  Từ chối", on_click=reject_dialog.open).classes(
                                            "flex-1 bg-red-600 text-white rounded-lg text-sm font-semibold"
                                        )

                    if current_status == "rejected" and api.has_feature("handovers.save_entry"):
                        has_action = True
                        async def _do_resubmit(eid=entry_id, uname=user_name):
                            try:
                                await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/resubmit", {})
                                ui.notify("Đã nộp lại chứng từ", type="positive")
                                right_panel.hide()
                                await load_grid()
                            except Exception as ex2:
                                if _handle_api_error(ex2): return
                        ui.button("↻  Nộp lại chứng từ", on_click=_do_resubmit).classes(
                            "w-full bg-amber-600 text-white rounded-lg text-sm font-semibold"
                        )

                    if is_cv and current_status == "confirmed" and api.has_feature("handovers.borrow"):
                        has_action = True
                        with ui.dialog() as borrow_dialog, ui.card():
                            ui.label("Mượn lại chứng từ").classes("font-bold text-lg mb-2")
                            reason_inp = ui.input("Lý do mượn *").classes("w-full")
                            with ui.row().classes("justify-end gap-2 mt-2"):
                                ui.button("Huỷ", on_click=borrow_dialog.close).props("flat")
                                async def _do_borrow_submit(eid=entry_id, uname=user_name):
                                    reason = reason_inp.value.strip()
                                    if not reason:
                                        ui.notify("Vui lòng nhập lý do mượn", type="warning")
                                        return
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/borrow", {"reason": reason})
                                        borrow_dialog.close()
                                        ui.notify("Đã gửi yêu cầu mượn", type="warning")
                                        await open_entry_panel(eid, uname)
                                        await load_grid()
                                    except Exception as ex2:
                                        if _handle_api_error(ex2): return
                                ui.button("Gửi yêu cầu", on_click=_do_borrow_submit).classes("bg-orange-600 text-white")
                        ui.button("↩  Mượn lại", on_click=borrow_dialog.open).classes(
                            "w-full bg-orange-500 text-white rounded-lg text-sm font-semibold"
                        )

                    if is_cv and current_status == "borrowed" and api.has_feature("handovers.handback"):
                        has_action = True
                        _current_count = hist.get("sheet_count", 1)
                        with ui.dialog() as handback_dialog, ui.card():
                            ui.label("Bàn giao lại chứng từ").classes("font-bold text-lg mb-1")
                            ui.label("Số tờ bàn giao lại sẽ cập nhật số tờ hiện tại.").classes("text-sm text-gray-500 mb-2")
                            count_inp = ui.number(label="Số tờ bàn giao *", value=_current_count, min=1, precision=0).classes("w-full")
                            with ui.row().classes("justify-end gap-2 mt-2"):
                                ui.button("Huỷ", on_click=handback_dialog.close).props("flat")
                                async def _do_handback_submit(eid=entry_id, uname=user_name):
                                    count = int(count_inp.value) if count_inp.value else 0
                                    if count <= 0:
                                        ui.notify("Vui lòng nhập số tờ hợp lệ", type="warning")
                                        return
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/handback", {"sheet_count": count})
                                        handback_dialog.close()
                                        ui.notify("Đã bàn giao lại chứng từ", type="positive")
                                        right_panel.hide()
                                        await load_grid()
                                    except Exception as ex2:
                                        if _handle_api_error(ex2): return
                                ui.button("Xác nhận bàn giao", on_click=_do_handback_submit).classes("bg-blue-600 text-white")
                        ui.button("📋  Bàn giao lại", on_click=handback_dialog.open).classes(
                            "w-full bg-blue-600 text-white rounded-lg text-sm font-semibold"
                        )

                    if not has_action:
                        ui.label("Không có thao tác khả dụng").classes("text-sm text-gray-400 italic")

                # Lịch sử
                with ui.column().classes("w-full px-4 py-3 gap-4"):
                    ui.label("LỊCH SỬ THAY ĐỔI").classes("text-xs font-bold text-gray-400 tracking-widest")
                    logs = hist.get("logs", [])
                    if not logs:
                        ui.label("Chưa có lịch sử").classes("text-sm text-gray-400 italic")
                    else:
                        for log in logs:
                            dot_c = _ACTION_COLOR_MAP.get(log.get("action_color", "blue"), "#2563EB")
                            with ui.row().classes("w-full gap-3 items-start"):
                                ui.element("div").style(
                                    f"min-width:10px;height:10px;border-radius:50%;"
                                    f"background:{dot_c};margin-top:5px;flex-shrink:0"
                                )
                                with ui.column().classes("flex-1 gap-0"):
                                    ui.label(log.get("timestamp", "")).classes("text-xs text-gray-400 font-mono")
                                    ui.label(log.get("performed_by_role", "")).classes("text-xs text-gray-500")
                                    ui.label(log.get("action_label", "")).classes("text-sm font-medium text-gray-800")

            right_panel.show()

        # ── Grid loader ───────────────────────────────────────────────────────
        async def load_grid():
            dept_id = sel_dept.value
            year    = sel_year.value
            month   = sel_month.value
            if not dept_id or not year or not month:
                return

            _save_filter_state()
            title_label.set_text(f"{dept_opts.get(dept_id, '')} tháng {month:02d}/{year}")

            grid_container.clear()
            loading_row.classes(remove="hidden")

            try:
                data = await asyncio.to_thread(
                    api.get,
                    "/api/handovers/grid",
                    {"department_id": dept_id, "year": year, "month": month},
                )
            except Exception as e:
                _handle_api_error(e)
                loading_row.classes(add="hidden")
                return

            loading_row.classes(add="hidden")

            users         = data["users"]
            entries       = data["entries"]
            days_in_month = data["days_in_month"]

            # cell_data[uid][day] = {sheet_count, entry_id, entry_status}
            cell_data: dict = {}
            for e in entries:
                uid_key = e["staff_id"]
                day_key = e["day"]
                cell_data.setdefault(uid_key, {})[day_key] = {
                    "sheet_count":   e["sheet_count"],
                    "entry_id":      e.get("entry_id"),
                    "entry_status":  e.get("entry_status", "confirmed"),
                }

            import calendar as _cal
            import html as _html

            # ── Build grid as single HTML string (much faster than NiceGUI widgets) ──
            NW  = 200  # name column width px
            CW  = 50   # cell width px — chiều rộng lý tưởng
            MCW = 30   # cell width tối thiểu — co xuống mức này để vừa màn hình, hẹp hơn nữa mới cuộn ngang
            # Bắt buộc: không có border-box thì padding/border của header (10px 2px + 1px)
            # và của ô dữ liệu (chỉ border 1–2px) cộng thêm khác nhau → header lệch cột với ô nhập.
            BB  = "box-sizing:border-box"
            _SB = {    # status → (bg, border)
                "confirmed":       ("#DCFCE7", "2px solid #16A34A"),
                "pending_confirm": ("#FEF3C7", "2px solid #F59E0B"),
                "borrowed":        ("#EDE9FE", "2px solid #7C3AED"),
                "rejected":        ("#FEE2E2", "2px solid #DC2626"),
            }

            if not users:
                with grid_container:
                    ui.label("Không có cán bộ nào trong phòng này").classes(
                        "text-gray-400 text-center py-8 w-full"
                    )
            else:
                p = [
                    '<div style="overflow-x:auto;width:100%;border:1px solid #bfdbfe;'
                    'border-radius:10px;box-shadow:0 2px 10px rgba(30,64,175,.10);">'
                ]
                # Chiều rộng tối thiểu của hàng: dưới mức này mới cho cuộn ngang
                row_min = NW + days_in_month * MCW

                # Header row
                p.append(
                    f'<div style="display:flex;flex-wrap:nowrap;min-width:{row_min}px;'
                    'background:#dbeafe;border-bottom:2px solid #93c5fd;">'
                    f'<div style="{BB};min-width:{NW}px;width:{NW}px;flex-shrink:0;font-size:14px;font-weight:700;'
                    f'color:#1e40af;padding:10px 14px;border-right:2px solid #93c5fd;'
                    f'position:sticky;left:0;z-index:3;background:#dbeafe;">Họ và tên</div>'
                )
                for d in range(1, days_in_month + 1):
                    dow = _cal.weekday(year, month, d)
                    hbg = "#fde68a" if dow >= 5 else "#dbeafe"
                    hcl = "#92400e" if dow >= 5 else "#1e40af"
                    p.append(
                        f'<div style="{BB};flex:0 1 {CW}px;min-width:{MCW}px;text-align:center;'
                        f'font-size:13px;font-weight:700;color:{hcl};padding:10px 2px;'
                        f'border-right:1px solid #bfdbfe;background:{hbg};">{d:02d}</div>'
                    )
                p.append('</div>')

                # Data rows
                for row_idx, u in enumerate(users):
                    uid    = u["id"]
                    name   = (u.get("full_name") or u.get("ipcas_code")
                              or u.get("employee_code") or u.get("username") or "")
                    rbg    = "#ffffff" if row_idx % 2 == 0 else "#f0f9ff"
                    p.append(
                        f'<div style="display:flex;flex-wrap:nowrap;min-width:{row_min}px;'
                        f'border-bottom:1px solid #dbeafe;background:{rbg};">'
                        f'<div style="{BB};min-width:{NW}px;width:{NW}px;flex-shrink:0;font-size:15px;font-weight:500;'
                        f'padding:7px 14px;border-right:2px solid #dbeafe;white-space:nowrap;overflow:hidden;'
                        f'display:flex;align-items:center;position:sticky;left:0;z-index:2;background:{rbg};">'
                        f'{_html.escape(name)}</div>'
                    )
                    for d in range(1, days_in_month + 1):
                        info    = cell_data.get(uid, {}).get(d, {})
                        val     = info.get("sheet_count", 0)
                        eid     = info.get("entry_id")
                        status  = info.get("entry_status", "confirmed")
                        dow     = _cal.weekday(year, month, d)
                        if val:
                            cbg, bdr = _SB.get(status, ("#f3f4f6", "1px solid #d1d5db"))
                        elif dow >= 5:
                            cbg, bdr = "#fef9c3", "1px solid #dbeafe"
                        else:
                            cbg, bdr = rbg, "1px solid #dbeafe"
                        eid_attr = f' data-eid="{eid}"' if eid else ""
                        _locked = not api.has_feature("handovers.confirm_entry") and status in ("confirmed", "borrowed") and val
                        _ro_attr = " readonly" if _locked else ""
                        _cursor  = "cursor:not-allowed;opacity:0.7;" if _locked else ""
                        p.append(
                            f'<div style="{BB};flex:0 1 {CW}px;min-width:{MCW}px;background:{cbg};border-right:{bdr};">'
                            f'<input class="hv-inp" id="hv_{row_idx}_{d}" data-uid="{uid}" data-day="{d}"'
                            f' data-orig="{val}" data-uname="{_html.escape(name, quote=True)}"{eid_attr}{_ro_attr}'
                            f' value="{val if val else ""}"'
                            f' style="width:100%;border:none;outline:none;background:transparent;{_cursor}'
                            f'font-size:14px;font-weight:600;color:#1e3a8a;text-align:center;'
                            f'padding:7px 0;box-sizing:border-box;" /></div>'
                        )
                    p.append('</div>')
                p.append('</div>')

                with grid_container:
                    ui.html("".join(p))

                ui.run_javascript(f"""
                    window._hv_max_row = {len(users) - 1};
                    window._hv_max_col = {days_in_month};
                    document.querySelectorAll('.hv-inp').forEach(function(inp) {{
                        inp.addEventListener('focus', function() {{
                            var eid = inp.dataset.eid;
                            if (eid) emitEvent('hv_open_panel', {{entry_id: parseInt(eid), user_name: inp.dataset.uname||''}});
                        }});
                    }});
                    if (!window._hv_arrow_registered) {{
                        window._hv_arrow_registered = true;
                        document.addEventListener('keydown', function(e) {{
                            if (!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) return;
                            var a = document.activeElement;
                            if (!a || !a.classList.contains('hv-inp')) return;
                            var pts = a.id.split('_');
                            if (pts.length < 3) return;
                            var row = parseInt(pts[1]), col = parseInt(pts[2]);
                            var mr = window._hv_max_row, mc = window._hv_max_col;
                            e.preventDefault();
                            var tr = row, tc = col;
                            if (e.key==='ArrowUp') tr=Math.max(0,row-1);
                            else if (e.key==='ArrowDown') tr=Math.min(mr,row+1);
                            else if (e.key==='ArrowLeft') {{ if(col>1)tc=col-1; else if(row>0){{tr=row-1;tc=mc;}} }}
                            else if (e.key==='ArrowRight') {{ if(col<mc)tc=col+1; else if(row<mr){{tr=row+1;tc=1;}} }}
                            if (tr!==row||tc!==col) {{
                                var el=document.getElementById('hv_'+tr+'_'+tc);
                                if(el) {{ el.focus(); el.select(); }}
                            }}
                        }});
                    }}
                """)

        # app.storage.tab chỉ khả dụng sau khi WebSocket kết nối
        try:
            await ui.context.client.connected()
        except Exception:
            pass

        saved = app.storage.tab
        init_dept  = saved.get("hv_dept",  default_dept)
        init_year  = saved.get("hv_year",  default_year)
        init_month = saved.get("hv_month", default_month)
        if init_dept not in dept_opts:
            init_dept = default_dept

        if not is_cv:
            sel_dept.value  = init_dept
        sel_year.value  = init_year
        sel_month.value = init_month

        ui.on('hv_open_panel', lambda e: asyncio.ensure_future(
            open_entry_panel(e.args['entry_id'], e.args.get('user_name', ''))
        ))

        await load_grid()
