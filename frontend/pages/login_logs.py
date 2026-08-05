"""Trang nhật ký đăng nhập."""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error


@ui.page("/login-logs")
async def login_logs_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.logs"):
        ui.navigate.to("/home")
        return
    _ = _sidebar("login-logs")

    with _content_area():
        _page_header("Nhật ký đăng nhập", "Lịch sử đăng nhập — tối đa 30 ngày gần nhất")

        _filter: list = [""]
        _page:   list = [1]
        _total_pages: list = [1]

        # ── Controls ───────────────────────────────────────────────────────────
        status_label    = ui.label("").classes("text-sm text-gray-500 mb-2")
        toolbar_row     = ui.row().classes("gap-2 mb-2 items-center flex-wrap")
        login_container = ui.column().classes("w-full gap-0")
        pager_row       = ui.row().classes("gap-2 mt-3 items-center justify-center")

        # ── Hàm render bảng ────────────────────────────────────────────────────
        async def _load(success_filter: str = "", page: int = 1):
            _filter[0] = success_filter
            _page[0]   = page
            status_label.set_text("Đang tải...")
            login_container.clear()
            pager_row.clear()
            try:
                data = await asyncio.to_thread(
                    api.get, "/api/admin/logs/logins",
                    {"success": success_filter, "page": page},
                )
            except Exception as e:
                status_label.set_text("Không thể tải nhật ký đăng nhập.")
                _handle_api_error(e)
                return

            entries  = data.get("entries", [])
            total    = data.get("total", 0)
            pages    = data.get("pages", 1)
            pg_size  = data.get("page_size", 50)
            _total_pages[0] = pages

            start_idx = (page - 1) * pg_size + 1
            status_label.set_text(
                f"Trang {page}/{pages} — "
                f"Bản ghi {start_idx}–{min(start_idx + pg_size - 1, total)} / {total}"
            )

            with login_container:
                if not entries:
                    ui.label("Không có bản ghi.").classes("text-gray-500 text-sm mt-2")
                    return
                with ui.row().classes("w-full bg-gray-100 border-b border-gray-200 px-3 py-2 items-center gap-2"):
                    ui.label("Thời gian").classes("font-semibold text-gray-700 text-xs w-36 shrink-0")
                    ui.label("Kết quả").classes("font-semibold text-gray-700 text-xs w-20 shrink-0")
                    ui.label("Username").classes("font-semibold text-gray-700 text-xs w-28 shrink-0")
                    ui.label("Họ và tên").classes("font-semibold text-gray-700 text-xs w-44 shrink-0")
                    ui.label("IP").classes("font-semibold text-gray-700 text-xs w-28 shrink-0")
                    ui.label("Chi tiết").classes("font-semibold text-gray-700 text-xs flex-1")
                for e in entries:
                    ok = e.get("success", False)
                    badge_cls = "bg-green-100 text-green-700" if ok else "bg-red-100 text-red-700"
                    badge_txt = "Thành công" if ok else "Thất bại"
                    row_bg    = "bg-green-50" if ok else "bg-red-50" if not ok else "bg-white"
                    with ui.row().classes(f"w-full {row_bg} border-b border-gray-100 px-3 py-1.5 items-center gap-2"):
                        ts = (e.get("created_at") or "")[:16].replace("T", " ")
                        ui.label(ts).classes("text-xs font-mono w-36 shrink-0 text-gray-600")
                        ui.label(badge_txt).classes(
                            f"text-xs px-1.5 py-0.5 rounded {badge_cls} w-20 shrink-0 text-center font-medium"
                        )
                        ui.label(e.get("username", "")).classes("text-xs w-28 shrink-0 font-mono truncate")
                        ui.label(e.get("full_name") or "—").classes("text-xs w-44 shrink-0 truncate")
                        ui.label(e.get("ip_address") or "—").classes("text-xs font-mono w-28 shrink-0 text-gray-500")
                        ui.label(e.get("detail") or "").classes("text-xs flex-1 text-gray-500 truncate")

            # ── Phân trang ──────────────────────────────────────────────────────
            with pager_row:
                ui.button("◀ Trước",
                          on_click=lambda: asyncio.ensure_future(_load(_filter[0], _page[0] - 1)),
                ).classes("text-sm bg-gray-200 text-gray-700").set_enabled(page > 1)
                ui.label(f"Trang {page} / {pages}").classes("text-sm text-gray-600 px-2")
                ui.button("Sau ▶",
                          on_click=lambda: asyncio.ensure_future(_load(_filter[0], _page[0] + 1)),
                ).classes("text-sm bg-gray-200 text-gray-700").set_enabled(page < pages)

        # ── Hàm export Excel ───────────────────────────────────────────────────
        async def _export_logins():
            try:
                from datetime import date as _d
                content = await asyncio.to_thread(
                    api.download, "/api/admin/logs/logins/export",
                    {"success": _filter[0]},
                )
                ui.download(content, f"nhat_ky_dang_nhap_{_d.today().strftime('%Y%m%d')}.xlsx")
            except Exception as e:
                _handle_api_error(e)

        # ── Gắn controls vào toolbar ────────────────────────────────────────────
        with toolbar_row:
            for sf, lbl in [("", "Tất cả"), ("true", "Thành công"), ("false", "Thất bại")]:
                ui.button(lbl,
                          on_click=lambda f=sf: asyncio.ensure_future(_load(f, 1))).classes(
                    "text-sm bg-gray-100 text-gray-700 hover:bg-gray-200")
            ui.button("↻", icon="refresh",
                      on_click=lambda: asyncio.ensure_future(_load(_filter[0], 1))).classes(
                "text-sm bg-gray-700 text-white")
            ui.button("Xuất Excel", icon="download",
                      on_click=_export_logins).classes(
                "text-sm bg-green-700 text-white").tooltip("Tải Excel toàn bộ nhật ký (theo bộ lọc hiện tại)")

        await _load("", 1)
