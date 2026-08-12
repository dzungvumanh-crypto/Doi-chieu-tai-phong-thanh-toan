"""Trang phân quyền chức năng theo nhóm — chỉ admin.

Cấu trúc phòng/menu/action lấy động từ API — không hardcode ở frontend.
Để thêm phòng/menu mới: chỉ sửa backend/core/features.py, trang này tự cập nhật.
"""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)


@ui.page("/group-features")
async def group_features_page():
    if not _require_auth():
        return
    user = api.get_current_user()
    if not user or user.get("role") != "admin":
        ui.navigate.to("/home")
        return

    _sidebar("group-features")
    with _content_area():
        _page_header("Phân quyền theo nhóm", "Chọn nhóm và tick các chức năng nhóm đó được phép dùng")

        # ── State ──────────────────────────────────────────────────────────────
        groups_data: list        = []
        structure: list          = []          # từ API /features/all
        selected_group_id: dict  = {"value": None}
        current_codes: list      = [set()]     # mutable wrapper tránh rebinding issue
        menu_refs: dict          = {}          # menu_code → checkbox element
        action_refs: dict        = {}          # action_code → checkbox element
        col_refs: dict           = {}          # menu_code → cột chứa action (để ẩn/hiện)
        menu_actions: dict       = {}          # menu_code → list action_code

        group_selector = None
        save_btn       = None
        status_label   = None

        # ── Load nhóm + cấu trúc features ─────────────────────────────────────
        async def load_initial():
            nonlocal groups_data, structure
            try:
                groups_data = await asyncio.to_thread(api.get, "/api/groups")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi tải danh sách nhóm: {e}", type="negative")
                return
            try:
                structure = await asyncio.to_thread(api.get, "/api/groups/features/all")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi tải cấu trúc tính năng: {e}", type="negative")
                return
            group_selector.options = {str(g["id"]): g["name"] for g in groups_data}
            group_selector.update()

        async def on_group_select(e):
            gid = e.value
            if not gid:
                return
            selected_group_id["value"] = int(gid)
            try:
                result = await asyncio.to_thread(api.get, f"/api/groups/{gid}/features")
                current_codes[0] = set(result.get("codes", []))
                _render_features.refresh()
                save_btn.set_visibility(True)
                status_label.set_text("")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")

        # ── Một menu + các action con ─────────────────────────────────────────
        def _menu_block(menu: dict, codes: set, icon: str = "", standalone: bool = False):
            """standalone=True: menu đứng một mình trong thẻ, ô tick đóng vai tiêu đề."""
            mcode    = menu["code"]
            actions  = menu.get("actions", [])
            acodes   = [a["code"] for a in actions]
            mchecked = mcode in codes
            menu_actions[mcode] = acodes

            def _on_menu_toggle(e, code=mcode):
                col = col_refs.get(code)
                if col is not None:
                    col.set_visibility(e.value)
                if not e.value:
                    for c in menu_actions.get(code, []):
                        if c in action_refs:
                            action_refs[c].set_value(False)

            row_cls = "w-full items-center py-2.5"
            if not standalone:
                row_cls += " border-b border-gray-100"
            with ui.row().classes(row_cls):
                if icon:
                    ui.icon(icon).classes("text-red-800 text-lg")
                menu_refs[mcode] = ui.checkbox(
                    menu["label"],
                    value=mchecked,
                    on_change=_on_menu_toggle if acodes else None,
                ).classes(
                    "text-base font-semibold text-red-900" if standalone
                    else "text-sm font-semibold text-gray-800"
                )

            if acodes:
                with ui.column().classes("pl-7 pb-2 pt-1 gap-1 w-full") as action_col:
                    col_refs[mcode] = action_col
                    action_col.set_visibility(mchecked)
                    for action in actions:
                        action_refs[action["code"]] = ui.checkbox(
                            action["label"],
                            value=action["code"] in codes and mchecked,
                        ).classes("text-sm text-gray-600")

        # ── Dải nhãn phòng + nút chọn nhanh ───────────────────────────────────
        def _section_header(label: str, menu_codes: list[str]):
            """Nhãn phòng KHÔNG phải ô tick — luật "mỗi ô tick là một quyền" giữ nguyên.
            Hai nút chỉ tác động lên MENU, không tự cấp ACTION.
            """
            def _set_all(value: bool):
                for c in menu_codes:
                    cb = menu_refs.get(c)
                    if cb is None:
                        continue
                    cb.set_value(value)
                    # Cập nhật thẳng, không dựa vào việc set_value có kích hoạt
                    # on_change hay không — tránh phụ thuộc chi tiết nội bộ NiceGUI.
                    col = col_refs.get(c)
                    if col is not None:
                        col.set_visibility(value)
                    if not value:
                        for a in menu_actions.get(c, []):
                            if a in action_refs:
                                action_refs[a].set_value(False)

            with ui.row().classes("w-full items-center gap-2 pt-3 pb-1"):
                ui.label(label).classes(
                    "text-[11px] font-semibold uppercase tracking-wide text-gray-500"
                )
                ui.space()
                ui.button("Chọn tất cả", on_click=lambda: _set_all(True)) \
                    .props("flat dense no-caps size=sm color=red-8")
                ui.button("Bỏ chọn", on_click=lambda: _set_all(False)) \
                    .props("flat dense no-caps size=sm color=grey-7")

        # ── Render cây phân quyền (refreshable) ───────────────────────────────
        @ui.refreshable
        def _render_features():
            menu_refs.clear()
            action_refs.clear()
            col_refs.clear()
            menu_actions.clear()

            if not structure or selected_group_id["value"] is None:
                ui.label("Chọn nhóm để xem và chỉnh sửa quyền").classes("text-gray-500 text-sm py-4")
                return

            codes = current_codes[0]

            for node in structure:
                with ui.card().classes("w-full shadow-sm rounded-xl overflow-hidden mb-3"):
                    # Thẻ không header: bọc header vào sẽ ra "Nghỉ phép / Nghỉ phép"
                    if node["kind"] == "menu":
                        with ui.column().classes("px-4 py-2 gap-0 w-full"):
                            _menu_block(node, codes, icon=node.get("icon", ""), standalone=True)
                        continue

                    with ui.row().classes("w-full bg-red-800 px-4 py-2.5 items-center gap-2"):
                        ui.icon(node["icon"]).classes("text-white text-base")
                        ui.label(node["dept"]).classes("font-semibold text-white text-sm")

                    with ui.column().classes("px-4 py-2 gap-0 w-full"):
                        for section in node["sections"]:
                            if section["label"]:
                                _section_header(
                                    section["label"],
                                    [m["code"] for m in section["menus"]],
                                )
                            for menu in section["menus"]:
                                _menu_block(menu, codes)

        # ── Lưu phân quyền ────────────────────────────────────────────────────
        async def save_features():
            gid = selected_group_id["value"]
            if not gid:
                return
            selected_codes: list[str] = []

            def _collect(menu: dict):
                mcb = menu_refs.get(menu["code"])
                if not mcb or not mcb.value:
                    return
                selected_codes.append(menu["code"])
                for action in menu.get("actions", []):
                    acb = action_refs.get(action["code"])
                    if acb and acb.value:
                        selected_codes.append(action["code"])

            # Phải duyệt đúng hai loại phần tử như _render_features — bỏ sót loại
            # nào thì quyền của loại đó bị xoá khi lưu (PUT ghi đè toàn bộ).
            for node in structure:
                if node["kind"] == "menu":
                    _collect(node)
                    continue
                for section in node["sections"]:
                    for menu in section["menus"]:
                        _collect(menu)
            try:
                await asyncio.to_thread(
                    api.put, f"/api/groups/{gid}/features", {"codes": selected_codes}
                )
                current_codes[0] = set(selected_codes)
                ui.notify("Đã lưu phân quyền", type="positive")
                status_label.set_text(f"Đã cấp {len(selected_codes)} quyền")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")

        # ── Layout ─────────────────────────────────────────────────────────────
        with ui.card().classes("w-full shadow-sm rounded-xl overflow-hidden mb-4"):
            with ui.row().classes("p-4 gap-4 items-end"):
                group_selector = ui.select(
                    options={},
                    label="Chọn nhóm",
                    with_input=True,
                    on_change=on_group_select,
                ).classes("w-72")
                status_label = ui.label("").classes("text-sm text-gray-500 self-center")

        _render_features()

        save_btn = ui.button(
            "Lưu thay đổi", icon="save", on_click=save_features
        ).classes("bg-red-700 text-white mt-2")
        save_btn.set_visibility(False)

        asyncio.ensure_future(load_initial())
