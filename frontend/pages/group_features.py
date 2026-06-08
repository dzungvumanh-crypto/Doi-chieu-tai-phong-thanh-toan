"""Trang phân quyền chức năng theo nhóm — chỉ admin."""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

# ── Cấu trúc menu theo phòng (định nghĩa tĩnh ở frontend) ───────────────────
_STRUCTURE = [
    {
        "dept": "Phòng KSNB & HTVH",
        "icon": "account_balance",
        "menus": [
            {
                "code": "menu.handovers",
                "label": "Bàn giao chứng từ",
                "actions": [
                    ("handovers.save_entry",    "Lưu số tờ chứng từ"),
                    ("handovers.confirm_entry", "Xác nhận cho mượn / đã nhận"),
                    ("handovers.reject_entry",  "Từ chối bàn giao"),
                    ("handovers.borrow",        "Mượn lại chứng từ"),
                    ("handovers.handback",      "Bàn giao lại chứng từ"),
                ],
            },
            {
                "code": "menu.bundles",
                "label": "Đóng chứng từ",
                "actions": [
                    ("bundles.generate",       "Tạo bìa chứng từ"),
                    ("bundles.download_cover", "Tải xuống bìa"),
                    ("bundles.mark_printed",   "Đánh dấu đã in"),
                    ("bundles.delete",         "Xóa nhóm bìa"),
                ],
            },
            {"code": "menu.storage", "label": "Lưu trữ",  "actions": []},
            {"code": "menu.reports", "label": "Báo cáo",  "actions": []},
        ],
    },
    {
        "dept": "Phòng Tổng hợp",
        "icon": "summarize",
        "menus": [
            {
                "code": "menu.leaves",
                "label": "Nghỉ phép",
                "actions": [
                    ("leaves.create",       "Tạo đơn nghỉ phép"),
                    ("leaves.cancel",       "Huỷ đơn nghỉ phép"),
                    ("leaves.resubmit",     "Sửa & Nộp lại đơn"),
                    ("leaves.approve_ksv",  "Duyệt / Từ chối (bước KSV)"),
                    ("leaves.forward_th",   "Chuyển GĐ/PGĐ / Từ chối (bước Tổng hợp)"),
                    ("leaves.approve_gd",   "Duyệt / Từ chối (bước Giám đốc)"),
                ],
            },
        ],
    },
    {
        "dept": "Quản lý hệ thống",
        "icon": "admin_panel_settings",
        "menus": [
            {
                "code": "menu.staff",
                "label": "Quản lý User",
                "actions": [
                    ("staff.create",     "Tạo tài khoản mới"),
                    ("staff.edit",       "Chỉnh sửa nhân viên"),
                    ("staff.delete",     "Xóa nhân viên"),
                    ("staff.export",     "Xuất Excel / DB"),
                    ("staff.import_db",  "Nhập DB"),
                ],
            },
            {"code": "menu.logs", "label": "Nhật ký hệ thống", "actions": []},
        ],
    },
]


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
        groups_data: list = []
        selected_group_id: dict = {"value": None}
        current_codes: set = set()
        menu_refs: dict = {}    # menu_code → checkbox element
        action_refs: dict = {}  # action_code → checkbox element

        group_selector = None
        features_area = None
        save_btn = None
        status_label = None

        # ── Load nhóm ──────────────────────────────────────────────────────────
        async def load_initial():
            nonlocal groups_data
            try:
                groups_data = await asyncio.to_thread(api.get, "/api/groups")
                group_selector.options = {str(g["id"]): g["name"] for g in groups_data}
                group_selector.update()
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")

        async def on_group_select(e):
            gid = e.value
            if not gid:
                return
            selected_group_id["value"] = int(gid)
            try:
                result = await asyncio.to_thread(api.get, f"/api/groups/{gid}/features")
                nonlocal current_codes
                current_codes = set(result.get("codes", []))
                _render_features()
                save_btn.set_visibility(True)
                status_label.set_text("")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")

        # ── Render cây phân quyền ─────────────────────────────────────────────
        def _render_features():
            features_area.clear()
            menu_refs.clear()
            action_refs.clear()
            with features_area:
                for dept_def in _STRUCTURE:
                    with ui.card().classes("w-full shadow-sm rounded-xl overflow-hidden mb-3"):

                        # Header phòng — không có checkbox
                        with ui.row().classes(
                            "w-full bg-red-800 px-4 py-2.5 items-center gap-2"
                        ):
                            ui.icon(dept_def["icon"]).classes("text-white text-base")
                            ui.label(dept_def["dept"]).classes(
                                "font-semibold text-white text-sm"
                            )

                        with ui.column().classes("px-4 py-2 gap-0 w-full"):
                            for menu in dept_def["menus"]:
                                mcode    = menu["code"]
                                acodes   = [ac for ac, _ in menu["actions"]]
                                mchecked = mcode in current_codes

                                # Dùng list làm mutable ref để closure on_change thấy được
                                col_ref = [None]

                                def _on_menu_toggle(e, ref=col_ref, codes=acodes):
                                    if ref[0] is not None:
                                        ref[0].set_visibility(e.value)
                                    if not e.value:
                                        for c in codes:
                                            if c in action_refs:
                                                action_refs[c].set_value(False)

                                # Menu item — có checkbox
                                with ui.row().classes(
                                    "w-full items-center border-b border-gray-100 py-2.5"
                                ):
                                    menu_cb = ui.checkbox(
                                        menu["label"],
                                        value=mchecked,
                                        on_change=_on_menu_toggle if acodes else None,
                                    ).classes("text-sm font-semibold text-gray-800")
                                menu_refs[mcode] = menu_cb

                                # Actions — chỉ render nếu menu có sub-features
                                if acodes:
                                    with ui.column().classes(
                                        "pl-7 pb-2 pt-1 gap-1 w-full"
                                    ) as action_col:
                                        col_ref[0] = action_col
                                        action_col.set_visibility(mchecked)
                                        for acode, alabel in menu["actions"]:
                                            achecked = acode in current_codes and mchecked
                                            acb = ui.checkbox(
                                                alabel, value=achecked
                                            ).classes("text-sm text-gray-600")
                                            action_refs[acode] = acb

        # ── Lưu phân quyền ────────────────────────────────────────────────────
        async def save_features():
            gid = selected_group_id["value"]
            if not gid:
                return
            # Duyệt _STRUCTURE để giữ đúng thứ tự và bỏ action khi menu không tick
            selected_codes: list[str] = []
            for dept_def in _STRUCTURE:
                for menu in dept_def["menus"]:
                    mcb = menu_refs.get(menu["code"])
                    if not mcb or not mcb.value:
                        continue
                    selected_codes.append(menu["code"])
                    for acode, _ in menu["actions"]:
                        acb = action_refs.get(acode)
                        if acb and acb.value:
                            selected_codes.append(acode)
            try:
                await asyncio.to_thread(
                    api.put, f"/api/groups/{gid}/features", {"codes": selected_codes}
                )
                nonlocal current_codes
                current_codes = set(selected_codes)
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

        with ui.column().classes("w-full gap-2") as features_area:
            ui.label("Chọn nhóm để xem và chỉnh sửa quyền").classes(
                "text-gray-400 text-sm py-4"
            )

        save_btn = ui.button(
            "Lưu thay đổi", icon="save", on_click=save_features
        ).classes("bg-red-700 text-white mt-2")
        save_btn.set_visibility(False)

        asyncio.ensure_future(load_initial())
