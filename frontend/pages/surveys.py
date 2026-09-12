"""Khảo sát — danh sách khảo sát gửi tới tôi và khảo sát tôi quản lý.

Bốn trang: /surveys (đây), /surveys/edit (soạn), /surveys/fill (trả lời),
/surveys/results (thống kê). Trang trả lời KHÔNG đòi `menu.surveys` — xem
docstring backend/api/surveys.py.
"""
import asyncio

from nicegui import ui

import frontend.api_client as api
import frontend.ui_kit as ui_kit
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error
from frontend.survey_common import fmt_dt, state_chip

_TH = "px-3 py-2 text-left text-xs font-semibold text-red-800 whitespace-nowrap"
_TD = "px-3 py-2 text-sm text-gray-700"


@ui.page("/surveys")
async def surveys_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.surveys"):
        ui.navigate.to("/home")
        return

    can_create = api.has_feature("surveys.create")
    can_view_all = api.has_feature("surveys.view_all")
    show_manage = can_create or can_view_all

    await _sidebar("surveys")
    with _content_area():
        _page_header("Khảo sát", "Trả lời khảo sát được gửi tới bạn, tạo khảo sát và xem thống kê")

        with ui.tabs().classes("text-red-800").props("align=left no-caps dense") as tabs:
            t_mine = ui.tab("mine", "Khảo sát của tôi", icon="inbox")
            t_manage = ui.tab("manage", "Quản lý khảo sát", icon="edit_note") if show_manage else None
        with ui.tab_panels(tabs, value=t_mine).classes("w-full bg-transparent"):
            with ui.tab_panel(t_mine).classes("p-0 pt-3"):
                mine_box = ui.column().classes("w-full gap-3")
            if show_manage:
                with ui.tab_panel(t_manage).classes("p-0 pt-3"):
                    with ui.row().classes("w-full items-center gap-3 mb-2"):
                        if can_create:
                            ui.button("Tạo khảo sát", icon="add",
                                      on_click=lambda: ui.navigate.to("/surveys/edit")
                                      ).classes("bg-red-700 text-white").props("no-caps")
                        scope = {"v": "mine"}
                        if can_view_all:
                            async def _doi_scope(e):
                                scope["v"] = e.value
                                await load_manage()
                            ui.toggle({"mine": "Do tôi tạo", "all": "Tất cả"}, value="mine",
                                      on_change=_doi_scope).props("dense no-caps toggle-color=red-8")
                    manage_box = ui.column().classes("w-full gap-0")

        # ── Khảo sát gửi tới tôi ──────────────────────────────────────────────
        async def load_mine():
            mine_box.clear()
            with mine_box:
                ui_kit.skeleton_cards(3)
            try:
                rows = await asyncio.to_thread(api.get, "/api/surveys/mine")
            except Exception as e:
                mine_box.clear()
                _handle_api_error(e)
                return
            mine_box.clear()
            with mine_box:
                if not rows:
                    ui_kit.empty_state("Chưa có khảo sát nào gửi tới bạn", "poll")
                    return
                with ui.element("div").classes("w-full grid gap-3").style(
                        "grid-template-columns: repeat(auto-fill, minmax(20rem, 1fr))"):
                    for s in rows:
                        _mine_card(s)

        def _mine_card(s: dict):
            todo = s["state"] == "open" and not s["responded"]
            border = "border-red-400" if todo else "border-gray-200"
            with ui.card().classes(f"w-full shadow-sm rounded-xl bg-white p-4 gap-2 border {border}"):
                with ui.row().classes("w-full items-start justify-between no-wrap gap-2"):
                    ui.label(s["title"]).classes("font-semibold text-gray-900 leading-snug")
                    state_chip(s["state"])
                if s.get("description"):
                    ui.label(s["description"]).classes("text-xs text-gray-500 line-clamp-2")
                with ui.column().classes("gap-0.5 text-xs text-gray-600"):
                    ui.label(f"Người tạo: {s.get('created_by_name') or '—'} · {s['question_count']} câu")
                    ui.label(f"Hạn chót: {fmt_dt(s['deadline'])}").classes(
                        "text-red-800 font-medium" if todo else "")
                    if s["responded"]:
                        ui.label(f"Đã trả lời lúc {fmt_dt(s['updated_at'] or s['submitted_at'])}"
                                 ).classes("text-green-700")
                with ui.row().classes("w-full justify-end mt-1"):
                    if todo:
                        lbl, icon = "Trả lời ngay", "edit"
                    elif s["responded"] and s["allow_edit"] and s["state"] == "open":
                        lbl, icon = "Sửa câu trả lời", "edit_note"
                    else:
                        lbl, icon = "Xem", "visibility"
                    btn = ui.button(lbl, icon=icon,
                                    on_click=lambda i=s["id"]: ui.navigate.to(f"/surveys/fill?id={i}")
                                    ).props("dense no-caps")
                    btn.classes("bg-red-700 text-white px-3" if todo else "text-red-800 px-2")
                    if not todo:
                        btn.props("flat")

        # ── Khảo sát tôi quản lý ──────────────────────────────────────────────
        async def load_manage():
            if not show_manage:
                return
            manage_box.clear()
            with manage_box:
                ui_kit.skeleton_rows(5)
            try:
                rows = await asyncio.to_thread(api.get, "/api/surveys/manage", {"scope": scope["v"]})
            except Exception as e:
                manage_box.clear()
                _handle_api_error(e)
                return
            manage_box.clear()
            with manage_box:
                if not rows:
                    ui_kit.empty_state("Chưa có khảo sát nào", "edit_note",
                                       "Bấm «Tạo khảo sát» để bắt đầu" if can_create else "")
                    return
                with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden "
                                       "border border-gray-200"):
                    with ui.element("div").classes("w-full overflow-x-auto"):
                        with ui.element("table").classes("w-full border-collapse"):
                            with ui.element("thead").classes("bg-red-50 border-b-2 border-red-200"):
                                with ui.element("tr"):
                                    for c in ("Khảo sát", "Người tạo", "Trạng thái", "Hạn chót",
                                              "Tiến độ", ""):
                                        with ui.element("th").classes(_TH):
                                            ui.label(c)
                            with ui.element("tbody"):
                                for s in rows:
                                    _manage_row(s)

        def _manage_row(s: dict):
            with ui.element("tr").classes("border-b border-gray-100 hover:bg-red-50"):
                with ui.element("td").classes(_TD):
                    ui.label(s["title"]).classes("font-medium text-gray-900")
                    ui.label(f"{s['question_count']} câu hỏi"
                             + (" · ẩn danh" if s["is_anonymous"] else "")).classes(
                        "text-xs text-gray-500")
                with ui.element("td").classes(_TD):
                    ui.label(s.get("created_by_name") or "—")
                with ui.element("td").classes(_TD):
                    state_chip(s["state"])
                with ui.element("td").classes(f"{_TD} whitespace-nowrap"):
                    ui.label(fmt_dt(s["deadline"]))
                with ui.element("td").classes(f"{_TD} min-w-[10rem]"):
                    n, d = s["recipient_count"], s["response_count"]
                    if s["state"] == "draft":
                        ui.label("—").classes("text-gray-400")
                    else:
                        ui.label(f"{d}/{n} người" + (f" ({round(d * 100 / n)}%)" if n else ""))
                        ui.linear_progress(value=(d / n) if n else 0, show_value=False).props(
                            "color=red-7 track-color=grey-3 rounded").classes("h-1.5 mt-1")
                with ui.element("td").classes(f"{_TD} whitespace-nowrap text-right"):
                    _actions(s)

        def _actions(s: dict):
            sid, owner = s["id"], s["is_owner"] and can_create
            if s["state"] != "draft":
                ui.button(icon="insights", on_click=lambda: ui.navigate.to(f"/surveys/results?id={sid}")
                          ).props("flat dense round").classes("text-red-800").tooltip("Thống kê kết quả")
            if owner:
                ui.button(icon="edit", on_click=lambda: ui.navigate.to(f"/surveys/edit?id={sid}")
                          ).props("flat dense round").classes("text-gray-700").tooltip("Sửa")
                if s["state"] in ("open", "scheduled", "expired"):
                    ui.button(icon="lock", on_click=lambda: do_close(s)
                              ).props("flat dense round").classes("text-gray-700").tooltip("Đóng khảo sát")
                ui.button(icon="delete", on_click=lambda: do_delete(s)
                          ).props("flat dense round").classes("text-red-700").tooltip("Xoá")

        async def _confirm(title: str, detail: str, ok: str) -> bool:
            with ui.dialog() as dlg, ui.card():
                ui.label(title).classes("font-semibold")
                ui.label(detail).classes("text-sm text-gray-600 max-w-md")
                with ui.row().classes("w-full justify-end gap-2 mt-3"):
                    ui.button("Huỷ", on_click=lambda: dlg.submit(False)).props("flat")
                    ui.button(ok, on_click=lambda: dlg.submit(True)).classes("bg-red-700 text-white")
            return bool(await dlg)

        async def do_close(s: dict):
            if not await _confirm(f"Đóng khảo sát «{s['title']}»?",
                                  "Người chưa trả lời sẽ không trả lời được nữa. Muốn mở lại thì "
                                  "vào Sửa, đặt hạn chót mới rồi phát hành lại.", "Đóng"):
                return
            try:
                await asyncio.to_thread(api.post, f"/api/surveys/{s['id']}/close")
            except Exception as e:
                _handle_api_error(e)
                return
            ui.notify("Đã đóng khảo sát", type="positive")
            await load_manage()

        async def do_delete(s: dict):
            if not await _confirm(f"Xoá khảo sát «{s['title']}»?",
                                  f"Xoá cả câu hỏi và {s['response_count']} câu trả lời đã nhận. "
                                  "Không hoàn tác được.", "Xoá"):
                return
            try:
                await asyncio.to_thread(api.delete, f"/api/surveys/{s['id']}")
            except Exception as e:
                _handle_api_error(e)
                return
            ui.notify("Đã xoá khảo sát", type="positive")
            await load_manage()

    try:
        await ui.context.client.connected()
    except Exception:
        pass        # hết giờ chờ / người dùng đóng tab — vẫn dựng tiếp phần còn lại
    # Tuần tự, KHÔNG asyncio.gather: gather bọc mỗi coroutine thành task riêng →
    # mất ngăn xếp slot của NiceGUI, ui.notify trong nhánh lỗi sẽ ném RuntimeError
    # (xem "Event handler async" trong docs/DESIGN.md).
    await load_mine()
    await load_manage()
