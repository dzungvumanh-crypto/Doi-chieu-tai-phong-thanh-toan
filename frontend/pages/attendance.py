"""Chấm công — Phòng Kế toán. Theo pattern frontend/pages/leaves.py."""
import asyncio
from datetime import date
from typing import Optional

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _card, _require_auth, _handle_api_error

_DOW_VN = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


def _empty():
    async def _e():
        return None
    return _e()


@ui.page("/attendance")
async def attendance_page(year: Optional[int] = None, month: Optional[int] = None):
    if not _require_auth():
        return
    await _sidebar("attendance")

    current_user = api.get_current_user()
    role = current_user.get("role", "") if current_user else ""
    my_id = current_user.get("id") if current_user else None
    is_manager = role in ("truong_phong", "pho_phong", "admin")
    is_admin = role == "admin"
    # Quyền xem cả phòng / xuất Excel: trưởng/phó phòng/admin (is_manager) LUÔN có,
    # CỘNG THÊM bất kỳ GDV nào được admin gán riêng qua màn Phân quyền theo nhóm
    # (attendance.view_dept / attendance.export) — không ai bị mất quyền đang có.
    can_view_dept = is_manager or api.has_feature("attendance.view_dept")
    can_export = is_manager or api.has_feature("attendance.export")

    today = date.today()
    year = year or today.year
    month = month or today.month

    with _content_area():
        _page_header("Chấm công", "Phòng Kế toán")

        try:
            results = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/attendance/month", {"scope": "mine", "year": year, "month": month}),
                asyncio.to_thread(api.get, "/api/attendance/month", {"scope": "dept", "year": year, "month": month}) if can_view_dept else _empty(),
                asyncio.to_thread(api.get, "/api/attendance/adjustments", {"scope": "mine"}),
                asyncio.to_thread(api.get, "/api/attendance/adjustments", {"scope": "pending"}) if is_manager else _empty(),
                asyncio.to_thread(api.get, "/api/attendance/symbols"),
                # Danh sách trưởng/phó phòng cho dropdown "Người kiểm soát" khi xuất Excel.
                asyncio.to_thread(api.get, "/api/attendance/managers") if can_export else _empty(),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, api.SessionExpiredError):
                    ui.notify(str(r), type="warning")
                    ui.navigate.to("/login")
                    return
            mine_month, dept_month, my_adjustments, pending_adjustments, symbols, managers = results
            if isinstance(mine_month, Exception):
                raise mine_month
            # Rà soát tiếp theo: return_exceptions=True nuốt lỗi (403/500/timeout) của
            # 5 nguồn dữ liệu phụ thành Exception — nếu không báo, chúng âm thầm biến
            # thành None/[] và UI hiện nhầm trạng thái "trống"/"chưa có nhân viên" thay
            # vì báo lỗi thật (vd GDV được cấp attendance.view_dept nhưng scope=dept bị
            # 403 ở backend vì lệch quyền). Cùng pattern đã fix ở frontend/pages/leaves.py.
            _fetch_errors = [
                _name for _name, _val in (
                    ("Bảng công phòng", dept_month), ("Yêu cầu của tôi", my_adjustments),
                    ("Yêu cầu chờ duyệt", pending_adjustments), ("Ký hiệu công", symbols),
                    ("Danh sách kiểm soát", managers),
                )
                if isinstance(_val, Exception)
            ]
            if _fetch_errors:
                ui.notify(
                    f"Không tải được: {', '.join(_fetch_errors)} — số liệu có thể thiếu/sai, vui lòng tải lại trang.",
                    type="negative", timeout=8000,
                )
            dept_month = dept_month if isinstance(dept_month, dict) else None
            my_adjustments = my_adjustments if isinstance(my_adjustments, list) else []
            pending_adjustments = pending_adjustments if isinstance(pending_adjustments, list) else []
            symbols = symbols if isinstance(symbols, list) else []
            managers = managers if isinstance(managers, list) else []
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Không tải được dữ liệu chấm công: {e}", type="negative")
            return

        symbol_options = {s["symbol"]: f'{s["symbol"]} — {s["description"]}' for s in symbols if s["is_active"]}

        # ── Thanh điều hướng tháng ──
        with ui.row().classes("items-center gap-3 mb-4"):
            def _go(y, m):
                ui.navigate.to(f"/attendance?year={y}&month={m}")

            py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
            ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
            ui.button(icon="chevron_left", on_click=lambda: _go(py, pm)).props("flat round")
            ui.label(f"Tháng {month:02d}/{year}").classes("text-lg font-semibold")
            ui.button(icon="chevron_right", on_click=lambda: _go(ny, nm)).props("flat round")

            if can_export:
                # Xuất Excel giờ cần chọn "Người kiểm soát" trước (theo mẫu thật của
                # phòng — 2 dòng ký "Lập bảng"/"Kiểm soát") nên mở dialog thay vì tải
                # trực tiếp như trước.
                ui.button("Xuất Excel", icon="download", on_click=lambda: kiem_soat_dialog.open()).classes("bg-red-700 text-white ml-4")

            if is_admin:
                ui.button(icon="settings", on_click=lambda: symbols_dialog.open()).props("flat round").tooltip("Cấu hình ký hiệu công")

        # ── Tabs ── (t_dept theo can_view_dept — cộng thêm quyền nhóm, không chỉ role)
        with ui.tabs().classes("mb-4") as att_tabs:
            t_dept = ui.tab("Bảng công phòng") if can_view_dept else None
            t_mine = ui.tab("Công của tôi")
            t_review = ui.tab("Duyệt điều chỉnh") if is_manager else None

        edit_dialog = ui.dialog()
        adjust_dialog = ui.dialog()
        reject_dialog = ui.dialog()
        symbols_dialog = ui.dialog()
        kiem_soat_dialog = ui.dialog()

        def _color_for(symbol):
            s = next((s for s in symbols if s["symbol"] == symbol), None)
            return s["color"] if s else "#E5E7EB"

        def _render_grid(month_data: dict, editable: bool, on_cell_click):
            days_in_month = month_data["days_in_month"]
            holidays = set(month_data["holidays"])
            cols = f"12rem repeat({days_in_month}, minmax(2rem, 1fr)) 5rem"
            with ui.element("div").style(f"display:grid;grid-template-columns:{cols};gap:1px;min-width:{40*days_in_month+300}px"):
                ui.label("Nhân viên").classes("text-xs font-bold bg-gray-100 p-1 sticky left-0")
                for day_num in range(1, days_in_month + 1):
                    d = date(year, month, day_num)
                    bg = "bg-green-100" if d.isoformat() in holidays else ("bg-yellow-100" if d.weekday() >= 5 else "bg-gray-100")
                    with ui.column().classes(f"items-center p-0.5 {bg}").style("gap:0"):
                        ui.label(str(day_num)).classes("text-xs font-bold")
                        ui.label(_DOW_VN[d.weekday()]).classes("text-[9px] text-gray-500")
                ui.label("Tổng").classes("text-xs font-bold bg-gray-100 p-1 text-center")

                for srow in month_data["staff"]:
                    ui.label(srow["full_name"]).classes("text-xs p-1 border-t sticky left-0 bg-white")
                    for day_num in range(1, days_in_month + 1):
                        d = date(year, month, day_num)
                        dinfo = srow["days"].get(d.isoformat()) or {}
                        symbol = dinfo.get("symbol")
                        if symbol:
                            color = _color_for(symbol)
                        elif d.isoformat() in holidays:
                            # Ô ngày lễ trong lưới dữ liệu trước đây trắng trơn như ô chưa
                            # chấm, khó phân biệt "nghỉ lễ" với "quên chấm" (rà soát vòng 2
                            # PR #22) — tô cùng màu xanh nhạt với dòng tiêu đề.
                            color = "#DCFCE7"
                        elif d > today:
                            color = "#F3F4F6"
                        else:
                            color = "#FFFFFF"
                        cell = ui.element("div").classes(
                            "text-xs flex items-center justify-center border-t h-7"
                            + (" cursor-pointer hover:opacity-70" if editable else "")
                        ).style(f"background-color:{color}")
                        with cell:
                            ui.label(symbol or "")
                        if editable:
                            cell.on("click", lambda e, sid=srow["staff_id"], sname=srow["full_name"], d=d: on_cell_click(sid, sname, d))
                    ui.label(f'{srow["total_work_value"]:g}').classes("text-xs font-bold p-1 border-t text-center")

        # ── Dialog: Trưởng/phó phòng sửa công 1 ngày ──
        edit_state = {}

        def open_edit_dialog(staff_id, staff_name, d: date):
            edit_state.update(staff_id=staff_id, date=d)
            edit_title.set_text(f"Sửa công — {staff_name} — {d.isoformat()}")
            edit_symbol.set_value(None)
            edit_note.set_value("")
            edit_dialog.open()

        with edit_dialog, ui.card().classes("w-96"):
            edit_title = ui.label("Sửa công").classes("font-bold")
            edit_symbol = ui.select(symbol_options, label="Ký hiệu").classes("w-full")
            edit_note = ui.textarea(label="Ghi chú (tuỳ chọn)").classes("w-full")
            with ui.row().classes("justify-end w-full gap-2"):
                ui.button("Huỷ", on_click=edit_dialog.close).props("flat")

                async def _save_edit():
                    if not edit_symbol.value:
                        ui.notify("Chọn ký hiệu", type="warning")
                        return
                    try:
                        path = f"/api/attendance/day?staff_id={edit_state['staff_id']}&date={edit_state['date'].isoformat()}"
                        await asyncio.to_thread(api.put, path, {"symbol": edit_symbol.value, "note": edit_note.value or None})
                        edit_dialog.close()
                        ui.notify("Đã lưu", type="positive")
                        ui.timer(0.8, lambda: ui.navigate.to(f"/attendance?year={year}&month={month}"), once=True)
                    except Exception as e:
                        if not _handle_api_error(e):
                            ui.notify(str(e), type="negative")
                ui.button("Lưu", on_click=_save_edit).classes("bg-red-700 text-white")

        # ── Dialog: chuyên viên xin điều chỉnh ──
        adjust_state = {}

        def open_adjust_dialog(staff_id, staff_name, d: date):
            adjust_state.update(staff_id=staff_id, date=d)
            adjust_title.set_text(f"Yêu cầu điều chỉnh công — {d.isoformat()}")
            adjust_symbol.set_value(None)
            adjust_reason.set_value("")
            adjust_dialog.open()

        with adjust_dialog, ui.card().classes("w-96"):
            adjust_title = ui.label("Yêu cầu điều chỉnh").classes("font-bold")
            adjust_symbol = ui.select(symbol_options, label="Ký hiệu mong muốn").classes("w-full")
            adjust_reason = ui.textarea(label="Lý do (bắt buộc)").classes("w-full")
            with ui.row().classes("justify-end w-full gap-2"):
                ui.button("Huỷ", on_click=adjust_dialog.close).props("flat")

                async def _submit_adjust():
                    if not adjust_symbol.value:
                        ui.notify("Chọn ký hiệu", type="warning")
                        return
                    if not adjust_reason.value or not adjust_reason.value.strip():
                        ui.notify("Nhập lý do", type="warning")
                        return
                    # Khoá nút ngay khi bấm — chặn bớt trường hợp bấm nhanh 2 lần
                    # trước khi có phản hồi (chống lặp thêm cùng với check ở
                    # backend, backend mới là chốt chặn chính vì debounce phía
                    # client không chặn được request bị mạng tự gửi lại).
                    submit_btn.set_enabled(False)
                    try:
                        body = {
                            "staff_id": adjust_state["staff_id"] if adjust_state["staff_id"] != my_id else None,
                            "date": adjust_state["date"].isoformat(),
                            "new_symbol": adjust_symbol.value,
                            "reason": adjust_reason.value.strip(),
                        }
                        await asyncio.to_thread(api.post, "/api/attendance/adjustments", body)
                        adjust_dialog.close()
                        ui.notify("Đã gửi yêu cầu điều chỉnh", type="positive")
                        ui.timer(0.8, lambda: ui.navigate.to(f"/attendance?year={year}&month={month}"), once=True)
                    except Exception as e:
                        if not _handle_api_error(e):
                            ui.notify(str(e), type="negative")
                    finally:
                        submit_btn.set_enabled(True)
                submit_btn = ui.button("Gửi", on_click=_submit_adjust).classes("bg-red-700 text-white")

        # ── Dialog: từ chối điều chỉnh (yêu cầu lý do) ──
        reject_state = {}
        with reject_dialog, ui.card().classes("w-96"):
            ui.label("Từ chối yêu cầu điều chỉnh").classes("font-bold")
            reject_reason_input = ui.textarea(label="Lý do từ chối (bắt buộc)").classes("w-full")
            with ui.row().classes("justify-end w-full gap-2"):
                ui.button("Huỷ", on_click=reject_dialog.close).props("flat")

                async def _confirm_reject():
                    if not reject_reason_input.value or not reject_reason_input.value.strip():
                        ui.notify("Nhập lý do từ chối", type="warning")
                        return
                    try:
                        await asyncio.to_thread(
                            api.put, f"/api/attendance/adjustments/{reject_state['id']}/review",
                            {"action": "reject", "reject_reason": reject_reason_input.value.strip()},
                        )
                        reject_dialog.close()
                        ui.notify("Đã từ chối", type="positive")
                        ui.timer(0.8, lambda: ui.navigate.to(f"/attendance?year={year}&month={month}"), once=True)
                    except Exception as e:
                        if not _handle_api_error(e):
                            ui.notify(str(e), type="negative")
                ui.button("Xác nhận từ chối", on_click=_confirm_reject).classes("bg-red-700 text-white")

        async def _approve_adjustment(adj_id):
            try:
                await asyncio.to_thread(api.put, f"/api/attendance/adjustments/{adj_id}/review", {"action": "approve"})
                ui.notify("Đã duyệt", type="positive")
                ui.timer(0.8, lambda: ui.navigate.to(f"/attendance?year={year}&month={month}"), once=True)
            except Exception as e:
                if not _handle_api_error(e):
                    ui.notify(str(e), type="negative")

        def open_reject_dialog(adj_id):
            reject_state["id"] = adj_id
            reject_reason_input.set_value("")
            reject_dialog.open()

        # ── Dialog: quản lý ký hiệu (admin) ──
        with symbols_dialog, ui.card().classes("w-[32rem]"):
            ui.label("Cấu hình ký hiệu công").classes("font-bold text-lg mb-2")
            for s in symbols:
                with ui.row().classes("items-center gap-2 w-full border-b py-1"):
                    ui.element("div").classes("w-4 h-4 rounded").style(f"background-color:{s['color']}")
                    ui.label(s["symbol"]).classes("font-bold w-10")
                    ui.label(s["description"]).classes("flex-1 text-sm")
                    ui.label(f'{s["work_value"]:g} công').classes("text-xs text-gray-500")
                    # BUG đã sửa: asyncio.create_task(...) tạo task tách rời khỏi
                    # slot context của NiceGUI → ui.notify() bên trong crash âm thầm
                    # (RuntimeError "slot stack is empty", không hiện trên trình
                    # duyệt). Trả thẳng coroutine để NiceGUI tự await đúng context.
                    ui.switch(
                        value=bool(s["is_active"]),
                        on_change=lambda e, sym=s["symbol"]: _toggle_symbol(sym, e.value),
                    ).props("dense")

            ui.separator().classes("my-3")
            ui.label("Thêm ký hiệu mới").classes("font-semibold text-sm mb-1")
            with ui.row().classes("w-full gap-2 items-start"):
                new_symbol_input = ui.input(label="Ký hiệu").classes("w-20")
                new_desc_input = ui.input(label="Mô tả").classes("flex-1")
            with ui.row().classes("w-full gap-2 items-start mt-1"):
                new_value_input = ui.number(label="Số công", value=1, step=0.5, min=0, max=1).classes("w-28")
                new_color_input = ui.input(label="Màu (hex)", value="#E5E7EB").classes("w-32")
            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                # BUG đã sửa (cùng nguyên nhân slot-context như trên). Vẫn cần lambda
                # (không truyền thẳng tên hàm) vì _create_symbol định nghĩa PHÍA DƯỚI
                # — lambda hoãn tra tên tới lúc gọi, nhưng KHÔNG bọc asyncio.create_task().
                ui.button("Thêm ký hiệu", on_click=lambda: _create_symbol()).classes("bg-red-700 text-white")

            ui.button("Đóng", on_click=symbols_dialog.close).classes("mt-3")

        async def _toggle_symbol(symbol, active):
            try:
                await asyncio.to_thread(api.put, f"/api/attendance/symbols/{symbol}", {"is_active": bool(active)})
                ui.notify(f"Đã cập nhật ký hiệu {symbol}", type="positive")
            except Exception as e:
                if not _handle_api_error(e):
                    ui.notify(str(e), type="negative")

        async def _create_symbol():
            sym = (new_symbol_input.value or "").strip()
            desc = (new_desc_input.value or "").strip()
            if not sym or not desc:
                ui.notify("Nhập đủ ký hiệu và mô tả", type="warning")
                return
            try:
                await asyncio.to_thread(api.post, "/api/attendance/symbols", {
                    "symbol": sym,
                    "description": desc,
                    "work_value": new_value_input.value if new_value_input.value is not None else 0,
                    "color": (new_color_input.value or "#E5E7EB").strip(),
                    "is_active": True,
                })
                ui.notify(f"Đã thêm ký hiệu '{sym}'", type="positive")
                symbols_dialog.close()
                ui.timer(0.8, lambda: ui.navigate.to(f"/attendance?year={year}&month={month}"), once=True)
            except Exception as e:
                if not _handle_api_error(e):
                    ui.notify(str(e), type="negative")

        # ── Dialog: chọn "Người kiểm soát" trước khi xuất Excel (theo mẫu thật) ──
        manager_options = {m["id"]: m["full_name"] for m in managers}
        with kiem_soat_dialog, ui.card().classes("w-96"):
            ui.label("Chọn người kiểm soát").classes("font-bold")
            kiem_soat_select = ui.select(manager_options, label="Người kiểm soát (trưởng/phó phòng)").classes("w-full")
            with ui.row().classes("justify-end w-full gap-2 mt-2"):
                ui.button("Huỷ", on_click=kiem_soat_dialog.close).props("flat")

                async def _download_export():
                    if not kiem_soat_select.value:
                        ui.notify("Chọn người kiểm soát", type="warning")
                        return
                    try:
                        content = await asyncio.to_thread(
                            api.download, "/api/attendance/export",
                            {"year": year, "month": month, "kiem_soat_id": kiem_soat_select.value},
                        )
                        ui.download(content, f"bang_cong_{year}_{month:02d}.xlsx")
                        kiem_soat_dialog.close()
                    except Exception as e:
                        if not _handle_api_error(e):
                            ui.notify(str(e), type="negative")
                # BUG đã sửa: đây chính là lỗi "tải báo cáo không hoạt động" người
                # dùng báo — backend trả 200 OK đúng, nhưng asyncio.create_task()
                # khiến ui.download() bên trong _download_export chạy ở task tách
                # rời, mất slot context nên crash âm thầm (không hiện lỗi ở trình
                # duyệt). _download_export định nghĩa ngay phía trên nên truyền
                # thẳng tên hàm, không cần lambda.
                ui.button("Tải xuống", on_click=_download_export).classes("bg-red-700 text-white")

        # ── Nội dung tab ──
        with ui.tab_panels(att_tabs, value=(t_dept if can_view_dept else t_mine)).classes("w-full"):
            if t_dept:
                with ui.tab_panel(t_dept):
                    with _card():
                        with ui.element("div").classes("overflow-x-auto w-full p-2"):
                            if dept_month and dept_month["staff"]:
                                # editable=is_manager (không phải can_view_dept) — GDV chỉ
                                # được cấp attendance.view_dept là XEM, sửa trực tiếp (PUT
                                # /day) vẫn chỉ dành cho trưởng/phó phòng/admin ở backend.
                                _render_grid(dept_month, is_manager, open_edit_dialog)
                            else:
                                ui.label("Chưa có nhân viên nào trong Phòng Kế toán.").classes("text-gray-500 p-4")

            with ui.tab_panel(t_mine):
                with _card():
                    with ui.element("div").classes("overflow-x-auto w-full p-2"):
                        _render_grid(mine_month, True, open_adjust_dialog)

                with _card("Yêu cầu điều chỉnh đã gửi"):
                    if not my_adjustments:
                        ui.label("Chưa có yêu cầu nào.").classes("text-gray-500 p-4")
                    for adj in my_adjustments:
                        status_color = {"pending": "text-yellow-600", "approved": "text-green-600", "rejected": "text-red-600"}.get(adj["status"], "")
                        with ui.row().classes("items-center gap-3 w-full border-b py-2 px-2"):
                            ui.label(adj["date"]).classes("text-sm w-24")
                            ui.label(f'{adj["old_symbol"] or "-"} → {adj["new_symbol"]}').classes("text-sm w-24")
                            ui.label(adj["reason"]).classes("text-sm flex-1 text-gray-600")
                            ui.label(adj["status"]).classes(f"text-sm font-semibold {status_color}")
                            if adj["status"] == "rejected" and adj.get("reject_reason"):
                                ui.label(f'Lý do: {adj["reject_reason"]}').classes("text-xs text-red-500")

            if t_review:
                with ui.tab_panel(t_review):
                    with _card(f"Yêu cầu chờ duyệt ({len(pending_adjustments)})"):
                        if not pending_adjustments:
                            ui.label("Không có yêu cầu nào chờ duyệt.").classes("text-gray-500 p-4")
                        for adj in pending_adjustments:
                            with ui.row().classes("items-center gap-3 w-full border-b py-2 px-2"):
                                ui.label(adj["staff_name"]).classes("text-sm w-32 font-semibold")
                                ui.label(adj["date"]).classes("text-sm w-24")
                                ui.label(f'{adj["old_symbol"] or "-"} → {adj["new_symbol"]}').classes("text-sm w-24")
                                ui.label(adj["reason"]).classes("text-sm flex-1 text-gray-600")
                                ui.button("Duyệt", on_click=lambda e, i=adj["id"]: _approve_adjustment(i)).props("dense").classes("bg-green-600 text-white")
                                ui.button("Từ chối", on_click=lambda e, i=adj["id"]: open_reject_dialog(i)).props("dense").classes("bg-red-600 text-white")
