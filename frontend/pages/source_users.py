"""Trang danh sách giao dịch viên."""
import asyncio
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _redirect_if_cv, _handle_api_error


@ui.page("/source_users")
async def source_users_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _ = _sidebar("source_users")
    with _content_area():
        _page_header("Danh sách giao dịch viên", "User IPCAS, PaymentHub và Họ tên giao dịch viên các phòng")

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") in ("admin", "hau_kiem_vien")

        try:
            depts = [d for d in await asyncio.to_thread(api.get, "/api/departments/") if d.get("is_active", True)]
        except Exception:
            depts = []

        dept_options = {d["id"]: d["name"] for d in depts}
        edit_su_target = {"id": None}

        # ── Edit dialog ───────────────────────────────────────────────────────
        edit_su_dialog = ui.dialog()
        with edit_su_dialog, ui.card().classes("w-96 p-6"):
            ui.label("Sửa thông tin cán bộ").classes("text-lg font-bold mb-4")
            esu_ipcas  = ui.input("User IPCAS *").classes("w-full")
            esu_hub    = ui.input("User PaymentHub").classes("w-full mt-2")
            esu_vn     = ui.input("Họ và tên").classes("w-full mt-2")
            esu_dept   = ui.select(dept_options, label="Phòng *").classes("w-full mt-2")
            esu_active = ui.checkbox("Đang hoạt động").classes("mt-3")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=lambda: edit_su_dialog.close()).classes("text-gray-500")
                async def do_edit_su():
                    if not edit_su_target["id"]:
                        return
                    try:
                        await asyncio.to_thread(api.put, f"/api/source-users/{edit_su_target['id']}", {
                            "user_code": esu_ipcas.value,
                            "full_name": esu_hub.value or None,
                            "vn_name": esu_vn.value or None,
                            "department_id": esu_dept.value,
                            "is_active": esu_active.value,
                        })
                    except Exception as e:
                        if _handle_api_error(e): return
                        return
                    edit_su_dialog.close()
                    ui.notify("Đã cập nhật cán bộ", type="positive")
                    await load_users()
                ui.button("Lưu", on_click=do_edit_su).classes("bg-red-700 text-white")

        # ── Add dialog ────────────────────────────────────────────────────────
        user_dialog = ui.dialog()
        with user_dialog, ui.card().classes("w-96 p-6"):
            ui.label("Thêm cán bộ").classes("text-lg font-bold mb-4")
            uf_ipcas = ui.input("User IPCAS *").classes("w-full")
            uf_hub   = ui.input("User PaymentHub").classes("w-full mt-2")
            uf_vn    = ui.input("Họ và tên").classes("w-full mt-2")
            uf_dept  = ui.select(dept_options, label="Phòng *",
                                 value=depts[0]["id"] if depts else None).classes("w-full mt-2")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=lambda: user_dialog.close()).classes("text-gray-500")
                async def do_add_user():
                    if not uf_ipcas.value or not uf_dept.value:
                        ui.notify("Vui lòng điền User IPCAS và chọn phòng", type="warning")
                        return
                    try:
                        await asyncio.to_thread(api.post, "/api/source-users/", {
                            "user_code": uf_ipcas.value,
                            "full_name": uf_hub.value or None,
                            "vn_name": uf_vn.value or None,
                            "department_id": uf_dept.value,
                        })
                    except Exception as e:
                        if _handle_api_error(e): return
                        return
                    user_dialog.close()
                    ui.notify("Đã thêm cán bộ", type="positive")
                    await load_users()
                ui.button("Lưu", on_click=do_add_user).classes("bg-red-700 text-white")

        # ── Controls ──────────────────────────────────────────────────────────
        with ui.row().classes("w-full justify-between items-center mb-4"):
            dept_filter = ui.select(
                {**{None: "-- Tất cả phòng --"}, **dept_options},
                label="Lọc theo phòng", value=None
            ).classes("w-72")
            if is_admin:
                ui.button("+ Thêm cán bộ", on_click=lambda: user_dialog.open()).classes("bg-red-700 text-white")

        su_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
        with su_loading:
            ui.spinner(size="2em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
        rows_container = ui.column().classes("w-full")

        def open_edit_su(u: dict):
            edit_su_target["id"] = u["id"]
            esu_ipcas.set_value(u["user_code"])
            esu_hub.set_value(u.get("full_name") or "")
            esu_vn.set_value(u.get("vn_name") or "")
            esu_dept.set_value(u["department_id"])
            esu_active.set_value(u.get("is_active", True))
            edit_su_dialog.open()

        async def load_users():
            su_loading.classes(remove="hidden")
            rows_container.clear()
            try:
                params: dict = {"active_only": False}
                if dept_filter.value:
                    params["department_id"] = dept_filter.value
                users = await asyncio.to_thread(api.get, "/api/source-users/", params)
            except Exception as e:
                _handle_api_error(e)
                su_loading.classes(add="hidden")
                return
            su_loading.classes(add="hidden")

            with rows_container:
                ui.label(f"{len(users)} cán bộ").classes("text-gray-500 text-sm mb-2")

                with ui.row().classes("w-full px-3 py-2 bg-red-50 font-semibold text-xs text-red-800 border border-red-100 rounded-t"):
                    ui.label("STT").classes("w-10 text-center")
                    ui.label("User IPCAS").classes("w-36")
                    ui.label("User PaymentHub").classes("w-44")
                    ui.label("Họ và tên").classes("flex-1")
                    ui.label("Phòng").classes("w-52")
                    ui.label("TT").classes("w-8 text-center")
                    if is_admin:
                        ui.label("").classes("w-20 text-center")

                for idx, u in enumerate(users):
                    is_active = u.get("is_active", True)

                    def _make_deactivate(uid):
                        async def _h():
                            try:
                                await asyncio.to_thread(api.delete, f"/api/source-users/{uid}")
                            except Exception as e:
                                if _handle_api_error(e): return
                                return
                            ui.notify("Đã ẩn cán bộ (dữ liệu lịch sử được giữ nguyên)", type="positive")
                            await load_users()
                        return _h

                    row_cls = "w-full px-3 py-2 border-b border-gray-100 items-center hover:bg-gray-50"
                    if not is_active:
                        row_cls += " opacity-50"
                    with ui.row().classes(row_cls):
                        ui.label(str(idx + 1)).classes("w-10 text-center text-gray-400 text-sm")
                        ui.label(u["user_code"]).classes("w-36 text-sm font-mono")
                        ui.label(u.get("full_name") or "—").classes("w-44 text-sm text-gray-600")
                        ui.label(u.get("vn_name") or "—").classes("flex-1 text-sm")
                        ui.label(dept_options.get(u["department_id"], "")).classes("w-52 text-sm text-gray-500")
                        if is_active:
                            ui.icon("check_circle").classes("w-8 text-center text-green-500")
                        else:
                            ui.icon("cancel").classes("w-8 text-center text-red-400")
                        if is_admin:
                            with ui.row().classes("w-20 gap-1 justify-center"):
                                ui.button(icon="edit", on_click=lambda u=u: open_edit_su(u)).props("flat dense").classes("text-red-600").tooltip("Sửa")
                                if is_active:
                                    ui.button(icon="visibility_off", on_click=_make_deactivate(u["id"])).props("flat dense").classes("text-gray-500").tooltip("Ẩn (giữ lịch sử)")

                if not users:
                    ui.label("Không có cán bộ nào").classes("text-gray-400 text-center py-6 w-full")

        dept_filter.on("update:model-value", lambda: load_users())
        await load_users()
