"""Trang Phân lịch trực — Phòng Thanh toán."""
import asyncio
import html as _html
from datetime import date, timedelta

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

_TYPE_ROW_COLOR = {
    "normal":          "#EFF6FF",
    "friday":          "#EEF2FF",
    "cutoff":          "#FFF7ED",
    "settlement_main": "#F5F3FF",
    "settlement_sub":  "#F9FAFB",
}

_SPECIAL_COLOR = {
    "holiday":    ("bg-red-50", "Nghỉ lễ",      "text-red-700"),
    "cutoff":     ("bg-orange-50", "Cut-off",    "text-orange-700"),
    "settlement": ("bg-purple-50", "Quyết toán", "text-purple-700"),
    "makeup":     ("bg-blue-50", "Ngày bù",      "text-blue-700"),
}

_TH = "px-3 py-2 text-left font-medium border border-red-700 bg-red-800 text-white text-sm"
_TD = "px-3 py-2 border border-gray-200 text-sm"

_THU_VN = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu"]


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _fmt_week_label(ws: date) -> str:
    we = ws + timedelta(days=4)
    return f"Tuần {ws:%d/%m} – {we:%d/%m/%Y}"


def _h(s) -> str:
    """HTML-escape để tránh XSS khi render dữ liệu user."""
    return _html.escape(str(s or ""))


def _ten_kem_sp(p: dict, la_sp: bool) -> str:
    """Tên người trực; đánh dấu (SP) cho người xử lý song phương của ca.
    Nhãn (SP) chỉ phục vụ giai đoạn đang phân lịch — gỡ khi chốt chương trình."""
    ten = _h((p or {}).get("full_name", ""))
    return f'{ten} <span class="text-blue-700 font-medium">(SP)</span>' if la_sp else ten


def _nhan_trang_thai(shifts: list) -> str:
    """Trạng thái tuần hiển thị cạnh tiêu đề — thay cho cột 'Trạng thái' đã bỏ khỏi bảng."""
    if not shifts:
        return ' <span class="text-gray-500 font-normal">— chưa có lịch</span>'
    da_xn = sum(1 for s in shifts if s["status"] == "confirmed")
    if da_xn == len(shifts):
        return ' <span class="text-green-700">— đã xác nhận</span>'
    if da_xn == 0:
        return ' <span class="text-orange-600">— bản thảo</span>'
    return f' <span class="text-orange-600">— đã xác nhận {da_xn}/{len(shifts)} ca</span>'


@ui.page("/duty_schedule")
async def duty_schedule_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.duty_schedule"):
        ui.navigate.to("/home")
        return

    can_generate     = api.has_feature("duty.generate")
    can_confirm      = api.has_feature("duty.confirm")
    can_delete       = api.has_feature("duty.delete")
    can_export       = api.has_feature("duty.export")
    can_manage_staff = api.has_feature("duty.manage_staff")
    can_manage_cfg   = api.has_feature("duty.manage_config")
    can_write        = any([can_generate, can_confirm, can_delete, can_export,
                            can_manage_staff, can_manage_cfg])

    _sidebar("duty_schedule")
    with _content_area():
        _page_header("Phân lịch trực", "Phân ca trực Phòng Thanh toán theo tuần")

        with ui.tabs().classes("mb-0") as tabs:
            tab_schedule = ui.tab("schedule",  label="Phân lịch",     icon="event")
            tab_staff    = ui.tab("staff",     label="Nhân viên",     icon="groups")
            tab_absence  = ui.tab("absence",   label="Vắng mặt",      icon="event_busy")
            tab_stats    = ui.tab("stats",     label="Thống kê",      icon="bar_chart")
            tab_specials = ui.tab("specials",  label="Ngày đặc biệt", icon="calendar_month")
            tab_settings = ui.tab("settings",  label="Cài đặt",       icon="settings")

        with ui.tab_panels(tabs, value=tab_schedule).classes("w-full"):

            # ════════════════════════════════════════════════════
            # TAB 1 — PHÂN LỊCH
            # ════════════════════════════════════════════════════
            with ui.tab_panel(tab_schedule):
                ws_ref = {"value": _week_start(date.today())}
                week_label = ui.html("").classes("text-base font-semibold text-red-800 my-1")
                schedule_area = ui.column().classes("w-full gap-1")

                # Danh sách nhân sự + vắng mặt, nạp cùng lịch để hộp thoại sửa dùng lại
                nhan_su_ref: dict = {"list": [], "vang_mat": set()}

                async def load_schedule():
                    ws = ws_ref["value"]
                    week_label.set_content(_fmt_week_label(ws))
                    schedule_area.clear()
                    shifts, staff_list, absences = await asyncio.gather(
                        asyncio.to_thread(api.get, "/api/duty/schedule/week",
                                          {"week_start": ws.isoformat()}),
                        asyncio.to_thread(api.get, "/api/duty/staff"),
                        asyncio.to_thread(api.get, "/api/duty/constraints/absences",
                                          {"month": ws.month, "year": ws.year}),
                        return_exceptions=True,
                    )
                    # Chỉ bảng lịch là bắt buộc. Danh sách nhân sự / vắng mặt hỏng thì
                    # vẫn phải xem được lịch — chỉ mất ghi chú trong hộp thoại sửa.
                    if isinstance(shifts, Exception):
                        if _handle_api_error(shifts):
                            return
                        return
                    if isinstance(staff_list, Exception):
                        ui.notify("Không tải được danh sách nhân sự — tạm thời chưa sửa được ca.",
                                  type="warning")
                        staff_list = []
                    if isinstance(absences, Exception):
                        ui.notify("Không tải được danh sách vắng mặt — hộp thoại sửa sẽ "
                                  "không ghi chú ai đang nghỉ phép.", type="warning")
                        absences = []

                    nhan_su_ref["list"] = staff_list
                    nhan_su_ref["vang_mat"] = {(a["staff_id"], a["absence_date"]) for a in absences}

                    week_label.set_content(_fmt_week_label(ws) + _nhan_trang_thai(shifts))

                    # Gom ca theo ngày — bảng luôn dựng đủ 5 hàng T2→T6
                    theo_ngay: dict = {}
                    for s in shifts:
                        theo_ngay.setdefault(s["shift_date"], []).append(s)

                    with schedule_area:
                        with ui.column().classes("w-full gap-0 border border-gray-200 rounded overflow-hidden"):
                            # ── Tiêu đề cột ──
                            with ui.row().classes("w-full bg-red-800 text-white px-2 py-2 "
                                                  "text-xs font-semibold gap-2 items-center"):
                                ui.label("Ngày trực").classes("w-28 shrink-0")
                                ui.label("Nhân viên 1").classes("flex-1 min-w-[130px]")
                                ui.label("Nhân viên 2").classes("flex-1 min-w-[130px]")
                                ui.label("Lãnh đạo").classes("flex-1 min-w-[130px]")
                                ui.label("Tình trạng").classes("w-36 shrink-0")

                            # ── 5 hàng T2 → T6 ──
                            for i in range(5):
                                ds = (ws + timedelta(days=i)).isoformat()
                                _dung_hang(i, ds, theo_ngay.get(ds, []))

                        if not shifts:
                            ui.label("Chưa có lịch trực tuần này. Nhấn 'Tạo lịch' để sinh tự động.").classes(
                                "text-gray-500 italic py-2"
                            )

                def _dung_hang(i: int, ds: str, ca_ngay: list) -> None:
                    """Một hàng = một ngày. Ngày quyết toán có 2 ca thì gộp người vào cùng hàng."""
                    bg = _TYPE_ROW_COLOR.get(ca_ngay[0]["shift_type"], "#FFFFFF") if ca_ngay else "#FFFFFF"

                    nguoi_nv, nguoi_ld, canh_bao = [], [], []
                    for s in ca_ngay:
                        warn = s.get("sp_warning") or ""
                        sp   = s.get("sp")
                        # sp=None kèm cảnh báo SP nghĩa là Lãnh đạo giữ vai song phương
                        ld_giu_sp = sp is None and warn in ("leader_sp", "multi_sp")

                        for p in ([sp] if sp else []) + (s.get("nvs") or []):
                            nguoi_nv.append(_ten_kem_sp(p, bool(sp) and p["id"] == sp["id"]))
                        if s.get("leader"):
                            nguoi_ld.append(_ten_kem_sp(s["leader"], ld_giu_sp))

                        if warn == "no_sp":
                            canh_bao.append("Ca không có ai xử lý song phương")
                        elif warn == "multi_sp":
                            canh_bao.append("Ca có nhiều hơn 1 người xử lý song phương")

                    # Người thứ 3 trở đi (ca cut-off/quyết toán) dồn vào ô Nhân viên 2
                    nv1 = nguoi_nv[0] if nguoi_nv else "—"
                    nv2 = "<br>".join(nguoi_nv[1:]) if len(nguoi_nv) > 1 else "—"

                    with ui.column().classes("w-full gap-0"):
                        with ui.row().classes("w-full items-center px-2 py-2 border-t "
                                              "border-gray-200 gap-2 text-sm").style(f"background:{bg}"):
                            ui.html(f'<span class="font-medium">{_THU_VN[i]}</span><br>'
                                    f'<span class="text-gray-500 text-xs">'
                                    f'{ds[8:10]}/{ds[5:7]}/{ds[:4]}</span>').classes("w-28 shrink-0")
                            ui.html(nv1).classes("flex-1 min-w-[130px]")
                            ui.html(nv2).classes("flex-1 min-w-[130px]")
                            ui.html("<br>".join(nguoi_ld) or "—").classes("flex-1 min-w-[130px]")

                            with ui.row().classes("w-36 shrink-0 items-center gap-1"):
                                if ca_ngay:
                                    da_xn = all(s["status"] == "confirmed" for s in ca_ngay)
                                    ui.html(
                                        '<span class="text-green-700 font-medium">Đã xác nhận</span>'
                                        if da_xn else '<span class="text-orange-600">Bản thảo</span>'
                                    ).classes("text-xs")
                                    if can_write:
                                        ui.button(
                                            icon="edit",
                                            on_click=lambda sid=ca_ngay[0]["id"]: mo_hop_thoai_sua(sid),
                                        ).props("flat dense round size=sm color=primary").tooltip("Sửa ca trực")
                                else:
                                    ui.html('<span class="text-gray-400">—</span>').classes("text-xs")

                        if canh_bao:
                            ui.html("⚠ " + " · ".join(canh_bao)).classes(
                                "w-full px-2 pb-1 text-xs text-red-600"
                            ).style(f"background:{bg}")

                def _nhan_chon(p: dict, ds: str) -> str:
                    """Tên kèm ghi chú để người phân lịch biết mình đang chọn ai.
                    Vẫn cho chọn — đi dự án / nghỉ phép chỉ là luật mềm."""
                    ghi_chu = []
                    if p.get("can_do_sp"):
                        ghi_chu.append("SP")
                    if p.get("is_on_project"):
                        ghi_chu.append("dự án")
                    if (p["id"], ds) in nhan_su_ref["vang_mat"]:
                        ghi_chu.append("nghỉ phép")
                    return f"{p['full_name']} ({', '.join(ghi_chu)})" if ghi_chu else p["full_name"]

                async def mo_hop_thoai_sua(shift_id: int) -> None:
                    try:
                        ca = await asyncio.to_thread(api.get, f"/api/duty/schedule/{shift_id}")
                    except Exception as e:
                        _handle_api_error(e)
                        return

                    ds = ca["shift_date"]
                    ds_vn = f"{ds[8:10]}/{ds[5:7]}/{ds[:4]}"
                    ds_nv = ([ca["sp"]["id"]] if ca.get("sp") else []) + [p["id"] for p in ca["nvs"]]

                    opt_ld = {str(p["id"]): _nhan_chon(p, ds)
                              for p in nhan_su_ref["list"] if p["duty_role"] == "LD"}
                    opt_nv = {str(p["id"]): _nhan_chon(p, ds)
                              for p in nhan_su_ref["list"] if p["duty_role"] == "NV"}

                    with ui.dialog() as dlg, ui.card().classes("w-[520px] max-w-full"):
                        ui.label(f"Sửa ca trực ngày {ds_vn}").classes(
                            "text-base font-semibold text-red-800")
                        ui.label("Ca trực bắt buộc 1 Lãnh đạo và 2 nhân viên. "
                                 "Người xử lý song phương do hệ thống tự xác định.").classes(
                            "text-xs text-gray-500 mb-2")

                        sel_ld = ui.select(label="Lãnh đạo", options=opt_ld, with_input=True,
                                           value=str(ca["leader"]["id"]) if ca.get("leader") else None
                                           ).classes("w-full")
                        sel_nv1 = ui.select(label="Nhân viên 1", options=opt_nv, with_input=True,
                                            value=str(ds_nv[0]) if len(ds_nv) > 0 else None
                                            ).classes("w-full")
                        sel_nv2 = ui.select(label="Nhân viên 2", options=opt_nv, with_input=True,
                                            value=str(ds_nv[1]) if len(ds_nv) > 1 else None
                                            ).classes("w-full")

                        loi_box = ui.html("").classes("text-sm text-red-600 mt-2")

                        if ca["status"] == "confirmed":
                            ui.label("Ca này đã xác nhận — sửa xong sẽ quay về bản thảo, "
                                     "cần xác nhận lại.").classes("text-xs text-orange-600 mt-2")

                        async def do_luu():
                            loi_box.set_content("")
                            if not (sel_ld.value and sel_nv1.value and sel_nv2.value):
                                loi_box.set_content("Phải chọn đủ 1 Lãnh đạo và 2 nhân viên.")
                                return
                            try:
                                kq = await asyncio.to_thread(
                                    api.put, f"/api/duty/schedule/{shift_id}",
                                    {"leader_id": int(sel_ld.value),
                                     "nv_ids": [int(sel_nv1.value), int(sel_nv2.value)]},
                                )
                            except Exception as ex:
                                if _handle_api_error(ex):
                                    return
                                loi_box.set_content(_h(str(ex)))
                                return

                            dlg.close()
                            canh_bao = kq.get("warnings") or []
                            if canh_bao:
                                # Vi phạm luật mềm vẫn ghi nhận — chỉ báo cho biết
                                ui.notify("Đã lưu. Lưu ý: " + " · ".join(canh_bao),
                                          type="warning", multi_line=True, timeout=8000)
                            else:
                                ui.notify(f"Đã cập nhật ca trực ngày {ds_vn}", type="positive")
                            await load_schedule()

                        with ui.row().classes("justify-end gap-2 mt-4 w-full"):
                            ui.button("Hủy", on_click=dlg.close).props("flat")
                            ui.button("Lưu", icon="save", on_click=do_luu).props("color=primary")

                    dlg.open()

                # ── Week navigation ──────────────────────────────
                with ui.row().classes("items-center gap-2 mb-2 flex-wrap"):
                    ui.button(icon="chevron_left",
                              on_click=lambda: [
                                  ws_ref.__setitem__("value", ws_ref["value"] - timedelta(weeks=1)),
                                  asyncio.ensure_future(load_schedule()),
                              ]).props("flat dense")
                    week_label
                    ui.button(icon="chevron_right",
                              on_click=lambda: [
                                  ws_ref.__setitem__("value", ws_ref["value"] + timedelta(weeks=1)),
                                  asyncio.ensure_future(load_schedule()),
                              ]).props("flat dense")
                    ui.button("Hôm nay",
                              on_click=lambda: [
                                  ws_ref.__setitem__("value", _week_start(date.today())),
                                  asyncio.ensure_future(load_schedule()),
                              ]).props("flat dense color=grey-6").classes("text-xs")

                if can_write:
                    with ui.row().classes("gap-2 mb-3 flex-wrap"):

                        async def do_generate():
                            ws = ws_ref["value"].isoformat()
                            try:
                                result = await asyncio.to_thread(
                                    api.post, "/api/duty/schedule/generate-week",
                                    {"week_start": ws, "overwrite_draft": True,
                                     "overwrite_confirmed": False}
                                )
                                ui.notify(
                                    f"Tạo {result['created']} ca, bỏ qua {result['skipped']}",
                                    type="positive"
                                )
                                await load_schedule()
                            except Exception as e:
                                _handle_api_error(e)

                        async def do_confirm_week():
                            ws = ws_ref["value"].isoformat()
                            try:
                                result = await asyncio.to_thread(
                                    api.post, f"/api/duty/schedule/confirm-week?week_start={ws}", {}
                                )
                                ui.notify(result.get("message", "Đã xác nhận"), type="positive")
                                await load_schedule()
                            except Exception as e:
                                _handle_api_error(e)

                        async def do_export():
                            ws = ws_ref["value"].isoformat()
                            try:
                                file_bytes = await asyncio.to_thread(
                                    api.get_bytes, "/api/duty/export/week",
                                    {"week_start": ws}
                                )
                                filename = f"lich_truc_{ws.replace('-', '')}.xlsx"
                                ui.download(file_bytes, filename=filename)
                            except Exception as e:
                                _handle_api_error(e)

                        async def do_delete_week():
                            ws = ws_ref["value"].isoformat()
                            with ui.dialog() as dlg, ui.card():
                                ui.label(f"Xóa toàn bộ ca trực tuần {ws}?").classes("font-semibold")
                                ui.label("Ca đã xác nhận cũng sẽ bị xóa.").classes("text-red-600 text-sm mt-1")
                                with ui.row().classes("justify-end gap-2 mt-3"):
                                    ui.button("Hủy", on_click=dlg.close).props("flat")
                                    async def _confirm_delete():
                                        dlg.close()
                                        try:
                                            result = await asyncio.to_thread(
                                                api.delete,
                                                f"/api/duty/schedule/week?week_start={ws}"
                                            )
                                            ui.notify(result.get("message", "Đã xóa"), type="warning")
                                            await load_schedule()
                                        except Exception as ex:
                                            _handle_api_error(ex)
                                    ui.button("Xóa", on_click=_confirm_delete).props("color=negative")
                            dlg.open()

                        if can_generate:
                            ui.button("Tạo lịch", icon="auto_fix_high",
                                      on_click=do_generate).props("color=primary")
                        if can_confirm:
                            ui.button("Xác nhận tuần", icon="done_all",
                                      on_click=do_confirm_week).props("color=positive")
                        if can_export:
                            ui.button("Xuất Excel", icon="download",
                                      on_click=do_export).props("color=teal")
                        if can_delete:
                            ui.button("Xóa tuần", icon="delete_outline",
                                      on_click=do_delete_week).props("color=negative flat")

                asyncio.ensure_future(load_schedule())

            # ════════════════════════════════════════════════════
            # TAB 2 — NHÂN VIÊN
            # ════════════════════════════════════════════════════
            with ui.tab_panel(tab_staff):
                staff_area = ui.column().classes("w-full")

                async def load_staff():
                    staff_area.clear()
                    try:
                        staff_list = await asyncio.to_thread(api.get, "/api/duty/staff")
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        return

                    with staff_area:
                        if can_manage_staff:
                            ui.label("Thay đổi checkbox tự lưu ngay (không cần bấm Save).").classes(
                                "text-xs text-gray-500 mb-3"
                            )

                        with ui.column().classes("w-full gap-1"):
                            # Header
                            with ui.row().classes("w-full bg-red-800 text-white px-2 py-2 rounded-t text-xs font-semibold gap-2"):
                                ui.label("Họ tên").classes("flex-1 min-w-[160px]")
                                ui.label("Chức vụ").classes("w-28")
                                ui.label("Làm SP").classes("w-16 text-center")
                                ui.label("Dự án").classes("w-16 text-center")

                            _ROLE_LABEL = {
                                "truong_phong": "Trưởng phòng",
                                "pho_phong":    "Phó phòng",
                                "chuyen_vien":  "Nhân viên",
                            }
                            _prev_role = None
                            for p in staff_list:
                                # Dòng separator phân nhóm chức vụ
                                if p["role"] != _prev_role:
                                    _prev_role = p["role"]
                                    group_label = _ROLE_LABEL.get(p["role"], p["role"])
                                    ui.label(group_label).classes(
                                        "w-full text-xs font-bold text-red-800 px-2 pt-2 pb-0.5 border-b border-red-100"
                                    )

                                duty_color = "text-blue-700 bg-blue-50" if p["duty_role"] == "LD" else "text-green-700 bg-green-50"

                                with ui.row().classes("w-full items-center px-2 py-1.5 border border-gray-100 hover:bg-gray-50 gap-2 text-sm"):
                                    ui.label(p["full_name"]).classes("flex-1 font-medium min-w-[160px]")
                                    ui.label(_ROLE_LABEL.get(p["role"], p["role"])).classes("w-28 text-xs text-gray-500")

                                    def _make_toggle(pid, field):
                                        async def handler(e):
                                            if not can_manage_staff:
                                                return
                                            try:
                                                await asyncio.to_thread(
                                                    api.post, f"/api/duty/staff/{pid}/meta",
                                                    {field: 1 if e.value else 0}
                                                )
                                            except Exception as ex:
                                                _handle_api_error(ex)
                                        return handler

                                    cb_sp = ui.checkbox(
                                        value=bool(p.get("can_do_sp", 0)),
                                        on_change=_make_toggle(p["id"], "can_do_sp")
                                    ).classes("w-16")
                                    cb_sp.props("dense")
                                    cb_sp.set_enabled(can_manage_staff)

                                    cb_proj = ui.checkbox(
                                        value=bool(p.get("is_on_project", 0)),
                                        on_change=_make_toggle(p["id"], "is_on_project")
                                    ).classes("w-16")
                                    cb_proj.props("dense")
                                    cb_proj.set_enabled(can_manage_staff)

                asyncio.ensure_future(load_staff())

            # ════════════════════════════════════════════════════
            # TAB 3 — VẮNG MẶT
            # ════════════════════════════════════════════════════
            with ui.tab_panel(tab_absence):
                today_ab   = date.today()
                ab_year_v  = {"v": today_ab.year}
                ab_month_v = {"v": today_ab.month}

                absence_area = ui.column().classes("w-full gap-1")

                async def load_absences():
                    absence_area.clear()
                    yr = ab_year_v["v"]
                    mo = ab_month_v["v"]
                    try:
                        data, staff_list = await asyncio.gather(
                            asyncio.to_thread(api.get, "/api/duty/constraints/absences",
                                              {"month": mo, "year": yr}),
                            asyncio.to_thread(api.get, "/api/duty/staff"),
                            return_exceptions=True,
                        )
                        if isinstance(data, Exception) or isinstance(staff_list, Exception):
                            raise (data if isinstance(data, Exception) else staff_list)
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        return

                    staff_map = {p["id"]: p["full_name"] for p in staff_list}

                    with absence_area:
                        # ── Form thêm vắng mặt ──────────────────────────────
                        if can_manage_staff:
                            with ui.card().classes("w-full max-w-xl p-4 mb-4"):
                                ui.label("Khai báo vắng mặt").classes("text-sm font-semibold text-red-800 mb-3")
                                staff_opts = {str(p["id"]): p["full_name"] for p in staff_list}
                                with ui.row().classes("items-end gap-2 flex-wrap"):
                                    sel_staff = ui.select(
                                        label="Nhân viên",
                                        options=staff_opts,
                                        with_input=True,
                                    ).classes("w-48")
                                    ab_from = ui.input(
                                        label="Từ ngày (YYYY-MM-DD)",
                                        placeholder=today_ab.isoformat(),
                                    ).classes("w-40")
                                    ab_to = ui.input(
                                        label="Đến ngày (để trống = 1 ngày)",
                                        placeholder=today_ab.isoformat(),
                                    ).classes("w-40")

                                    async def do_add_absence():
                                        if not sel_staff.value or not ab_from.value:
                                            ui.notify("Chọn nhân viên và nhập ngày bắt đầu", type="warning")
                                            return
                                        try:
                                            from_d = ab_from.value.strip()
                                            to_d   = (ab_to.value.strip() or from_d)
                                            if from_d == to_d:
                                                await asyncio.to_thread(
                                                    api.post, "/api/duty/constraints/absences",
                                                    {"staff_id": int(sel_staff.value),
                                                     "absence_date": from_d}
                                                )
                                            else:
                                                await asyncio.to_thread(
                                                    api.post, "/api/duty/constraints/absences/range",
                                                    {"staff_id": int(sel_staff.value),
                                                     "from_date": from_d, "to_date": to_d}
                                                )
                                            ab_from.value = ""
                                            ab_to.value   = ""
                                            await load_absences()
                                            ui.notify("Đã khai báo vắng mặt", type="positive")
                                        except Exception as ex:
                                            _handle_api_error(ex)

                                    ui.button("Thêm", icon="add", on_click=do_add_absence).props("color=primary")

                        # ── Danh sách vắng mặt theo ngày ────────────────────
                        if not data:
                            ui.label("Không có khai báo vắng mặt nào trong tháng này.").classes(
                                "text-gray-500 italic py-4"
                            )
                        else:
                            # Gom nhóm theo ngày
                            by_date: dict = {}
                            for ab in data:
                                by_date.setdefault(ab["absence_date"], []).append(ab)

                            for d_str in sorted(by_date):
                                with ui.row().classes("w-full items-start gap-2 border-b border-gray-100 py-2"):
                                    ui.label(d_str).classes("font-mono text-sm font-semibold text-gray-700 w-28 shrink-0 pt-1")
                                    with ui.row().classes("flex-wrap gap-1"):
                                        for ab in by_date[d_str]:
                                            name = staff_map.get(ab["staff_id"], f"#{ab['staff_id']}")
                                            with ui.row().classes(
                                                "items-center gap-1 bg-red-50 border border-red-200 "
                                                "rounded-full px-2 py-0.5 text-xs text-red-800"
                                            ):
                                                ui.label(name)
                                                if can_manage_staff:
                                                    async def _del(aid=ab["id"]):
                                                        try:
                                                            await asyncio.to_thread(
                                                                api.delete,
                                                                f"/api/duty/constraints/absences/{aid}"
                                                            )
                                                            await load_absences()
                                                        except Exception as ex:
                                                            _handle_api_error(ex)
                                                    ui.button(icon="close", on_click=_del).props(
                                                        "flat dense round size=xs color=red"
                                                    )

                # ── Bộ lọc tháng/năm ────────────────────────────────────────
                with ui.row().classes("items-end gap-3 mb-3 flex-wrap"):
                    ab_yr_inp = ui.number(
                        label="Năm", value=today_ab.year, min=2020, max=2099, format="%d"
                    ).classes("w-28")
                    ab_mo_inp = ui.number(
                        label="Tháng", value=today_ab.month, min=1, max=12, format="%d"
                    ).classes("w-24")

                    def _on_ab_filter_change():
                        ab_year_v["v"]  = int(ab_yr_inp.value or today_ab.year)
                        ab_month_v["v"] = int(ab_mo_inp.value or today_ab.month)
                        asyncio.ensure_future(load_absences())

                    ab_yr_inp.on("change", lambda _: _on_ab_filter_change())
                    ab_mo_inp.on("change", lambda _: _on_ab_filter_change())
                    ui.button("Tải", icon="refresh",
                              on_click=lambda: asyncio.ensure_future(load_absences())).props("flat dense color=primary")

                asyncio.ensure_future(load_absences())

            # ════════════════════════════════════════════════════
            # TAB 4 — THỐNG KÊ (was 3)
            # ════════════════════════════════════════════════════
            with ui.tab_panel(tab_stats):
                today_yr = date.today().year
                stats_year = ui.number(label="Năm", value=today_yr, min=2020, max=2099, format="%d").classes("w-28")
                stats_area = ui.column().classes("w-full mt-2")

                async def load_stats():
                    stats_area.clear()
                    yr = int(stats_year.value or today_yr)
                    try:
                        data = await asyncio.to_thread(
                            api.get, "/api/duty/stats/shift-count", {"year": yr}
                        )
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        return

                    with stats_area:
                        rows_html = ""
                        for p in data:
                            total = p.get("total", 0)
                            bg = "background:#F0FDF4" if total > 0 else ""
                            rows_html += (
                                f'<tr style="{bg}">'
                                f'<td class="{_TD}">{_h(p["full_name"])}</td>'
                                f'<td class="{_TD} text-xs text-gray-500">{_h(p["duty_role"])}</td>'
                                f'<td class="{_TD} text-center">{p.get("normal",0) or ""}</td>'
                                f'<td class="{_TD} text-center">{p.get("friday",0) or ""}</td>'
                                f'<td class="{_TD} text-center">{p.get("cutoff",0) or ""}</td>'
                                f'<td class="{_TD} text-center">{p.get("settlement_main",0) or ""}</td>'
                                f'<td class="{_TD} text-center">{p.get("settlement_sub",0) or ""}</td>'
                                f'<td class="{_TD} text-center font-bold">{total or ""}</td>'
                                f'</tr>'
                            )
                        ui.html(
                            '<div class="w-full overflow-x-auto">'
                            '<table class="w-full border-collapse text-sm">'
                            f'<thead><tr>'
                            f'<th class="{_TH}">Họ tên</th>'
                            f'<th class="{_TH}">Role</th>'
                            f'<th class="{_TH}">Thường</th>'
                            f'<th class="{_TH}">Thứ 6</th>'
                            f'<th class="{_TH}">Cut-off</th>'
                            f'<th class="{_TH}">QT Chính</th>'
                            f'<th class="{_TH}">QT Phụ</th>'
                            f'<th class="{_TH}">Tổng</th>'
                            f'</tr></thead>'
                            f'<tbody>{rows_html}</tbody>'
                            '</table></div>'
                        )

                ui.button("Tải thống kê", icon="refresh",
                          on_click=load_stats).props("flat dense color=primary").classes("mb-1")
                asyncio.ensure_future(load_stats())

            # ════════════════════════════════════════════════════
            # TAB 4 — NGÀY ĐẶC BIỆT
            # ════════════════════════════════════════════════════
            with ui.tab_panel(tab_specials):
                today_yr2 = date.today().year
                today_mo  = date.today().month

                with ui.row().classes("items-end gap-3 mb-3 flex-wrap"):
                    yr_sp = ui.number(label="Năm", value=today_yr2, min=2020, max=2099, format="%d").classes("w-28")
                    mo_sp = ui.number(label="Tháng (tuỳ chọn)", value=None, min=1, max=12, format="%d").classes("w-36")
                    ui.button("Tải", icon="refresh",
                              on_click=lambda: asyncio.ensure_future(load_specials())).props("flat dense color=primary")
                    if can_manage_cfg:
                        ui.button("Set Ngày lễ", icon="auto_fix_high",
                                  on_click=lambda: asyncio.ensure_future(do_seed_holidays())).props("flat dense color=teal")
                        ui.button("Tính Cut-off", icon="calculate",
                                  on_click=lambda: asyncio.ensure_future(do_compute_cutoff())).props("flat dense color=orange")

                specials_area = ui.column().classes("w-full gap-1")

                async def load_specials():
                    specials_area.clear()
                    yr = int(yr_sp.value or today_yr2)
                    mo_val = mo_sp.value
                    mo = int(mo_val) if mo_val else None
                    params = {"year": yr}
                    if mo:
                        params["month"] = mo
                    try:
                        data = await asyncio.to_thread(
                            api.get, "/api/duty/constraints/special-days", params
                        )
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        return

                    with specials_area:
                        if not data:
                            ui.label("Không có ngày đặc biệt nào.").classes("text-gray-500 italic py-4")
                        else:
                            for item in data:
                                bg_cls, type_lbl, text_cls = _SPECIAL_COLOR.get(
                                    item["day_type"], ("bg-gray-50", item["day_type"], "text-gray-700")
                                )
                                with ui.row().classes(f"w-full items-center gap-3 px-3 py-2 rounded {bg_cls} border border-gray-100"):
                                    ui.label(item["date"]).classes("font-mono font-semibold w-28 text-sm")
                                    ui.label(type_lbl).classes(f"text-xs font-semibold w-24 {text_cls}")
                                    ui.label(item.get("label") or "").classes("text-sm flex-1")
                                    if item.get("is_confirmed"):
                                        ui.icon("check_circle").classes("text-green-600")
                                    else:
                                        ui.label("Chưa xác nhận").classes("text-xs text-gray-500")
                                    if can_manage_cfg:
                                        if not item.get("is_confirmed"):
                                            async def _confirm_sp(sid=item["id"]):
                                                try:
                                                    await asyncio.to_thread(
                                                        api.post,
                                                        f"/api/duty/constraints/special-days/{sid}/confirm", {}
                                                    )
                                                    await load_specials()
                                                except Exception as ex:
                                                    _handle_api_error(ex)
                                            ui.button("Xác nhận", on_click=_confirm_sp).props("flat dense color=positive").classes("text-xs")
                                        async def _del_sp(sid=item["id"]):
                                            try:
                                                await asyncio.to_thread(
                                                    api.delete,
                                                    f"/api/duty/constraints/special-days/{sid}"
                                                )
                                                await load_specials()
                                            except Exception as ex:
                                                _handle_api_error(ex)
                                        ui.button(icon="delete", on_click=_del_sp).props("flat dense color=negative")

                        if can_manage_cfg:
                            ui.separator().classes("my-3")
                            ui.label("Thêm ngày đặc biệt").classes("text-sm font-semibold text-gray-700 mb-2")
                            with ui.row().classes("items-end gap-2 flex-wrap"):
                                new_date = ui.input(label="Ngày (YYYY-MM-DD)", placeholder="2026-01-01").classes("w-40")
                                new_type = ui.select(
                                    label="Loại",
                                    options={"holiday": "Nghỉ lễ", "cutoff": "Cut-off",
                                             "settlement": "Quyết toán", "makeup": "Ngày bù"},
                                    value="cutoff",
                                ).classes("w-40")
                                new_label = ui.input(label="Ghi chú (tuỳ chọn)").classes("w-48")

                                async def do_add_special():
                                    if not new_date.value:
                                        ui.notify("Nhập ngày trước", type="warning")
                                        return
                                    try:
                                        await asyncio.to_thread(
                                            api.post, "/api/duty/constraints/special-days",
                                            {"date": new_date.value, "day_type": new_type.value,
                                             "label": new_label.value or None}
                                        )
                                        new_date.value = ""
                                        new_label.value = ""
                                        await load_specials()
                                        ui.notify("Đã thêm", type="positive")
                                    except Exception as ex:
                                        _handle_api_error(ex)

                                ui.button("Thêm", icon="add", on_click=do_add_special).props("color=primary")

                async def do_seed_holidays():
                    yr = int(yr_sp.value or today_yr2)
                    try:
                        result = await asyncio.to_thread(
                            api.post, f"/api/duty/constraints/special-days/seed-holidays?year={yr}", {}
                        )
                        ui.notify(f"Đã set {result['seeded']} ngày lễ năm {yr}", type="positive")
                        await load_specials()
                    except Exception as e:
                        _handle_api_error(e)

                async def do_compute_cutoff():
                    yr = int(yr_sp.value or today_yr2)
                    mo = int(mo_sp.value or today_mo)
                    try:
                        result = await asyncio.to_thread(
                            api.post, "/api/duty/constraints/special-days/compute-cutoff",
                            {"month": mo, "year": yr}
                        )
                        ui.notify(f"Đã tính {len(result)} ngày cut-off cho T{mo}/{yr}", type="positive")
                        await load_specials()
                    except Exception as e:
                        _handle_api_error(e)

                asyncio.ensure_future(load_specials())

            # ════════════════════════════════════════════════════
            # TAB 5 — CÀI ĐẶT
            # ════════════════════════════════════════════════════
            with ui.tab_panel(tab_settings):
                today_yr3 = date.today().year

                with ui.card().classes("w-full max-w-md p-4 mt-2"):
                    ui.label("Cấu hình ca trực").classes("text-base font-semibold text-red-800 mb-3")
                    yr_cfg = ui.number(label="Năm", value=today_yr3, min=2020, max=2099, format="%d").classes("w-28 mb-2")
                    nv_count_inp  = ui.number(label="Số NV mỗi ca", value=2, min=1, max=5, format="%d").classes("w-36")
                    signer_inp    = ui.input(label="Tên người ký Excel").classes("w-64")

                    async def load_cfg():
                        yr = int(yr_cfg.value or today_yr3)
                        try:
                            cfg = await asyncio.to_thread(
                                api.get, f"/api/duty/constraints/shift-config/{yr}"
                            )
                            nv_count_inp.value = cfg.get("nv_count", 2)
                            signer_inp.value   = cfg.get("signer_name") or ""
                        except Exception:
                            pass  # Không có config → giữ giá trị mặc định

                    yr_cfg.on("change", lambda: asyncio.ensure_future(load_cfg()))

                    if can_manage_cfg:
                        async def do_save_cfg():
                            yr = int(yr_cfg.value or today_yr3)
                            try:
                                await asyncio.to_thread(
                                    api.put, f"/api/duty/constraints/shift-config/{yr}",
                                    {"nv_count": int(nv_count_inp.value or 2),
                                     "signer_name": signer_inp.value or None}
                                )
                                ui.notify("Đã lưu", type="positive")
                            except Exception as ex:
                                _handle_api_error(ex)

                        ui.button("Lưu cài đặt", icon="save",
                                  on_click=do_save_cfg).props("color=primary").classes("mt-2")

                if can_manage_cfg:
                    with ui.card().classes("w-full max-w-md p-4 mt-3"):
                        ui.label("Vòng xoay phân lịch").classes("text-base font-semibold text-red-800 mb-2")
                        ui.label("Reset vòng xoay sẽ xóa toàn bộ thống kê ca trực năm được chọn. Dùng khi bắt đầu năm mới.").classes("text-xs text-gray-500 mb-3")

                        async def do_reset_rotation():
                            yr = int(yr_cfg.value or today_yr3)
                            with ui.dialog() as dlg_r, ui.card():
                                ui.label(f"Reset vòng xoay năm {yr}?").classes("font-semibold")
                                ui.label("Thống kê sẽ bị xóa và bắt đầu lại.").classes("text-red-600 text-sm")
                                with ui.row().classes("justify-end gap-2 mt-3"):
                                    ui.button("Hủy", on_click=dlg_r.close).props("flat")
                                    async def _do_reset():
                                        dlg_r.close()
                                        try:
                                            await asyncio.to_thread(
                                                api.post,
                                                f"/api/duty/schedule/rotation/reset?year={yr}", {}
                                            )
                                            ui.notify(f"Đã reset vòng xoay năm {yr}", type="warning")
                                        except Exception as ex:
                                            _handle_api_error(ex)
                                    ui.button("Reset", on_click=_do_reset).props("color=negative")
                            dlg_r.open()

                        ui.button("Reset vòng xoay", icon="refresh",
                                  on_click=do_reset_rotation).props("color=negative flat")

                asyncio.ensure_future(load_cfg())
