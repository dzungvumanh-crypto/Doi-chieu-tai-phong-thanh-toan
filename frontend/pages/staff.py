"""Trang quản lý tài khoản cán bộ TTTT."""
import asyncio
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _redirect_if_cv, _handle_api_error


@ui.page("/staff")
async def staff_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return

    try:
        all_depts = await asyncio.to_thread(api.get, "/api/departments/")
    except Exception:
        all_depts = []
    dept_id_to_name = {d["id"]: d["name"] for d in all_depts}
    all_dept_opts   = {d["id"]: d["name"] for d in all_depts}

    _ = _sidebar("staff")
    with _content_area():
        _page_header("Quản lý User", "Quản lý tài khoản đăng nhập hệ thống")

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") == "admin"

        ROLE_OPTS = {
            "chuyen_vien":   "Chuyên viên",
            "pho_phong":     "Phó phòng",
            "truong_phong":  "Trưởng phòng",
            "hau_kiem_vien": "Hậu kiểm viên",
            "giam_doc":      "Giám đốc",
            "pho_giam_doc":  "Phó Giám đốc",
            "admin":         "Quản trị viên",
        }
        # controller kept in display map cho JWT session cũ chưa expire
        role_map = {**ROLE_OPTS, "controller": "Phó phòng"}

        staff_cache = []
        edit_target = {"id": None}

        # ── Edit dialog ───────────────────────────────────────────────────────
        edit_dialog = ui.dialog()
        with edit_dialog, ui.card().classes("w-[28rem] p-6"):
            ui.label("Sửa tài khoản").classes("text-lg font-bold mb-4")
            ef_name        = ui.input("Họ tên *").classes("w-full")
            ef_empcode     = ui.input("Mã cán bộ").props('placeholder="VD: 201700886"').classes("w-full mt-2")
            ef_role        = ui.select(ROLE_OPTS, label="Quyền *").classes("w-full mt-2")
            ef_dept        = ui.select(all_dept_opts, label="Phòng *").classes("w-full mt-2")
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
                    if not ef_dept.value:
                        ui.notify("Vui lòng chọn Phòng", type="warning")
                        return
                    try:
                        await asyncio.to_thread(api.put, f"/api/staff/{edit_target['id']}", {
                            "employee_code": ef_empcode.value.strip() or None,
                            "full_name": ef_name.value,
                            "role": ef_role.value,
                            "phone": ef_phone.value or None,
                            "is_active": ef_active.value,
                            "department_id": ef_dept.value,
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
            f_role       = ui.select(ROLE_OPTS, label="Quyền *", value="chuyen_vien").classes("w-full mt-2")
            f_dept       = ui.select(all_dept_opts, label="Phòng *").classes("w-full mt-2")
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
                    if not f_dept.value:
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
                            "department_id": f_dept.value,
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

        # ── Controls ──────────────────────────────────────────────────────────
        with ui.row().classes("w-full justify-between items-center mb-4 gap-2 flex-wrap"):
            with ui.row().classes("items-center gap-2"):
                search = ui.input(placeholder="Tên hoặc username...").classes("w-52").props("dense")
                dept_filter_opts = {0: "Tất cả phòng", **{d["id"]: d["name"] for d in all_depts}}
                dept_filter = ui.select(dept_filter_opts, value=0, label="Phòng").classes("w-48").props("dense")
                ui.button("Tìm kiếm", icon="search", on_click=lambda: render_staff_rows()).classes("bg-gray-700 text-white").props("dense")
            if is_admin:
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
                ui.button("Xuất Excel", icon="download", on_click=lambda: asyncio.ensure_future(_do_export_excel())).props("dense").classes("bg-green-700 text-white")
                ui.button("Xuất DB", icon="download", on_click=do_export).props("dense outline").classes("text-gray-700")
                import_input = ui.upload(
                    label="Nhập DB",
                    on_upload=lambda e: asyncio.create_task(_do_import(e)),
                    auto_upload=True,
                ).props('accept=".db" dense flat').classes("text-gray-700")

                async def _do_import(e):
                    try:
                        result = await asyncio.to_thread(
                            api.post_upload,
                            "/api/staff/import-db",
                            {"file": (e.name, e.content.read(), "application/octet-stream")},
                        )
                        ui.notify(f"Nhập xong: +{result['inserted']} mới, ~{result['updated']} cập nhật", type="positive")
                        await load_staff()
                    except Exception as ex:
                        if _handle_api_error(ex): return
                        ui.notify(str(ex), type="negative")

        staff_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
        with staff_loading:
            ui.spinner(size="2em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
        rows_container = ui.column().classes("w-full")

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
            # Phân loại: Ban GĐ / tất cả phòng còn lại
            _BGD_ROLES = {"giam_doc", "pho_giam_doc"}
            bgd_list  = [s for s in filtered if s.get("role") in _BGD_ROLES]
            dept_list = [s for s in filtered if s.get("role") not in _BGD_ROLES]

            with rows_container:
                # Header
                with ui.row().classes("w-full px-3 py-2 bg-red-50 font-semibold text-xs text-red-800 border border-red-100 rounded-t"):
                    ui.label("Họ tên").classes("flex-1")
                    ui.label("Mã cán bộ").classes("w-28")
                    ui.label("Quyền").classes("w-28 text-center")
                    ui.label("Phòng").classes("w-36")
                    ui.label("Username").classes("w-24")
                    ui.label("Vào ngành / Phép").classes("w-32 text-center")
                    ui.label("User IPCAS").classes("w-24 text-center")
                    ui.label("User Payment").classes("w-32")
                    ui.label("TT").classes("w-16 text-center")
                    if is_admin:
                        ui.label("Thao tác").classes("w-16 text-center")

                def _fmt_join(iso_str, leave_days):
                    if not iso_str:
                        return "—"
                    try:
                        from datetime import date as _date
                        d = _date.fromisoformat(str(iso_str))
                        return f"{d.strftime('%d/%m/%Y')} ({leave_days or 12}n)"
                    except Exception:
                        return str(iso_str)

                def _row(s: dict):
                    dname = dept_id_to_name.get(s.get("department_id"), "—")
                    with ui.row().classes("w-full px-3 py-2 border-b border-gray-100 items-center hover:bg-gray-50"):
                        ui.label(s["full_name"]).classes("flex-1 text-sm")
                        ui.label(s.get("employee_code") or "—").classes("w-28 text-sm font-mono text-gray-500")
                        ui.label(role_map.get(s["role"], s["role"])).classes("w-28 text-center text-sm")
                        ui.label(dname).classes("w-36 text-sm text-gray-600")
                        ui.label(s.get("username", "")).classes("w-24 text-sm text-gray-500")
                        ui.label(_fmt_join(s.get("join_industry_date"), s.get("annual_leave_days"))).classes("w-32 text-center text-xs text-gray-600")
                        ui.label(s.get("ipcas_code") or "—").classes("w-24 text-center text-sm font-mono text-gray-600")
                        ui.label(s.get("payment_username") or "—").classes("w-32 text-sm text-gray-500")
                        if s.get("is_active"):
                            ui.badge("Hoạt động").classes("w-16 text-center").props('color="positive"')
                        else:
                            ui.badge("Tạm khóa").classes("w-16 text-center").props('color="grey"')
                        if is_admin:
                            with ui.row().classes("w-16 gap-0 justify-center"):
                                ui.button(icon="edit", on_click=lambda s=s: open_edit(s)).props("flat dense").classes("text-red-600").tooltip("Sửa")
                                ui.button(icon="delete", on_click=lambda sid=s["id"], nm=s["full_name"]: do_deactivate_staff(sid, nm)).props("flat dense").classes("text-red-500").tooltip("Xóa")

                # Nhóm Ban Giám đốc
                if bgd_list:
                    with ui.row().classes("w-full px-3 py-1 bg-red-50 text-xs text-red-700 font-semibold border-b border-red-100 items-center gap-1"):
                        ui.icon("star").classes("text-sm")
                        ui.label("Ban Giám đốc")
                    for s in bgd_list:
                        _row(s)

                # Nhóm theo phòng — Admin/HKV/TP/PP/CV gộp theo department_id
                if dept_list:
                    by_dept: dict = {}
                    for s in dept_list:
                        by_dept.setdefault(s.get("department_id"), []).append(s)
                    for dept_id, members in sorted(by_dept.items(),
                                                   key=lambda x: dept_id_to_name.get(x[0], "")):
                        dname = dept_id_to_name.get(dept_id, "Chưa phân phòng")
                        with ui.row().classes("w-full px-3 py-1 bg-blue-50 text-xs text-blue-700 font-semibold border-b border-blue-100 items-center gap-1"):
                            ui.icon("badge").classes("text-sm")
                            ui.label(dname)
                        for s in members:
                            _row(s)

                if not filtered:
                    ui.label("Không có kết quả").classes("text-gray-400 text-center py-6 w-full")

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
