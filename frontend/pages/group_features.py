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

        # ── Render cây phân quyền (refreshable) ───────────────────────────────
        @ui.refreshable
        def _render_features():
            menu_refs.clear()
            action_refs.clear()

            if not structure or selected_group_id["value"] is None:
                ui.label("Chọn nhóm để xem và chỉnh sửa quyền").classes("text-gray-500 text-sm py-4")
                return

            codes = current_codes[0]

            for dept_def in structure:
                with ui.card().classes("w-full shadow-sm rounded-xl overflow-hidden mb-3"):

                    # Header phòng
                    with ui.row().classes("w-full bg-red-800 px-4 py-2.5 items-center gap-2"):
                        ui.icon(dept_def["icon"]).classes("text-white text-base")
                        ui.label(dept_def["dept"]).classes("font-semibold text-white text-sm")

                    with ui.column().classes("px-4 py-2 gap-0 w-full"):
                        for menu in dept_def["menus"]:
                            mcode    = menu["code"]
                            actions  = menu.get("actions", [])
                            acodes   = [a["code"] for a in actions]
                            mchecked = mcode in codes

                            col_ref = [None]

                            def _on_menu_toggle(e, ref=col_ref, act_codes=acodes):
                                if ref[0] is not None:
                                    ref[0].set_visibility(e.value)
                                if not e.value:
                                    for c in act_codes:
                                        if c in action_refs:
                                            action_refs[c].set_value(False)

                            with ui.row().classes("w-full items-center border-b border-gray-100 py-2.5"):
                                menu_cb = ui.checkbox(
                                    menu["label"],
                                    value=mchecked,
                                    on_change=_on_menu_toggle if acodes else None,
                                ).classes("text-sm font-semibold text-gray-800")
                            menu_refs[mcode] = menu_cb

                            if acodes:
                                with ui.column().classes("pl-7 pb-2 pt-1 gap-1 w-full") as action_col:
                                    col_ref[0] = action_col
                                    action_col.set_visibility(mchecked)
                                    for action in actions:
                                        achecked = action["code"] in codes and mchecked
                                        acb = ui.checkbox(
                                            action["label"], value=achecked
                                        ).classes("text-sm text-gray-600")
                                        action_refs[action["code"]] = acb

        # ── Lưu phân quyền ────────────────────────────────────────────────────
        async def save_features():
            gid = selected_group_id["value"]
            if not gid:
                return
            selected_codes: list[str] = []
            for dept_def in structure:
                for menu in dept_def["menus"]:
                    mcb = menu_refs.get(menu["code"])
                    if not mcb or not mcb.value:
                        continue
                    selected_codes.append(menu["code"])
                    for action in menu.get("actions", []):
                        acb = action_refs.get(action["code"])
                        if acb and acb.value:
                            selected_codes.append(action["code"])
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
