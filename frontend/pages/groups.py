"""Trang quản lý nhóm user — Quản trị viên cấp 1 và cấp 2."""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

_ROLE_LABEL = {
    "admin": "Quản trị viên cấp 1",
    "admin_l2": "Quản trị viên cấp 2",
    "hau_kiem_vien": "Hậu kiểm viên",
    "truong_phong": "Trưởng phòng",
    "pho_phong": "Phó phòng",
    "chuyen_vien": "Chuyên viên",
    "giam_doc": "Giám đốc",
    "pho_giam_doc": "Phó Giám đốc",
}

_ROLE_ORDER = {
    "giam_doc": 0,
    "pho_giam_doc": 1,
    "admin_l2": 2,
    "truong_phong": 3,
    "pho_phong": 4,
    "hau_kiem_vien": 5,
    "chuyen_vien": 6,
}


@ui.page("/groups")
async def groups_page():
    if not _require_auth():
        return
    user = api.get_current_user()
    if not user or user.get("role") not in ("admin", "admin_l2"):
        ui.navigate.to("/home")
        return
    # Cấp 2 không được thao tác lên nhóm chứa chính mình (tự nâng quyền).
    # Backend chặn thật; đây chỉ là lớp hiển thị để không bấm rồi nhận 403.
    la_cap_2 = user.get("role") == "admin_l2"
    my_id = user.get("id")

    await _sidebar("groups")
    with _content_area():
        _page_header("Nhóm user", "Tạo nhóm, quản lý thành viên và phân quyền chức năng")

        # ── State ──────────────────────────────────────────────────────────────
        selected_group: dict = {}
        groups_data: list = []
        members_data: list = []
        all_staff: list = []

        # ── UI refs ────────────────────────────────────────────────────────────
        group_list_col = None
        detail_col = None
        member_table_ref: dict = {"table": None}
        group_name_input = None
        group_desc_input = None
        group_active_checkbox = None
        no_selection_label = None
        detail_card = None
        add_user_select = None
        save_btn = delete_btn = add_member_btn = None
        locked_note = None

        # ── Load helpers ───────────────────────────────────────────────────────
        async def load_groups():
            nonlocal groups_data
            try:
                groups_data = await asyncio.to_thread(api.get, "/api/groups")
                _render_group_list()
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")

        def _refresh_add_options():
            current_member_ids = {m["id"] for m in members_data}
            add_user_select.options = {
                str(s["id"]): f"{s['full_name']} — {_ROLE_LABEL.get(s['role'], s['role'])}"
                for s in all_staff
                if s["id"] not in current_member_ids and s["role"] != "admin"
                and not (la_cap_2 and s["id"] == my_id)
            }
            add_user_select.update()

        async def load_members(group_id: int):
            nonlocal members_data
            try:
                members_data = await asyncio.to_thread(
                    api.get, f"/api/groups/{group_id}/members"
                )
                _render_members()
                _refresh_add_options()
            except Exception as e:
                if _handle_api_error(e):
                    return

        async def load_all_staff():
            nonlocal all_staff
            try:
                all_staff = await asyncio.to_thread(api.get, "/api/staff/")
            except Exception:
                all_staff = []

        # ── Render group list ──────────────────────────────────────────────────
        def _render_group_list():
            group_list_col.clear()
            with group_list_col:
                for g in groups_data:
                    is_sel = selected_group.get("id") == g["id"]
                    if is_sel:
                        row_cls  = "bg-red-700 text-white"
                        sub_cls  = "text-xs text-red-200"
                        icon_cls = "text-base mr-2 shrink-0 text-white"
                    else:
                        row_cls  = "text-gray-800 hover:bg-red-50"
                        sub_cls  = "text-xs text-gray-500"
                        icon_cls = "text-base mr-2 shrink-0 text-red-700"
                    with ui.row().classes(
                        f"w-full items-center px-3 py-2.5 cursor-pointer rounded-lg {row_cls}"
                    ).on("click", lambda gid=g["id"]: asyncio.ensure_future(_select_group(gid))):
                        ui.icon("group").classes(icon_cls)
                        with ui.column().classes("flex-1 min-w-0"):
                            ui.label(g["name"]).classes("text-sm font-medium truncate")
                            status = "Hoạt động" if g["is_active"] else "Tạm dừng"
                            ui.label(f"{g['member_count']} thành viên • {status}").classes(sub_cls)

        async def _select_group(group_id: int):
            nonlocal selected_group
            selected_group = next((g for g in groups_data if g["id"] == group_id), {})
            _render_group_list()
            _show_detail()
            await load_members(group_id)

        # ── Detail panel ───────────────────────────────────────────────────────
        def _bi_khoa() -> bool:
            """Cấp 2 mở nhóm mà chính mình là thành viên → chỉ được xem."""
            return la_cap_2 and bool(selected_group.get("contains_me"))

        def _show_detail():
            no_selection_label.set_visibility(False)
            detail_card.set_visibility(True)
            khoa = _bi_khoa()
            locked_note.set_visibility(khoa)
            for el in (save_btn, delete_btn, add_member_btn, add_user_select,
                       group_name_input, group_desc_input, group_active_checkbox):
                el.set_enabled(not khoa)
            group_name_input.set_value(selected_group.get("name", ""))
            group_desc_input.set_value(selected_group.get("description") or "")
            group_active_checkbox.set_value(bool(selected_group.get("is_active", True)))

        def _render_members():
            sorted_members = sorted(
                (m for m in members_data if m["role"] != "admin"),
                key=lambda m: _ROLE_ORDER.get(m["role"], 99),
            )

            def _remove_cb(mid: int):
                async def _cb():
                    await remove_member(mid)
                return _cb

            container = member_table_ref["table"]
            container.clear()
            with container:
                if not sorted_members:
                    ui.label("Chưa có thành viên nào").classes("text-gray-500 text-sm py-2")
                    return
                with ui.row().classes(
                    "w-full px-2 py-1.5 bg-red-50 border-b border-red-100 "
                    "text-xs font-semibold text-red-700"
                ):
                    ui.label("Họ tên").classes("flex-1")
                    ui.label("Chức vụ").classes("w-28")
                    ui.label("Phòng ban").classes("flex-1")
                    ui.element("div").classes("w-8")
                for m in sorted_members:
                    with ui.row().classes(
                        "w-full px-2 py-2 border-b border-gray-100 items-center hover:bg-gray-50"
                    ):
                        ui.label(m["full_name"]).classes("flex-1 text-sm")
                        ui.label(_ROLE_LABEL.get(m["role"], m["role"])).classes("w-28 text-sm text-gray-600")
                        ui.label(m.get("department_name") or "—").classes("flex-1 text-sm text-gray-600")
                        ui.button(
                            icon="person_remove",
                            on_click=_remove_cb(m["id"])
                        ).props("flat dense color=red-6").set_enabled(not _bi_khoa())

        # ── Actions ────────────────────────────────────────────────────────────
        async def save_group():
            gid = selected_group.get("id")
            if not gid:
                return
            try:
                await asyncio.to_thread(api.put, f"/api/groups/{gid}", {
                    "name": group_name_input.value.strip(),
                    "description": group_desc_input.value.strip() or None,
                    "is_active": group_active_checkbox.value,
                })
                ui.notify("Đã lưu nhóm", type="positive")
                await load_groups()
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")

        async def delete_group():
            gid = selected_group.get("id")
            if not gid:
                return

            async def _confirm_delete():
                dialog.close()
                try:
                    await asyncio.to_thread(api.delete, f"/api/groups/{gid}")
                    ui.notify("Đã xóa nhóm", type="positive")
                    selected_group.clear()
                    no_selection_label.set_visibility(True)
                    detail_card.set_visibility(False)
                    await load_groups()
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(str(e), type="negative")

            with ui.dialog() as dialog, ui.card().classes("p-6 w-80"):
                ui.label("Xác nhận xóa nhóm").classes("text-lg font-bold text-red-800 mb-2")
                ui.label(f"Xóa nhóm '{selected_group.get('name')}'? Thao tác không thể hoàn tác.").classes("text-sm text-gray-600 mb-4")
                with ui.row().classes("justify-end gap-2"):
                    ui.button("Hủy", on_click=dialog.close).props("flat")
                    ui.button("Xóa", on_click=_confirm_delete).classes("bg-red-600 text-white")
            dialog.open()

        async def create_group_dialog():
            name_inp = None
            desc_inp = None

            async def _do_create():
                n = name_inp.value.strip()
                if not n:
                    ui.notify("Tên nhóm không được trống", type="warning")
                    return
                try:
                    g = await asyncio.to_thread(api.post, "/api/groups", {
                        "name": n,
                        "description": desc_inp.value.strip() or None,
                    })
                    create_dialog.close()
                    ui.notify(f"Đã tạo nhóm '{n}'", type="positive")
                    await load_groups()
                    await _select_group(g["id"])
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(str(e), type="negative")

            with ui.dialog() as create_dialog, ui.card().classes("p-6 w-96"):
                ui.label("Tạo nhóm mới").classes("text-lg font-bold text-red-800 mb-4")
                name_inp = ui.input("Tên nhóm *").classes("w-full")
                desc_inp = ui.input("Mô tả (tùy chọn)").classes("w-full mt-2")
                with ui.row().classes("justify-end gap-2 mt-4"):
                    ui.button("Hủy", on_click=create_dialog.close).props("flat")
                    ui.button("Tạo nhóm", on_click=_do_create).classes("bg-red-700 text-white")
            create_dialog.open()

        async def add_member():
            gid = selected_group.get("id")
            if not gid or not add_user_select.value:
                ui.notify("Chọn nhân viên cần thêm", type="warning")
                return
            try:
                await asyncio.to_thread(api.post, f"/api/groups/{gid}/members", {
                    "staff_id": int(add_user_select.value)
                })
                add_user_select.set_value(None)
                ui.notify("Đã thêm thành viên", type="positive")
                await load_members(gid)
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")

        async def remove_member(staff_id: int):
            gid = selected_group.get("id")
            if not gid:
                return
            try:
                await asyncio.to_thread(api.delete, f"/api/groups/{gid}/members/{staff_id}")
                ui.notify("Đã xóa thành viên", type="positive")
                await load_members(gid)
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")

        # ── Layout ─────────────────────────────────────────────────────────────
        with ui.row().classes("w-full gap-4 items-start"):
            # Cột trái — danh sách nhóm
            with ui.card().classes("w-72 shrink-0 shadow-sm rounded-xl overflow-hidden"):
                with ui.row().classes("w-full bg-red-50 px-4 py-3 border-b border-red-100 items-center"):
                    ui.label("Danh sách nhóm").classes("font-semibold text-red-800 flex-1")
                    ui.button(icon="add", on_click=create_group_dialog).props("flat dense").classes("text-red-700")
                with ui.column().classes("w-full p-2 gap-1") as group_list_col:
                    ui.label("Đang tải...").classes("text-gray-500 text-sm px-2 py-2")

            # Cột phải — chi tiết nhóm
            with ui.column().classes("flex-1 gap-4"):
                with ui.label("Chọn một nhóm ở bên trái để xem chi tiết") as no_selection_label:
                    no_selection_label.classes("text-gray-500 text-sm py-4")

                with ui.column().classes("w-full gap-4") as detail_card:
                    detail_card.set_visibility(False)

                    # Card thông tin nhóm
                    with ui.card().classes("w-full shadow-sm rounded-xl overflow-hidden"):
                        with ui.row().classes("w-full bg-red-50 px-4 py-3 border-b border-red-100"):
                            ui.label("Thông tin nhóm").classes("font-semibold text-red-800")
                        with ui.column().classes("p-4 gap-3"):
                            group_name_input = ui.input("Tên nhóm *").classes("w-full")
                            group_desc_input = ui.input("Mô tả").classes("w-full")
                            group_active_checkbox = ui.checkbox("Đang hoạt động")
                            locked_note = ui.label(
                                "Bạn là thành viên của nhóm này — Quản trị viên cấp 2 "
                                "chỉ được xem, không sửa được nhóm của chính mình."
                            ).classes("text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 w-full")
                            locked_note.set_visibility(False)
                            with ui.row().classes("gap-2"):
                                save_btn = ui.button(
                                    "Lưu thay đổi", icon="save", on_click=save_group
                                ).classes("bg-red-700 text-white")
                                delete_btn = ui.button(
                                    "Xóa nhóm", icon="delete", on_click=delete_group
                                ).props("flat").classes("text-red-500")

                    # Card thành viên
                    with ui.card().classes("w-full shadow-sm rounded-xl overflow-hidden"):
                        with ui.row().classes("w-full bg-red-50 px-4 py-3 border-b border-red-100"):
                            ui.label("Thành viên").classes("font-semibold text-red-800")
                        with ui.column().classes("p-4 gap-3"):
                            with ui.row().classes("w-full gap-2 items-end"):
                                add_user_select = ui.select(
                                    options={},
                                    label="Thêm nhân viên",
                                    with_input=True,
                                ).classes("flex-1")
                                add_member_btn = ui.button(
                                    "Thêm", icon="person_add", on_click=add_member
                                ).classes("bg-red-700 text-white")

                            with ui.column().classes(
                                "w-full rounded border border-gray-100 overflow-hidden"
                            ) as member_col:
                                pass
                            member_table_ref["table"] = member_col

        # ── Initial load ───────────────────────────────────────────────────────
        async def _init():
            groups, staff = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/groups"),
                asyncio.to_thread(api.get, "/api/staff/"),
                return_exceptions=True,
            )
            if isinstance(groups, Exception):
                if _handle_api_error(groups):
                    return
            else:
                nonlocal groups_data, all_staff
                groups_data = groups
                _render_group_list()
            if not isinstance(staff, Exception):
                all_staff = staff

        asyncio.ensure_future(_init())
