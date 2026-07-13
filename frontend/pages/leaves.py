"""Trang nghỉ phép → đăng ký, duyệt và lịch nghỉ."""

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

    "bat_buoc":     "Nghỉ phép bắt buộc",

    "annual":       "Nghỉ phép năm",

    "thai_san":     "Nghỉ thai sản",

    "bao_hiem":     "Nghỉ bảo hiểm",

    "other":        "Khác",

}

# Nhóm hiển thị 3 trạng thái đơn giản trong cột Trạng thái của bảng

_STATUS_GROUP = {

    "pending_ksv":      ("Chờ KSV duyệt",    "bg-orange-100 text-orange-700"),

    "pending_tong_hop": ("Chờ Tổng hợp",      "bg-yellow-100 text-yellow-700"),

    "pending_gd":       ("Chờ Ban lãnh đạo",  "bg-blue-100 text-blue-700"),

    "approved":         ("Hoàn thành",         "bg-green-100 text-green-700"),

    "rejected":         ("Từ chối",            "bg-red-100 text-red-700"),

    "cancelled":        ("Đã hủy",             "bg-gray-100 text-gray-500"),

}





def _leave_status_badge(status: str):

    label, cls = _LEAVE_STATUS.get(status, (status, "bg-gray-100 text-gray-500"))

    ui.label(label).classes(f"text-xs font-medium px-2 py-0.5 rounded border {cls}")





def _fmt_leave_dates(start_str: str, end_str: str, spread_dates=None) -> str:

    """1 ngày → DD/MM/YYYY; liên tiếp → DD/MM → DD/MM/YYYY; lẻ → DD/MM, DD/MM, DD/MM/YYYY"""

    if not start_str or not end_str:

        return "→"

    try:

        from datetime import date as _date

        s = _date.fromisoformat(start_str[:10])

        e = _date.fromisoformat(end_str[:10])

        if s == e:

            return s.strftime("%d/%m/%Y")

        if spread_dates and len(spread_dates) >= 2:

            parsed = sorted(_date.fromisoformat(d[:10]) for d in spread_dates)

            if len(parsed) <= 4:

                parts = [d.strftime("%d/%m") for d in parsed[:-1]]

                parts.append(parsed[-1].strftime("%d/%m/%Y"))

                return ", ".join(parts)

            else:

                first2 = ", ".join(d.strftime("%d/%m") for d in parsed[:2])

                return f"{first2} +{len(parsed) - 2} ngày"

        return f"{s.strftime('%d/%m')} → {e.strftime('%d/%m/%Y')}"

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

    if not api.has_feature("menu.leaves"):

        ui.navigate.to("/home")

        return

    badge_refs = _sidebar("leaves")



    current_user = api.get_current_user()

    user_role    = current_user.get("role", "") if current_user else ""

    user_id      = current_user.get("id") if current_user else None  # key lưu là "id", không phải "staff_id"

    # ── Kiểm tra broadcast notification ủy quyền ─────────────────────────────
    _last_seen_key = f"_deleg_seen_{user_id}"
    _last_seen     = app.storage.user.get(_last_seen_key, "")
    _broadcast     = app.storage.general.get("_deleg_broadcast", {})
    _deleg_end     = _broadcast.get("end_date", "")
    _deleg_active  = not _deleg_end or _deleg_end >= __import__("datetime").date.today().isoformat()
    if _broadcast and _broadcast.get("ts", "") > _last_seen and _deleg_active:
        app.storage.user[_last_seen_key] = _broadcast["ts"]
        async def _show_deleg_popup(msg=_broadcast["msg"]):
            with ui.dialog(value=True) as _dp, ui.card().classes("p-6 max-w-lg"):
                ui.label("📋 Thông báo ủy quyền").classes("text-lg font-bold text-red-900 mb-3")
                ui.label(msg).classes("text-sm text-gray-700 leading-relaxed")
                ui.button("Đã hiểu", on_click=_dp.close).classes("bg-red-700 text-white mt-4 w-full")
        ui.timer(0.5, _show_deleg_popup, once=True)

    # ── Popup thông báo carry-over hết hiệu lực sau Q1 (1 lần/năm/user) ──────
    async def _check_carryover_notice():
        try:
            res = await asyncio.to_thread(api.get, "/api/leaves/carryover-notice")
        except Exception:
            return
        if not isinstance(res, dict) or not res.get("show"):
            return
        with ui.dialog(value=True) as _cn_dp, ui.card().classes("p-6 max-w-lg"):
            ui.label("📌 Thông báo ngày phép chuyển kỳ").classes("text-lg font-bold text-red-900 mb-3")
            ui.label(
                "Ngày phép chuyển kỳ (carry-over) từ năm trước đã hết hiệu lực sau ngày 31/03. "
                "Các ngày chưa sử dụng đã bị thu hồi và không còn được cộng vào hạn mức phép năm nay."
            ).classes("text-sm text-gray-700 leading-relaxed")
            async def _ack():
                try:
                    await asyncio.to_thread(api.post, "/api/leaves/carryover-notice/ack", {})
                except Exception:
                    pass
                _cn_dp.close()
            ui.button("Đã hiểu", on_click=_ack).classes("bg-red-700 text-white mt-4 w-full")
    ui.timer(0.8, _check_carryover_notice, once=True)



    can_all        = (user_role in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")

                      or api.has_feature("leaves.forward_th"))  # Phòng TH xem toàn bộ

    can_delegation = user_role == "admin"

    show_approver  = user_role not in ("giam_doc", "pho_giam_doc", "admin", "truong_phong")



    # ── Drawer và dialog phải lý con trực tiếp của page ──────────────────────

    with ui.right_drawer(value=False).props("width=440 overlay behavior=mobile").classes(

        "bg-white shadow-2xl overflow-y-auto"

    ) as detail_drawer:

        drawer_container = ui.column().classes("w-full gap-0")



    with ui.dialog() as history_dialog, ui.card().classes("p-0 w-[560px] max-h-[80vh] overflow-y-auto"):

        history_container = ui.column().classes("w-full gap-0")



    # ── Dialog xác nhận chung ─────────────────────────────────────────────────

    _confirm_cb: list = [None]



    # _do_confirm_ref giúp button reference _do_confirm TRƯỚC khi nó được define

    _do_confirm_ref: list = [None]



    async def _cfm_on_click():

        """Wrapper async → NiceGUI gĐi trực tiếp nên có đồng client context."""

        if _do_confirm_ref[0]:

            await _do_confirm_ref[0]()



    with ui.dialog() as confirm_dialog, ui.card().classes("p-6 w-96"):

        _cfm_title = ui.label("").classes("text-lg font-bold text-red-900 mb-1")

        _cfm_msg   = ui.label("").classes("text-sm text-gray-600 mb-5")

        with ui.row().classes("gap-3 justify-end w-full"):

            ui.button("Hủy", on_click=confirm_dialog.close).props("flat").classes("text-gray-500")

            _cfm_ok = ui.button("Xác nhận", on_click=_cfm_on_click).classes("text-white")



    async def _do_confirm():

        confirm_dialog.close()

        if _confirm_cb[0]:

            await _confirm_cb[0]()



    _do_confirm_ref[0] = _do_confirm



    def _ask_confirm(title: str, msg: str, callback, ok_label: str = "Xác nhận", ok_cls: str = "bg-green-600"):

        _cfm_title.set_text(title)

        _cfm_msg.set_text(msg)

        _cfm_ok.set_text(ok_label)

        _cfm_ok.classes(replace=f"text-white {ok_cls}")

        _confirm_cb[0] = callback

        confirm_dialog.open()



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

        ui.label("Xác nhận & chuyển lên Ban lãnh đạo").classes("text-lg font-bold text-red-900 mb-4")

        th_gd_select = ui.select({}, label="Chọn GĐ / PGĐ phê duyệt").classes("w-full")

        th_note      = ui.textarea("Ghi chú (tuỳ chọn)").classes("w-full mt-2").props("rows=2")



        async def _load_gd_opts():

            try:

                lst = await asyncio.to_thread(api.get, "/api/leaves/gd-list")

                th_gd_select.options = {s["id"]: f"{s['full_name']} → {s['role_label']}" for s in (lst or [])}

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

        # ── Banner thông báo ủy quyền đang hiệu lực ──────────────────────────
        try:
            _active_deleg = api.get("/api/delegations/active") or []
        except Exception:
            _active_deleg = []

        if _active_deleg:
            _deleg_texts = []
            for d in _active_deleg:
                _deleg_texts.append(
                    f"📋 {d.get('giam_doc_name','GĐ')} ủy quyền cho "
                    f"{d.get('pho_giam_doc_name','PGĐ')} "
                    f"từ {d.get('start_date','')[:10]} đến {d.get('end_date','')[:10]}"
                )
            _banner_text = "   ·   ".join(_deleg_texts) + "   " * 5
            ui.html(f"""
                <div style="background:white; color:#8B0000;
                            border: 2px solid #8B0000; border-radius:8px;
                            padding:10px 16px; margin-bottom:10px;
                            overflow:hidden; font-size:15px; font-weight:600;">
                  <marquee behavior="scroll" direction="left" scrollamount="5"
                           style="white-space:nowrap; color:#8B0000;">
                    {_banner_text * 3}
                  </marquee>
                </div>
            """).classes("w-full")

        _page_header("Quản lý Nghỉ phép", "Đăng ký và phê duyệt nghỉ phép")



        # ── Load dữ liệu song song ────────────────────────────────────────────

        my_leaves, pending_leaves, all_leaves, dept_leaves, declared_leaves, delegations, balance_info, approver_list = \
            [], [], [], [], [], [], {}, []



        can_dept     = user_role in ("truong_phong", "pho_phong", "hau_kiem_vien")

        can_declared = api.has_feature("leaves.declare_direct")

        # Placeholder → chỉ có giá trị khi can_all=True (filter Dashboard)

        _f_from = _f_to = None



        async def _empty():

            return []



        try:

            results = await asyncio.gather(

                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "mine"}),

                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "pending"}),

                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "all"}) if can_all else _empty(),

                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "dept"}) if can_dept else _empty(),

                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "declared"}) if can_declared else _empty(),

                asyncio.to_thread(api.get, "/api/delegations/") if can_delegation else _empty(),

                asyncio.to_thread(api.get, "/api/auth/me"),

                asyncio.to_thread(api.get, "/api/leaves/approvers") if show_approver else _empty(),

                return_exceptions=True,

            )

            my_leaves, pending_leaves, all_leaves, dept_leaves, declared_leaves, delegations, balance_info, approver_list = results

            for r in results:

                if isinstance(r, api.SessionExpiredError):

                    ui.notify(str(r), type="warning")

                    ui.navigate.to("/login")

                    return

            my_leaves      = my_leaves       if isinstance(my_leaves, list)      else []

            pending_leaves = pending_leaves  if isinstance(pending_leaves, list)  else []

            all_leaves     = all_leaves      if isinstance(all_leaves, list)      else []

            dept_leaves    = dept_leaves     if isinstance(dept_leaves, list)     else []

            declared_leaves = declared_leaves if isinstance(declared_leaves, list) else []

            delegations    = delegations     if isinstance(delegations, list)     else []

            balance_info   = balance_info    if isinstance(balance_info, dict)    else {}

            approver_list  = approver_list   if isinstance(approver_list, list)   else []

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

        approver_opts = {s["id"]: f"{s['full_name']} → {s['role_label']}" for s in approver_list}



        _today_slash = _dt_mod.date.today().isoformat().replace('-', '/')

        _today_iso   = _dt_mod.date.today().isoformat()

        _VI_LOCALE = (
            ":locale=\"{ days: ['Chủ nhật','Thứ 2','Thứ 3','Thứ 4','Thứ 5','Thứ 6','Thứ 7'],"
            " daysShort: ['CN','T2','T3','T4','T5','T6','T7'],"
            " months: ['Tháng 1','Tháng 2','Tháng 3','Tháng 4','Tháng 5','Tháng 6',"
            "'Tháng 7','Tháng 8','Tháng 9','Tháng 10','Tháng 11','Tháng 12'],"
            " monthsShort: ['T01','T02','T03','T04','T05','T06','T07','T08','T09','T10','T11','T12'] }\""
        )

        _OPT_FUTURE  = f":options=\"d => d >= '{_today_slash}'\" {_VI_LOCALE}"

        _OPT_ALL     = f":options=\"() => true\" {_VI_LOCALE}"



        # Lấy danh sách GĐ/PGĐ để chọn khi tạo đơn

        gd_opts: dict = {}

        try:

            gd_list = await asyncio.to_thread(api.get, "/api/delegations/staff/giam-doc")

            pgd_list = await asyncio.to_thread(api.get, "/api/delegations/staff/pho-giam-doc")

            for s in (gd_list or []):

                gd_opts[s["id"]] = s["full_name"] + " (GĐ)"

            for s in (pgd_list or []):

                gd_opts[s["id"]] = s["full_name"] + " (PGĐ)"

        except Exception:

            pass



        with ui.dialog() as create_dialog, ui.card().classes("p-6 w-[420px]"):

            ui.label("Tạo đơn nghỉ phép").classes("text-lg font-bold text-red-900 mb-4")

            import calendar as _cal_mod2
            from datetime import date as _dobj

            _c_today_ref = _dobj.today()
            _c_sel       = set()
            _c_cur       = [_c_today_ref.year, _c_today_ref.month]
            _c_min       = [_c_today_ref]   # list để mutate trong closure

            c_grid_area = ui.column().classes("w-full border border-gray-200 rounded p-2 bg-white")
            c_hint      = ui.label("Click chọn từng ngày · Click lại để bỏ chọn").classes("text-xs text-orange-500 mt-0.5")

            # ── Date picker cho thai sản / bảo hiểm ──────────────────────────────
            _rs_val = [""]   # YYYY-MM-DD ngày bắt đầu
            _re_val = [""]   # YYYY-MM-DD ngày kết thúc
            _rs_cur = [_c_today_ref.year, _c_today_ref.month]
            _re_cur = [_c_today_ref.year, _c_today_ref.month]

            c_range_area = ui.column().classes("w-full gap-2 mt-1")
            c_range_area.set_visibility(False)
            with c_range_area:
                ui.label("Chọn khoảng thời gian nghỉ").classes("text-xs text-blue-600 font-medium -mb-1")
                # Picker ngày bắt đầu
                with ui.column().classes("w-full gap-0"):
                    with ui.row().classes("w-full items-center gap-1"):
                        c_range_start = ui.input("Ngày bắt đầu", placeholder="DD/MM/YYYY").classes("flex-1")
                        _rs_cal_btn   = ui.button(icon="calendar_month").props("flat round dense size=sm color=grey-7")
                    _rs_cal = ui.column().classes("w-full border border-gray-200 rounded p-2 bg-white mt-1")
                    _rs_cal.set_visibility(False)
                # Picker ngày kết thúc
                with ui.column().classes("w-full gap-0 mt-1"):
                    with ui.row().classes("w-full items-center gap-1"):
                        c_range_end = ui.input("Ngày kết thúc", placeholder="DD/MM/YYYY").classes("flex-1")
                        _re_cal_btn  = ui.button(icon="calendar_month").props("flat round dense size=sm color=grey-7")
                    _re_cal = ui.column().classes("w-full border border-gray-200 rounded p-2 bg-white mt-1")
                    _re_cal.set_visibility(False)

            # ── Render calendar cho từng picker ───────────────────────────────────
            def _rs_render():
                _rs_cal.clear()
                y, m = _rs_cur
                with _rs_cal:
                    with ui.row().classes("w-full items-center justify-between mb-1"):
                        ui.button(icon="chevron_left",  on_click=_rs_prev).props("flat round dense size=sm")
                        ui.label(f"Tháng {m:02d}/{y}").classes("text-sm font-semibold text-gray-700")
                        ui.button(icon="chevron_right", on_click=_rs_next).props("flat round dense size=sm")
                    with ui.row().classes("w-full gap-0"):
                        for h in ["T2","T3","T4","T5","T6","T7","CN"]:
                            ui.label(h).classes("text-xs text-center text-gray-400 w-[14.28%] py-0.5")
                    first_wd = _dobj(y, m, 1).weekday()
                    last_day = _cal_mod2.monthrange(y, m)[1]
                    today_   = _dobj.today()
                    with ui.row().classes("w-full gap-0 flex-wrap"):
                        for _ in range(first_wd):
                            ui.label("").classes("w-[14.28%] h-7")
                        for day in range(1, last_day + 1):
                            ds = f"{y:04d}-{m:02d}-{day:02d}"; dobj = _dobj(y, m, day)
                            sel = (ds == _rs_val[0]); is_td = (dobj == today_); wknd = dobj.weekday() >= 5
                            def _pick_rs(ds=ds):
                                def _do():
                                    _rs_val[0] = ds
                                    c_range_start.value = f"{ds[8:10]}/{ds[5:7]}/{ds[0:4]}"
                                    _rs_cal.set_visibility(False); _rs_render()
                                return _do
                            with ui.element("div").classes("w-[14.28%] h-7 flex items-center justify-center"):
                                if sel:
                                    ui.label(str(day)).classes("w-6 h-6 rounded-full bg-red-700 text-white text-xs font-bold flex items-center justify-center cursor-pointer").on("click", _pick_rs())
                                elif is_td:
                                    ui.label(str(day)).classes("w-6 h-6 rounded-full ring-2 ring-red-500 text-red-600 text-xs font-bold flex items-center justify-center cursor-pointer hover:bg-red-50").on("click", _pick_rs())
                                elif wknd:
                                    ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-blue-300 hover:bg-blue-50 cursor-pointer").on("click", _pick_rs())
                                else:
                                    ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-gray-600 hover:bg-red-50 hover:text-red-700 cursor-pointer").on("click", _pick_rs())

            def _rs_prev():
                y, m = _rs_cur; _rs_cur[0], _rs_cur[1] = (y-1, 12) if m == 1 else (y, m-1); _rs_render()
            def _rs_next():
                y, m = _rs_cur; _rs_cur[0], _rs_cur[1] = (y+1, 1) if m == 12 else (y, m+1); _rs_render()
            def _rs_toggle():
                vis = not _rs_cal.visible; _rs_cal.set_visibility(vis)
                if vis: _rs_render()
            def _rs_parse():
                txt = c_range_start.value.strip()
                if not txt: _rs_val[0] = ""; return
                try:
                    parts = txt.replace("-", "/").split("/")
                    if len(parts) != 3 or len(parts[2]) != 4:
                        raise ValueError("Định dạng phải là dd/mm/yyyy")
                    d, mo, yr = int(parts[0]), int(parts[1]), int(parts[2])
                    _dobj(yr, mo, d); _rs_val[0] = f"{yr:04d}-{mo:02d}-{d:02d}"
                except Exception: _rs_val[0] = ""
            _rs_cal_btn.on("click", _rs_toggle)
            c_range_start.on("blur", _rs_parse)

            def _re_render():
                _re_cal.clear()
                y, m = _re_cur
                with _re_cal:
                    with ui.row().classes("w-full items-center justify-between mb-1"):
                        ui.button(icon="chevron_left",  on_click=_re_prev).props("flat round dense size=sm")
                        ui.label(f"Tháng {m:02d}/{y}").classes("text-sm font-semibold text-gray-700")
                        ui.button(icon="chevron_right", on_click=_re_next).props("flat round dense size=sm")
                    with ui.row().classes("w-full gap-0"):
                        for h in ["T2","T3","T4","T5","T6","T7","CN"]:
                            ui.label(h).classes("text-xs text-center text-gray-400 w-[14.28%] py-0.5")
                    first_wd = _dobj(y, m, 1).weekday()
                    last_day = _cal_mod2.monthrange(y, m)[1]
                    today_   = _dobj.today()
                    with ui.row().classes("w-full gap-0 flex-wrap"):
                        for _ in range(first_wd):
                            ui.label("").classes("w-[14.28%] h-7")
                        for day in range(1, last_day + 1):
                            ds = f"{y:04d}-{m:02d}-{day:02d}"; dobj = _dobj(y, m, day)
                            sel = (ds == _re_val[0]); is_td = (dobj == today_); wknd = dobj.weekday() >= 5
                            def _pick_re(ds=ds):
                                def _do():
                                    _re_val[0] = ds
                                    c_range_end.value = f"{ds[8:10]}/{ds[5:7]}/{ds[0:4]}"
                                    _re_cal.set_visibility(False); _re_render()
                                return _do
                            with ui.element("div").classes("w-[14.28%] h-7 flex items-center justify-center"):
                                if sel:
                                    ui.label(str(day)).classes("w-6 h-6 rounded-full bg-red-700 text-white text-xs font-bold flex items-center justify-center cursor-pointer").on("click", _pick_re())
                                elif is_td:
                                    ui.label(str(day)).classes("w-6 h-6 rounded-full ring-2 ring-red-500 text-red-600 text-xs font-bold flex items-center justify-center cursor-pointer hover:bg-red-50").on("click", _pick_re())
                                elif wknd:
                                    ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-blue-300 hover:bg-blue-50 cursor-pointer").on("click", _pick_re())
                                else:
                                    ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-gray-600 hover:bg-red-50 hover:text-red-700 cursor-pointer").on("click", _pick_re())

            def _re_prev():
                y, m = _re_cur; _re_cur[0], _re_cur[1] = (y-1, 12) if m == 1 else (y, m-1); _re_render()
            def _re_next():
                y, m = _re_cur; _re_cur[0], _re_cur[1] = (y+1, 1) if m == 12 else (y, m+1); _re_render()
            def _re_toggle():
                vis = not _re_cal.visible; _re_cal.set_visibility(vis)
                if vis: _re_render()
            def _re_parse():
                txt = c_range_end.value.strip()
                if not txt: _re_val[0] = ""; return
                try:
                    parts = txt.replace("-", "/").split("/")
                    if len(parts) != 3 or len(parts[2]) != 4:
                        raise ValueError("Định dạng phải là dd/mm/yyyy")
                    d, mo, yr = int(parts[0]), int(parts[1]), int(parts[2])
                    _dobj(yr, mo, d); _re_val[0] = f"{yr:04d}-{mo:02d}-{d:02d}"
                except Exception: _re_val[0] = ""
            _re_cal_btn.on("click", _re_toggle)
            c_range_end.on("blur", _re_parse)

            def _c_render():
                c_grid_area.clear()
                y, m = _c_cur
                min_d = _c_min[0]
                with c_grid_area:
                    with ui.row().classes("w-full items-center justify-between mb-1"):
                        ui.button(icon="chevron_left", on_click=_c_prev).props("flat round dense size=sm")
                        ui.label(f"Tháng {m:02d}/{y}").classes("text-sm font-semibold text-gray-700")
                        ui.button(icon="chevron_right", on_click=_c_next).props("flat round dense size=sm")
                    with ui.row().classes("w-full gap-0"):
                        for h in ["T2","T3","T4","T5","T6","T7","CN"]:
                            ui.label(h).classes("text-xs text-center text-gray-400 w-[14.28%] py-0.5")
                    first_wd  = _dobj(y, m, 1).weekday()
                    last_day  = _cal_mod2.monthrange(y, m)[1]
                    _c_today_ = _dobj.today()
                    with ui.row().classes("w-full gap-0 flex-wrap"):
                        for _ in range(first_wd):
                            ui.label("").classes("w-[14.28%] h-7")
                        for day in range(1, last_day + 1):
                            ds    = f"{y:04d}-{m:02d}-{day:02d}"
                            dobj  = _dobj(y, m, day)
                            sel   = ds in _c_sel
                            past  = dobj < min_d
                            wknd  = dobj.weekday() >= 5
                            is_td = (dobj == _c_today_)
                            def _mk(ds=ds):
                                def _toggle():
                                    _c_sel.discard(ds) if ds in _c_sel else _c_sel.add(ds)
                                    _c_render()
                                return _toggle
                            wrap_cls = "w-[14.28%] h-7 flex items-center justify-center"
                            with ui.element("div").classes(wrap_cls):
                                if sel:
                                    inner = "w-6 h-6 rounded-full bg-red-700 text-white text-xs font-bold flex items-center justify-center cursor-pointer"
                                    if is_td:
                                        inner += " ring-2 ring-offset-1 ring-red-400"
                                    ui.label(str(day)).classes(inner).on("click", _mk())
                                elif past:
                                    inner = "w-6 h-6 flex items-center justify-center text-xs text-gray-400 hover:bg-red-50 hover:text-red-700 cursor-pointer rounded"
                                    if is_td:
                                        inner += " rounded-full ring-2 ring-gray-300"
                                    ui.label(str(day)).classes(inner).on("click", _mk())
                                elif is_td:
                                    ui.label(str(day)).classes(
                                        "w-6 h-6 rounded-full ring-2 ring-red-500 text-red-600 text-xs font-bold flex items-center justify-center cursor-pointer hover:bg-red-50"
                                    ).on("click", _mk())
                                elif wknd:
                                    ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-blue-300 hover:bg-blue-50 cursor-pointer").on("click", _mk())
                                else:
                                    ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-gray-600 hover:bg-red-50 hover:text-red-700 cursor-pointer").on("click", _mk())

            def _c_prev():
                y, m = _c_cur
                _c_cur[0], _c_cur[1] = (y-1, 12) if m == 1 else (y, m-1)
                _c_render()

            def _c_next():
                y, m = _c_cur
                _c_cur[0], _c_cur[1] = (y+1, 1) if m == 12 else (y, m+1)
                _c_render()

            _c_render()

            c_type     = ui.select({k: v for k, v in _LEAVE_TYPE.items()}, label="Loại nghỉ phép", value="annual").classes("w-full mt-2")

            c_reason   = ui.textarea("Lý do (tuỳ chọn)").classes("w-full mt-2")

            c_approver = ui.select(approver_opts, label="Người phê duyệt (KSV)").classes("w-full mt-2") if show_approver else None

            c_gd       = ui.select(gd_opts, label="Ban lãnh đạo phê duyệt (GĐ/PGĐ)").classes("w-full mt-2") if (gd_opts and user_role != "giam_doc") else None



            def _c_on_type():

                lt = c_type.value
                is_range = lt in ("thai_san", "bao_hiem")

                c_grid_area.set_visibility(not is_range)
                c_hint.set_visibility(not is_range)
                c_range_area.set_visibility(is_range)

                c_reason.props(f'label="{"Lý do (bắt buộc)" if lt == "other" else "Lý do (tuỳ chọn)"}"')

                if not is_range:
                    if lt in ("annual", "bat_buoc"):
                        _c_min[0] = _dobj.today()
                        c_hint.set_text("Chỉ chọn ngày từ hôm nay trở đi" if lt == "annual" else "Tối thiểu 5 ngày làm việc")
                        c_hint.style("color:#f97316" if lt == "annual" else "color:#3b82f6")
                    else:
                        _c_min[0] = _dobj(2000, 1, 1)
                        c_hint.set_text("Nhập lý do bên dưới" if lt == "other" else "Click chọn từng ngày")
                        c_hint.style("color:#6b7280")
                    _c_sel.clear()
                    _c_render()



            c_type.on("update:model-value", _c_on_type)



            async def do_create():

                lt = c_type.value
                is_range = lt in ("thai_san", "bao_hiem")

                if is_range:
                    _rs_parse(); _re_parse()   # flush giá trị nhập tay nếu chưa blur
                    start_val = _rs_val[0]
                    end_val   = _re_val[0]
                    if not start_val or not end_val:
                        ui.notify("Vui lòng chọn hoặc nhập ngày bắt đầu và ngày kết thúc (DD/MM/YYYY)", type="warning"); return
                    if end_val < start_val:
                        ui.notify("Ngày kết thúc phải sau ngày bắt đầu", type="warning"); return
                    body = {"start_date": start_val, "end_date": end_val,
                            "leave_type": lt, "reason": c_reason.value or None}
                else:
                    dates = sorted(_c_sel)

                    if not dates:
                        ui.notify("Vui lòng chọn ít nhất 1 ngày", type="warning"); return

                    if lt == "other" and not (c_reason.value or "").strip():
                        ui.notify("Vui lòng nhập lý do khi chọn loại Khác", type="warning"); return

                    body = {"start_date": dates[0], "end_date": dates[-1],
                            "spread_dates": dates,
                            "leave_type": lt, "reason": c_reason.value or None}

                if show_approver and not c_approver.value:
                    ui.notify("Vui lòng chọn người phê duyệt (KSV)", type="warning"); return

                if c_gd and not c_gd.value:
                    ui.notify("Vui lòng chọn Ban lãnh đạo phê duyệt", type="warning"); return

                if show_approver:
                    body["ksv_approver_id"] = c_approver.value

                if c_gd and c_gd.value:
                    body["gd_approver_id"] = c_gd.value

                try:

                    await asyncio.to_thread(api.post, "/api/leaves/", body)

                    create_dialog.close()

                    if user_role == "giam_doc":
                        ui.notify("✅ Đơn nghỉ phép đã được ghi nhận và tự động duyệt.",
                                  type="positive", timeout=4000)
                    else:
                        ui.notify("✅ Gửi đơn nghỉ phép thành công! Đơn đang chờ phê duyệt.",
                                  type="positive", timeout=4000)

                    ui.timer(2.5, lambda: ui.navigate.to("/leaves"), once=True)

                except Exception as e:

                    if not _handle_api_error(e):

                        ui.notify(f"Gửi đơn thất bại: {e}", type="negative", timeout=5000)



            def _c_open():
                _c_today_now = _dobj.today()
                _c_sel.clear()
                _c_min[0] = _c_today_now
                _c_cur[0], _c_cur[1] = _c_today_now.year, _c_today_now.month
                c_type.value = "annual"
                _rs_val[0] = ""; _re_val[0] = ""
                _rs_cur[0], _rs_cur[1] = _c_today_now.year, _c_today_now.month
                _re_cur[0], _re_cur[1] = _c_today_now.year, _c_today_now.month
                c_range_start.value = ""
                c_range_end.value   = ""
                _rs_cal.set_visibility(False)
                _re_cal.set_visibility(False)
                c_grid_area.set_visibility(True)
                c_hint.set_visibility(True)
                c_range_area.set_visibility(False)
                _c_render()
                create_dialog.open()

            with ui.row().classes("w-full justify-end gap-2 mt-4"):

                ui.button("Hủy", on_click=create_dialog.close).classes("text-gray-500")

                ui.button("Gửi đơn", on_click=do_create).classes("bg-red-700 text-white")



        # ── Dialog Xem & Sửa đơn (preview dạng mẫu giấy) ────────────────────
        _edit_id: list = [None]

        with ui.dialog().props("maximized") as edit_preview_dialog, \
             ui.card().classes("w-full h-full max-w-2xl mx-auto p-0 overflow-auto"):

            with ui.column().classes("w-full gap-0"):
                # Toolbar
                with ui.row().classes("w-full bg-red-800 px-4 py-3 items-center justify-between"):
                    ui.label("Xem & Sửa đơn nghỉ phép").classes("text-white font-bold text-base")
                    ui.button(icon="close", on_click=edit_preview_dialog.close).props("flat round dense").classes("text-white")

                # Form preview giống mẫu giấy
                with ui.column().classes("w-full p-6 gap-3 bg-white"):
                    # Header quốc hiệu
                    with ui.column().classes("w-full items-center gap-0 mb-2"):
                        ui.label("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM").classes("font-bold text-sm text-center")
                        ui.label("Độc lập – Tự do – Hạnh phúc").classes("text-sm text-center")
                        ui.label("─────────────────").classes("text-gray-400 text-xs text-center")
                        ep_date_lbl = ui.label("").classes("text-sm text-right w-full italic")

                    ui.label("ĐƠN XIN NGHỈ PHÉP").classes("font-bold text-lg text-center w-full mt-2")

                    # Info nhân viên (read-only)
                    ep_name_lbl  = ui.label("").classes("text-sm")
                    ep_dept_lbl  = ui.label("").classes("text-sm")
                    ep_intro_lbl = ui.label("").classes("text-sm mb-2")

                    ui.separator()

                    # Trường có thể sửa
                    ui.label("Loại nghỉ phép:").classes("text-xs font-semibold text-gray-500 mt-2")
                    ep_type = ui.select(
                        {k: v for k, v in _LEAVE_TYPE.items()}, value="annual"
                    ).classes("w-full")

                    ui.label("Ngày nghỉ:").classes("text-xs font-semibold text-gray-500 mt-2")
                    ep_dates = ui.date(value=[]).props(
                        f"multiple mask='YYYY-MM-DD' no-header first-day-of-week='1' {_OPT_ALL}"
                    ).classes("w-full")
                    ep_dates_hint = ui.label("").classes("text-xs text-orange-500")

                    ui.label("Lý do xin nghỉ:").classes("text-xs font-semibold text-gray-500 mt-2")
                    ep_reason = ui.textarea(placeholder="Nhập lý do...").props("rows=3").classes("w-full")

                    ui.separator().classes("my-2")

                    ui.label("Người phê duyệt (KSV):").classes("text-xs font-semibold text-gray-500")
                    ep_ksv = ui.select(approver_opts, label="Chọn KSV phê duyệt").classes("w-full") if show_approver else None

                    ui.label("Ban lãnh đạo phê duyệt (GĐ/PGĐ):").classes("text-xs font-semibold text-gray-500 mt-2")
                    ep_gd = ui.select({}, label="Chọn GĐ/PGĐ").classes("w-full")

                    # Buttons
                    with ui.row().classes("w-full justify-end gap-2 mt-4"):
                        ui.button("Hủy", on_click=edit_preview_dialog.close).props("flat").classes("text-gray-600")

                        async def _ep_save():
                            lid = _edit_id[0]
                            if not lid: return
                            raw = ep_dates.value
                            if not raw:
                                ui.notify("Chọn ít nhất 1 ngày", type="warning"); return
                            dates = sorted(set(raw if isinstance(raw, list) else [raw]))
                            dates = [d[:10] for d in dates if d]
                            if not dates:
                                ui.notify("Chọn ít nhất 1 ngày", type="warning"); return
                            if show_approver and ep_ksv and not ep_ksv.value:
                                ui.notify("Vui lòng chọn người phê duyệt KSV", type="warning"); return
                            body = {
                                "start_date":   dates[0], "end_date": dates[-1],
                                "spread_dates": dates,
                                "leave_type":   ep_type.value,
                                "reason":       ep_reason.value or None,
                            }
                            if show_approver and ep_ksv:
                                body["ksv_approver_id"] = ep_ksv.value
                            if ep_gd.value:
                                body["gd_approver_id"] = ep_gd.value
                            try:
                                await asyncio.to_thread(api.put, f"/api/leaves/{lid}/resubmit", body)
                                edit_preview_dialog.close()
                                detail_drawer.hide()
                                ui.notify("Đã lưu & nộp lại đơn!", type="positive")
                                ui.navigate.to("/leaves")
                            except Exception as e:
                                _handle_api_error(e)

                        ui.button("Lưu & Nộp lại", icon="send", on_click=_ep_save).classes("bg-red-700 text-white")

        # ── Dialog nộp lại ────────────────────────────────────────────────────

        _rsub_id: list = [None]

        with ui.dialog() as resubmit_dialog, ui.card().classes("p-6 w-[420px]"):

            ui.label("Chỉnh sửa & Nộp lại").classes("text-lg font-bold text-red-900 mb-4")

            r_dates    = ui.date(value=[]).props(f"multiple mask='YYYY-MM-DD' no-header first-day-of-week='1' {_OPT_FUTURE}").classes("w-full")

            r_hint     = ui.label("Click chọn từng ngày → Click lại để bỏ chọn").classes("text-xs text-orange-500 mt-0.5")

            r_type     = ui.select({k: v for k, v in _LEAVE_TYPE.items()}, label="Loại nghỉ phép", value="annual").classes("w-full mt-2")

            r_reason   = ui.textarea("Lý do (tuỳ chọn)").classes("w-full mt-2")

            r_approver = ui.select(approver_opts, label="Người phê duyệt (KSV)").classes("w-full mt-2") if show_approver else None

            r_gd_select = ui.select({}, label="Ban lãnh đạo phê duyệt (GĐ/PGĐ)").classes("w-full mt-2")

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

                    r_hint.set_text("Có thể chọn ngày trong quý khứ" if lt == "dot_xuat" else "")

                    r_hint.style("color:#6b7280")



            r_type.on("update:model-value", _r_on_type)



            async def do_resubmit():

                lid = _rsub_id[0]

                raw = r_dates.value

                if not lid or not raw:

                    ui.notify("Vui lòng chọn ít nhất 1 ngày", type="warning"); return

                dates = sorted(set(raw if isinstance(raw, list) else [raw]))

                dates = [d[:10] for d in dates if d]

                if not dates:

                    ui.notify("Vui lòng chọn ít nhất 1 ngày", type="warning"); return

                if show_approver and not r_approver.value:

                    ui.notify("Vui lòng chọn người phê duyệt", type="warning"); return

                body = {"start_date": dates[0], "end_date": dates[-1],

                        "spread_dates": dates,

                        "leave_type": r_type.value, "reason": r_reason.value or None}

                if show_approver:
                    body["ksv_approver_id"] = r_approver.value

                if r_gd_select.value:
                    body["gd_approver_id"] = r_gd_select.value

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



        # ── Hôm mở drawer chi tiết ────────────────────────────────────────────

        async def open_detail(leave: dict):

            drawer_container.clear()

            with drawer_container:

                lid      = leave["id"]

                status   = leave["status"]

                is_owner = user_id is not None and leave.get("staff_id") == user_id

                in_pend  = lid in pending_ids

                _approver_roles = ("truong_phong", "pho_phong", "hau_kiem_vien",
                                   "giam_doc", "pho_giam_doc", "admin")
                _can_act = user_role in _approver_roles

                ksv_act  = status == "pending_ksv" and in_pend and user_role in ("truong_phong", "pho_phong", "hau_kiem_vien")

                th_act   = status == "pending_tong_hop" and in_pend and _can_act

                gd_act   = status == "pending_gd" and in_pend and user_role in ("giam_doc", "pho_giam_doc")

                # Đơn của GĐ đã tự động approved — TH chỉ cần "xác nhận đã biết" (thông báo),
                # không phải điều kiện duyệt.
                th_ack_act = (status == "approved" and leave.get("staff_role") == "giam_doc"
                              and not leave.get("tong_hop_approver_id"))



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

                            ui.label(str(val) if val else "→").classes("text-sm font-medium flex-1")



                    _info("Phòng:", leave.get("department_name") or "→")

                    _sd = leave.get("spread_dates")

                    _s  = (leave.get("start_date") or "")[:10]

                    _e  = (leave.get("end_date") or "")[:10]

                    if _sd and len(_sd) >= 2:

                        from datetime import date as _d

                        with ui.row().classes("w-full items-start gap-2"):

                            ui.label("Ngày nghỉ:").classes("text-sm text-gray-500 w-28 shrink-0")

                            with ui.column().classes("flex-1 gap-0.5"):

                                for _dstr in sorted(_sd):

                                    try:

                                        ui.label(_d.fromisoformat(_dstr[:10]).strftime("%d/%m/%Y")).classes("text-sm font-medium")

                                    except Exception:

                                        ui.label(_dstr[:10]).classes("text-sm font-medium")

                    else:

                        _info("Từ ngày:", _s)

                        _info("Đến ngày:", _e)

                    _info("Số ngày nghỉ:", f"{leave.get('leave_days', '')} ngày")

                    _info("Loại:", _LEAVE_TYPE.get(leave.get("leave_type", ""), leave.get("leave_type", "")))

                    _info("Lý do:", leave.get("reason") or "→")



                    if leave.get("is_direct"):

                        # Khai báo hộ → không qua quy trình duyệt

                        with ui.column().classes("w-full bg-purple-50 rounded-lg p-3 gap-1 border border-purple-100"):

                            ui.label("Khai báo hộ → Duyệt trực tiếp").classes("text-xs font-bold text-purple-700 uppercase")

                            _info("Người khai báo:", leave.get("declarer_name") or "→")

                            _info("Ghi chú:", "Đơn được khai báo và duyệt trực tiếp, không qua quy trình phê duyệt.")

                    else:

                        _is_admin = user_role == "admin"

                        # Bước 1: KSV
                        if leave.get("ksv_approver_id") or status == "pending_ksv":

                            with ui.column().classes("w-full bg-orange-50 rounded-lg p-3 gap-1 border border-orange-100"):

                                with ui.row().classes("w-full items-center justify-between"):
                                    ui.label("Bước 1 → KSV phê duyệt").classes("text-xs font-bold text-orange-700 uppercase")
                                    if _is_admin and status == "pending_ksv":
                                        with ui.row().classes("gap-1"):
                                            async def _admin_ksv_approve(l=lid):
                                                async def _do(_l=l):
                                                    await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review", {"action": "approve"})
                                                    ui.notify("Đã duyệt bước KSV! Tiếp tục duyệt bước TH.", type="positive")
                                                    updated = await asyncio.to_thread(api.get, f"/api/leaves/{_l}")
                                                    if updated: await open_detail(updated)
                                                _ask_confirm("Duyệt bước KSV", "Xác nhận phê duyệt bước KSV?", _do, "Phê duyệt", "bg-green-600")
                                            ui.button(icon="check", on_click=_admin_ksv_approve).props("round dense flat").classes("text-green-600 bg-green-50").tooltip("Phê duyệt KSV")
                                            async def _admin_ksv_reject(l=lid):
                                                async def _cb(reason, _l=l):
                                                    await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review", {"action": "reject", "comment": reason})
                                                    detail_drawer.hide(); ui.notify("Đã từ chối!", type="warning"); _nav_pending()
                                                _reject_cb[0] = _cb; reject_dialog.open()
                                            ui.button(icon="close", on_click=_admin_ksv_reject).props("round dense flat").classes("text-red-600 bg-red-50").tooltip("Từ chối KSV")

                                _info("Người duyệt:", leave.get("ksv_approver_name") or "Chưa xác định")

                                if leave.get("ksv_approved_at"):
                                    _info("Ngày duyệt:", leave["ksv_approved_at"][:10])
                                    _info("Ý kiến:", leave.get("ksv_comment") or "→")
                                    ui.label("✓ Đã phê duyệt").classes("text-xs text-green-600 font-semibold mt-1")
                                elif status != "pending_ksv" and leave.get("ksv_approver_id"):
                                    ui.label("(Dữ liệu không ghi ngày duyệt)").classes("text-xs text-gray-400 italic")



                        # Bước 2: Tổng hợp

                        with ui.column().classes("w-full bg-yellow-50 rounded-lg p-3 gap-1 border border-yellow-100"):

                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label("Bước 2 → Phòng Tổng hợp").classes("text-xs font-bold text-yellow-700 uppercase")
                                if _is_admin and status == "pending_tong_hop":
                                    with ui.row().classes("gap-1"):
                                        async def _admin_th_approve(lv=leave, l=lid):
                                            async def _do(_l=l, _lv=lv):
                                                await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",
                                                    {"action": "forward", "gd_approver_id": _lv.get("gd_approver_id"), "comment": None})
                                                ui.notify("Đã xác nhận TH! Tiếp tục duyệt bước GĐ.", type="positive")
                                                updated = await asyncio.to_thread(api.get, f"/api/leaves/{_l}")
                                                if updated: await open_detail(updated)
                                            _ask_confirm("Xác nhận TH", "Xác nhận & chuyển lên Ban lãnh đạo?", _do, "Xác nhận", "bg-green-600")
                                        ui.button(icon="check", on_click=_admin_th_approve).props("round dense flat").classes("text-green-600 bg-green-50").tooltip("Xác nhận TH")
                                        async def _admin_th_reject(l=lid):
                                            async def _cb(reason, _l=l):
                                                await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review", {"action": "reject", "comment": reason})
                                                detail_drawer.hide(); ui.notify("Đã từ chối!", type="warning"); _nav_pending()
                                            _reject_cb[0] = _cb; reject_dialog.open()
                                        ui.button(icon="close", on_click=_admin_th_reject).props("round dense flat").classes("text-red-600 bg-red-50").tooltip("Từ chối TH")

                            _th_name = leave.get("tong_hop_approver_name")
                            _info("Người xử lý:", _th_name or "Chưa xử lý")

                            if leave.get("tong_hop_approved_at"):
                                _info("Ngày:", leave["tong_hop_approved_at"][:10])
                                _info("Ghi chú:", leave.get("tong_hop_comment") or "→")
                                ui.label("✓ Đã xác nhận").classes("text-xs text-green-600 font-semibold mt-1")
                            elif status not in ("pending_ksv", "pending_tong_hop") and _th_name:
                                ui.label("(Dữ liệu không ghi ngày xác nhận)").classes("text-xs text-gray-400 italic")

                            if th_ack_act and api.has_feature("leaves.forward_th"):
                                ui.label("Đơn của Giám đốc đã tự động duyệt — chỉ cần Tổng hợp xác nhận đã biết.").classes("text-xs text-gray-500 italic mt-1")
                                async def _th_ack(l=lid):
                                    try:
                                        await asyncio.to_thread(api.put, f"/api/leaves/{l}/tong-hop-ack", {})
                                        detail_drawer.hide()
                                        ui.notify("Đã xác nhận đã biết đơn của Giám đốc", type="positive")
                                        _nav_pending()
                                    except Exception as e:
                                        _handle_api_error(e)
                                ui.button("Xác nhận đã biết", icon="visibility", on_click=_th_ack).classes("bg-yellow-600 text-white text-xs mt-1")



                        # Bước 3: GĐ

                        with ui.column().classes("w-full bg-blue-50 rounded-lg p-3 gap-1 border border-blue-100"):

                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label("Bước 3 → Giám đốc phê duyệt").classes("text-xs font-bold text-blue-700 uppercase")
                                if _is_admin and status == "pending_gd":
                                    with ui.row().classes("gap-1"):
                                        async def _admin_gd_approve(l=lid):
                                            async def _do(_l=l):
                                                await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review", {"action": "approve"})
                                                detail_drawer.hide(); ui.notify("Đã duyệt GĐ!", type="positive"); _nav_pending()
                                            _ask_confirm("Duyệt bước GĐ", "Xác nhận phê duyệt bước Giám đốc?", _do, "Phê duyệt", "bg-green-600")
                                        ui.button(icon="check", on_click=_admin_gd_approve).props("round dense flat").classes("text-green-600 bg-green-50").tooltip("Phê duyệt GĐ")
                                        async def _admin_gd_reject(l=lid):
                                            async def _cb(reason, _l=l):
                                                await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review", {"action": "reject", "comment": reason})
                                                detail_drawer.hide(); ui.notify("Đã từ chối!", type="warning"); _nav_pending()
                                            _reject_cb[0] = _cb; reject_dialog.open()
                                        ui.button(icon="close", on_click=_admin_gd_reject).props("round dense flat").classes("text-red-600 bg-red-50").tooltip("Từ chối GĐ")

                            _info("Người duyệt:", _gd_display(leave) or "Chưa xác định")

                            if leave.get("gd_approved_at"):
                                _info("Ngày duyệt:", leave["gd_approved_at"][:10])
                                _info("Ý kiến:", leave.get("gd_comment") or "→")
                                ui.label("✓ Đã phê duyệt").classes("text-xs text-green-600 font-semibold mt-1")
                            elif status == "approved":
                                ui.label("(Dữ liệu không ghi ngày duyệt)").classes("text-xs text-gray-400 italic")



                    ui.separator()



                    async def _download(l=lid):

                        try:

                            content = await asyncio.to_thread(api.download, f"/api/leaves/{l}/download")

                            ui.download(content, f"phieu_nghi_phep_{l}.docx")

                        except Exception as e:

                            _handle_api_error(e)



                    with ui.row().classes("gap-2 flex-nowrap mt-4 border-t border-gray-100 pt-4 w-full items-center").style("display:grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));"):

                        ui.button("Tải phiếu", icon="download", on_click=_download).props("outline").classes("text-gray-700 font-bold w-full")




                        # KSV

                        if ksv_act and api.has_feature("leaves.approve_ksv"):

                            def _ksv_approve(l=lid):

                                async def _do(_l=l):

                                    try:

                                        await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review", {"action": "approve"})

                                        detail_drawer.hide()

                                        ui.notify("Phê duyệt KSV thành công!", type="positive", timeout=3000)

                                        _nav_pending()

                                    except Exception as e:

                                        _handle_api_error(e)

                                _ask_confirm("Xác nhận phê duyệt", "Bạn có chắc chắn muốn phê duyệt đơn này?", _do, "Phê duyệt", "bg-green-600")



                            def _ksv_reject_open(l=lid):

                                async def _cb(reason, _l=l):

                                    try:

                                        await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review",

                                            {"action": "reject", "comment": reason})

                                        detail_drawer.hide()

                                        ui.notify("Đã từ chối đơn.", type="warning", timeout=3000)

                                        _nav_pending()

                                    except Exception as e:

                                        _handle_api_error(e)

                                _reject_cb[0] = _cb

                                reject_dialog.open()



                            ui.button("Phê duyệt", icon="check_circle", on_click=_ksv_approve).classes("bg-green-600 text-white font-bold w-full")

                            ui.button("Từ chối", icon="cancel", on_click=_ksv_reject_open).classes("bg-red-600 text-white font-bold w-full")



                        # TH → ẩn khi đơn lý recall request (backend cũng block, nhưng ẩn cho UX)

                        if th_act and not leave.get("recall_reason") and api.has_feature("leaves.forward_th"):

                            def _th_forward_open(lv=leave, l=lid):
                                async def _do_forward(_l=l, _lv=lv):
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",
                                            {"action": "forward",
                                             "gd_approver_id": _lv.get("gd_approver_id"),
                                             "comment": None})
                                        detail_drawer.hide()
                                        ui.notify("Đã xác nhận & chuyển lên Ban lãnh đạo!", type="positive", timeout=3000)
                                        _nav_pending_th()
                                    except Exception as e:
                                        _handle_api_error(e)

                                _ask_confirm(
                                    "Xác nhận phê duyệt",
                                    f"Xác nhận đơn của {lv.get('staff_name','')} và chuyển lên Ban lãnh đạo?",
                                    _do_forward,
                                    ok_label="Xác nhận",
                                    ok_cls="bg-green-600"
                                )



                            def _th_reject_open(l=lid):

                                async def _cb(reason, _l=l):

                                    try:

                                        await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",

                                            {"action": "reject", "comment": reason})

                                        detail_drawer.hide()

                                        ui.notify("Đã từ chối đơn.", type="warning", timeout=3000)

                                        _nav_pending_th()

                                    except Exception as e:

                                        _handle_api_error(e)

                                _reject_cb[0] = _cb

                                reject_dialog.open()



                            ui.button("Phê duyệt", icon="check_circle",
                                      on_click=lambda lv=leave, l=lid: _th_forward_open(lv, l)).classes("bg-green-600 text-white font-bold w-full")

                            ui.button("Từ chối", icon="cancel", on_click=_th_reject_open).classes("bg-red-600 text-white font-bold w-full")



                        # GĐ

                        if gd_act and api.has_feature("leaves.approve_gd"):

                            def _gd_approve(l=lid):

                                async def _do(_l=l):

                                    try:

                                        await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review", {"action": "approve"})

                                        detail_drawer.hide()

                                        ui.notify("Phê duyệt Ban lãnh đạo thành công!", type="positive", timeout=3000)

                                        _nav_pending()

                                    except Exception as e:

                                        _handle_api_error(e)

                                _ask_confirm("Xác nhận phê duyệt", "Bạn có chắc chắn muốn phê duyệt đơn này?", _do, "Phê duyệt", "bg-green-600")



                            def _gd_reject_open(l=lid):

                                async def _cb(reason, _l=l):

                                    try:

                                        await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review",

                                            {"action": "reject", "comment": reason})

                                        detail_drawer.hide()

                                        ui.notify("Đã từ chối đơn.", type="warning", timeout=3000)

                                        _nav_pending()

                                    except Exception as e:

                                        _handle_api_error(e)

                                _reject_cb[0] = _cb

                                reject_dialog.open()



                            ui.button("Phê duyệt", icon="check_circle", on_click=_gd_approve).classes("bg-green-600 text-white font-bold w-full")

                            ui.button("Từ chối", icon="cancel", on_click=_gd_reject_open).classes("bg-red-600 text-white font-bold w-full")



                        # Resubmit

                        if is_owner and status == "rejected" and api.has_feature("leaves.resubmit"):

                            async def _open_resubmit(lv=leave):

                                _spread = lv.get("spread_dates")

                                r_dates.value  = _spread if _spread else [(lv.get("start_date") or "")[:10]]

                                r_type.value   = lv.get("leave_type", "annual")

                                r_reason.value = lv.get("reason") or ""

                                _rsub_id[0]    = lv["id"]

                                if r_approver:
                                    r_approver.value = lv.get("ksv_approver_id")

                                # Load danh sách GĐ/PGĐ mỗi lần mở dialog
                                try:
                                    lst = await asyncio.to_thread(api.get, "/api/leaves/gd-list")
                                    r_gd_select.options = {
                                        s["id"]: f"{s['full_name']} ({s.get('role_label', '')})"
                                        for s in (lst or [])
                                    }
                                    r_gd_select.update()
                                except Exception:
                                    pass

                                r_gd_select.value = lv.get("gd_approver_id")

                                resubmit_dialog.open()



                            ui.button("Sửa & Nộp lại", icon="refresh", on_click=_open_resubmit).classes("bg-orange-500 text-white text-sm")

                        # Hủy đơn bị từ chối (không resubmit nữa)
                        if is_owner and status == "rejected":
                            async def _cancel_rejected(l=lid):
                                async def _do_cancel(_l=l):
                                    try:
                                        await asyncio.to_thread(api.patch, f"/api/leaves/{_l}/cancel", {})
                                        detail_drawer.hide()
                                        ui.notify("Đã hủy đơn thành công", type="positive")
                                        _nav_pending()
                                    except Exception as e:
                                        _handle_api_error(e)
                                _ask_confirm("Xác nhận hủy đơn",
                                             "Bạn có chắc muốn hủy đơn nghỉ này không?",
                                             _do_cancel,
                                             ok_label="Hủy đơn",
                                             ok_cls="bg-gray-600")
                            ui.button("Hủy đơn", icon="delete_forever", on_click=_cancel_rejected).classes("bg-gray-500 text-white text-sm")

                        # Hủy
                        # GĐ có toàn quyền huỷ đơn của chính mình bất cứ lúc nào — luôn hiện nút
                        # dù feature "leaves.cancel" chưa được cấp qua cấu hình phân quyền.
                        if (is_owner or user_role == "admin") and status not in ("cancelled", "rejected") \
                                and (api.has_feature("leaves.cancel") or (is_owner and user_role == "giam_doc")):

                            def _cancel_open(l=lid, cur_status=status):
                                async def _do_cancel(_l=l, _st=cur_status):
                                    try:
                                        await asyncio.to_thread(api.patch, f"/api/leaves/{_l}/cancel", {})
                                        detail_drawer.hide()
                                        ui.notify("Đã hủy đơn thành công", type="warning")
                                        if _st == "pending_tong_hop":
                                            _nav_pending_th()
                                        else:
                                            _nav_pending()
                                    except Exception as e:
                                        _handle_api_error(e)
                                _ask_confirm("Xác nhận hủy đơn",
                                             "Bạn có chắc muốn hủy đơn nghỉ này không?",
                                             _do_cancel, ok_label="Hủy đơn", ok_cls="bg-gray-600")

                            ui.button("Hủy đơn", icon="cancel", on_click=_cancel_open).classes("bg-gray-200 text-gray-700 text-sm")



                        # Rút đơn (recall) → chủ nhân yêu cầu rút đơn đã duyệt.
                        # GĐ đã có nút "Hủy đơn" tự xử lý ngay, không cần thêm bước này.

                        has_recall = api.has_feature("leaves.recall")

                        if is_owner and status == "approved" and not leave.get("recall_reason") \
                                and has_recall and user_role != "giam_doc":

                            def _open_recall(l=lid):

                                async def _cb(reason, _l=l):

                                    try:

                                        await asyncio.to_thread(api.post, f"/api/leaves/{_l}/recall", {"reason": reason})

                                        detail_drawer.hide()

                                        ui.notify("Đã gửi yêu cầu rút → chờ Phòng Tổng hợp xác nhận", type="info")

                                        ui.navigate.to("/leaves")

                                    except Exception as e:

                                        _handle_api_error(e)

                                _reject_cb[0] = _cb

                                reject_dialog.open()



                            ui.button("Rút đơn", icon="undo", on_click=_open_recall).classes("bg-orange-100 text-orange-800 text-sm")



                        # Xác nhận rút đơn → TH xác nhận khi đơn ở pending_tong_hop và recall

                        if th_act and leave.get("recall_reason") and has_recall:

                            async def _confirm_recall(l=lid):

                                try:

                                    await asyncio.to_thread(api.put, f"/api/leaves/{l}/recall-approve")

                                    detail_drawer.hide()

                                    ui.notify("Đã xác nhận rút đơn", type="positive")

                                    ui.navigate.to("/leaves")

                                except Exception as e:

                                    _handle_api_error(e)



                            ui.button("Xác nhận rút đơn", icon="undo", on_click=_confirm_recall).classes("bg-orange-700 text-white text-sm")



            detail_drawer.show()



        # ── Hôm mở dialog lịch sử ────────────────────────────────────────────

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

        _sel: set = set()         # cho approve/reject

        _export_sel: set = set()  # cho xuất Excel leaves (dashboard / khai báo hộ)

        _quota_sel:  set = set()  # cho xuất Excel hạn mức phép

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

            if not ids:

                ui.notify("Vui lòng tick chọn đơn cần phê duyệt", type="warning")

                return



            async def _do_bulk(_ids=ids):

                lv_map   = {lv["id"]: lv for lv in pending_leaves}

                th_ids   = [i for i in _ids if lv_map.get(i, {}).get("status") == "pending_tong_hop"]

                other_ids = [i for i in _ids if i not in th_ids]



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
                    # TH bulk: dùng gd_approver_id sẵn có trong từng đơn
                    for i in th_ids:
                        lv_data = lv_map.get(i, {})
                        try:
                            await asyncio.to_thread(api.post, f"/api/leaves/{i}/tong-hop-review",
                                {"action": "forward",
                                 "gd_approver_id": lv_data.get("gd_approver_id"),
                                 "comment": None})
                        except Exception:
                            pass

                _sel.clear()
                ui.notify(f"Đã phê duyệt {len(_ids)} đơn thành công!", type="positive", timeout=3000)
                _nav_pending_th() if th_ids else _nav_pending()



            _ask_confirm("Xác nhận phê duyệt",

                         f"Bạn có chắc chắn muốn phê duyệt {len(ids)} đơn đã chọn?",

                         _do_bulk, "Phê duyệt", "bg-green-600")



        async def _bulk_reject_open():

            ids = list(_sel)

            if not ids:

                ui.notify("Vui lòng tick chọn đơn cần từ chối", type="warning")

                return

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

                ui.notify(f"Đã từ chối {len(ids)} đơn.", type="warning", timeout=3000)

                # Có th_ids → từ TH tab, không → từ KSV/GĐ tab
                th_ids_rej = [i for i in ids if lv_map.get(i, {}).get("status") == "pending_tong_hop"]
                if th_ids_rej:
                    _nav_pending_th()
                else:
                    _nav_pending()

            _reject_cb[0] = _cb

            reject_dialog.open()



        # ── Toolbar ───────────────────────────────────────────────────────────

        _has_any_approve = (
            user_role not in ("chuyen_vien",)
            and any(api.has_feature(f) for f in (
                "leaves.approve_ksv", "leaves.forward_th", "leaves.approve_gd"
            ))
        )

        with ui.row().classes("gap-2 mb-4 items-center flex-wrap"):

            create_btn = ui.button("Tạo đơn", icon="add", on_click=_c_open).classes("bg-red-700 text-white text-base")

            # admin không tham gia quy trình nghỉ phép (backend chặn 403) — ẩn nút dù has_feature() luôn True cho admin
            create_btn.set_visibility(api.has_feature("leaves.create") and user_role != "admin")

            ab = ui.button("Phê duyệt", icon="check_circle",

                           on_click=lambda: asyncio.ensure_future(_bulk_approve())).classes(

                "bg-green-600 text-white")

            ab.set_visibility(_has_any_approve)

            rb = ui.button("Từ chối", icon="cancel",

                           on_click=lambda: asyncio.ensure_future(_bulk_reject_open())).classes(

                "bg-red-600 text-white")

            rb.set_visibility(_has_any_approve)



            def _make_fname(base: str, from_val: str = "", to_val: str = "") -> str:

                """T→n file: base + khoảng lĐọc (nếu c→) + ngày xuất hôm nay."""

                import datetime as _dt_fname

                today = _dt_fname.date.today().strftime("%d%m%Y")

                f = (from_val or "").strip().replace("/", "")

                t = (to_val   or "").strip().replace("/", "")

                if f and t:

                    return f"{base}_{f}-{t}_xuat{today}.xlsx"

                elif f:

                    return f"{base}_tu{f}_xuat{today}.xlsx"

                elif t:

                    return f"{base}_den{t}_xuat{today}.xlsx"

                return f"{base}_xuat{today}.xlsx"



            def _tab_match(tab, cur):

                """So s→nh tab đang active với tab object.

                NiceGUI trả string (props['name']) từ leave_tabs.value."""

                if tab is None:

                    return False

                if cur is tab:

                    return True

                # NiceGUI lưu label/name trong _props

                props = getattr(tab, "_props", {})

                tab_name = props.get("name") or props.get("label") or getattr(tab, "text", None)

                return cur == tab_name



            async def _export_leaves():

                try:

                    cur = leave_tabs.value

                    import datetime as _dtt

                    today = _dtt.date.today().strftime("%d%m%Y")

                    # ── Hạn mức phép ──────────────────────────────────────────

                    if _tab_match(t_quota, cur):

                        yr  = q_year_sel.value

                        ids_str = ",".join(str(i) for i in sorted(_quota_sel)) if _quota_sel else ""

                        fname = (f"han_muc_phep_{yr}_da_chon_xuat{today}.xlsx"

                                 if ids_str else f"han_muc_phep_{yr}_xuat{today}.xlsx")

                        params = {"ids": ids_str} if ids_str else {}

                        content = await asyncio.to_thread(

                            api.download, f"/api/leaves/quotas/{yr}/export", params=params

                        )

                        ui.download(content, fname)

                        return

                    # ── C→c tab nghỉ phép ──────────────────────────────────────

                    # Tab Báo cáo năm → xuất tất cả đơn trong năm
                    if t_stats and _tab_match(t_stats, cur):
                        from datetime import date as _d_stats
                        _yr_stats = _d_stats.today().year
                        fname = f"bao_cao_tat_ca_don_nghi_phep_{_yr_stats}.xlsx"
                        content = await asyncio.to_thread(
                            api.download, "/api/leaves/export/annual",
                            params={"year": _yr_stats}
                        )
                        ui.download(content, fname)
                        return

                    # Dùng _export_sel (từ bảng export_sel) hoặc _sel (từ bảng phê duyệt) nếu có tick
                    # Không áp dụng _sel nếu đang ở tab không liên quan đến đơn phép
                    _active_export_ids = _export_sel if _export_sel else (_sel if _sel else set())

                    if _active_export_ids:

                        ids_str = ",".join(str(i) for i in sorted(_active_export_ids))

                        if _tab_match(t_direct, cur):

                            fv, tv = getattr(_df_from, "value", ""), getattr(_df_to, "value", "")

                            fname = _make_fname("don_khai_bao_ho_da_chon", fv, tv)

                        else:

                            fv, tv = ((_f_from.value or "") if _f_from else ""), ((_f_to.value or "") if _f_to else "")

                            fname = _make_fname("don_nghi_phep_da_chon", fv, tv)

                        content = await asyncio.to_thread(

                            api.download, "/api/leaves/export",

                            params={"scope": "all", "ids": ids_str},

                        )

                        ui.download(content, fname)

                        return

                    # Không có tick → xuất theo tab + khoảng ngày filter

                    if t_pending_th and _tab_match(t_pending_th, cur):
                        # Tab "Chờ xác nhận TT": chỉ xuất pending_tong_hop
                        th_ids_str = ",".join(str(lv["id"]) for lv in _pending_th_list)
                        fname = _make_fname("don_cho_xac_nhan_tt")
                        content = await asyncio.to_thread(
                            api.download, "/api/leaves/export",
                            params={"scope": "all", "ids": th_ids_str},
                        )
                        ui.download(content, fname)
                        return

                    elif _tab_match(t_pending, cur):

                        scp  = "pending"

                        fname = _make_fname("don_cho_duyet")

                    elif _tab_match(t_dept, cur):

                        scp  = "dept"

                        fname = _make_fname("don_phong_toi")

                    elif _tab_match(t_mine, cur):

                        scp  = "mine"

                        fname = _make_fname("don_cua_toi")

                    elif _tab_match(t_direct, cur):

                        scp  = "declared"

                        fv, tv = getattr(_df_from, "value", ""), getattr(_df_to, "value", "")

                        fname = _make_fname("don_khai_bao_ho", fv, tv)

                    elif _tab_match(t_dashboard, cur):

                        scp  = "all" if can_all else "mine"

                        fv, tv = ((_f_from.value or "") if _f_from else ""), ((_f_to.value or "") if _f_to else "")

                        fname = _make_fname("tat_ca_don_nghi_phep", fv, tv)

                    else:

                        scp  = "all" if can_all else "mine"

                        fname = _make_fname("danh_sach_nghi_phep")

                    content = await asyncio.to_thread(

                        api.download, "/api/leaves/export", params={"scope": scp},

                    )

                    ui.download(content, fname)

                except Exception as e:

                    _handle_api_error(e)



            ui.button("Xuất Excel", icon="download",

                      on_click=_export_leaves).classes("bg-blue-700 text-white").tooltip("Xuất Excel theo tab đang xem")



        # ── H→m vẽ bảng ──────────────────────────────────────────────────────

        _PAGE_SIZE = 50

        def _draw_table_paged(leaves: list, show_name: bool = False, show_checkbox: bool = True,
                              export_sel: set = None):
            """Wrapper thêm pagination 50 dòng/trang cho _draw_table."""
            if not leaves:
                ui.label("Không có đơn nghỉ phép nào.").classes("text-gray-400 text-sm mt-4")
                return
            total = len(leaves)
            total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
            state = {"page": 1}
            body = ui.column().classes("w-full gap-0")

            def _render(p=None):
                if p is not None:
                    state["page"] = max(1, min(p, total_pages))
                pg = state["page"]
                body.clear()
                with body:
                    _draw_table(
                        leaves[(pg-1)*_PAGE_SIZE : pg*_PAGE_SIZE],
                        show_name=show_name, show_checkbox=show_checkbox, export_sel=export_sel,
                        _row_offset=(pg-1)*_PAGE_SIZE
                    )

            _render()

            if True:
                with ui.row().classes("w-full justify-center items-center gap-2 mt-3"):
                    ui.button("«", on_click=lambda: _render(1)).props("flat dense").classes("text-gray-600")
                    ui.button("‹", on_click=lambda: _render(state["page"]-1)).props("flat dense").classes("text-gray-600")
                    _pg_lbl = ui.label(f"Trang {state['page']} / {total_pages}   ({total} đơn)").classes("text-xs text-gray-500 px-2")
                    ui.button("›", on_click=lambda: (_render(state["page"]+1), _pg_lbl.set_text(f"Trang {state['page']} / {total_pages}   ({total} đơn)"))).props("flat dense").classes("text-gray-600")
                    ui.button("»", on_click=lambda: _render(total_pages)).props("flat dense").classes("text-gray-600")
                    def _go_page(e):
                        try:
                            _render(int(e.value))
                            _pg_lbl.set_text(f"Trang {state['page']} / {total_pages}   ({total} đơn)")
                        except Exception:
                            pass
                    ui.input("Đến trang", on_change=_go_page).props("dense outlined").classes("w-20 text-xs")

        def _draw_table(leaves: list, show_name: bool = False, show_checkbox: bool = True,
                        export_sel: set = None, _row_offset: int = 0):

            if not leaves:

                ui.label("Không có đơn nghỉ phép nào.").classes("text-gray-400 text-sm mt-4")

                return

            # CSS border cho cột khi không có checkbox (dashboard view)

            _col_cls  = "text-xs shrink-0 border-r border-gray-400 pr-2 mr-1"

            _hdr_cls  = "font-semibold text-red-800 text-xs shrink-0 border-r border-red-400 pr-2 mr-1"

            with ui.column().classes("w-full gap-0 border-2 border-gray-400 rounded"):

                # Header

                with ui.row().classes("w-full bg-red-50 border-b-2 border-red-400 px-3 py-2 items-center gap-0"):

                    if show_checkbox or export_sel is not None:
                        _all_ids = [lv["id"] for lv in leaves]
                        _row_cks: list = []  # references tới từng checkbox hàng

                        def _select_all(e, _row_refs=_row_cks, _ids=_all_ids):
                            for ck in _row_refs:
                                ck.set_value(e.value)
                            if e.value:
                                _sel.update(_ids)
                            else:
                                for i in _ids: _sel.discard(i)
                            _upd_btns()

                        def _select_all_exp(e, _row_refs=_row_cks, _ids=_all_ids, _s=export_sel):
                            for ck in _row_refs:
                                ck.set_value(e.value)
                            if e.value:
                                _s.update(_ids)
                            else:
                                for i in _ids: _s.discard(i)

                        if show_checkbox:
                            ui.checkbox(value=False, on_change=_select_all).props("dense").classes("w-6 shrink-0 mr-2").tooltip("Chọn / Bỏ chọn tất cả")
                        elif export_sel is not None:
                            ui.checkbox(value=False, on_change=_select_all_exp).props("dense").classes("w-6 shrink-0 mr-2").tooltip("Chọn / Bỏ chọn tất cả")

                    ui.label("STT").classes(f"{_hdr_cls} w-8 text-center")

                    ui.label("Ngày tạo").classes(f"{_hdr_cls} w-20")

                    ui.label("Loại").classes(f"{_hdr_cls} w-28")

                    ui.label("Trạng thái").classes(f"{_hdr_cls} w-28")

                    ui.label("Loại đơn").classes(f"{_hdr_cls} w-24")

                    if show_name:

                        ui.label("Họ và tên").classes(f"{_hdr_cls} w-28")

                    ui.label("Phòng").classes(f"{_hdr_cls} w-32")

                    ui.label("Ngày nghỉ").classes(f"{_hdr_cls} w-36")

                    ui.label("KSV xác nhận").classes(f"{_hdr_cls} w-28")

                    ui.label("Phòng TH xác nhận").classes(f"{_hdr_cls} w-32")

                    ui.label("Ban lãnh đạo xác nhận").classes("font-semibold text-red-800 text-xs flex-1")

                    ui.label("").classes("w-16 shrink-0")



                for _row_idx, lv in enumerate(leaves, _row_offset + 1):

                    sg_lbl, sg_cls = _STATUS_GROUP.get(lv["status"], (lv["status"], "bg-gray-100 text-gray-500"))

                    # Highlight đỏ nhạt nếu dòng này cần user hiện tại xử lý
                    _needs_action = (
                        (lv.get("status") == "rejected" and lv.get("staff_id") == user_id)
                        or (lv.get("status") == "pending_ksv"      and user_role in ("truong_phong", "pho_phong", "hau_kiem_vien") and lv.get("ksv_approver_id") == user_id)
                        or (lv.get("status") == "pending_tong_hop" and user_role not in ("chuyen_vien",) and lv.get("tong_hop_approver_id") == user_id)
                        or (lv.get("status") == "pending_tong_hop" and user_role not in ("chuyen_vien",) and not lv.get("tong_hop_approver_id"))
                        or (lv.get("status") == "pending_gd"      and user_role in ("giam_doc", "pho_giam_doc") and lv.get("gd_approver_id") == user_id)
                    )
                    _row_bg = "bg-red-50 border-red-300" if _needs_action else "bg-white border-gray-300"

                    with ui.row().classes(f"w-full {_row_bg} border-b border-gray-300 px-3 py-1.5 items-center gap-0 hover:bg-red-100"):

                        if show_checkbox:

                            def _on_ck(e, l=lv["id"]):

                                _sel.add(l) if e.value else _sel.discard(l)

                                _upd_btns()

                            _ck = ui.checkbox(value=False, on_change=_on_ck).props("dense").classes("w-6 shrink-0 mr-2")
                            _row_cks.append(_ck)

                        elif export_sel is not None:

                            def _on_exp_ck(e, l=lv["id"], _s=export_sel):

                                _s.add(l) if e.value else _s.discard(l)

                            _ck = ui.checkbox(value=False, on_change=_on_exp_ck).props("dense").classes("w-6 shrink-0 mr-2")
                            _row_cks.append(_ck)



                        ui.label(str(_row_idx)).classes("text-xs w-8 shrink-0 text-center text-gray-400 border-r border-gray-400 pr-2 mr-1")

                        ui.label((lv.get("created_at") or "")[:10]).classes("text-xs w-20 shrink-0 border-r border-gray-400 pr-2 mr-1")

                        ui.label(_LEAVE_TYPE.get(lv.get("leave_type",""), lv.get("leave_type",""))).classes("text-xs w-28 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                        with ui.column().classes("w-28 shrink-0 gap-0.5 border-r border-gray-400 pr-2 mr-1"):

                            ui.label(sg_lbl).classes(f"text-xs px-1.5 py-0.5 rounded {sg_cls} text-center")

                            if lv.get("rejected_step"):

                                _rs = lv["rejected_step"]

                                _rs_cls = {"KSV": "bg-orange-100 text-orange-700",

                                           "TH":  "bg-yellow-100 text-yellow-700",

                                           "GĐ":  "bg-blue-100 text-blue-700"}.get(_rs, "bg-gray-100 text-gray-600")

                                ui.label(f"Từ chối tại {_rs}").classes(f"text-[10px] px-1 py-0 rounded {_rs_cls} text-center")

                        # Cột Loại đơn
                        with ui.column().classes("w-24 shrink-0 gap-0.5 border-r border-gray-400 pr-2 mr-1 items-center justify-center"):

                            if lv.get("is_direct"):

                                ui.label("Khai báo hộ").classes("text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 text-center font-semibold")

                            elif lv.get("is_resubmitted"):

                                ui.label("Gửi lại").classes("text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 text-center font-semibold")

                            else:

                                ui.label("—").classes("text-xs text-gray-300 text-center")

                        if show_name:

                            ui.label(lv.get("staff_name", "")).classes("text-xs w-28 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                        ui.label(lv.get("department_name") or "→").classes("text-xs w-32 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                        ui.label(_fmt_leave_dates(lv.get("start_date",""), lv.get("end_date",""), lv.get("spread_dates"))).classes("text-xs w-36 shrink-0 border-r border-gray-400 pr-2 mr-1")

                        ui.label(lv.get("ksv_approver_name") or "→").classes("text-xs w-28 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                        ui.label(lv.get("tong_hop_approver_name") or "→").classes("text-xs w-32 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                        ui.label(_gd_display(lv) or "→").classes("text-xs flex-1 truncate")

                        with ui.row().classes("w-16 gap-0.5 justify-end shrink-0"):

                            ui.button(icon="info", on_click=lambda l=lv: asyncio.ensure_future(open_detail(l))).props(

                                "flat round dense size=sm").classes("text-blue-600").tooltip("Chi tiết")

                            ui.button(icon="history", on_click=lambda l=lv: asyncio.ensure_future(open_history(l))).props(

                                "flat round dense size=sm").classes("text-gray-500").tooltip("Lịch sử")



        # ── Tabs ──────────────────────────────────────────────────────────────

        with ui.tabs().classes("mb-4") as leave_tabs:

            _has_dash  = api.has_feature("leaves.dashboard")

            t_dashboard = ui.tab("Dashboard") if _has_dash else None

            # Nếu có Dashboard → gộp "Của tôi" và "Phòng tôi" vào Dashboard

            t_mine    = ui.tab("Của tôi") if not _has_dash else None

            _can_approve = user_role not in ("chuyen_vien",)

            # Tách pending thành 2 danh sách: duyệt phòng (KSV) và xác nhận TT (TH)
            # Đơn của GĐ đã tự động approved cũng hiện ở đây để TH "xác nhận đã biết"
            # (thông báo, không phải điều kiện duyệt).
            _pending_ksv_list = [lv for lv in pending_leaves if lv.get("status") == "pending_ksv"]
            _pending_th_list  = [lv for lv in pending_leaves if lv.get("status") == "pending_tong_hop"
                                 or (lv.get("status") == "approved" and lv.get("staff_role") == "giam_doc"
                                     and not lv.get("tong_hop_approver_id"))]
            _is_dual_role     = api.has_feature("leaves.forward_th") and user_role in ("truong_phong", "pho_phong", "hau_kiem_vien")

            if _can_approve:
                if _is_dual_role:
                    # PP/TP Tổng hợp: 2 tab riêng
                    t_pending    = ui.tab(f"Chờ duyệt ({len(_pending_ksv_list)})") if _pending_ksv_list or True else None
                    t_pending_th = ui.tab(f"Chờ xác nhận TT ({len(_pending_th_list)})")
                else:
                    t_pending    = ui.tab(f"Chờ duyệt ({len(pending_leaves)})")
                    t_pending_th = None
            else:
                t_pending    = None
                t_pending_th = None

            t_dept    = ui.tab(f"Phòng tôi ({len(dept_leaves)})") if (can_dept and not _has_dash) else None

            t_declared = None  # gộp vào Dashboard

            t_cal     = ui.tab("Lịch nghỉ phép")
            if not api.has_feature("leaves.schedule"):
                t_cal.set_visibility(False)

            t_deleg   = ui.tab("Ủy quyền GĐ") if can_delegation else None

            t_holiday = ui.tab("Ngày lễ") if can_delegation else None

            t_quota   = ui.tab("Hạn mức phép") if api.has_feature("leaves.quota_admin") else None

            t_stats   = ui.tab("Báo cáo năm") if api.has_feature("leaves.stats_export") else None

            t_direct  = ui.tab("Khai báo hộ") if api.has_feature("leaves.declare_direct") else None



        _goto = app.storage.user.pop("_leaves_goto", None)

        if _goto == "khai_bao_ho" and t_direct:
            _default_tab = t_direct
        elif _goto == "pending" and t_pending:
            _default_tab = t_pending
        elif _goto == "pending_th" and t_pending_th:
            _default_tab = t_pending_th
        else:
            _default_tab = t_dashboard if t_dashboard else (t_mine or t_pending or t_cal)

        def _nav_pending():
            app.storage.user["_leaves_goto"] = "pending"
            ui.navigate.to("/leaves")

        def _nav_pending_th():
            # Nếu user có tab pending_th riêng thì về đó, không thì về pending
            if t_pending_th is not None:
                app.storage.user["_leaves_goto"] = "pending_th"
            else:
                app.storage.user["_leaves_goto"] = "pending"
            ui.navigate.to("/leaves")

        def _draw_pending_with_filter(src: list):
            """Bộ lọc inline cho tab Chờ duyệt / Chờ xác nhận TT."""
            from datetime import date as _d_cls
            _dept_opts = {"": "Tất cả phòng"}
            for lv in src:
                dn = lv.get("department_name") or lv.get("dept_name") or ""
                if dn and dn not in _dept_opts:
                    _dept_opts[dn] = dn

            with ui.card().classes("w-full p-3 mb-3 border border-gray-200 rounded-lg bg-gray-50"):
                with ui.row().classes("gap-3 flex-wrap items-end"):
                    _pf_name   = ui.input("Tìm theo tên").props("dense clearable outlined").classes("w-40")
                    _pf_dept   = ui.select(_dept_opts, value="", label="Phòng").props("dense outlined").classes("w-36") if len(_dept_opts) > 1 else None
                    with ui.input("Ngày nghỉ từ").props("dense clearable readonly outlined").classes("w-32") as _pf_from:
                        with _pf_from.add_slot("append"):
                            ui.icon("event").classes("cursor-pointer").on("click", lambda: _pf_cal_from.open())
                        with ui.menu() as _pf_cal_from:
                            ui.date(mask="DD/MM/YYYY").props(f'{_OPT_ALL} first-day-of-week="1"').bind_value(_pf_from)
                    with ui.input("đến ngày").props("dense clearable readonly outlined").classes("w-32") as _pf_to:
                        with _pf_to.add_slot("append"):
                            ui.icon("event").classes("cursor-pointer").on("click", lambda: _pf_cal_to.open())
                        with ui.menu() as _pf_cal_to:
                            ui.date(mask="DD/MM/YYYY").props(f'{_OPT_ALL} first-day-of-week="1"').bind_value(_pf_to)
                    # Buttons cùng hàng
                    _pf_search_btn = ui.button("Tìm kiếm", icon="search").classes("bg-red-700 text-white")
                    _pf_reset_btn  = ui.button("Xóa lọc", icon="clear").props("flat").classes("text-gray-500")

            _pf_body = ui.column().classes("w-full gap-0")

            def _pf_parse(s):
                if not s: return None
                try:
                    p = s.split("/")
                    return _d_cls(int(p[2]), int(p[1]), int(p[0])) if "/" in s else _d_cls.fromisoformat(s[:10])
                except Exception: return None

            def _pf_apply():
                nq = (_pf_name.value or "").strip().lower()
                dq = (_pf_dept.value or "") if _pf_dept else ""
                fd = _pf_parse(_pf_from.value)
                td = _pf_parse(_pf_to.value)
                filtered = []
                for lv in src:
                    if nq and nq not in (lv.get("staff_name") or "").lower(): continue
                    if dq and (lv.get("department_name") or lv.get("dept_name") or "") != dq: continue
                    if fd or td:
                        s = _pf_parse(lv.get("start_date", ""))
                        e = _pf_parse(lv.get("end_date", ""))
                        if s and e:
                            if fd and e < fd: continue
                            if td and s > td: continue
                    filtered.append(lv)
                _pf_body.clear()
                with _pf_body:
                    _draw_table_paged(filtered, show_name=True)

            def _pf_reset():
                _pf_name.value = ""
                if _pf_dept: _pf_dept.value = ""
                _pf_from.value = _pf_to.value = ""
                _pf_body.clear()
                with _pf_body:
                    _draw_table_paged(src, show_name=True)

            _pf_search_btn.on("click", lambda: _pf_apply())
            _pf_reset_btn.on("click", lambda: _pf_reset())
            _pf_name.on("keydown.enter", lambda _: _pf_apply())

            with _pf_body:
                _draw_table_paged(src, show_name=True)

        with ui.tab_panels(leave_tabs, value=_default_tab).classes("w-full"):

            if t_dashboard:

                with ui.tab_panel(t_dashboard):

                    _db_area = ui.column().classes("w-full gap-4")



                    async def _load_dashboard():

                        _db_area.clear()

                        _yr = _dt_mod.date.today().year

                        try:

                            data = await asyncio.to_thread(

                                api.get, "/api/leaves/stats/leader-dashboard", {"year": _yr}

                            )

                        except Exception as e:

                            if _handle_api_error(e):

                                return

                            with _db_area:

                                ui.label("Không thể tải dashboard.").classes("text-red-500 text-sm")

                            return

                        data = data if isinstance(data, dict) else {}

                        by_status = data.get("by_status", {})

                        pending_d = data.get("pending", [])

                        top_d     = data.get("top_staff", [])



                        with _db_area:

                            # Thẻ tổng quan

                            with ui.row().classes("gap-3 flex-wrap"):

                                _cards = [

                                    ("Chờ KSV", by_status.get("pending_ksv", 0), "bg-orange-50 border-orange-200 text-orange-700"),

                                    ("Chờ Tổng hợp", by_status.get("pending_tong_hop", 0), "bg-yellow-50 border-yellow-200 text-yellow-700"),

                                    ("Chờ GĐ", by_status.get("pending_gd", 0), "bg-blue-50 border-blue-200 text-blue-700"),

                                    ("Đã duyệt", by_status.get("approved", 0), "bg-green-50 border-green-200 text-green-700"),

                                    ("Khai báo hộ", by_status.get("direct", 0), "bg-purple-50 border-purple-200 text-purple-700"),

                                ]

                                for lbl, cnt, cls in _cards:

                                    with ui.card().classes(f"border p-4 rounded-xl min-w-36 {cls}"):

                                        ui.label(lbl).classes("text-xs font-medium")

                                        ui.label(str(cnt)).classes("text-2xl font-bold mt-1")



                            # Đơn đang ch??

                            pass  # bỏ Đơn đang chờ duyệt (đã có trong module Chờ duyệt)



                            # Top nghỉ nhiều

                            pass  # bỏ Top nghỉ nhiều



                    await _load_dashboard()



                    if can_all:

                        ui.separator().classes("my-4")



                        # ── Filter controls ───────────────────────────────────

                        _all_depts = sorted({lv.get("department_name") or "" for lv in all_leaves if lv.get("department_name")})

                        _status_opts = {"": "Tất cả trạng thái", **{k: v[0] for k, v in _LEAVE_STATUS.items()}}

                        _type_opts   = {"": "Tất cả loại", **_LEAVE_TYPE}

                        _dept_opts   = {"": "Tất cả phòng", **{d: d for d in _all_depts}}



                        with ui.card().classes("w-full p-4 mb-3 border-2 border-red-800 rounded-lg"):

                            ui.label("Bộ lọc tìm kiếm").classes("text-xs font-bold text-red-800 uppercase mb-2")

                            with ui.row().classes("gap-3 flex-wrap items-end"):

                                _f_name   = ui.input("Tìm theo tên").classes("w-40").props("dense clearable")

                                _f_status = ui.select(_status_opts, value="", label="Trạng thái").classes("w-40").props("dense")

                                _f_type   = ui.select(_type_opts, value="", label="Loại nghỉ").classes("w-36").props("dense")

                                _f_dept   = ui.select(_dept_opts, value="", label="Phòng").classes("w-40").props("dense")

                                _f_ltype  = ui.select({
                                    "": "Tất cả loại đơn",
                                    "direct": "Khai báo hộ",
                                    "resubmit": "Gửi lại",
                                    "normal": "Thường",
                                }, value="", label="Loại đơn").classes("w-36").props("dense")

                                with ui.input("Ngày nghỉ từ").classes("w-36").props("dense clearable readonly") as _f_from:

                                    with _f_from.add_slot("append"):

                                        ui.icon("event").classes("cursor-pointer").on("click", lambda: _cal_from.open())

                                    with ui.menu() as _cal_from:

                                        ui.date(mask="DD/MM/YYYY").props(f'{_OPT_ALL} first-day-of-week="1"').bind_value(_f_from)

                                with ui.input("đến ngày").classes("w-36").props("dense clearable readonly") as _f_to:

                                    with _f_to.add_slot("append"):

                                        ui.icon("event").classes("cursor-pointer").on("click", lambda: _cal_to.open())

                                    with ui.menu() as _cal_to:

                                        ui.date(mask="DD/MM/YYYY").props(f'{_OPT_ALL} first-day-of-week="1"').bind_value(_f_to)

                            with ui.row().classes("gap-3 mt-2 items-center flex-wrap"):

                                _f_count  = ui.label("").classes("text-sm font-medium text-red-800 flex-1")

                                _f_mine_state = {"active": False}

                                _f_mine_btn = ui.button("👤 Đơn của tôi", icon="person",

                                    on_click=lambda: _toggle_mine()).props("outline").classes("text-red-700 border-red-400")

                                ui.button("Tìm kiếm", icon="search",

                                          on_click=lambda: _apply_filter()).classes("bg-red-700 text-white")

                                ui.button("Xóa lọc", icon="clear",

                                          on_click=lambda: _reset_filter()).props("flat").classes("text-gray-500")



                        def _toggle_mine():

                            _f_mine_state["active"] = not _f_mine_state["active"]

                            if _f_mine_state["active"]:

                                _f_mine_btn.style("background:#8B0000; color:white; border-color:#8B0000")

                            else:

                                _f_mine_btn.style("background:transparent; color:#b91c1c; border-color:#fca5a5")

                            _apply_filter()



                        _all_container = ui.column().classes("w-full gap-0")



                        def _parse_date(s):

                            """dd/mm/yyyy hoặc yyyy-mm-dd → date object, None nếu lỗi."""

                            from datetime import date as _d

                            s = (s or "").strip()

                            if not s:

                                return None

                            try:

                                if "/" in s:

                                    parts = s.split("/")

                                    if len(parts) == 3:

                                        return _d(int(parts[2]), int(parts[1]), int(parts[0]))

                                return _d.fromisoformat(s[:10])

                            except Exception:

                                return None



                        def _apply_filter():

                            name_q  = (_f_name.value or "").strip().lower()

                            st_q    = _f_status.value or ""

                            ty_q    = _f_type.value or ""

                            dept_q  = _f_dept.value or ""

                            ltype_q = _f_ltype.value or ""

                            from_d  = _parse_date(_f_from.value)

                            to_d    = _parse_date(_f_to.value)

                            mine_only = _f_mine_state.get("active", False)

                            filtered = []

                            for lv in all_leaves:

                                if mine_only and lv.get("staff_id") != user_id:

                                    continue

                                if name_q and name_q not in (lv.get("staff_name") or "").lower():

                                    continue

                                if st_q and lv.get("status") != st_q:

                                    continue

                                if ty_q and lv.get("leave_type") != ty_q:

                                    continue

                                if dept_q and (lv.get("department_name") or "") != dept_q:

                                    continue

                                if ltype_q == "direct" and not lv.get("is_direct"):
                                    continue
                                if ltype_q == "resubmit" and not lv.get("is_resubmitted"):
                                    continue
                                if ltype_q == "normal" and (lv.get("is_direct") or lv.get("is_resubmitted")):
                                    continue

                                if from_d or to_d:

                                    lv_start = _parse_date(lv.get("start_date", ""))

                                    lv_end   = _parse_date(lv.get("end_date", ""))

                                    if lv_start and lv_end:

                                        if from_d and lv_end < from_d:

                                            continue

                                        if to_d and lv_start > to_d:

                                            continue

                                filtered.append(lv)

                            _f_count.set_text(f"{len(filtered)} / {len(all_leaves)} đơn")

                            _all_container.clear()

                            _export_sel.clear()

                            with _all_container:

                                _draw_table_paged(filtered, show_name=True, show_checkbox=False,

                                            export_sel=_export_sel)



                        def _reset_filter():

                            _f_name.value   = ""

                            _f_status.value = ""

                            _f_type.value   = ""

                            _f_dept.value   = ""

                            _f_ltype.value  = ""

                            _f_from.value   = ""

                            _f_to.value     = ""

                            _f_mine_state["active"] = False

                            _f_mine_btn.style("background:transparent; color:#b91c1c; border-color:#fca5a5")

                            _apply_filter()



                        _f_name.on("keydown.enter", lambda _: _apply_filter())

                        _f_from.on("keydown.enter", lambda _: _apply_filter())

                        _f_to.on("keydown.enter",   lambda _: _apply_filter())



                        _apply_filter()  # render lần đầu

                    elif can_declared and declared_leaves:

                        ui.separator().classes("my-4")

                        ui.label(f"Đơn đã khai báo hộ ({len(declared_leaves)})").classes("font-bold text-gray-700 text-sm mb-2")

                        _draw_table(declared_leaves, show_name=True)



                    # Nếu không có "Của tôi" / "Phòng tôi" ri→ng → hiện trong Dashboard với filter

                    if _has_dash and not can_all:



                        def _make_section_filter(src_leaves: list, title_prefix: str, show_name_: bool):

                            """Tạo filter card + container cho một section."""

                            _sf_status_opts = {"": "Tất cả trạng thái", **{k: v[0] for k, v in _LEAVE_STATUS.items()}}

                            _sf_type_opts   = {"": "Tất cả loại", **_LEAVE_TYPE}

                            with ui.card().classes("w-full p-4 mb-3 border-2 border-red-800 rounded-lg"):

                                ui.label("Bộ lọc tìm kiếm").classes("text-xs font-bold text-red-800 uppercase mb-2")

                                with ui.row().classes("gap-3 flex-wrap items-end"):

                                    _sf_name   = ui.input("Tìm theo tên").classes("w-40").props("dense clearable")

                                    _sf_status = ui.select(_sf_status_opts, value="", label="Trạng thái").classes("w-40").props("dense")

                                    _sf_type   = ui.select(_sf_type_opts, value="", label="Loại nghỉ").classes("w-36").props("dense")

                                    # Phòng filter
                                    _sf_dept_opts = {"": "Tất cả phòng"}
                                    for lv in src_leaves:
                                        dn = lv.get("department_name") or lv.get("dept_name") or ""
                                        if dn and dn not in _sf_dept_opts.values():
                                            _sf_dept_opts[dn] = dn
                                    _sf_dept = ui.select(_sf_dept_opts, value="", label="Phòng").classes("w-40").props("dense") if len(_sf_dept_opts) > 2 else None

                                    with ui.input("Ngày nghỉ từ").classes("w-36").props("dense clearable readonly") as _sf_from:

                                        with _sf_from.add_slot("append"):

                                            ui.icon("event").classes("cursor-pointer").on("click", lambda: _sf_cal_from.open())

                                        with ui.menu() as _sf_cal_from:

                                            ui.date(mask="DD/MM/YYYY").props(f'{_OPT_ALL} first-day-of-week="1"').bind_value(_sf_from)

                                    with ui.input("đến ngày").classes("w-36").props("dense clearable readonly") as _sf_to:

                                        with _sf_to.add_slot("append"):

                                            ui.icon("event").classes("cursor-pointer").on("click", lambda: _sf_cal_to.open())

                                        with ui.menu() as _sf_cal_to:

                                            ui.date(mask="DD/MM/YYYY").props(f'{_OPT_ALL} first-day-of-week="1"').bind_value(_sf_to)

                                with ui.row().classes("gap-3 mt-2 items-center flex-wrap"):

                                    _sf_count = ui.label(f"{len(src_leaves)} / {len(src_leaves)} đơn").classes("text-sm font-medium text-red-800 flex-1")

                                    _sf_mine_state = {"active": False}

                                    _sf_mine_btn = ui.button("👤 Đơn của tôi",

                                        on_click=lambda: _sf_toggle_mine()

                                    ).props("flat").classes("border rounded px-3 text-red-700 border-red-400")

                                    ui.button("Tìm kiếm", icon="search",

                                              on_click=lambda: _sf_apply()).classes("bg-red-700 text-white")

                                    ui.button("Xóa lọc", icon="clear",

                                              on_click=lambda: _sf_reset()).props("flat").classes("text-gray-500")



                            def _sf_toggle_mine():

                                _sf_mine_state["active"] = not _sf_mine_state["active"]

                                if _sf_mine_state["active"]:

                                    _sf_mine_btn.style("background:#8B0000; color:white; border-color:#8B0000")

                                else:

                                    _sf_mine_btn.style("background:transparent; color:#b91c1c; border-color:#fca5a5")

                                _sf_apply()



                            _sf_container = ui.column().classes("w-full gap-0")



                            def _parse_sf_date(s):

                                from datetime import date as _dd

                                s = (s or "").strip()

                                if not s: return None

                                try:

                                    if "/" in s:

                                        p = s.split("/")

                                        return _dd(int(p[2]), int(p[1]), int(p[0]))

                                    return _dd.fromisoformat(s[:10])

                                except Exception:

                                    return None



                            def _sf_apply():

                                nq = (_sf_name.value or "").strip().lower()

                                sq = _sf_status.value or ""

                                tq = _sf_type.value or ""

                                dq = (_sf_dept.value or "") if _sf_dept else ""

                                fd = _parse_sf_date(_sf_from.value)

                                td = _parse_sf_date(_sf_to.value)

                                mine_only = _sf_mine_state.get("active", False)

                                filtered = []

                                for lv in src_leaves:

                                    if mine_only and lv.get("staff_id") != user_id: continue

                                    if nq and nq not in (lv.get("staff_name") or "").lower(): continue

                                    if sq and lv.get("status") != sq: continue

                                    if tq and lv.get("leave_type") != tq: continue

                                    if dq and (lv.get("department_name") or lv.get("dept_name") or "") != dq: continue

                                    if fd or td:

                                        s = _parse_sf_date(lv.get("start_date",""))

                                        e = _parse_sf_date(lv.get("end_date",""))

                                        if s and e:

                                            if fd and e < fd: continue

                                            if td and s > td: continue

                                    filtered.append(lv)

                                _sf_count.set_text(f"{len(filtered)} / {len(src_leaves)} đơn")

                                _sf_container.clear()

                                with _sf_container:

                                    _draw_table_paged(filtered, show_name=show_name_, show_checkbox=False, export_sel=_export_sel)



                            def _sf_reset():

                                _sf_name.value = _sf_status.value = _sf_type.value = ""

                                _sf_from.value = _sf_to.value = ""

                                if _sf_dept: _sf_dept.value = ""

                                _sf_mine_state["active"] = False

                                _sf_mine_btn.style("background:transparent; color:#b91c1c; border-color:#fca5a5")

                                _sf_count.set_text(f"{len(src_leaves)} / {len(src_leaves)} đơn")

                                _sf_container.clear()

                                with _sf_container:

                                    _draw_table_paged(src_leaves, show_name=show_name_, show_checkbox=False, export_sel=_export_sel)



                            _sf_name.on("keydown.enter", lambda _: _sf_apply())

                            with _sf_container:

                                _draw_table_paged(src_leaves, show_name=show_name_, show_checkbox=False, export_sel=_export_sel)



                        if can_dept and dept_leaves:

                            ui.separator().classes("my-4")

                            ui.label(f"Đơn phòng tôi ({len(dept_leaves)})").classes("font-bold text-gray-700 text-sm mb-2")

                            _make_section_filter(dept_leaves, "Phòng tôi", True)

                        else:

                            # Luôn hiện "Của tôi" kể cả khi chưa có đơn nào

                            ui.separator().classes("my-4")

                            ui.label(f"Đơn của tôi ({len(my_leaves)})").classes("font-bold text-gray-700 text-sm mb-2")

                            _make_section_filter(my_leaves, "Của tôi", False)



            if can_declared and t_declared:

                with ui.tab_panel(t_declared):

                    _draw_table_paged(declared_leaves, show_name=True)



            if t_mine:

                with ui.tab_panel(t_mine):

                    _draw_table_paged(my_leaves)



            if t_pending:
                with ui.tab_panel(t_pending):
                    _show_pending = _pending_ksv_list if _is_dual_role else pending_leaves
                    _draw_pending_with_filter(_show_pending)

            if t_pending_th:
                with ui.tab_panel(t_pending_th):
                    with ui.column().classes("w-full gap-2"):
                        ui.label("Đơn chờ xác nhận của toàn Trung tâm").classes("text-sm text-gray-500 italic")
                        _draw_pending_with_filter(_pending_th_list)



            if can_dept and t_dept:

                with ui.tab_panel(t_dept):

                    _draw_table_paged(dept_leaves, show_name=True)



            if can_declared and t_declared:

                with ui.tab_panel(t_declared):

                    _draw_table_paged(declared_leaves, show_name=True)



            with ui.tab_panel(t_cal):

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

                        # Chú th→ch

                        with ui.row().classes("gap-4 mb-3 flex-wrap items-center"):

                            for _lt, _cls in _CAL_TYPE_COLOR.items():

                                with ui.row().classes("items-center gap-1"):

                                    ui.html(f'<span class="text-xs px-2 py-0.5 rounded {_cls}">{_LEAVE_TYPE.get(_lt, _lt)}</span>')

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

                            # → trống trước ngày 1

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

                                        # Rít g??n hờ tên → lấy tên cuối

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

                        d_pgd  = ui.select(pgd_opts, label="PGĐ được ủy quyền").classes("w-full mt-2")

                        ui.label("Click chọn từng ngày → Click lại để bỏ chọn").classes("text-xs text-orange-500 mt-2")

                        _d_sel: list = []

                        def _on_d_change(e):
                            _d_sel.clear()
                            v = e.value
                            if isinstance(v, list):
                                _d_sel.extend(d for d in v if d and d != "undefined")
                            elif isinstance(v, dict):
                                _d_sel.extend(k for k, ok in v.items() if ok)
                            elif isinstance(v, str) and v:
                                _d_sel.append(v)

                        d_dates = ui.date(value=[], on_change=_on_d_change).props(
                            f"multiple mask='YYYY-MM-DD' no-header first-day-of-week='1' {_OPT_ALL}"
                        ).classes("w-full")

                        d_note = ui.input("Ghi chú (tuỳ chọn)").classes("w-full mt-2")



                        async def do_create_deleg():

                            if not d_gd.value or not d_pgd.value:
                                ui.notify("Vui lòng chọn Giám đốc và PGĐ", type="warning"); return

                            dates = sorted(set(_d_sel))
                            if not dates:
                                ui.notify("Vui lòng chọn ít nhất 1 ngày", type="warning"); return

                            start_date = dates[0]
                            end_date   = dates[-1]

                            try:

                                await asyncio.to_thread(api.post, "/api/delegations/", {

                                    "giam_doc_id": d_gd.value, "pho_giam_doc_id": d_pgd.value,

                                    "start_date": start_date, "end_date": end_date,

                                    "note": d_note.value or None,

                                })

                                deleg_dialog.close()

                                ui.notify("Đã tạo ủy quyền thành công!", type="positive")

                                # Broadcast thông báo đến tất cả user
                                from datetime import datetime as _dt_bc
                                gd_name  = gd_opts.get(d_gd.value, "Giám đốc")
                                pgd_name = pgd_opts.get(d_pgd.value, "Phó Giám đốc")
                                _msg = (f"📋 ỦY QUYỀN MỚI: {gd_name} ủy quyền cho "
                                        f"{pgd_name} từ {start_date} đến {end_date}")
                                if d_note.value:
                                    _msg += f" — {d_note.value}"
                                app.storage.general["_deleg_broadcast"] = {
                                    "msg": _msg, "ts": _dt_bc.now().isoformat(),
                                    "end_date": end_date,
                                }

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

                                for hdr in ["Giám đốc", "PGĐ được ủy quyền", "Từ ngày", "Đến ngày", "Ghi chú", "Trạng thái", ""]:

                                    ui.label(hdr).classes("font-semibold text-red-800 text-sm flex-1")

                            for d in delegations:

                                today_str = __import__("datetime").date.today().isoformat()

                                is_eff = d["is_active"] and d["start_date"] <= today_str <= d["end_date"]

                                badge_cls = "bg-green-100 text-green-700" if is_eff else "bg-gray-100 text-gray-500"

                                badge_txt = "đang hiệu lực" if is_eff else "Không hiệu lực"

                                with ui.row().classes("w-full bg-white border-b border-gray-100 px-4 py-2 gap-3 items-center"):

                                    ui.label(d.get("giam_doc_name", "")).classes("text-sm flex-1")

                                    ui.label(d.get("pho_giam_doc_name", "")).classes("text-sm flex-1")

                                    ui.label(d.get("start_date", "")[:10]).classes("text-sm flex-1")

                                    ui.label(d.get("end_date", "")[:10]).classes("text-sm flex-1")

                                    ui.label(d.get("note") or "→").classes("text-xs text-gray-500 flex-1")

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

                        h_date_in = ui.date(value="").props(f"label='Ngày lễ' mask='YYYY-MM-DD' first-day-of-week='1' {_VI_LOCALE}").classes("w-full")

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



            # ── Tab: Hạn mức phép ─────────────────────────────────────────────

            if t_quota:

                with ui.tab_panel(t_quota):

                    _today_year = _dt_mod.date.today().year

                    with ui.row().classes("gap-3 mb-4 items-center flex-wrap"):

                        q_year_sel = ui.select(

                            {y: str(y) for y in range(_today_year - 2, _today_year + 2)},

                            label="Năm", value=_today_year,

                        ).classes("w-28")

                    quota_area = ui.column().classes("w-full gap-0")



                    # Dialog sửa hạn mức + ngày vào ngânh

                    _quota_cb: list = [None]

                    with ui.dialog() as quota_dialog, ui.card().classes("p-6 w-96"):

                        ui.label("Chỉnh sửa thông tin phép").classes("text-lg font-bold text-red-900 mb-1")

                        _q_staff_lbl = ui.label("").classes("text-sm text-gray-500 mb-3")

                        _q_calc_lbl  = ui.label("").classes("text-xs text-blue-600 mb-1")



                        def _auto_calc_quota(e=None):

                            js = (q_join_input.value or "").strip()

                            # ??ủ định dạng DD-MM-YYYY

                            if len(js) == 10 and js[2] == "-" and js[5] == "-":

                                try:

                                    yr_join = int(js[6:10])

                                    yr_ref  = q_year_sel.value

                                    yrs     = max(0, yr_ref - yr_join)

                                    calc    = 12 + yrs // 5

                                    q_days_input.value = calc

                                    _q_calc_lbl.set_text(

                                        f"✓ {yrs} năm công tác → {calc} ngày phép tự động")

                                except Exception:

                                    _q_calc_lbl.set_text("")

                            else:

                                _q_calc_lbl.set_text("")



                        q_join_input = ui.input("Ngày vào ngânh (DD-MM-YYYY)",

                                                on_change=_auto_calc_quota).classes("w-full").props(

                            "dense mask='##-##-####' placeholder='DD-MM-YYYY'")

                        q_days_input = ui.number("Hạn mức ngày phép (tự động điền, có thể sửa thủ công)",

                                                 value=12, min=0, max=365).classes("w-full mt-2")

                        ui.label("Công thức: 12 ngày + 1 ngày mỗi 5 năm công tác").classes("text-xs text-gray-400 mt-1 mb-4")



                        async def _confirm_quota():

                            cb = _quota_cb[0]

                            quota_dialog.close()

                            if cb:

                                await cb(q_days_input.value, q_join_input.value)



                        with ui.row().classes("w-full justify-end gap-2 mt-2"):

                            ui.button("Hủy", on_click=quota_dialog.close).props("flat").classes("text-gray-500")

                            ui.button("Lưu", icon="save", on_click=_confirm_quota).classes("bg-red-700 text-white")



                    async def _reload_quota():

                        quota_area.clear()

                        yr = q_year_sel.value

                        try:

                            data = await asyncio.to_thread(api.get, f"/api/leaves/quotas/{yr}")

                        except Exception:

                            data = []

                        data = data if isinstance(data, list) else []

                        _quota_sel.clear()

                        with quota_area:

                            if not data:

                                ui.label("Không có dữ liệu.").classes("text-gray-400 text-sm mt-4")

                                return

                            # Group theo phòng

                            from collections import defaultdict as _ddict

                            groups = _ddict(list)

                            for row in data:

                                groups[row.get("dept_name") or "→ Chưa có phòng →"].append(row)



                            _qh = "text-xs font-semibold text-red-800 shrink-0 border-r border-red-200 pr-3 mr-1"

                            _qc = "text-xs shrink-0 border-r border-gray-200 pr-3 mr-1"



                            def _render_quota_header():

                                with ui.row().classes("w-full bg-red-50 border-b border-red-200 px-3 py-1.5 items-center gap-0"):

                                    ui.label("").classes("w-6 shrink-0 mr-3")

                                    ui.label("Họ và tên").classes(f"{_qh} w-36")

                                    ui.label("Ngày vào ngành").classes(f"{_qh} w-28 text-center")

                                    ui.label("Hạn mức").classes(f"{_qh} w-20 text-center")

                                    ui.label("Ngày phép chuyển kỳ").classes(f"{_qh} w-28 text-center")

                                    ui.label("Đã dùng").classes(f"{_qh} w-20 text-center")

                                    ui.label("Ngày phép của năm").classes(f"{_qh} flex-1 text-center")

                                    ui.label("").classes("w-8 shrink-0")



                            _DEPT_ORDER = {

                                "Ban Giám đốc": 0,

                                "Phòng Thanh toán": 1,

                                "Phòng Tổng hợp": 2,

                                "Phòng Swift": 3,

                                "Phòng Quản lý Tài khoản Nostro Vostro": 4,

                                "Phòng Kế toán": 5,

                                "Phòng KSNB&HTVH": 6,

                            }

                            with ui.column().classes("w-full gap-3"):

                                for dept_name, dept_rows in sorted(

                                    groups.items(),

                                    key=lambda x: (_DEPT_ORDER.get(x[0], 99), x[0])

                                ):

                                    with ui.column().classes("w-full gap-0 border border-gray-200 rounded overflow-hidden"):

                                        # Ti→u đờ phòng

                                        with ui.row().classes("w-full bg-red-900 px-3 py-1.5 items-center gap-2"):

                                            ui.label(dept_name).classes("text-white text-xs font-bold uppercase flex-1")

                                            ui.label(f"{len(dept_rows)} người").classes("text-red-200 text-xs")

                                        _render_quota_header()

                                        for row in dept_rows:

                                            with ui.row().classes("w-full bg-white border-b border-gray-300 px-3 py-1.5 items-center gap-0 hover:bg-red-50"):

                                                def _on_qck(e, sid=row["staff_id"]):

                                                    _quota_sel.add(sid) if e.value else _quota_sel.discard(sid)

                                                ui.checkbox(value=False, on_change=_on_qck).classes("w-6 shrink-0 mr-3")

                                                ui.label(row.get("staff_name", "")).classes(f"{_qc} w-36 truncate")

                                                jd = row.get("join_industry_date") or ""

                                                jd_fmt = f"{jd[8:10]}/{jd[5:7]}/{jd[:4]}" if len(jd) >= 10 else "→"

                                                ui.label(jd_fmt).classes(f"{_qc} w-28 text-center")

                                                ui.label(f"{row.get('quota_days', 0):.0f}").classes(f"{_qc} w-20 text-center font-mono")

                                                co = row.get("carry_over", 0)  # hết hiệu lực sau Q1 (31/3) — tự biến mất

                                                co_cls = "text-blue-700 font-semibold" if co > 0 else "text-gray-300"

                                                ui.label(f"{co:.1f}" if co > 0 else "0").classes(f"text-xs w-28 shrink-0 border-r border-gray-200 pr-3 mr-1 text-center font-mono {co_cls}")

                                                ui.label(f"{row.get('used_days', 0):.1f}").classes(f"{_qc} w-20 text-center font-mono")

                                                rem = row.get("remaining", 0)

                                                rem_cls = "text-green-700 font-semibold" if rem > 0 else "text-red-600 font-semibold"

                                                ui.label(f"{rem:.1f}").classes(f"text-xs flex-1 text-center font-mono {rem_cls}")



                                                def _open_quota_set2(sid=row["staff_id"], sname=row["staff_name"],

                                                                    cur_days=row["quota_days"],

                                                                    cur_join=row.get("join_industry_date","")):

                                                    _q_staff_lbl.set_text(sname)

                                                    q_days_input.value = cur_days

                                                    # Chuyển YYYY-MM-DD → DD-MM-YYYY để hiển thị

                                                    if cur_join and len(cur_join) >= 10:

                                                        q_join_input.value = f"{cur_join[8:10]}-{cur_join[5:7]}-{cur_join[:4]}"

                                                    else:

                                                        q_join_input.value = ""

                                                    async def _cb2(days, join_str, _sid=sid, _sname=sname, _yr=yr):

                                                        errs = []

                                                        try:

                                                            await asyncio.to_thread(api.post, "/api/leaves/quotas",

                                                                {"staff_id": _sid, "year": _yr, "quota_days": float(days)})

                                                        except Exception as ex:

                                                            errs.append(str(ex))

                                                        # Chuyển DD-MM-YYYY → YYYY-MM-DD trước khi lưu

                                                        js = (join_str or "").strip().replace("_", "")

                                                        if js and len(js) == 10 and js[2] == "-" and js[5] == "-":

                                                            iso = f"{js[6:10]}-{js[3:5]}-{js[:2]}"

                                                        else:

                                                            iso = js

                                                        if iso:

                                                            try:

                                                                await asyncio.to_thread(api.patch,

                                                                    f"/api/leaves/quotas/staff/{_sid}/join-date",

                                                                    {"join_industry_date": iso})

                                                            except Exception as ex:

                                                                errs.append(str(ex))

                                                        if errs:

                                                            ui.notify(f"Lỗi: {'; '.join(errs)}", type="negative", timeout=5000)

                                                        else:

                                                            ui.notify(f"Đã cập nhật {_sname}", type="positive", timeout=3000)

                                                            await _reload_quota()

                                                    _quota_cb[0] = _cb2

                                                    quota_dialog.open()

                                                ui.button(icon="edit", on_click=_open_quota_set2).props(

                                                    "flat round dense size=sm").classes("text-blue-600 shrink-0")





                    q_year_sel.on("update:model-value", lambda: asyncio.ensure_future(_reload_quota()))

                    await _reload_quota()



            # ── Tab: B→o cáo năm ─────────────────────────────────────────────

            if t_stats:

                with ui.tab_panel(t_stats):

                    _today_year = _dt_mod.date.today().year

                    with ui.row().classes("gap-3 mb-4 items-center"):

                        s_year_sel = ui.select(

                            {y: str(y) for y in range(_today_year - 2, _today_year + 2)},

                            label="Năm", value=_today_year,

                        ).classes("w-28")



                        async def _download_stats():

                            try:

                                content = await asyncio.to_thread(

                                    api.download, "/api/leaves/export/annual",
                                    params={"year": s_year_sel.value}

                                )

                                ui.download(content, f"bao_cao_tat_ca_don_nghi_phep_{s_year_sel.value}.xlsx")

                            except Exception as e:

                                _handle_api_error(e)



                        ui.button("Tải báo cáo Excel", icon="download", on_click=_download_stats).classes("bg-blue-700 text-white")



                    ui.label("Chọn năm và nhấn 'Tải báo cáo Excel' để xuất file tổng hợp phép.").classes("text-sm text-gray-500")



            # ── Tab: Khai báo hộ ─────────────────────────────────────────────

            if t_direct:

                with ui.tab_panel(t_direct):

                    # Load danh sách nhân viên

                    direct_staff_list = []

                    try:

                        direct_staff_list = await asyncio.to_thread(api.get, "/api/staff/")

                    except Exception:

                        direct_staff_list = []

                    direct_staff_list = direct_staff_list if isinstance(direct_staff_list, list) else []

                    direct_staff_opts  = {s["id"]: s["full_name"] for s in direct_staff_list}



                    _today_iso_d = _dt_mod.date.today().isoformat()
                    _drs_val = [""]   # ISO start date cho range thai_san/bao_hiem
                    _dre_val = [""]   # ISO end date cho range



                    ui.label("Khai báo nghỉ phép cho nhân viên khác (tạo đơn đã duyệt ngay).").classes("text-sm text-gray-500 mb-4")

                    ui.add_css(".q-date__header { display: none !important; }")



                    # ── Define helpers TRƯỚC để _submit có thể d→ng ──────────

                    _decl_state = {"leaves": list(declared_leaves)}



                    # Placeholder containers → sẽ được assign sau khi render

                    _decl_refs = {"title": None, "container": None}



                    def _render_decl_table(leaves: list):

                        _decl_state["leaves"] = leaves

                        c = _decl_refs["container"]

                        t = _decl_refs["title"]

                        if c is None:

                            return

                        c.clear()

                        if t:

                            t.set_text(f"Đơn đã khai báo hộ ({len(leaves)})")

                        with c:

                            if not leaves:

                                ui.label("Chưa có đơn nào được khai báo.").classes("text-gray-400 text-sm")

                                return

                            _hc = "font-semibold text-red-800 text-xs shrink-0 border-r border-red-400 pr-2 mr-1"

                            _export_sel.clear()
                            _decl_row_cks: list = []

                            def _decl_select_all(e, _leaves=leaves):
                                for ck in _decl_row_cks:
                                    ck.set_value(e.value)
                                if e.value:
                                    _export_sel.update(dl["id"] for dl in _leaves)
                                else:
                                    for dl in _leaves: _export_sel.discard(dl["id"])

                            with ui.column().classes("w-full gap-0 border-2 border-gray-400 rounded"):

                                with ui.row().classes("w-full bg-red-50 border-b-2 border-red-400 px-3 py-2 items-center gap-0"):

                                    ui.checkbox(value=False, on_change=_decl_select_all).props("dense").classes("w-6 shrink-0 mr-2").tooltip("Chọn / Bỏ chọn tất cả")

                                    ui.label("STT").classes(f"{_hc} w-8 text-center")

                                    ui.label("Ngày khai").classes(f"{_hc} w-20")

                                    ui.label("Nhân viên").classes(f"{_hc} w-32")

                                    ui.label("Phòng").classes(f"{_hc} w-32")

                                    ui.label("Người khai báo").classes(f"{_hc} w-32")

                                    ui.label("Loại").classes(f"{_hc} w-28")

                                    ui.label("Ngày nghỉ").classes("font-semibold text-red-800 text-xs flex-1")

                                    ui.label("").classes("w-8 shrink-0")

                                for _di, dl in enumerate(leaves, 1):

                                    with ui.row().classes("w-full bg-white border-b border-gray-100 px-3 py-1.5 items-center gap-0 hover:bg-purple-50"):

                                        def _on_decl_ck(e, l=dl["id"]):

                                            _export_sel.add(l) if e.value else _export_sel.discard(l)

                                        _dck = ui.checkbox(value=False, on_change=_on_decl_ck).props("dense").classes("w-6 shrink-0 mr-2")
                                        _decl_row_cks.append(_dck)

                                        ui.label(str(_di)).classes("text-xs w-8 shrink-0 text-center text-gray-400 border-r border-gray-400 pr-2 mr-1")

                                        ui.label((dl.get("created_at") or "")[:10]).classes("text-xs w-20 shrink-0 border-r border-gray-400 pr-2 mr-1 text-gray-500")

                                        ui.label(dl.get("staff_name") or "→").classes("text-xs w-32 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                                        ui.label(dl.get("department_name") or "→").classes("text-xs w-32 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                                        ui.label(dl.get("declarer_name") or "→").classes("text-xs w-32 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                                        ui.label(_LEAVE_TYPE.get(dl.get("leave_type",""), dl.get("leave_type",""))).classes("text-xs w-28 shrink-0 truncate border-r border-gray-400 pr-2 mr-1")

                                        ui.label(_fmt_leave_dates(dl.get("start_date",""), dl.get("end_date",""), dl.get("spread_dates"))).classes("text-xs flex-1")

                                        def _del(did=dl["id"], sname=dl.get("staff_name","?")):

                                            with ui.dialog() as _ddlg, ui.card().classes("p-6 w-80"):

                                                ui.label("Xác nhận xóa").classes("text-lg font-bold text-red-900 mb-1")

                                                ui.label(f"Xóa đơn khai báo hộ của {sname}. Không thể hoàn tác.").classes("text-sm text-gray-600 mb-4")

                                                with ui.row().classes("gap-3 justify-end w-full"):

                                                    ui.button("Hủy", on_click=_ddlg.close).props("flat").classes("text-gray-500")

                                                    async def _do_del(_id=did, _dg=_ddlg):

                                                        try:

                                                            await asyncio.to_thread(api.delete, f"/api/leaves/{_id}")

                                                        except Exception as ex:

                                                            _dg.close()

                                                            ui.notify(f"Xóa thất bại: {ex}", type="negative", timeout=5000)

                                                            return

                                                        _dg.close()

                                                        ui.notify("✅ Đã xóa đơn khai báo hộ!", type="positive", timeout=3000)

                                                        app.storage.user["_leaves_goto"] = "khai_bao_ho"

                                                        ui.timer(1.5, lambda: ui.navigate.to("/leaves"), once=True)

                                                    ui.button("Xóa", icon="delete",

                                                              on_click=_do_del).classes("bg-red-600 text-white")

                                            _ddlg.open()

                                        ui.button(icon="delete", on_click=_del).props(

                                            "flat round dense size=sm").classes("text-red-500 shrink-0").tooltip("Xóa đơn")



                    async def _refresh_decl():

                        try:

                            fresh = await asyncio.to_thread(api.get, "/api/leaves/", {"scope": "declared"})

                            _render_decl_table(fresh if isinstance(fresh, list) else [])

                        except Exception:

                            pass



                    # ── Form + bảng layout ────────────────────────────────────

                    with ui.row().classes("w-full gap-6 items-start flex-wrap"):

                      with ui.card().classes("p-6 w-96 shrink-0"):

                        d_staff  = ui.select(direct_staff_opts, label="Nhân viên").classes("w-full")

                        d_dates_wrap = ui.column().classes("w-full mt-2 gap-0")
                        with d_dates_wrap:
                            d_dates = ui.date(value=[]).props(f"multiple mask='YYYY-MM-DD' first-day-of-week='1' {_VI_LOCALE}").classes("w-full")
                            ui.label("Click chọn từng ngày → Click lại để bỏ chọn").classes("text-xs text-orange-500 mt-0.5")

                        import calendar as _cal_d
                        _d_today_ref = _dt_mod.date.today()
                        _d_rs_cur = [_d_today_ref.year, _d_today_ref.month]
                        _d_re_cur = [_d_today_ref.year, _d_today_ref.month]

                        d_range_wrap = ui.column().classes("w-full mt-2 gap-2")
                        d_range_wrap.set_visibility(False)
                        with d_range_wrap:
                            ui.label("Chọn khoảng thời gian nghỉ").classes("text-xs text-blue-600 font-medium -mb-1")
                            with ui.column().classes("w-full gap-0"):
                                with ui.row().classes("w-full items-center gap-1"):
                                    d_range_start = ui.input("Ngày bắt đầu", placeholder="DD/MM/YYYY").classes("flex-1")
                                    _d_rs_btn = ui.button(icon="calendar_month").props("flat round dense size=sm color=grey-7")
                                _d_rs_cal = ui.column().classes("w-full border border-gray-200 rounded p-2 bg-white mt-1")
                                _d_rs_cal.set_visibility(False)
                            with ui.column().classes("w-full gap-0 mt-1"):
                                with ui.row().classes("w-full items-center gap-1"):
                                    d_range_end = ui.input("Ngày kết thúc", placeholder="DD/MM/YYYY").classes("flex-1")
                                    _d_re_btn = ui.button(icon="calendar_month").props("flat round dense size=sm color=grey-7")
                                _d_re_cal = ui.column().classes("w-full border border-gray-200 rounded p-2 bg-white mt-1")
                                _d_re_cal.set_visibility(False)

                        def _d_rs_render():
                            _d_rs_cal.clear()
                            y, m = _d_rs_cur
                            with _d_rs_cal:
                                with ui.row().classes("w-full items-center justify-between mb-1"):
                                    ui.button(icon="chevron_left",  on_click=_d_rs_prev).props("flat round dense size=sm")
                                    ui.label(f"Tháng {m:02d}/{y}").classes("text-sm font-semibold text-gray-700")
                                    ui.button(icon="chevron_right", on_click=_d_rs_next).props("flat round dense size=sm")
                                with ui.row().classes("w-full gap-0"):
                                    for h in ["T2","T3","T4","T5","T6","T7","CN"]:
                                        ui.label(h).classes("text-xs text-center text-gray-400 w-[14.28%] py-0.5")
                                first_wd = _dt_mod.date(y, m, 1).weekday()
                                last_day = _cal_d.monthrange(y, m)[1]
                                today_d  = _dt_mod.date.today()
                                with ui.row().classes("w-full gap-0 flex-wrap"):
                                    for _ in range(first_wd):
                                        ui.label("").classes("w-[14.28%] h-7")
                                    for day in range(1, last_day + 1):
                                        ds = f"{y:04d}-{m:02d}-{day:02d}"; dobj = _dt_mod.date(y, m, day)
                                        sel = (ds == _drs_val[0]); is_td = (dobj == today_d); wknd = dobj.weekday() >= 5
                                        def _pick_d_rs(ds=ds):
                                            def _do():
                                                _drs_val[0] = ds
                                                d_range_start.value = f"{ds[8:10]}/{ds[5:7]}/{ds[0:4]}"
                                                _d_rs_cal.set_visibility(False); _d_rs_render()
                                            return _do
                                        with ui.element("div").classes("w-[14.28%] h-7 flex items-center justify-center"):
                                            if sel:
                                                ui.label(str(day)).classes("w-6 h-6 rounded-full bg-red-700 text-white text-xs font-bold flex items-center justify-center cursor-pointer").on("click", _pick_d_rs())
                                            elif is_td:
                                                ui.label(str(day)).classes("w-6 h-6 rounded-full ring-2 ring-red-500 text-red-600 text-xs font-bold flex items-center justify-center cursor-pointer hover:bg-red-50").on("click", _pick_d_rs())
                                            elif wknd:
                                                ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-blue-300 hover:bg-blue-50 cursor-pointer").on("click", _pick_d_rs())
                                            else:
                                                ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-gray-600 hover:bg-red-50 hover:text-red-700 cursor-pointer").on("click", _pick_d_rs())

                        def _d_rs_prev():
                            y, m = _d_rs_cur; _d_rs_cur[0], _d_rs_cur[1] = (y-1, 12) if m == 1 else (y, m-1); _d_rs_render()
                        def _d_rs_next():
                            y, m = _d_rs_cur; _d_rs_cur[0], _d_rs_cur[1] = (y+1, 1) if m == 12 else (y, m+1); _d_rs_render()
                        def _d_rs_toggle():
                            vis = not _d_rs_cal.visible; _d_rs_cal.set_visibility(vis)
                            if vis: _d_rs_render()
                        def _parse_drs():
                            txt = d_range_start.value.strip()
                            if not txt: _drs_val[0] = ""; return
                            try:
                                p = txt.replace("-", "/").split("/")
                                if len(p) != 3 or len(p[2]) != 4:
                                    raise ValueError("Định dạng phải là dd/mm/yyyy")
                                d_,mo,yr = int(p[0]),int(p[1]),int(p[2])
                                _dt_mod.date(yr, mo, d_)
                                _drs_val[0] = f"{yr:04d}-{mo:02d}-{d_:02d}"
                            except Exception: _drs_val[0] = ""
                        _d_rs_btn.on("click", _d_rs_toggle)
                        d_range_start.on("blur", _parse_drs)

                        def _d_re_render():
                            _d_re_cal.clear()
                            y, m = _d_re_cur
                            with _d_re_cal:
                                with ui.row().classes("w-full items-center justify-between mb-1"):
                                    ui.button(icon="chevron_left",  on_click=_d_re_prev).props("flat round dense size=sm")
                                    ui.label(f"Tháng {m:02d}/{y}").classes("text-sm font-semibold text-gray-700")
                                    ui.button(icon="chevron_right", on_click=_d_re_next).props("flat round dense size=sm")
                                with ui.row().classes("w-full gap-0"):
                                    for h in ["T2","T3","T4","T5","T6","T7","CN"]:
                                        ui.label(h).classes("text-xs text-center text-gray-400 w-[14.28%] py-0.5")
                                first_wd = _dt_mod.date(y, m, 1).weekday()
                                last_day = _cal_d.monthrange(y, m)[1]
                                today_d  = _dt_mod.date.today()
                                with ui.row().classes("w-full gap-0 flex-wrap"):
                                    for _ in range(first_wd):
                                        ui.label("").classes("w-[14.28%] h-7")
                                    for day in range(1, last_day + 1):
                                        ds = f"{y:04d}-{m:02d}-{day:02d}"; dobj = _dt_mod.date(y, m, day)
                                        sel = (ds == _dre_val[0]); is_td = (dobj == today_d); wknd = dobj.weekday() >= 5
                                        def _pick_d_re(ds=ds):
                                            def _do():
                                                _dre_val[0] = ds
                                                d_range_end.value = f"{ds[8:10]}/{ds[5:7]}/{ds[0:4]}"
                                                _d_re_cal.set_visibility(False); _d_re_render()
                                            return _do
                                        with ui.element("div").classes("w-[14.28%] h-7 flex items-center justify-center"):
                                            if sel:
                                                ui.label(str(day)).classes("w-6 h-6 rounded-full bg-red-700 text-white text-xs font-bold flex items-center justify-center cursor-pointer").on("click", _pick_d_re())
                                            elif is_td:
                                                ui.label(str(day)).classes("w-6 h-6 rounded-full ring-2 ring-red-500 text-red-600 text-xs font-bold flex items-center justify-center cursor-pointer hover:bg-red-50").on("click", _pick_d_re())
                                            elif wknd:
                                                ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-blue-300 hover:bg-blue-50 cursor-pointer").on("click", _pick_d_re())
                                            else:
                                                ui.label(str(day)).classes("w-6 h-6 rounded flex items-center justify-center text-xs text-gray-600 hover:bg-red-50 hover:text-red-700 cursor-pointer").on("click", _pick_d_re())

                        def _d_re_prev():
                            y, m = _d_re_cur; _d_re_cur[0], _d_re_cur[1] = (y-1, 12) if m == 1 else (y, m-1); _d_re_render()
                        def _d_re_next():
                            y, m = _d_re_cur; _d_re_cur[0], _d_re_cur[1] = (y+1, 1) if m == 12 else (y, m+1); _d_re_render()
                        def _d_re_toggle():
                            vis = not _d_re_cal.visible; _d_re_cal.set_visibility(vis)
                            if vis: _d_re_render()
                        def _parse_dre():
                            txt = d_range_end.value.strip()
                            if not txt: _dre_val[0] = ""; return
                            try:
                                p = txt.replace("-", "/").split("/")
                                if len(p) != 3 or len(p[2]) != 4:
                                    raise ValueError("Định dạng phải là dd/mm/yyyy")
                                d_,mo,yr = int(p[0]),int(p[1]),int(p[2])
                                _dt_mod.date(yr, mo, d_)
                                _dre_val[0] = f"{yr:04d}-{mo:02d}-{d_:02d}"
                            except Exception: _dre_val[0] = ""
                        _d_re_btn.on("click", _d_re_toggle)
                        d_range_end.on("blur", _parse_dre)

                        d_type   = ui.select({k: v for k, v in _LEAVE_TYPE.items()}, label="Loại nghỉ", value="annual").classes("w-full mt-2")

                        d_reason = ui.textarea("Lý do (tuỳ chọn)").classes("w-full mt-2").props("rows=2")
                        d_reason.set_visibility(False)

                        def _on_type_change(e):
                            lt = e.value
                            is_rng = lt in ("thai_san", "bao_hiem")
                            d_dates_wrap.set_visibility(not is_rng)
                            d_range_wrap.set_visibility(is_rng)
                            d_reason.set_visibility(lt == "other")

                        d_type.on_value_change(_on_type_change)



                        async def do_direct():

                            if not d_staff.value:
                                ui.notify("Vui lòng chọn nhân viên", type="warning"); return

                            lt = d_type.value
                            is_rng = lt in ("thai_san", "bao_hiem")
                            staff_name = direct_staff_opts.get(d_staff.value, "nhân viên")

                            if is_rng:
                                _parse_drs(); _parse_dre()
                                start_val, end_val = _drs_val[0], _dre_val[0]
                                if not start_val or not end_val:
                                    ui.notify("Vui lòng nhập ngày bắt đầu và ngày kết thúc (DD/MM/YYYY)", type="warning"); return
                                if end_val < start_val:
                                    ui.notify("Ngày kết thúc phải sau ngày bắt đầu", type="warning"); return
                                body = {"staff_id": d_staff.value, "start_date": start_val, "end_date": end_val,
                                        "leave_type": lt, "reason": d_reason.value or None}
                                confirm_lbl = f"Khai báo {_LEAVE_TYPE.get(lt, lt)} cho {staff_name} (từ {start_val} đến {end_val}). Đơn sẽ được duyệt ngay."
                            else:
                                raw = d_dates.value
                                if not raw:
                                    ui.notify("Vui lòng chọn ít nhất 1 ngày", type="warning"); return
                                dates = sorted(set(raw if isinstance(raw, list) else [raw]))
                                dates = [d[:10] for d in dates if d]
                                if not dates:
                                    ui.notify("Vui lòng chọn ít nhất 1 ngày", type="warning"); return
                                if lt == "other" and not (d_reason.value or "").strip():
                                    ui.notify("Vui lòng nhập lý do khi chọn loại Khác", type="warning"); return
                                body = {"staff_id": d_staff.value, "start_date": dates[0], "end_date": dates[-1],
                                        "spread_dates": dates, "leave_type": lt, "reason": d_reason.value or None}
                                confirm_lbl = f"Khai báo nghỉ cho {staff_name} ({len(dates)} ngày). Đơn sẽ được duyệt ngay."

                            # Inline dialog → không dùng shared _ask_confirm

                            with ui.dialog() as _dlg, ui.card().classes("p-6 w-96"):

                                ui.label("Xác nhận khai báo hộ").classes("text-lg font-bold text-red-900 mb-1")

                                ui.label(confirm_lbl).classes("text-sm text-gray-600 mb-4")

                                with ui.row().classes("gap-3 justify-end w-full"):

                                    ui.button("Hủy", on_click=_dlg.close).props("flat").classes("text-gray-500")

                                    async def _on_confirm(_b=body, _d=_dlg, _rng=is_rng):

                                        _d.close()

                                        try:

                                            await asyncio.to_thread(api.post, "/api/leaves/direct", _b)

                                        except Exception as e:

                                            if not _handle_api_error(e):

                                                ui.notify(f"Khai báo thất bại: {e}", type="negative", timeout=5000)

                                            return

                                        ui.notify("✅ Khai báo hộ thành công!", type="positive", timeout=4000)

                                        d_staff.value = None
                                        if _rng:
                                            _drs_val[0] = ""; _dre_val[0] = ""
                                            d_range_start.value = ""; d_range_end.value = ""
                                        else:
                                            d_dates.value = None

                                        d_type.value = "annual"
                                        d_dates_wrap.set_visibility(True)
                                        d_range_wrap.set_visibility(False)

                                        d_reason.value = ""

                                        d_reason.set_visibility(False)

                                        await _refresh_decl()

                                    ui.button("Khai báo", icon="check",

                                              on_click=_on_confirm).classes("bg-purple-700 text-white")

                            _dlg.open()



                        ui.button("Khai báo", icon="check",

                                  on_click=do_direct).classes("bg-purple-700 text-white mt-4")



                      # ── Cột phải: bảng đơn đã khai báo hộ ──────────────────

                      with ui.column().classes("flex-1 min-w-64"):

                        # Filter bảng khai báo hộ → giống style Dashboard

                        _df_type_opts = {"": "Tất cả loại", **_LEAVE_TYPE}

                        _df_depts     = sorted({s.get("department_name") or "" for s in direct_staff_list if s.get("department_name")})

                        _df_dept_opts = {"": "Tất cả phòng", **{d: d for d in _df_depts}}

                        with ui.card().classes("w-full p-4 mb-3 border-2 border-red-800 rounded-lg"):

                            ui.label("Bộ lọc tìm kiếm").classes("text-xs font-bold text-red-800 uppercase mb-2")

                            with ui.row().classes("gap-3 flex-wrap items-end"):

                                _df_name = ui.input("Tìm theo tên").classes("w-40").props("dense clearable")

                                _df_type = ui.select(_df_type_opts, value="", label="Loại nghỉ").classes("w-36").props("dense")

                                _df_dept = ui.select(_df_dept_opts, value="", label="Phòng").classes("w-40").props("dense")

                                with ui.input("Ngày nghỉ từ").classes("w-36").props("dense clearable readonly") as _df_from:

                                    with _df_from.add_slot("append"):

                                        ui.icon("event").classes("cursor-pointer").on("click", lambda: _dcal_from.open())

                                    with ui.menu() as _dcal_from:

                                        ui.date(mask="DD/MM/YYYY").props(f'{_OPT_ALL} first-day-of-week="1"').bind_value(_df_from)

                                with ui.input("đến ngày").classes("w-36").props("dense clearable readonly") as _df_to:

                                    with _df_to.add_slot("append"):

                                        ui.icon("event").classes("cursor-pointer").on("click", lambda: _dcal_to.open())

                                    with ui.menu() as _dcal_to:

                                        ui.date(mask="DD/MM/YYYY").props(f'{_OPT_ALL} first-day-of-week="1"').bind_value(_df_to)

                            with ui.row().classes("gap-3 mt-2 items-center"):

                                _df_count = ui.label("").classes("text-sm font-medium text-red-800 flex-1")

                                ui.button("Tìm kiếm", icon="search",

                                          on_click=lambda: _apply_decl_filter()).classes("bg-red-700 text-white")

                                ui.button("Xóa lọc", icon="clear",

                                          on_click=lambda: _reset_decl_filter()).props("flat").classes("text-gray-500")



                        _decl_refs["title"]     = ui.label("").classes("font-bold text-gray-700 text-sm mb-2")

                        _decl_refs["container"] = ui.column().classes("w-full gap-0")



                        def _parse_decl_date(s):

                            from datetime import date as _dd

                            s = (s or "").strip()

                            if not s: return None

                            try:

                                if "/" in s:

                                    p = s.split("/")

                                    return _dd(int(p[2]), int(p[1]), int(p[0]))

                                return _dd.fromisoformat(s[:10])

                            except Exception:

                                return None



                        def _apply_decl_filter():

                            name_q  = (_df_name.value or "").strip().lower()

                            type_q  = _df_type.value or ""

                            dept_q  = _df_dept.value or ""

                            from_d  = _parse_decl_date(_df_from.value)

                            to_d    = _parse_decl_date(_df_to.value)

                            src = _decl_state.get("leaves", declared_leaves)

                            filtered_d = []

                            for dl in src:

                                if name_q and name_q not in (dl.get("staff_name") or "").lower():

                                    continue

                                if type_q and dl.get("leave_type") != type_q:

                                    continue

                                if dept_q and (dl.get("department_name") or "") != dept_q:

                                    continue

                                if from_d or to_d:

                                    s = _parse_decl_date(dl.get("start_date", ""))

                                    e = _parse_decl_date(dl.get("end_date", ""))

                                    if s and e:

                                        if from_d and e < from_d:

                                            continue

                                        if to_d and s > to_d:

                                            continue

                                filtered_d.append(dl)

                            _df_count.set_text(f"{len(filtered_d)} / {len(src)} đơn")

                            _render_decl_table(filtered_d)



                        def _reset_decl_filter():

                            _df_name.value = ""

                            _df_type.value = ""

                            _df_dept.value = ""

                            _df_from.value = ""

                            _df_to.value   = ""

                            src = _decl_state.get("leaves", declared_leaves)

                            _df_count.set_text(f"{len(src)} / {len(src)} đơn")

                            _render_decl_table(src)



                        _df_name.on("keydown.enter", lambda _: _apply_decl_filter())

                        _df_from.on("keydown.enter", lambda _: _apply_decl_filter())

                        _df_to.on("keydown.enter",   lambda _: _apply_decl_filter())



                        _render_decl_table(declared_leaves)

                        # Hiện count ngay từ đầu

                        _df_count.set_text(f"{len(declared_leaves)} / {len(declared_leaves)} đơn")



