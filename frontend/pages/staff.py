"""Trang quản lý tài khoản cán bộ TTTT."""
import asyncio
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error


@ui.page("/staff")
async def staff_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.staff"):
        ui.navigate.to("/home")
        return

    try:
        all_depts = await asyncio.to_thread(api.get, "/api/departments/")
    except Exception:
        all_depts = []
    dept_id_to_name = {d["id"]: d["name"] for d in all_depts}
    all_dept_opts   = {d["id"]: d["name"] for d in all_depts}

    _ = await _sidebar("staff")
    with _content_area():
        _page_header("Quản lý User", "Quản lý tài khoản đăng nhập hệ thống")

        current_user = api.get_current_user()
        # QTV cấp 1 + cấp 2 đều thấy công cụ quản lý; từng nút vẫn gated theo has_feature
        _ADMIN_ROLES = ("admin", "admin_l2")
        is_admin = current_user and current_user.get("role") in _ADMIN_ROLES
        acting_is_l2 = bool(current_user and current_user.get("role") == "admin_l2")

        ROLE_OPTS = {
            "chuyen_vien":   "Chuyên viên",
            "pho_phong":     "Phó phòng",
            "truong_phong":  "Trưởng phòng",
            "hau_kiem_vien": "Hậu kiểm viên",
            "giam_doc":      "Giám đốc",
            "pho_giam_doc":  "Phó Giám đốc",
            "admin":         "Quản trị viên cấp 1",
            "admin_l2":      "Quản trị viên cấp 2",
        }
        # Cấp 2 không được gán "Quản trị viên cấp 1" → ẩn khỏi dropdown
        FORM_ROLE_OPTS = {k: v for k, v in ROLE_OPTS.items()
                          if not (acting_is_l2 and k == "admin")}
        role_map = dict(ROLE_OPTS)

        staff_cache = []
        edit_target = {"id": None}

        # ── Lớp CSS của bảng danh sách ────────────────────────────────────────
        # Mỗi cột phải có `shrink-0`: mặc định flex cho phép item CO LẠI
        # (flex-shrink:1) khi tổng bề rộng vượt khung, nên w-28/w-36 bị bóp nhỏ
        # hơn khai báo và chữ tràn ra đè lên cột bên cạnh. Cột nào chữ có thể dài
        # thì thêm `truncate` để cắt bằng "…" thay vì tràn.
        # `min-w-max` giữ hàng rộng đúng nội dung, để nền/viền hàng vẽ hết bảng
        # khi rows_container cuộn ngang trên màn hình hẹp.
        _ROW_BASE = "w-full min-w-max px-3 py-2"
        _HDR_ROW  = (f"{_ROW_BASE} bg-red-50 font-semibold text-xs text-red-800 "
                     "border border-red-100 rounded-t")
        _DATA_ROW = f"{_ROW_BASE} border-b border-gray-100 hover:bg-gray-50"
        # Inline style, KHÔNG dùng class: `.nicegui-row` tự đặt flex-wrap:wrap và
        # gap:1rem trong stylesheet riêng của NiceGUI — class Tailwind cùng độ ưu
        # tiên nên thắng/thua tuỳ thứ tự file CSS. Inline thì luôn thắng.
        _ROW_STYLE = "flex-wrap:nowrap; gap:0.5rem; align-items:center"

        # ── Edit dialog ───────────────────────────────────────────────────────
        edit_dialog = ui.dialog()
        with edit_dialog, ui.card().classes("w-[28rem] p-6"):
            ui.label("Sửa tài khoản").classes("text-lg font-bold mb-4")
            ef_name        = ui.input("Họ tên *").classes("w-full")
            ef_empcode     = ui.input("Mã cán bộ").props('placeholder="VD: 201700886"').classes("w-full mt-2")
            ef_role        = ui.select(FORM_ROLE_OPTS, label="Quyền *").classes("w-full mt-2")
            ef_dept        = ui.select(all_dept_opts, label="Phòng *").classes("w-full mt-2")
            ef_admin_note  = ui.label("Quản trị viên không thuộc phòng nào — thuộc nhóm Quản trị viên.").classes("text-xs text-purple-600 mt-1")

            def _sync_edit_dept():
                is_adm = ef_role.value in _ADMIN_ROLES
                ef_dept.set_visibility(not is_adm)
                ef_admin_note.set_visibility(is_adm)
                if is_adm:
                    ef_dept.set_value(None)
            ef_role.on_value_change(lambda _e: _sync_edit_dept())

            ef_phone       = ui.input("Điện thoại").classes("w-full mt-2")
            ef_join_date   = ui.input("Ngày vào ngành").props('type="date"').classes("w-full mt-2")
            ef_ipcas       = ui.input("User IPCAS").props('placeholder="VD: HQNTHN"').classes("w-full mt-2")
            ef_payment     = ui.input("User Payment").props('placeholder="VD: linhnguyendieu3"').classes("w-full mt-2")
            ef_active      = ui.checkbox("Đang hoạt động").classes("mt-2")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=lambda: edit_dialog.close()).classes("text-gray-500")
                async def do_edit():
                    if not edit_target["id"]:
                        return
                    is_adm = ef_role.value in _ADMIN_ROLES
                    if not is_adm and not ef_dept.value:
                        ui.notify("Vui lòng chọn Phòng", type="warning")
                        return
                    try:
                        await asyncio.to_thread(api.put, f"/api/staff/{edit_target['id']}", {
                            "employee_code": ef_empcode.value.strip() or None,
                            "full_name": ef_name.value,
                            "role": ef_role.value,
                            "phone": ef_phone.value or None,
                            "is_active": ef_active.value,
                            "department_id": None if is_adm else ef_dept.value,
                            "join_industry_date": ef_join_date.value or None,
                            "ipcas_code": ef_ipcas.value.strip().upper() or None,
                            "payment_username": ef_payment.value.strip() or None,
                        })
                        edit_dialog.close()
                        ui.notify("Đã cập nhật tài khoản", type="positive")
                        await load_staff()
                    except Exception as e:
                        if _handle_api_error(e): return
                ui.button("Lưu", on_click=do_edit).classes("bg-red-700 text-white")

        # ── Add dialog ────────────────────────────────────────────────────────
        add_dialog = ui.dialog()
        with add_dialog, ui.card().classes("w-96 p-6"):
            ui.label("Thêm tài khoản").classes("text-lg font-bold mb-4")
            f_name       = ui.input("Họ tên *").classes("w-full")
            f_empcode    = ui.input("Mã cán bộ").props('placeholder="VD: 201700886"').classes("w-full mt-2")
            f_role       = ui.select(FORM_ROLE_OPTS, label="Quyền *", value="chuyen_vien").classes("w-full mt-2")
            f_dept       = ui.select(all_dept_opts, label="Phòng *").classes("w-full mt-2")
            f_admin_note = ui.label("Quản trị viên không thuộc phòng nào — thuộc nhóm Quản trị viên.").classes("text-xs text-purple-600 mt-1")

            def _sync_add_dept():
                is_adm = f_role.value in _ADMIN_ROLES
                f_dept.set_visibility(not is_adm)
                f_admin_note.set_visibility(is_adm)
                if is_adm:
                    f_dept.set_value(None)
            f_role.on_value_change(lambda _e: _sync_add_dept())
            _sync_add_dept()

            f_username   = ui.input("Username *").classes("w-full mt-2")
            f_password   = ui.input("Mật khẩu *", password=True).classes("w-full mt-2")
            f_phone      = ui.input("Điện thoại").classes("w-full mt-2")
            f_join_date  = ui.input("Ngày vào ngành").props('type="date"').classes("w-full mt-2")
            f_ipcas      = ui.input("User IPCAS").props('placeholder="VD: HQNTHN"').classes("w-full mt-2")
            f_payment    = ui.input("User Payment").props('placeholder="VD: linhnguyendieu3"').classes("w-full mt-2")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=lambda: add_dialog.close()).classes("text-gray-500")
                async def do_add():
                    if not f_name.value or not f_username.value or not f_password.value:
                        ui.notify("Vui lòng điền đầy đủ Họ tên, Username và Mật khẩu", type="warning")
                        return
                    is_adm = f_role.value in _ADMIN_ROLES
                    if not is_adm and not f_dept.value:
                        ui.notify("Vui lòng chọn Phòng", type="warning")
                        return
                    try:
                        await asyncio.to_thread(api.post, "/api/staff/", {
                            "employee_code": f_empcode.value.strip() or f_username.value,
                            "full_name": f_name.value,
                            "role": f_role.value,
                            "username": f_username.value,
                            "password": f_password.value,
                            "phone": f_phone.value or None,
                            "department_id": None if is_adm else f_dept.value,
                            "join_industry_date": f_join_date.value or None,
                            "ipcas_code": f_ipcas.value.strip().upper() or None,
                            "payment_username": f_payment.value.strip() or None,
                        })
                        add_dialog.close()
                        ui.notify("Đã thêm tài khoản", type="positive")
                        await load_staff()
                    except Exception as e:
                        if _handle_api_error(e): return
                ui.button("Lưu", on_click=do_add).classes("bg-red-700 text-white")

        # ── Nhập Ngày vào ngành hàng loạt từ Excel ────────────────────────────
        # Luôn xem trước (dry_run) rồi mới ghi: file danh sách cán bộ hay lệch mã
        # với DB, ghi thẳng thì không ai biết ai bị bỏ sót.
        join_file = {"name": None, "bytes": None}
        join_import_dialog = ui.dialog()
        with join_import_dialog, ui.card().classes("w-[34rem] p-6"):
            ui.label("Nhập Ngày vào ngành từ Excel").classes("text-lg font-bold")
            ui.label("Khớp theo cột Mã cán bộ. File cần có 2 cột: "
                     "'Mã cán bộ' và 'Ngày vào ngành' (dd/mm/yyyy)."
                     ).classes("text-xs text-gray-500 mb-3")

            ji_overwrite = ui.checkbox("Ghi đè cả người đã có ngày vào ngành").classes("text-sm")
            ji_result = ui.column().classes("w-full mt-2 gap-1")

            def _render_preview(r: dict):
                ji_result.clear()
                with ji_result:
                    ui.label(f"Đọc được {r['total_rows']} dòng").classes("text-sm font-semibold")
                    ui.label(f"• Sẽ cập nhật: {r['updated']}").classes("text-sm text-green-700")
                    ui.label(f"• Đã đúng, bỏ qua: {r['unchanged']}").classes("text-sm text-gray-600")
                    for key, title, color in (
                        ("kept_existing", "Đã có ngày khác — giữ nguyên", "text-amber-700"),
                        ("not_found", "Không tìm thấy mã cán bộ trong hệ thống", "text-red-600"),
                        ("bad_date", "Ô ngày trống hoặc không đọc được", "text-red-600"),
                    ):
                        lst = r.get(key) or []
                        if not lst:
                            continue
                        with ui.expansion(f"{title}: {len(lst)}").classes(f"w-full text-sm {color}"):
                            for line in lst[:60]:
                                ui.label(line).classes("text-xs text-gray-600")
                            if len(lst) > 60:
                                ui.label(f"… và {len(lst) - 60} dòng nữa").classes("text-xs text-gray-400")

            async def _join_preview():
                if not join_file["bytes"]:
                    return
                qs = f"?dry_run=true&overwrite={'true' if ji_overwrite.value else 'false'}"
                try:
                    r = await asyncio.to_thread(
                        api.post_upload, f"/api/staff/import-join-dates{qs}",
                        {"file": (join_file["name"], join_file["bytes"],
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    )
                except Exception as ex:
                    if _handle_api_error(ex): return
                    ji_result.clear()
                    with ji_result:
                        ui.label(str(ex)).classes("text-sm text-red-600")
                    ji_apply.disable()
                    return
                _render_preview(r)
                (ji_apply.enable if r["updated"] else ji_apply.disable)()

            async def _join_upload(e):
                join_file["name"] = e.name
                join_file["bytes"] = e.content.read()
                await _join_preview()

            async def _join_apply():
                if not join_file["bytes"]:
                    ui.notify("Chưa chọn file", type="warning")
                    return
                qs = f"?overwrite={'true' if ji_overwrite.value else 'false'}"
                try:
                    r = await asyncio.to_thread(
                        api.post_upload, f"/api/staff/import-join-dates{qs}",
                        {"file": (join_file["name"], join_file["bytes"],
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    )
                except Exception as ex:
                    if _handle_api_error(ex): return
                    ui.notify(str(ex), type="negative")
                    return
                ui.notify(f"Đã cập nhật {r['updated']} người", type="positive")
                join_import_dialog.close()
                await load_staff()

            ui.upload(label="Chọn file Excel", on_upload=_join_upload, auto_upload=True
                      ).props('accept=".xlsx,.xlsm" flat dense').classes("w-full")
            ji_overwrite.on_value_change(lambda _e: _join_preview())
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Đóng", on_click=lambda: join_import_dialog.close()).classes("text-gray-500")
                ji_apply = ui.button("Ghi vào hệ thống", on_click=_join_apply).classes("bg-red-700 text-white")
            ji_apply.disable()

        # ── Controls ──────────────────────────────────────────────────────────
        with ui.row().classes("w-full justify-between items-center mb-4 gap-2 flex-wrap"):
            with ui.row().classes("items-center gap-2"):
                search = ui.input(placeholder="Tên hoặc username...").classes("w-52").props("dense")
                dept_filter_opts = {0: "Tất cả phòng", **{d["id"]: d["name"] for d in all_depts}}
                dept_filter = ui.select(dept_filter_opts, value=0, label="Phòng").classes("w-48").props("dense")
                ui.button("Tìm kiếm", icon="search", on_click=lambda: render_staff_rows()).classes("bg-gray-700 text-white").props("dense")
            if is_admin:
                if api.has_feature("staff.create"):
                    ui.button("+ Thêm tài khoản", on_click=lambda: add_dialog.open()).classes("bg-red-700 text-white").props("dense")
                async def _do_export_excel():
                    try:
                        from datetime import date
                        data = await asyncio.to_thread(api.download, "/api/staff/export")
                        ui.download(data, f"danh_sach_can_bo_{date.today().strftime('%Y%m%d')}.xlsx")
                    except Exception as e:
                        if _handle_api_error(e): return
                        ui.notify(str(e), type="negative")

                async def do_export():
                    try:
                        data = await asyncio.to_thread(api.download, "/api/staff/export-db")
                        from datetime import date
                        ui.download(data, f"users_{date.today().strftime('%Y%m%d')}.db")
                    except Exception as e:
                        if _handle_api_error(e): return
                        ui.notify(str(e), type="negative")
                if api.has_feature("staff.export"):
                    ui.button("Xuất Excel", icon="download", on_click=lambda: asyncio.ensure_future(_do_export_excel())).props("dense").classes("bg-green-700 text-white")
                    ui.button("Xuất DB", icon="download", on_click=do_export).props("dense outline").classes("text-gray-700")
                if api.has_feature("staff.import_join_date"):
                    ui.button("Nhập Ngày vào ngành", icon="event",
                              on_click=lambda: join_import_dialog.open()
                              ).props("dense outline").classes("text-blue-700")
                if api.has_feature("staff.import_db"):
                    # Truyền THẲNG hàm async — bọc create_task làm rỗng ngăn xếp
                    # slot của NiceGUI, ui.notify bên trong sẽ im lặng không hiện
                    import_input = ui.upload(
                        label="Nhập DB",
                        on_upload=lambda e: _do_import(e),
                        auto_upload=True,
                    ).props('accept=".db" dense flat').classes("text-gray-700")

                async def _do_import(e):
                    try:
                        result = await asyncio.to_thread(
                            api.post_upload,
                            "/api/staff/import-db",
                            {"file": (e.name, e.content.read(), "application/octet-stream")},
                        )
                        bo_qua = result.get("skipped") or []
                        msg = f"Nhập xong: +{result['inserted']} mới, ~{result['updated']} cập nhật"
                        if bo_qua:
                            # Dòng bị bỏ phải hiện ra: im lặng bỏ qua là kiểu hỏng
                            # tệ nhất — người nhập tưởng đã vào đủ
                            msg += f", BỎ QUA {len(bo_qua)} dòng"
                            ui.notify(msg, type="warning", timeout=0, close_button="Đóng")
                            for d in bo_qua[:10]:
                                ui.notify(d, type="warning", timeout=0, close_button="Đóng")
                        else:
                            ui.notify(msg, type="positive")
                        await load_staff()
                    except Exception as ex:
                        if _handle_api_error(ex): return
                        ui.notify(str(ex), type="negative")

        staff_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
        with staff_loading:
            ui.spinner(size="2em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
        # overflow-x-auto: màn hình hẹp thì cuộn ngang, KHÔNG bóp cột lại
        rows_container = ui.column().classes("w-full overflow-x-auto")

        def open_edit(s: dict):
            edit_target["id"] = s["id"]
            ef_name.set_value(s["full_name"])
            ef_empcode.set_value(s.get("employee_code") or "")
            ef_role.set_value(s["role"])
            ef_dept.set_value(s.get("department_id"))
            ef_phone.set_value(s.get("phone") or "")
            ef_join_date.set_value(s.get("join_industry_date") or "")
            ef_ipcas.set_value(s.get("ipcas_code") or "")
            ef_payment.set_value(s.get("payment_username") or "")
            ef_active.set_value(s.get("is_active", True))
            _sync_edit_dept()
            edit_dialog.open()

        def render_staff_rows():
            rows_container.clear()
            q = search.value.lower()
            sel_dept = dept_filter.value  # 0 = all
            filtered = [
                s for s in staff_cache
                if (not q or q in s["full_name"].lower()
                    or q in s.get("username", "").lower()
                    or q in s.get("employee_code", "").lower())
                and (sel_dept == 0 or s.get("department_id") == sel_dept)
            ]
            # Phân loại: Ban GĐ / Quản trị viên / tất cả phòng còn lại
            _BGD_ROLES = {"giam_doc", "pho_giam_doc"}
            bgd_list   = [s for s in filtered if s.get("role") in _BGD_ROLES]
            admin_list = [s for s in filtered if s.get("role") in _ADMIN_ROLES]
            dept_list  = [s for s in filtered if s.get("role") not in _BGD_ROLES and s.get("role") not in _ADMIN_ROLES]

            with rows_container:
                # Header
                with ui.row().classes(_HDR_ROW).style(_ROW_STYLE):
                    ui.label("Họ tên").classes("w-56 shrink-0 truncate")
                    ui.label("Mã cán bộ").classes("w-28 shrink-0")
                    ui.label("Ngày vào ngành").classes("w-28 shrink-0 text-center")
                    ui.label("Quyền").classes("w-28 shrink-0 text-center")
                    ui.label("Phòng").classes("w-36 shrink-0")
                    ui.label("Username").classes("w-24 shrink-0")
                    ui.label("User IPCAS").classes("w-24 shrink-0 text-center")
                    ui.label("User Payment").classes("w-32 shrink-0")
                    ui.label("TT").classes("w-16 shrink-0 text-center")
                    if is_admin:
                        ui.label("Thao tác").classes("w-16 shrink-0 text-center")
                    ui.space()   # hút chỗ thừa về cuối, không để cột Họ tên giãn ra

                def _fmt_join(iso_str):
                    if not iso_str:
                        return "—"
                    try:
                        from datetime import date as _date
                        return _date.fromisoformat(str(iso_str)[:10]).strftime("%d/%m/%Y")
                    except Exception:
                        return str(iso_str)

                def _row(s: dict):
                    dname = dept_id_to_name.get(s.get("department_id"), "—")
                    with ui.row().classes(_DATA_ROW).style(_ROW_STYLE):
                        ui.label(s["full_name"]).classes("w-56 shrink-0 truncate text-sm")
                        ui.label(s.get("employee_code") or "—").classes("w-28 shrink-0 text-sm font-mono text-gray-500")
                        ui.label(_fmt_join(s.get("join_industry_date"))).classes("w-28 shrink-0 text-center text-sm text-gray-600")
                        ui.label(role_map.get(s["role"], s["role"])).classes("w-28 shrink-0 truncate text-center text-sm")
                        ui.label(dname).classes("w-36 shrink-0 truncate text-sm text-gray-600")
                        ui.label(s.get("username", "")).classes("w-24 shrink-0 truncate text-sm text-gray-500")
                        ui.label(s.get("ipcas_code") or "—").classes("w-24 shrink-0 truncate text-center text-sm font-mono text-gray-600")
                        ui.label(s.get("payment_username") or "—").classes("w-32 shrink-0 truncate text-sm text-gray-500")
                        if s.get("is_active"):
                            ui.badge("Hoạt động").classes("w-16 shrink-0 text-center").props('color="positive"')
                        else:
                            ui.badge("Tạm khóa").classes("w-16 shrink-0 text-center").props('color="grey"')
                        if is_admin:
                            # Cấp 2 không được thao tác trên tài khoản cấp 1
                            _locked = acting_is_l2 and s.get("role") == "admin"
                            with ui.row().classes("w-16 shrink-0 gap-0 justify-center"):
                                if _locked:
                                    ui.icon("lock").classes("text-gray-300 text-sm").tooltip("Chỉ QTV cấp 1 thao tác được")
                                else:
                                    if api.has_feature("staff.edit"):
                                        ui.button(icon="edit", on_click=lambda s=s: open_edit(s)).props("flat dense").classes("text-red-600").tooltip("Sửa")
                                    if api.has_feature("staff.delete"):
                                        ui.button(icon="delete", on_click=lambda sid=s["id"], nm=s["full_name"]: do_deactivate_staff(sid, nm)).props("flat dense").classes("text-red-500").tooltip("Xóa")
                        ui.space()

                # Nhóm Ban Giám đốc
                if bgd_list:
                    with ui.row().classes("w-full min-w-max px-3 py-1 bg-red-50 text-xs text-red-700 font-semibold border-b border-red-100 items-center gap-1"):
                        ui.icon("star").classes("text-sm")
                        ui.label("Ban Giám đốc")
                    for s in bgd_list:
                        _row(s)

                # Nhóm Quản trị viên
                if admin_list:
                    with ui.row().classes("w-full min-w-max px-3 py-1 bg-purple-50 text-xs text-purple-700 font-semibold border-b border-purple-100 items-center gap-1"):
                        ui.icon("admin_panel_settings").classes("text-sm")
                        ui.label("Quản trị viên")
                    for s in admin_list:
                        _row(s)

                # Nhóm theo phòng — Admin/HKV/TP/PP/CV gộp theo department_id
                if dept_list:
                    by_dept: dict = {}
                    for s in dept_list:
                        by_dept.setdefault(s.get("department_id"), []).append(s)
                    for dept_id, members in sorted(by_dept.items(),
                                                   key=lambda x: dept_id_to_name.get(x[0], "")):
                        dname = dept_id_to_name.get(dept_id, "Chưa phân phòng")
                        with ui.row().classes("w-full min-w-max px-3 py-1 bg-blue-50 text-xs text-blue-700 font-semibold border-b border-blue-100 items-center gap-1"):
                            ui.icon("badge").classes("text-sm")
                            ui.label(dname)
                        for s in members:
                            _row(s)

                if not filtered:
                    ui.label("Không có kết quả").classes("text-gray-500 text-center py-6 w-full")

        async def load_staff():
            nonlocal staff_cache
            staff_loading.classes(remove="hidden")
            try:
                staff_cache = await asyncio.to_thread(api.get, "/api/staff/", {"active_only": False})
            except Exception as e:
                _handle_api_error(e)
            finally:
                staff_loading.classes(add="hidden")
            render_staff_rows()

        confirm_delete_dialog = ui.dialog()
        confirm_delete_sid = {"id": None, "name": ""}
        with confirm_delete_dialog, ui.card().classes("p-6 w-80"):
            ui.label("Xác nhận xóa tài khoản").classes("text-lg font-bold text-red-700 mb-2")
            confirm_delete_label = ui.label("").classes("text-sm text-gray-700 mb-4")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Hủy", on_click=confirm_delete_dialog.close).props("flat").classes("text-gray-500")
                async def _do_confirm_delete():
                    confirm_delete_dialog.close()
                    try:
                        await asyncio.to_thread(api.delete, f"/api/staff/{confirm_delete_sid['id']}")
                        ui.notify("Đã xóa tài khoản", type="positive")
                        await load_staff()
                    except Exception as ex:
                        if _handle_api_error(ex): return
                ui.button("Xóa", on_click=_do_confirm_delete).classes("bg-red-700 text-white")

        async def do_deactivate_staff(sid: int, name: str = ""):
            confirm_delete_sid["id"] = sid
            confirm_delete_sid["name"] = name
            confirm_delete_label.set_text(f'Bạn có chắc muốn xóa tài khoản "{name}" không? Thao tác này không thể hoàn tác.')
            confirm_delete_dialog.open()

        await load_staff()
