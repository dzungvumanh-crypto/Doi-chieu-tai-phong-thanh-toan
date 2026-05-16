"""Trang nghỉ phép — đăng ký, duyệt và lịch nghỉ."""
import asyncio
import datetime as _dt_mod
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error

# ─── LEAVES PAGE ─────────────────────────────────────────────────────────────
_LEAVE_STATUS = {
    "pending_ksv":      ("Chờ KSV duyệt",  "bg-orange-100 text-orange-700 border-orange-300"),
    "pending_tong_hop": ("Chờ Tổng hợp",   "bg-yellow-100 text-yellow-700 border-yellow-300"),
    "pending_gd":       ("Chờ GĐ duyệt",   "bg-blue-100 text-blue-700 border-blue-300"),
    "approved":         ("Đã duyệt",        "bg-green-100 text-green-700 border-green-300"),
    "rejected":         ("Từ chối",         "bg-red-100 text-red-700 border-red-300"),
    "cancelled":        ("Đã hủy",          "bg-gray-100 text-gray-500 border-gray-300"),
}
_LEAVE_TYPE = {
    "annual":   "Nghỉ phép năm",
    "dot_xuat": "Nghỉ đột xuất",
    "bat_buoc": "Nghỉ phép bắt buộc",
    "sick":     "Nghỉ ốm",
    "personal": "Nghỉ việc riêng",
    "other":    "Khác",
}
# Nhóm hiển thị 3 trạng thái đơn giản trong cột Trạng thái của bảng
_STATUS_GROUP = {
    "pending_ksv":      ("Chờ phê duyệt", "bg-orange-100 text-orange-700"),
    "pending_tong_hop": ("Chờ phê duyệt", "bg-orange-100 text-orange-700"),
    "pending_gd":       ("Chờ phê duyệt", "bg-orange-100 text-orange-700"),
    "approved":         ("Hoàn thành",    "bg-green-100 text-green-700"),
    "rejected":         ("Từ chối",       "bg-red-100 text-red-700"),
    "cancelled":        ("Đã hủy",        "bg-gray-100 text-gray-500"),
}


def _leave_status_badge(status: str):
    label, cls = _LEAVE_STATUS.get(status, (status, "bg-gray-100 text-gray-500"))
    ui.label(label).classes(f"text-xs font-medium px-2 py-0.5 rounded border {cls}")


def _fmt_leave_dates(start_str: str, end_str: str) -> str:
    """1 ngày → DD/MM/YYYY; nhiều ngày → DD/MM – DD/MM/YYYY"""
    if not start_str or not end_str:
        return "—"
    try:
        from datetime import date as _date
        s = _date.fromisoformat(start_str[:10])
        e = _date.fromisoformat(end_str[:10])
        if s == e:
            return s.strftime("%d/%m/%Y")
        return f"{s.strftime('%d/%m')} – {e.strftime('%d/%m/%Y')}"
    except Exception:
        return start_str[:10]


def _gd_display(leave: dict) -> str:
    """Thêm (TUQ) nếu PGĐ ký thay GĐ."""
    name = leave.get("gd_approver_name") or ""
    if name and leave.get("gd_is_pgd"):
        return f"{name} (TUQ)"
    return name


@ui.page("/leaves")
async def leaves_page():
    if not _require_auth():
        return
    badge_refs = _sidebar("leaves")

    current_user = api.get_current_user()
    user_role    = current_user.get("role", "") if current_user else ""
    user_id      = current_user.get("staff_id") if current_user else None

    can_all        = user_role in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")
    can_delegation = user_role == "admin"
    show_approver  = user_role not in ("giam_doc", "pho_giam_doc", "admin")

    # ── Drawer và dialog phải là con trực tiếp của page ──────────────────────
    with ui.right_drawer(value=False).props("width=440 overlay").classes(
        "bg-white shadow-2xl overflow-y-auto"
    ) as detail_drawer:
        drawer_container = ui.column().classes("w-full gap-0")

    with ui.dialog() as history_dialog, ui.card().classes("p-0 w-[560px] max-h-[80vh] overflow-y-auto"):
        history_container = ui.column().classes("w-full gap-0")

    # ── Dialog từ chối (yêu cầu lý do) ──────────────────────────────────────
    _reject_cb: list = [None]
    with ui.dialog() as reject_dialog, ui.card().classes("p-6 w-80"):
        ui.label("Nhập lý do từ chối").classes("text-lg font-bold text-red-900 mb-4")
        reject_reason = ui.textarea("Lý do từ chối").classes("w-full").props("rows=3")

        async def _confirm_reject():
            if not reject_reason.value.strip():
                ui.notify("Vui lòng nhập lý do từ chối", type="warning")
                return
            cb = _reject_cb[0]
            reason = reject_reason.value.strip()
            reject_reason.value = ""
            reject_dialog.close()
            if cb:
                await cb(reason)

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Hủy", on_click=reject_dialog.close).classes("text-gray-500")
            ui.button("Xác nhận từ chối", on_click=_confirm_reject).classes("bg-red-700 text-white")

    # ── Dialog TH chọn GĐ/PGĐ ────────────────────────────────────────────────
    _th_cb: list = [None]
    with ui.dialog() as th_dialog, ui.card().classes("p-6 w-96"):
        ui.label("Chuyển lên GĐ/PGĐ phê duyệt").classes("text-lg font-bold text-red-900 mb-4")
        th_gd_select = ui.select({}, label="Chọn GĐ / Phó GĐ").classes("w-full")
        th_note      = ui.textarea("Ghi chú (tuỳ chọn)").classes("w-full mt-2").props("rows=2")

        async def _load_gd_opts():
            try:
                lst = await asyncio.to_thread(api.get, "/api/leaves/gd-list")
                th_gd_select.options = {s["id"]: f"{s['full_name']} — {s['role_label']}" for s in (lst or [])}
                th_gd_select.update()
            except Exception:
                pass

        async def _confirm_th_forward():
            if not th_gd_select.value:
                ui.notify("Vui lòng chọn GĐ/PGĐ", type="warning")
                return
            gd_id = th_gd_select.value
            note  = th_note.value or None
            th_note.value = ""
            th_dialog.close()
            cb = _th_cb[0]
            if cb:
                await cb(gd_id, note)

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Hủy", on_click=th_dialog.close).classes("text-gray-500")
            ui.button("Xác nhận", on_click=_confirm_th_forward).classes("bg-blue-700 text-white")

    with _content_area():
        _page_header("Quản lý Nghỉ phép", "Đăng ký và phê duyệt nghỉ phép")

        # ── Load dữ liệu song song ────────────────────────────────────────────
        my_leaves, pending_leaves, all_leaves, delegations, balance_info, approver_list = \
            [], [], [], [], {}, []

        async def _empty():
            return []

        try:
            results = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "mine"}),
                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "pending"}),
                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "all"}) if can_all else _empty(),
                asyncio.to_thread(api.get, "/api/delegations/") if can_delegation else _empty(),
                asyncio.to_thread(api.get, "/api/auth/me"),
                asyncio.to_thread(api.get, "/api/leaves/approvers") if show_approver else _empty(),
                return_exceptions=True,
            )
            my_leaves, pending_leaves, all_leaves, delegations, balance_info, approver_list = results
            for r in results:
                if isinstance(r, api.SessionExpiredError):
                    ui.notify(str(r), type="warning")
                    ui.navigate.to("/login")
                    return
            my_leaves      = my_leaves      if isinstance(my_leaves, list)     else []
            pending_leaves = pending_leaves if isinstance(pending_leaves, list) else []
            all_leaves     = all_leaves     if isinstance(all_leaves, list)    else []
            delegations    = delegations    if isinstance(delegations, list)   else []
            balance_info   = balance_info   if isinstance(balance_info, dict)  else {}
            approver_list  = approver_list  if isinstance(approver_list, list) else []
        except Exception as e:
            if _handle_api_error(e):
                return

        pending_ids = {lv["id"] for lv in pending_leaves}

        # ── Cập nhật badge sidebar ────────────────────────────────────────────
        _lcnt = len(pending_leaves)
        if "leaves" in badge_refs and _lcnt > 0:
            badge_refs["leaves"].set_text(str(_lcnt))
            badge_refs["leaves"].set_visibility(True)

        if any(lv.get("status") == "rejected" for lv in my_leaves):
            ui.notify("Có đơn nghỉ phép bị từ chối. Xem tab 'Của tôi'.", type="negative", timeout=8000)

        # ── Balance card ──────────────────────────────────────────────────────
        annual    = balance_info.get("annual_leave_days", 12)
        used      = balance_info.get("used_leave_days", 0)
        remaining = max(0, annual - used)
        with ui.row().classes("gap-4 mb-4"):
            with ui.card().classes("bg-blue-50 border border-blue-200 p-4 rounded-xl min-w-40"):
                ui.label("Phép còn lại").classes("text-xs text-blue-600")
                ui.label(f"{remaining} / {annual} ngày").classes("text-xl font-bold text-blue-800")

        # ── Dialogs tạo đơn / nộp lại ────────────────────────────────────────
        approver_opts = {s["id"]: f"{s['full_name']} — {s['role_label']}" for s in approver_list}

        _today_slash = _dt_mod.date.today().isoformat().replace('-', '/')
        _today_iso   = _dt_mod.date.today().isoformat()
        _OPT_FUTURE  = f":options=\"d => d >= '{_today_slash}'\""
        _OPT_ALL     = ":options=\"() => true\""

        with ui.dialog() as create_dialog, ui.card().classes("p-6 w-[420px]"):
            ui.label("Tạo đơn nghỉ phép").classes("text-lg font-bold text-red-900 mb-4")
            c_dates    = ui.date(value=None).props(f"range mask='YYYY-MM-DD' {_OPT_FUTURE}").classes("w-full")
            c_hint     = ui.label("Chỉ chọn ngày từ hôm nay trở đi").classes("text-xs text-orange-500 mt-0.5")
            c_type     = ui.select({k: v for k, v in _LEAVE_TYPE.items()}, label="Loại nghỉ phép", value="annual").classes("w-full mt-2")
            c_reason   = ui.textarea("Lý do (tuỳ chọn)").classes("w-full mt-2")
            c_approver = ui.select(approver_opts, label="Người phê duyệt (KSV)").classes("w-full mt-2") if show_approver else None

            def _c_on_type():
                lt = c_type.value
                if lt == "annual":
                    c_dates.props(_OPT_FUTURE)
                    c_hint.set_text("Chỉ chọn ngày từ hôm nay trở đi")
                    c_hint.style("color:#f97316")
                elif lt == "bat_buoc":
                    c_dates.props(_OPT_FUTURE)
                    c_hint.set_text("Tối thiểu 5 ngày làm việc liên tiếp")
                    c_hint.style("color:#3b82f6")
                else:
                    c_dates.props(_OPT_ALL)
                    c_hint.set_text("Có thể chọn ngày trong quá khứ" if lt == "dot_xuat" else "")
                    c_hint.style("color:#6b7280")

            c_type.on("update:model-value", _c_on_type)

            async def do_create():
                _cv = c_dates.value or {}
                c_start_str = (_cv.get("from") or "")[:10] if isinstance(_cv, dict) else ""
                c_end_str   = (_cv.get("to")   or "")[:10] if isinstance(_cv, dict) else ""
                if not c_start_str or not c_end_str:
                    ui.notify("Vui lòng chọn ngày", type="warning")
                    return
                if show_approver and not c_approver.value:
                    ui.notify("Vui lòng chọn người phê duyệt", type="warning")
                    return
                body = {"start_date": c_start_str, "end_date": c_end_str,
                        "leave_type": c_type.value, "reason": c_reason.value or None}
                if show_approver:
                    body["ksv_approver_id"] = c_approver.value
                try:
                    await asyncio.to_thread(api.post, "/api/leaves/", body)
                    create_dialog.close()
                    ui.notify("Đã tạo đơn nghỉ phép thành công!", type="positive")
                    ui.navigate.to("/leaves")
                except Exception as e:
                    _handle_api_error(e)

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=create_dialog.close).classes("text-gray-500")
                ui.button("Gửi đơn", on_click=do_create).classes("bg-red-700 text-white")

        # ── Dialog nộp lại ────────────────────────────────────────────────────
        _rsub_id: list = [None]
        with ui.dialog() as resubmit_dialog, ui.card().classes("p-6 w-[420px]"):
            ui.label("Chỉnh sửa & Nộp lại").classes("text-lg font-bold text-red-900 mb-4")
            r_dates    = ui.date(value=None).props(f"range mask='YYYY-MM-DD' {_OPT_FUTURE}").classes("w-full")
            r_hint     = ui.label("Chỉ chọn ngày từ hôm nay trở đi").classes("text-xs text-orange-500 mt-0.5")
            r_type     = ui.select({k: v for k, v in _LEAVE_TYPE.items()}, label="Loại nghỉ phép", value="annual").classes("w-full mt-2")
            r_reason   = ui.textarea("Lý do (tuỳ chọn)").classes("w-full mt-2")
            r_approver = ui.select(approver_opts, label="Người phê duyệt (KSV)").classes("w-full mt-2") if show_approver else None

            def _r_on_type():
                lt = r_type.value
                if lt == "annual":
                    r_dates.props(_OPT_FUTURE)
                    r_hint.set_text("Chỉ chọn ngày từ hôm nay trở đi")
                    r_hint.style("color:#f97316")
                elif lt == "bat_buoc":
                    r_dates.props(_OPT_FUTURE)
                    r_hint.set_text("Tối thiểu 5 ngày làm việc liên tiếp")
                    r_hint.style("color:#3b82f6")
                else:
                    r_dates.props(_OPT_ALL)
                    r_hint.set_text("Có thể chọn ngày trong quá khứ" if lt == "dot_xuat" else "")
                    r_hint.style("color:#6b7280")

            r_type.on("update:model-value", _r_on_type)

            async def do_resubmit():
                lid = _rsub_id[0]
                _rv = r_dates.value or {}
                r_start_str = (_rv.get("from") or "")[:10] if isinstance(_rv, dict) else ""
                r_end_str   = (_rv.get("to")   or "")[:10] if isinstance(_rv, dict) else ""
                if not lid or not r_start_str or not r_end_str:
                    ui.notify("Vui lòng chọn ngày", type="warning")
                    return
                if show_approver and not r_approver.value:
                    ui.notify("Vui lòng chọn người phê duyệt", type="warning")
                    return
                body = {"start_date": r_start_str, "end_date": r_end_str,
                        "leave_type": r_type.value, "reason": r_reason.value or None}
                if show_approver:
                    body["ksv_approver_id"] = r_approver.value
                try:
                    await asyncio.to_thread(api.put, f"/api/leaves/{lid}/resubmit", body)
                    resubmit_dialog.close()
                    detail_drawer.hide()
                    ui.notify("Đã nộp lại đơn!", type="positive")
                    ui.navigate.to("/leaves")
                except Exception as e:
                    _handle_api_error(e)

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=resubmit_dialog.close).classes("text-gray-500")
                ui.button("Nộp lại", on_click=do_resubmit).classes("bg-orange-600 text-white")

        # ── Hàm mở drawer chi tiết ────────────────────────────────────────────
        async def open_detail(leave: dict):
            drawer_container.clear()
            with drawer_container:
                lid      = leave["id"]
                status   = leave["status"]
                is_owner = user_id is not None and leave.get("staff_id") == user_id
                in_pend  = lid in pending_ids
                ksv_act  = status == "pending_ksv" and in_pend and user_role in ("truong_phong", "pho_phong", "hau_kiem_vien")
                th_act   = status == "pending_tong_hop" and in_pend
                gd_act   = status == "pending_gd" and in_pend and user_role in ("giam_doc", "pho_giam_doc")

                with ui.row().classes("w-full bg-red-800 text-white px-5 py-4 items-center gap-2"):
                    ui.icon("event_busy").classes("text-2xl")
                    with ui.column().classes("gap-0"):
                        ui.label("Chi tiết đơn nghỉ phép").classes("font-bold text-base")
                        ui.label(leave.get("staff_name", "")).classes("text-red-200 text-sm")

                with ui.column().classes("px-5 py-4 gap-3 w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label("Trạng thái:").classes("text-sm text-gray-600 font-medium")
                        _leave_status_badge(status)

                    def _info(lbl, val):
                        with ui.row().classes("w-full items-start gap-2"):
                            ui.label(lbl).classes("text-sm text-gray-500 w-28 shrink-0")
                            ui.label(str(val) if val else "—").classes("text-sm font-medium flex-1")

                    _info("Phòng:", leave.get("department_name") or "—")
                    _info("Từ ngày:", (leave.get("start_date") or "")[:10])
                    _info("Đến ngày:", (leave.get("end_date") or "")[:10])
                    _info("Số ngày nghỉ:", f"{leave.get('leave_days', '')} ngày")
                    _info("Loại:", _LEAVE_TYPE.get(leave.get("leave_type", ""), leave.get("leave_type", "")))
                    _info("Lý do:", leave.get("reason") or "—")

                    # Bước 1: KSV (ẩn nếu GĐ/PGĐ/admin tạo thẳng lên TH)
                    if leave.get("ksv_approver_id") or status == "pending_ksv":
                        with ui.column().classes("w-full bg-orange-50 rounded-lg p-3 gap-1 border border-orange-100"):
                            ui.label("Bước 1 — KSV phê duyệt").classes("text-xs font-bold text-orange-700 uppercase")
                            _info("Người duyệt:", leave.get("ksv_approver_name") or "Chưa xác định")
                            if leave.get("ksv_approved_at"):
                                _info("Ngày duyệt:", leave["ksv_approved_at"][:10])
                                _info("Ý kiến:", leave.get("ksv_comment") or "—")

                    # Bước 2: Tổng hợp
                    with ui.column().classes("w-full bg-yellow-50 rounded-lg p-3 gap-1 border border-yellow-100"):
                        ui.label("Bước 2 — Phòng Tổng hợp").classes("text-xs font-bold text-yellow-700 uppercase")
                        _info("Người xử lý:", leave.get("tong_hop_approver_name") or "Chưa xử lý")
                        if leave.get("tong_hop_approved_at"):
                            _info("Ngày:", leave["tong_hop_approved_at"][:10])
                            _info("Ghi chú:", leave.get("tong_hop_comment") or "—")

                    # Bước 3: GĐ
                    with ui.column().classes("w-full bg-blue-50 rounded-lg p-3 gap-1 border border-blue-100"):
                        ui.label("Bước 3 — Giám đốc phê duyệt").classes("text-xs font-bold text-blue-700 uppercase")
                        _info("Người duyệt:", _gd_display(leave) or "Chưa xác định")
                        if leave.get("gd_approved_at"):
                            _info("Ngày duyệt:", leave["gd_approved_at"][:10])
                            _info("Ý kiến:", leave.get("gd_comment") or "—")

                    ui.separator()

                    async def _download(l=lid):
                        try:
                            content = await asyncio.to_thread(api.download, f"/api/leaves/{l}/download")
                            ui.download(content, f"phieu_nghi_phep_{l}.docx")
                        except Exception as e:
                            _handle_api_error(e)

                    with ui.row().classes("gap-2 flex-wrap"):
                        ui.button("Tải phiếu", icon="download", on_click=_download).classes("bg-gray-100 text-gray-700 text-sm")

                        # KSV
                        if ksv_act:
                            async def _ksv_approve(l=lid):
                                try:
                                    await asyncio.to_thread(api.put, f"/api/leaves/{l}/ksv-review", {"action": "approve"})
                                    detail_drawer.hide()
                                    ui.notify("Đã phê duyệt KSV", type="positive")
                                    ui.navigate.to("/leaves")
                                except Exception as e:
                                    _handle_api_error(e)

                            def _ksv_reject_open(l=lid):
                                async def _cb(reason, _l=l):
                                    try:
                                        await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review",
                                            {"action": "reject", "comment": reason})
                                        detail_drawer.hide()
                                        ui.notify("Đã từ chối", type="warning")
                                        ui.navigate.to("/leaves")
                                    except Exception as e:
                                        _handle_api_error(e)
                                _reject_cb[0] = _cb
                                reject_dialog.open()

                            ui.button("Phê duyệt", on_click=_ksv_approve).classes("bg-green-600 text-white text-sm")
                            ui.button("Từ chối",   on_click=_ksv_reject_open).classes("bg-red-600 text-white text-sm")

                        # TH
                        if th_act:
                            async def _th_forward_open(l=lid):
                                await _load_gd_opts()

                                async def _cb(gd_id, note, _l=l):
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",
                                            {"action": "forward", "gd_approver_id": gd_id, "comment": note})
                                        detail_drawer.hide()
                                        ui.notify("Đã chuyển lên GĐ/PGĐ", type="positive")
                                        ui.navigate.to("/leaves")
                                    except Exception as e:
                                        _handle_api_error(e)
                                _th_cb[0] = _cb
                                th_dialog.open()

                            def _th_reject_open(l=lid):
                                async def _cb(reason, _l=l):
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",
                                            {"action": "reject", "comment": reason})
                                        detail_drawer.hide()
                                        ui.notify("Đã từ chối", type="warning")
                                        ui.navigate.to("/leaves")
                                    except Exception as e:
                                        _handle_api_error(e)
                                _reject_cb[0] = _cb
                                reject_dialog.open()

                            ui.button("Chuyển GĐ/PGĐ", icon="forward",
                                      on_click=lambda l=lid: asyncio.ensure_future(_th_forward_open(l))).classes("bg-blue-600 text-white text-sm")
                            ui.button("Từ chối", on_click=_th_reject_open).classes("bg-red-600 text-white text-sm")

                        # GĐ
                        if gd_act:
                            async def _gd_approve(l=lid):
                                try:
                                    await asyncio.to_thread(api.put, f"/api/leaves/{l}/gd-review", {"action": "approve"})
                                    detail_drawer.hide()
                                    ui.notify("Đã phê duyệt", type="positive")
                                    ui.navigate.to("/leaves")
                                except Exception as e:
                                    _handle_api_error(e)

                            def _gd_reject_open(l=lid):
                                async def _cb(reason, _l=l):
                                    try:
                                        await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review",
                                            {"action": "reject", "comment": reason})
                                        detail_drawer.hide()
                                        ui.notify("Đã từ chối", type="warning")
                                        ui.navigate.to("/leaves")
                                    except Exception as e:
                                        _handle_api_error(e)
                                _reject_cb[0] = _cb
                                reject_dialog.open()

                            ui.button("Phê duyệt", on_click=_gd_approve).classes("bg-green-600 text-white text-sm")
                            ui.button("Từ chối",   on_click=_gd_reject_open).classes("bg-red-600 text-white text-sm")

                        # Resubmit
                        if is_owner and status == "rejected":
                            def _open_resubmit(lv=leave):
                                r_dates.value  = {"from": (lv.get("start_date") or "")[:10], "to": (lv.get("end_date") or "")[:10]}
                                r_type.value   = lv.get("leave_type", "annual")
                                r_reason.value = lv.get("reason") or ""
                                _rsub_id[0]    = lv["id"]
                                if r_approver:
                                    r_approver.value = lv.get("ksv_approver_id")
                                resubmit_dialog.open()

                            ui.button("Sửa & Nộp lại", icon="refresh", on_click=_open_resubmit).classes("bg-orange-500 text-white text-sm")

                        # Hủy
                        if is_owner and status in ("pending_ksv", "pending_tong_hop", "pending_gd"):
                            async def _cancel(l=lid):
                                try:
                                    await asyncio.to_thread(api.patch, f"/api/leaves/{l}/cancel", {})
                                    detail_drawer.hide()
                                    ui.notify("Đã hủy đơn", type="warning")
                                    ui.navigate.to("/leaves")
                                except Exception as e:
                                    _handle_api_error(e)

                            ui.button("Hủy đơn", icon="cancel", on_click=_cancel).classes("bg-gray-200 text-gray-700 text-sm")

            detail_drawer.show()

        # ── Hàm mở dialog lịch sử ────────────────────────────────────────────
        async def open_history(leave: dict):
            history_container.clear()
            with history_container:
                with ui.row().classes("w-full bg-gray-800 text-white px-5 py-3 items-center gap-2"):
                    ui.icon("history").classes("text-xl")
                    with ui.column().classes("gap-0"):
                        ui.label("Lịch sử thao tác").classes("font-bold text-base")
                        ui.label(leave.get("staff_name", "")).classes("text-gray-300 text-sm")
                try:
                    logs = await asyncio.to_thread(api.get, f"/api/leaves/{leave['id']}/history")
                except Exception:
                    logs = []
                if not logs:
                    with ui.column().classes("p-6"):
                        ui.label("Chưa có lịch sử thao tác.").classes("text-gray-400 text-sm")
                else:
                    _COLOR = {"green": "bg-green-100 text-green-700", "red": "bg-red-100 text-red-700",
                              "blue": "bg-blue-100 text-blue-700", "orange": "bg-orange-100 text-orange-700",
                              "grey": "bg-gray-100 text-gray-500"}
                    with ui.column().classes("px-5 py-4 gap-3 w-full"):
                        for log in logs:
                            cls = _COLOR.get(log.get("action_color", "grey"), "bg-gray-100 text-gray-500")
                            with ui.row().classes("w-full items-start gap-3 border-b border-gray-100 pb-3"):
                                with ui.column().classes("flex-1 gap-1"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(log.get("action_label", log.get("action", ""))).classes(
                                            f"text-xs font-medium px-2 py-0.5 rounded {cls}")
                                        ui.label(log.get("actor_name", "")).classes("text-sm font-medium")
                                    if log.get("comment"):
                                        ui.label(f"Lý do: {log['comment']}").classes("text-xs text-gray-500")
                                    ts = log.get("created_at", "")
                                    if ts:
                                        ui.label(ts[:16].replace("T", " ")).classes("text-xs text-gray-400")
            history_dialog.open()

        # ── Tracking selection ────────────────────────────────────────────────
        _sel: set = set()
        _approve_btn: list = []
        _reject_btn:  list = []

        def _upd_btns():
            en = bool(_sel)
            for b in _approve_btn:
                b.set_enabled(en)
            for b in _reject_btn:
                b.set_enabled(en)

        # ── Bulk actions ──────────────────────────────────────────────────────
        async def _bulk_approve():
            ids = list(_sel)
            lv_map = {lv["id"]: lv for lv in pending_leaves}
            th_ids     = [i for i in ids if lv_map.get(i, {}).get("status") == "pending_tong_hop"]
            other_ids  = [i for i in ids if i not in th_ids]

            for i in other_ids:
                st = lv_map.get(i, {}).get("status", "")
                try:
                    if st == "pending_ksv":
                        await asyncio.to_thread(api.put, f"/api/leaves/{i}/ksv-review", {"action": "approve"})
                    elif st == "pending_gd":
                        await asyncio.to_thread(api.put, f"/api/leaves/{i}/gd-review", {"action": "approve"})
                except Exception:
                    pass

            if th_ids:
                await _load_gd_opts()
                async def _th_bulk(gd_id, note):
                    for i in th_ids:
                        try:
                            await asyncio.to_thread(api.post, f"/api/leaves/{i}/tong-hop-review",
                                {"action": "forward", "gd_approver_id": gd_id, "comment": note})
                        except Exception:
                            pass
                    _sel.clear()
                    ui.notify("Hoàn thành", type="positive")
                    ui.navigate.to("/leaves")
                _th_cb[0] = _th_bulk
                th_dialog.open()
            else:
                _sel.clear()
                ui.notify("Đã phê duyệt các đơn đã chọn", type="positive")
                ui.navigate.to("/leaves")

        async def _bulk_reject_open():
            ids = list(_sel)
            lv_map = {lv["id"]: lv for lv in pending_leaves}
            async def _cb(reason):
                for i in ids:
                    st = lv_map.get(i, {}).get("status", "")
                    try:
                        if st == "pending_ksv":
                            await asyncio.to_thread(api.put, f"/api/leaves/{i}/ksv-review",
                                {"action": "reject", "comment": reason})
                        elif st == "pending_tong_hop":
                            await asyncio.to_thread(api.post, f"/api/leaves/{i}/tong-hop-review",
                                {"action": "reject", "comment": reason})
                        elif st == "pending_gd":
                            await asyncio.to_thread(api.put, f"/api/leaves/{i}/gd-review",
                                {"action": "reject", "comment": reason})
                    except Exception:
                        pass
                _sel.clear()
                ui.notify("Đã từ chối các đơn đã chọn", type="warning")
                ui.navigate.to("/leaves")
            _reject_cb[0] = _cb
            reject_dialog.open()

        # ── Toolbar ───────────────────────────────────────────────────────────
        with ui.row().classes("gap-2 mb-4 items-center flex-wrap"):
            ui.button("+ Tạo đơn", icon="add", on_click=create_dialog.open).classes("bg-red-700 text-white")
            ab = ui.button("Phê duyệt", icon="check_circle",
                           on_click=lambda: asyncio.ensure_future(_bulk_approve())).classes(
                "bg-green-600 text-white").props("disabled")
            rb = ui.button("Từ chối", icon="cancel",
                           on_click=lambda: asyncio.ensure_future(_bulk_reject_open())).classes(
                "bg-red-600 text-white").props("disabled")
            _approve_btn.append(ab)
            _reject_btn.append(rb)

            async def _export_leaves():
                try:
                    _scp = "all" if can_all else "mine"
                    content = await asyncio.to_thread(
                        api.download, "/api/leaves/export",
                        params={"scope": _scp},
                    )
                    ui.download(content, "danh_sach_nghi_phep.xlsx")
                except Exception as e:
                    _handle_api_error(e)

            ui.button("Xuất Excel", icon="download",
                      on_click=_export_leaves).classes("bg-blue-700 text-white").tooltip("Tải file Excel")

        # ── Hàm vẽ bảng ──────────────────────────────────────────────────────
        def _draw_table(leaves: list, show_name: bool = False):
            if not leaves:
                ui.label("Không có đơn nghỉ phép nào.").classes("text-gray-400 text-sm mt-4")
                return
            with ui.column().classes("w-full gap-0"):
                # Header
                with ui.row().classes("w-full bg-red-50 border-b border-red-100 px-3 py-2 items-center gap-2"):
                    ui.label("").classes("w-6 shrink-0")
                    ui.label("Ngày tạo").classes("font-semibold text-red-800 text-xs w-20 shrink-0")
                    ui.label("Loại").classes("font-semibold text-red-800 text-xs w-28 shrink-0")
                    ui.label("Trạng thái").classes("font-semibold text-red-800 text-xs w-28 shrink-0")
                    if show_name:
                        ui.label("Họ và tên").classes("font-semibold text-red-800 text-xs w-28 shrink-0")
                    ui.label("Ngày nghỉ").classes("font-semibold text-red-800 text-xs w-32 shrink-0")
                    ui.label("Kiểm soát").classes("font-semibold text-red-800 text-xs w-24 shrink-0")
                    ui.label("Phòng TH").classes("font-semibold text-red-800 text-xs w-24 shrink-0")
                    ui.label("Giám đốc").classes("font-semibold text-red-800 text-xs flex-1")
                    ui.label("").classes("w-16 shrink-0")

                for lv in leaves:
                    sg_lbl, sg_cls = _STATUS_GROUP.get(lv["status"], (lv["status"], "bg-gray-100 text-gray-500"))
                    with ui.row().classes("w-full bg-white border-b border-gray-100 px-3 py-1.5 items-center gap-2 hover:bg-red-50"):
                        ck = ui.checkbox(value=False).classes("w-6 shrink-0")
                        ck.on("update:model-value", lambda v, l=lv["id"]: (_sel.add(l) if v else _sel.discard(l)) or _upd_btns())

                        ui.label((lv.get("created_at") or "")[:10]).classes("text-xs w-20 shrink-0")
                        ui.label(_LEAVE_TYPE.get(lv.get("leave_type",""), lv.get("leave_type",""))).classes("text-xs w-28 shrink-0 truncate")
                        ui.label(sg_lbl).classes(f"text-xs px-1.5 py-0.5 rounded {sg_cls} w-28 shrink-0 text-center")
                        if show_name:
                            ui.label(lv.get("staff_name", "")).classes("text-xs w-28 shrink-0 truncate")
                        ui.label(_fmt_leave_dates(lv.get("start_date",""), lv.get("end_date",""))).classes("text-xs w-32 shrink-0")
                        ui.label(lv.get("ksv_approver_name") or "—").classes("text-xs w-24 shrink-0 truncate")
                        ui.label(lv.get("tong_hop_approver_name") or "—").classes("text-xs w-24 shrink-0 truncate")
                        ui.label(_gd_display(lv) or "—").classes("text-xs flex-1 truncate")
                        with ui.row().classes("w-16 gap-0.5 justify-end shrink-0"):
                            ui.button(icon="info", on_click=lambda l=lv: asyncio.ensure_future(open_detail(l))).props(
                                "flat round dense size=sm").classes("text-blue-600").tooltip("Chi tiết")
                            ui.button(icon="history", on_click=lambda l=lv: asyncio.ensure_future(open_history(l))).props(
                                "flat round dense size=sm").classes("text-gray-500").tooltip("Lịch sử")

        # ── Tabs ──────────────────────────────────────────────────────────────
        with ui.tabs().classes("mb-4") as leave_tabs:
            t_mine    = ui.tab("Của tôi")
            t_pending = ui.tab(f"Chờ duyệt ({len(pending_leaves)})")
            t_all     = ui.tab("Tất cả") if can_all else None
            t_cal     = ui.tab("Lịch nghỉ phép")
            t_deleg   = ui.tab("Ủy quyền GĐ") if can_delegation else None
            t_holiday = ui.tab("Ngày lễ") if can_delegation else None

        with ui.tab_panels(leave_tabs, value=t_mine).classes("w-full"):
            with ui.tab_panel(t_mine):
                _draw_table(my_leaves)

            with ui.tab_panel(t_pending):
                _draw_table(pending_leaves, show_name=True)

            if can_all and t_all:
                with ui.tab_panel(t_all):
                    _draw_table(all_leaves, show_name=True)

            with ui.tab_panel(t_cal):
                import datetime as _dt_mod
                _today = _dt_mod.date.today()
                with ui.row().classes("gap-3 mb-4 items-center"):
                    cal_year  = ui.select({y: str(y) for y in range(2024, _today.year + 2)},
                                          label="Năm", value=_today.year).classes("w-28")
                    cal_month = ui.select({m: f"Tháng {m:02d}" for m in range(1, 13)},
                                          label="Tháng", value=_today.month).classes("w-36")

                _CAL_TYPE_COLOR = {
                    "annual":   "bg-blue-100 text-blue-800",
                    "sick":     "bg-orange-100 text-orange-800",
                    "personal": "bg-purple-100 text-purple-800",
                    "other":    "bg-gray-100 text-gray-600",
                }
                _CAL_TYPE_DOT = {
                    "annual":   "#1565C0",
                    "sick":     "#E65100",
                    "personal": "#6A1B9A",
                    "other":    "#546E7A",
                }
                _DOW_VN = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

                cal_container = ui.column().classes("w-full gap-0")

                async def _reload_cal():
                    cal_container.clear()
                    try:
                        data = await asyncio.to_thread(
                            api.get, "/api/leaves/calendar",
                            {"year": cal_year.value, "month": cal_month.value},
                        )
                    except Exception:
                        data = {}
                    days_map = data.get("days", {}) if isinstance(data, dict) else {}
                    y, m = cal_year.value, cal_month.value

                    import calendar as _cal_mod
                    first_wd = _dt_mod.date(y, m, 1).weekday()  # 0=Thứ 2
                    last_day = _cal_mod.monthrange(y, m)[1]

                    with cal_container:
                        # Chú thích
                        with ui.row().classes("gap-4 mb-3 flex-wrap items-center"):
                            for _lt, _cls in _CAL_TYPE_COLOR.items():
                                with ui.row().classes("items-center gap-1"):
                                    ui.element("span").classes(f"text-xs px-2 py-0.5 rounded {_cls}").set_text(
                                        _LEAVE_TYPE.get(_lt, _lt))
                        # Header ngày trong tuần
                        with ui.row().classes("w-full grid gap-1").style(
                                "display:grid;grid-template-columns:repeat(7,1fr)"):
                            for d in _DOW_VN:
                                ui.label(d).classes(
                                    "text-center text-xs font-bold text-gray-500 py-1"
                                    + (" text-red-600" if d == "CN" else "")
                                )
                        # Lưới ngày
                        with ui.element("div").style(
                                "display:grid;grid-template-columns:repeat(7,1fr);gap:4px"):
                            # Ô trống trước ngày 1
                            for _ in range(first_wd):
                                ui.element("div").classes("rounded bg-gray-50 min-h-[72px] p-1")
                            for day in range(1, last_day + 1):
                                d_str = f"{y}-{m:02d}-{day:02d}"
                                d_obj = _dt_mod.date(y, m, day)
                                people = days_map.get(d_str, [])
                                is_weekend = d_obj.weekday() >= 5
                                is_today   = d_obj == _today
                                bg = "bg-blue-50 border-blue-300" if is_today else (
                                     "bg-red-50" if is_weekend else "bg-white border-gray-100")
                                with ui.element("div").classes(
                                        f"rounded border {bg} min-h-[72px] p-1 overflow-hidden"
                                ):
                                    ui.label(str(day)).classes(
                                        "text-xs font-bold mb-1 " + (
                                            "text-blue-700" if is_today else
                                            "text-red-500" if is_weekend else "text-gray-700"
                                        )
                                    )
                                    for p in people[:3]:
                                        lt   = p.get("leave_type", "other")
                                        cls  = _CAL_TYPE_COLOR.get(lt, "bg-gray-100 text-gray-600")
                                        name = p.get("staff_name", "")
                                        # Rút gọn họ tên → lấy tên cuối
                                        short = name.split()[-1] if name else ""
                                        ui.label(short).classes(
                                            f"text-[10px] leading-tight px-1 rounded truncate {cls} mb-0.5 w-full")
                                    if len(people) > 3:
                                        ui.label(f"+{len(people)-3}").classes(
                                            "text-[9px] text-gray-400 leading-tight")

                cal_year.on("update:model-value",  lambda: asyncio.ensure_future(_reload_cal()))
                cal_month.on("update:model-value", lambda: asyncio.ensure_future(_reload_cal()))
                await _reload_cal()

            if can_delegation and t_deleg:
                with ui.tab_panel(t_deleg):
                    # ── Dialog tạo ủy quyền ───────────────────────────────────
                    gd_staff_list, pgd_staff_list = [], []
                    try:
                        gd_staff_list, pgd_staff_list = await asyncio.gather(
                            asyncio.to_thread(api.get, "/api/delegations/staff/giam-doc"),
                            asyncio.to_thread(api.get, "/api/delegations/staff/pho-giam-doc"),
                        )
                    except Exception:
                        pass

                    gd_opts  = {s["id"]: s["full_name"] for s in (gd_staff_list  or [])}
                    pgd_opts = {s["id"]: s["full_name"] for s in (pgd_staff_list or [])}

                    with ui.dialog() as deleg_dialog, ui.card().classes("p-6 w-96"):
                        ui.label("Tạo ủy quyền Giám đốc").classes("text-lg font-bold text-red-900 mb-4")
                        d_gd   = ui.select(gd_opts,  label="Giám đốc ủy quyền").classes("w-full")
                        d_pgd  = ui.select(pgd_opts, label="Phó GĐ được ủy quyền").classes("w-full mt-2")
                        d_from = ui.date(value="").props("label='Từ ngày' mask='YYYY-MM-DD'").classes("w-full mt-2")
                        d_to   = ui.date(value="").props("label='Đến ngày' mask='YYYY-MM-DD'").classes("w-full mt-2")
                        d_note = ui.input("Ghi chú (tuỳ chọn)").classes("w-full mt-2")

                        async def do_create_deleg():
                            if not d_gd.value or not d_pgd.value or not d_from.value or not d_to.value:
                                ui.notify("Vui lòng điền đầy đủ thông tin", type="warning")
                                return
                            try:
                                await asyncio.to_thread(api.post, "/api/delegations/", {
                                    "giam_doc_id": d_gd.value, "pho_giam_doc_id": d_pgd.value,
                                    "start_date": d_from.value, "end_date": d_to.value,
                                    "note": d_note.value or None,
                                })
                                deleg_dialog.close()
                                ui.notify("Đã tạo ủy quyền thành công!", type="positive")
                                ui.navigate.to("/leaves")
                            except Exception as e:
                                _handle_api_error(e)

                        with ui.row().classes("w-full justify-end gap-2 mt-4"):
                            ui.button("Hủy", on_click=deleg_dialog.close).classes("text-gray-500")
                            ui.button("Tạo ủy quyền", on_click=do_create_deleg).classes("bg-red-700 text-white")

                    ui.button("+ Tạo ủy quyền", on_click=deleg_dialog.open).classes("bg-red-700 text-white mb-4")

                    if not delegations:
                        ui.label("Chưa có bản ghi ủy quyền nào.").classes("text-gray-400 text-sm")
                    else:
                        with ui.column().classes("w-full gap-0"):
                            with ui.row().classes("w-full bg-red-50 border-b border-red-100 px-4 py-2 gap-3"):
                                for hdr in ["Giám đốc", "Phó GĐ được ủy quyền", "Từ ngày", "Đến ngày", "Ghi chú", "Trạng thái", ""]:
                                    ui.label(hdr).classes("font-semibold text-red-800 text-sm flex-1")
                            for d in delegations:
                                today_str = __import__("datetime").date.today().isoformat()
                                is_eff = d["is_active"] and d["start_date"] <= today_str <= d["end_date"]
                                badge_cls = "bg-green-100 text-green-700" if is_eff else "bg-gray-100 text-gray-500"
                                badge_txt = "Đang hiệu lực" if is_eff else "Không hiệu lực"
                                with ui.row().classes("w-full bg-white border-b border-gray-100 px-4 py-2 gap-3 items-center"):
                                    ui.label(d.get("giam_doc_name", "")).classes("text-sm flex-1")
                                    ui.label(d.get("pho_giam_doc_name", "")).classes("text-sm flex-1")
                                    ui.label(d.get("start_date", "")[:10]).classes("text-sm flex-1")
                                    ui.label(d.get("end_date", "")[:10]).classes("text-sm flex-1")
                                    ui.label(d.get("note") or "—").classes("text-xs text-gray-500 flex-1")
                                    ui.label(badge_txt).classes(f"text-xs px-2 py-0.5 rounded {badge_cls} flex-1")
                                    if d["is_active"]:
                                        async def do_deactivate(did=d["id"]):
                                            try:
                                                await asyncio.to_thread(api.patch, f"/api/delegations/{did}/deactivate", {})
                                                ui.notify("Đã hủy ủy quyền", type="warning")
                                                ui.navigate.to("/leaves")
                                            except Exception as e:
                                                _handle_api_error(e)
                                        ui.button("Hủy", on_click=do_deactivate).classes("text-xs bg-gray-100 text-gray-600")
                                    else:
                                        ui.label("").classes("flex-1")

            if can_delegation and t_holiday:
                with ui.tab_panel(t_holiday):
                    _cur_year = __import__("datetime").date.today().year
                    with ui.row().classes("gap-3 mb-4 items-center"):
                        h_year_sel = ui.select(
                            {y: str(y) for y in range(2024, _cur_year + 3)},
                            label="Năm", value=_cur_year,
                        ).classes("w-28")
                        ui.button("+ Thêm ngày lễ", icon="add",
                                  on_click=lambda: add_holiday_dialog.open()).classes("bg-red-700 text-white")

                    holiday_table_area = ui.column().classes("w-full gap-0")

                    with ui.dialog() as add_holiday_dialog, ui.card().classes("p-6 w-80"):
                        ui.label("Thêm ngày lễ").classes("text-lg font-bold text-red-900 mb-4")
                        h_date_in = ui.date(value="").props("label='Ngày lễ' mask='YYYY-MM-DD'").classes("w-full")
                        h_name_in = ui.input("Tên ngày lễ").classes("w-full mt-2")

                        async def do_add_holiday():
                            if not h_date_in.value or not h_name_in.value.strip():
                                ui.notify("Vui lòng nhập đầy đủ thông tin", type="warning")
                                return
                            try:
                                await asyncio.to_thread(api.post, "/api/admin/holidays/", {
                                    "date": h_date_in.value,
                                    "name": h_name_in.value.strip(),
                                })
                                h_date_in.value = ""
                                h_name_in.value = ""
                                add_holiday_dialog.close()
                                ui.notify("Đã thêm ngày lễ!", type="positive")
                                await _reload_holidays()
                            except Exception as e:
                                _handle_api_error(e)

                        with ui.row().classes("w-full justify-end gap-2 mt-4"):
                            ui.button("Hủy", on_click=add_holiday_dialog.close).classes("text-gray-500")
                            ui.button("Thêm", on_click=do_add_holiday).classes("bg-red-700 text-white")

                    async def _reload_holidays():
                        holiday_table_area.clear()
                        try:
                            holidays_data = await asyncio.to_thread(
                                api.get, "/api/admin/holidays/", {"year": h_year_sel.value}
                            )
                        except Exception:
                            holidays_data = []
                        holidays_data = holidays_data if isinstance(holidays_data, list) else []
                        with holiday_table_area:
                            if not holidays_data:
                                ui.label("Chưa có ngày lễ nào trong năm này.").classes("text-gray-400 text-sm mt-4")
                                return
                            with ui.column().classes("w-full gap-0"):
                                with ui.row().classes("w-full bg-red-50 border-b border-red-100 px-4 py-2 gap-3"):
                                    ui.label("Ngày").classes("font-semibold text-red-800 text-sm w-32 shrink-0")
                                    ui.label("Tên ngày lễ").classes("font-semibold text-red-800 text-sm flex-1")
                                    ui.label("").classes("w-12 shrink-0")
                                for h in holidays_data:
                                    with ui.row().classes("w-full bg-white border-b border-gray-100 px-4 py-2 gap-3 items-center"):
                                        ui.label(h.get("date", "")[:10]).classes("text-sm w-32 shrink-0 font-mono")
                                        ui.label(h.get("name", "")).classes("text-sm flex-1")
                                        async def do_del_holiday(hid=h["id"]):
                                            try:
                                                await asyncio.to_thread(api.delete, f"/api/admin/holidays/{hid}")
                                                ui.notify("Đã xóa ngày lễ", type="warning")
                                                await _reload_holidays()
                                            except Exception as ex:
                                                _handle_api_error(ex)
                                        ui.button(icon="delete", on_click=do_del_holiday).props(
                                            "flat round dense size=sm").classes("text-red-500 w-12 shrink-0")

                    h_year_sel.on("update:model-value", lambda: asyncio.ensure_future(_reload_holidays()))
                    await _reload_holidays()
