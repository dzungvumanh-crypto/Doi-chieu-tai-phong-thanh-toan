"""Trang đóng chứng từ — tạo bìa và quản lý nhóm tập."""
import asyncio
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _redirect_if_cv, _handle_api_error

@ui.page("/bundles")
async def bundles_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    if not api.has_feature("menu.bundles"):
        ui.navigate.to("/home")
        return
    _ = _sidebar("bundles")
    with _content_area():
        _page_header("Đóng chứng từ", "Tạo bìa chứng từ và quản lý")

        from datetime import date as _bd
        _today_b = _bd.today()

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") in ("admin", "hau_kiem_vien")

        try:
            await ui.context.client.connected()
        except Exception:
            pass
        with ui.tabs().classes("mb-4") as tabs:
            t_list = ui.tab("Danh sách bìa chứng từ")
            t_new  = ui.tab("Tạo bìa chứng từ")

        with ui.tab_panels(tabs, value=t_list).classes("w-full"):

            # ── Tab 1: Danh sách bìa ─────────────────────────────────────────
            with ui.tab_panel(t_list):
                try:
                    _list_depts = await asyncio.to_thread(
                        api.get, "/api/departments/"
                    )
                    _list_depts = [d for d in _list_depts if d.get("is_source")]
                except Exception:
                    _list_depts = []
                _list_dept_opts = {None: "-- Tất cả phòng --",
                                   **{d["id"]: d["name"] for d in _list_depts}}

                _year_opts  = {None: "-- Tất cả năm --", **{y: str(y) for y in range(2023, _today_b.year + 2)}}
                _month_opts = {None: "-- Tất cả tháng --", **{m: f"Tháng {m:02d}" for m in range(1, 13)}}
                with ui.row().classes("items-end gap-3 mb-4"):
                    list_dept_sel  = ui.select(_list_dept_opts, label="Lọc theo phòng", value=None).classes("w-64")
                    list_year_sel  = ui.select(_year_opts,      label="Năm",            value=None).classes("w-36")
                    list_month_sel = ui.select(_month_opts,     label="Tháng",          value=None).classes("w-36")
                    ui.button("Lọc", icon="filter_list",
                              on_click=lambda: asyncio.ensure_future(load_groups())
                              ).classes("bg-red-700 text-white")

                bundles_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
                with bundles_loading:
                    ui.spinner(size="2em", color="red")
                    ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
                groups_container = ui.column().classes("w-full")

                async def _download_all_covers(group_id: int, label: str = ""):
                    try:
                        content = await asyncio.to_thread(api.download, f"/api/bundles/groups/{group_id}/cover-all")
                        fname = f"{label}.docx" if label else f"bia_chung_tu_{group_id}.docx"
                        ui.download(content, fname)
                        ui.notify("Đang tải bìa...", type="positive")
                    except Exception as e:
                        if _handle_api_error(e): return

                async def _mark_group_printed(group_id: int):
                    try:
                        await asyncio.to_thread(api.post, f"/api/bundles/groups/{group_id}/mark-printed")
                        ui.notify("Đã đánh dấu đã in", type="positive")
                        await load_groups()
                    except Exception as e:
                        if _handle_api_error(e): return

                confirm_del_dialog = ui.dialog()
                _del_target = {"id": None, "name": ""}
                with confirm_del_dialog, ui.card().classes("p-6 w-80"):
                    ui.label("Xác nhận xóa").classes("text-lg font-bold mb-2 text-red-700")
                    del_msg = ui.label("").classes("text-sm text-gray-600 mb-4")
                    with ui.row().classes("justify-end gap-2"):
                        ui.button("Hủy", on_click=lambda: confirm_del_dialog.close()).classes("text-gray-500")
                        async def _do_delete():
                            gid = _del_target["id"]
                            confirm_del_dialog.close()
                            if not gid:
                                return
                            try:
                                await asyncio.to_thread(api.delete, f"/api/bundles/groups/{gid}")
                                ui.notify("Đã xóa nhóm bìa", type="positive")
                                await load_groups()
                            except Exception as e:
                                if _handle_api_error(e): return
                        ui.button("Xóa", on_click=_do_delete).classes("bg-red-600 text-white")

                def _delete_group(group_id: int, dept_name: str):
                    _del_target["id"] = group_id
                    _del_target["name"] = dept_name
                    del_msg.set_text(f'Xóa toàn bộ bìa chứng từ của "{dept_name}"?')
                    confirm_del_dialog.open()

                async def load_groups():
                    bundles_loading.classes(remove="hidden")
                    groups_container.clear()
                    try:
                        params = {}
                        if list_dept_sel.value:
                            params["department_id"] = list_dept_sel.value
                        if list_year_sel.value:
                            params["year"] = list_year_sel.value
                        if list_month_sel.value:
                            params["month"] = list_month_sel.value
                        groups = await asyncio.to_thread(api.get, "/api/bundles/groups", params)
                    except Exception as e:
                        _handle_api_error(e)
                        bundles_loading.classes(add="hidden")
                        return
                    bundles_loading.classes(add="hidden")

                    with groups_container:
                        if not groups:
                            ui.label("Chưa có bìa chứng từ nào").classes(
                                "text-gray-400 text-center py-8"
                            )
                            return

                        # Header
                        with ui.row().classes(
                            "w-full px-4 py-2 bg-red-50 rounded-lg mb-1 text-xs font-semibold text-red-700"
                        ):
                            ui.label("Tên bìa chứng từ").classes("flex-1")
                            ui.label("Ngày tạo").classes("w-40 text-center")
                            ui.label("Người tạo").classes("w-40 text-center")
                            ui.label("Số bìa").classes("w-20 text-center")
                            ui.label("").classes("w-64")

                        for g in groups:
                            dept         = g.get("department") or {}
                            dept_name    = dept.get("name", "—")
                            notes        = g.get("notes") or ""
                            bundle_lbl   = f"{dept_name} – {notes}" if notes else dept_name
                            creator      = g.get("created_by_staff") or {}
                            creator_name = creator.get("full_name", "—")
                            created_at   = (g.get("created_at") or "")[:16].replace("T", " ")
                            n_bundles    = g.get("total_bundles", 0)
                            gid          = g["id"]

                            # Build download filename: "Phòng X tháng 04 năm 2025"
                            try:
                                month_year = notes.replace("Tháng ", "").strip()  # "04/2025"
                                m_str, y_str = month_year.split("/")
                                file_label = f"{dept_name} tháng {m_str} năm {y_str}"
                            except Exception:
                                file_label = bundle_lbl

                            with ui.row().classes(
                                "w-full px-4 py-3 bg-white border border-gray-100"
                                " rounded-lg mb-2 items-center shadow-sm"
                            ):
                                ui.label(bundle_lbl).classes(
                                    "flex-1 font-semibold text-gray-800 text-sm"
                                )
                                ui.label(created_at).classes("w-40 text-center text-sm text-gray-500")
                                ui.label(creator_name).classes("w-40 text-center text-sm text-gray-600")
                                ui.label(str(n_bundles)).classes(
                                    "w-20 text-center text-sm font-semibold text-red-700"
                                )
                                with ui.row().classes("w-64 justify-end gap-2"):
                                    if api.has_feature("bundles.download_cover"):
                                        ui.button("Tải xuống", icon="download",
                                                  on_click=lambda g_id=gid, lbl=file_label: _download_all_covers(g_id, lbl)
                                                  ).classes("bg-red-700 text-white text-xs px-3 py-1")
                                    if api.has_feature("bundles.mark_printed"):
                                        ui.button("In", icon="print",
                                                  on_click=lambda g_id=gid: _mark_group_printed(g_id)
                                                  ).classes("bg-green-700 text-white text-xs px-3 py-1")
                                    if api.has_feature("bundles.delete"):
                                        ui.button("Xóa", icon="delete",
                                                  on_click=lambda g_id=gid, d=bundle_lbl: _delete_group(g_id, d)
                                                  ).classes("bg-red-600 text-white text-xs px-3 py-1")

                list_dept_sel.on("update:model-value",  load_groups)
                list_year_sel.on("update:model-value",  load_groups)
                list_month_sel.on("update:model-value", load_groups)
                await load_groups()

            # ── Tab 2: Tạo bìa ───────────────────────────────────────────────
            with ui.tab_panel(t_new):
                try:
                    depts = await asyncio.to_thread(api.get, "/api/departments/")
                    ksnb_dept = next((d for d in depts if d.get("code") == "KSNB"), None)
                    staff_list = await asyncio.to_thread(
                        api.get, "/api/staff/",
                        {"department_id": ksnb_dept["id"]} if ksnb_dept else None,
                    )
                    depts = [d for d in depts if d.get("is_source")]
                except Exception as e:
                    if isinstance(e, api.SessionExpiredError):
                        ui.notify(str(e), type="warning")
                        ui.navigate.to("/login")
                        return
                    depts, staff_list = [], []

                dept_opts2  = {d["id"]: d["name"] for d in depts}
                staff_opts2 = {s["id"]: s["full_name"] for s in staff_list}
                year_opts2  = {y: str(y) for y in range(2023, _today_b.year + 3)}
                month_opts2 = {m: f"Tháng {m:02d}" for m in range(1, 13)}

                selected_entry_ids = []

                # ── Dialog thông báo thành công ───────────────────────────────
                success_dialog = ui.dialog().props("persistent")
                with success_dialog, ui.card().classes("p-8 items-center text-center gap-3"):
                    ui.icon("check_circle", color="green").classes("text-6xl")
                    ui.label("Tạo bìa thành công!").classes("text-xl font-bold text-green-700")
                    success_detail = ui.label("").classes("text-gray-600 text-sm")
                    async def _ok_and_go():
                        success_dialog.close()
                        tabs.set_value(t_list)
                        await load_groups()
                    ui.button("OK", on_click=_ok_and_go).classes("bg-red-700 text-white px-10 mt-2")

                with ui.row().classes("w-full gap-4 items-start"):
                    # ── Trái: Cấu hình ────────────────────────────────────────
                    with ui.card().classes("w-72 p-4 bg-white rounded-xl shadow-sm shrink-0"):
                        ui.label("Cấu hình").classes("font-semibold text-red-800 mb-3")
                        nb_dept  = ui.select(dept_opts2,  label="Phòng nghiệp vụ *").classes("w-full")
                        nb_year  = ui.select(year_opts2,  label="Năm *",
                                             value=_today_b.year).classes("w-full mt-2")
                        nb_month = ui.select(month_opts2, label="Tháng *",
                                             value=_today_b.month).classes("w-full mt-2")
                        nb_cust  = ui.select(staff_opts2, label="Cán bộ đóng chứng từ").classes("w-full mt-3")

                        async def do_generate():
                            if not nb_dept.value:
                                ui.notify("Vui lòng chọn phòng", type="warning")
                                return
                            dept_label  = dept_opts2.get(nb_dept.value, "")
                            month_label = f"Tháng {nb_month.value:02d}/{nb_year.value}"
                            bundle_name = f"{dept_label} – {month_label}"
                            try:
                                grid_data = await asyncio.to_thread(api.get, "/api/handovers/grid", {
                                    "department_id": nb_dept.value,
                                    "year": nb_year.value,
                                    "month": nb_month.value,
                                })
                            except Exception as e:
                                if _handle_api_error(e): return
                                return
                            entry_ids = [
                                e["entry_id"]
                                for e in grid_data.get("entries", [])
                                if e.get("entry_id")
                            ]
                            if not entry_ids:
                                ui.notify("Không có chứng từ để tạo bìa", type="warning")
                                return
                            try:
                                result = await asyncio.to_thread(api.post, "/api/bundles/generate", {
                                    "department_id": nb_dept.value,
                                    "entry_ids": entry_ids,
                                    "custodian_id": nb_cust.value,
                                    "notes": month_label,
                                })
                                n = result.get("total_bundles", 0)
                                success_detail.set_text(
                                    f"{bundle_name} — {n} bìa chứng từ"
                                )
                                success_dialog.open()
                                # Cập nhật preview bằng grid_data đã có, không gọi API lại
                                await _refresh_preview(grid_data)
                            except Exception as e:
                                if _handle_api_error(e): return

                        gen_btn = ui.button("Tạo bìa chứng từ", icon="folder_zip",
                                  on_click=do_generate).classes(
                            "w-full bg-red-700 text-white mt-4 py-2 rounded"
                        )
                        gen_btn.set_visibility(api.has_feature("bundles.generate"))

                    # ── Phải: Preview chứng từ ────────────────────────────────
                    with ui.column().classes("flex-1 min-w-0"):
                        preview_container = ui.column().classes("w-full")

                async def _refresh_preview(grid_data: dict):
                    preview_container.clear()
                    year  = nb_year.value
                    month = nb_month.value
                    grid_entries = [e for e in grid_data.get("entries", []) if e.get("entry_id")]
                    selected_entry_ids.clear()
                    selected_entry_ids.extend([e["entry_id"] for e in grid_entries])
                    users_map = {u["id"]: u for u in grid_data.get("users", [])}
                    with preview_container:
                        total_sheets = sum(e.get("sheet_count", 0) for e in grid_entries)
                        ui.label(
                            f"{len(grid_entries)} chứng từ tháng {month:02d}/{year}"
                            f" – tổng {total_sheets} tờ"
                        ).classes("text-gray-600 text-sm mb-2")
                        if grid_entries:
                            with ui.element("div").classes("max-h-96 overflow-y-auto w-full"):
                                with ui.table(
                                    columns=[
                                        {"name": "name",   "label": "Họ và tên",  "field": "name",   "align": "left"},
                                        {"name": "date",   "label": "Ngày",        "field": "date",   "align": "center"},
                                        {"name": "sheets", "label": "Số tờ",       "field": "sheets", "align": "center"},
                                    ],
                                    rows=[{
                                        "id": e["entry_id"],
                                        "name": (users_map.get(e["staff_id"]) or {}).get("full_name")
                                                or (users_map.get(e["staff_id"]) or {}).get("ipcas_code") or "",
                                        "date": f"{year}-{month:02d}-{e['day']:02d}",
                                        "sheets": e["sheet_count"],
                                    } for e in grid_entries],
                                    row_key="id"
                                ).classes("w-full"):
                                    pass
                        else:
                            ui.label("Không có chứng từ nào trong tháng này").classes(
                                "text-gray-400 text-sm text-center py-4"
                            )

                async def load_entries_preview():
                    dept_id = nb_dept.value
                    year    = nb_year.value
                    month   = nb_month.value
                    if not dept_id or not year or not month:
                        return
                    try:
                        grid_data = await asyncio.to_thread(api.get, "/api/handovers/grid", {
                            "department_id": dept_id,
                            "year": year,
                            "month": month,
                        })
                    except Exception as e:
                        if _handle_api_error(e): return
                        return
                    await _refresh_preview(grid_data)

                nb_dept.on("update:model-value",  load_entries_preview)
                nb_year.on("update:model-value",  load_entries_preview)
                nb_month.on("update:model-value", load_entries_preview)
                if nb_dept.value:
                    await load_entries_preview()
