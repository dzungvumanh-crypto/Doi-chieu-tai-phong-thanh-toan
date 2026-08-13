"""Trang Nhật ký hệ thống — lịch sử thao tác ghi dữ liệu (ai, làm gì, kết quả, IP).

Nhãn "Công việc" và "Kết quả" do backend dịch sẵn (backend/services/audit_labels.py)
— frontend chỉ hiển thị, tránh phải đồng bộ 2 bảng ánh xạ ở 2 nơi.
"""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error


@ui.page("/audit-logs")
async def audit_logs_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.logs"):
        ui.navigate.to("/home")
        return
    _ = _sidebar("audit-logs")

    with _content_area():
        _page_header("Nhật ký hệ thống", "Lịch sử thao tác ghi dữ liệu — giữ tối đa 365 ngày")

        _method: list = [""]
        _q:      list = [""]
        _page:   list = [1]

        status_label   = ui.label("").classes("text-sm text-gray-500 mb-2")
        toolbar_row    = ui.row().classes("gap-2 mb-2 items-center flex-wrap")
        audit_container = ui.column().classes("w-full gap-0")
        pager_row      = ui.row().classes("gap-2 mt-3 items-center justify-center")

        async def _load(method: str = None, q: str = None, page: int = 1):
            if method is not None:
                _method[0] = method
            if q is not None:
                _q[0] = q
            _page[0] = page
            status_label.set_text("Đang tải...")
            audit_container.clear()
            pager_row.clear()
            try:
                data = await asyncio.to_thread(
                    api.get, "/api/admin/logs/audit",
                    {"method": _method[0], "q": _q[0], "page": page},
                )
            except Exception as e:
                status_label.set_text("Không thể tải nhật ký hệ thống.")
                _handle_api_error(e)
                return

            entries = data.get("entries", [])
            total   = data.get("total", 0)
            pages   = data.get("pages", 1)
            pg_size = data.get("page_size", 50)
            start_idx = (page - 1) * pg_size + 1
            status_label.set_text(
                f"Trang {page}/{pages} — "
                f"Bản ghi {start_idx}–{min(start_idx + pg_size - 1, total)} / {total} (mới nhất trước)"
            )

            with audit_container:
                if not entries:
                    ui.label("Không có bản ghi.").classes("text-gray-500 text-sm mt-2")
                    return
                with ui.row().classes("w-full bg-gray-100 border-b border-gray-200 px-3 py-2 items-center gap-2"):
                    ui.label("Thời gian").classes("font-semibold text-gray-700 text-xs w-36 shrink-0")
                    ui.label("Người thao tác").classes("font-semibold text-gray-700 text-xs w-44 shrink-0")
                    ui.label("Công việc").classes("font-semibold text-gray-700 text-xs flex-1")
                    ui.label("Kết quả").classes("font-semibold text-gray-700 text-xs w-32 shrink-0")
                    ui.label("IP").classes("font-semibold text-gray-700 text-xs w-32 shrink-0")
                for e in entries:
                    ts = (e.get("created_at") or "")[:19].replace("T", " ")
                    ok = e.get("result_ok", True)
                    res_cls = "bg-green-100 text-green-700" if ok else "bg-orange-100 text-orange-700"
                    with ui.row().classes(
                        f"w-full {'bg-white' if ok else 'bg-orange-50'} border-b border-gray-100 px-3 py-1.5 items-center gap-2"
                    ):
                        ui.label(ts).classes("text-xs font-mono w-36 shrink-0 text-gray-600")
                        ui.label(e.get("full_name") or e.get("username") or "—").classes(
                            "text-xs w-44 shrink-0 truncate")
                        # Công việc — path kỹ thuật ở tooltip cho ai cần tra cứu
                        ui.label(e.get("work") or "—").classes(
                            "text-xs flex-1 font-medium text-gray-800 truncate"
                        ).tooltip(e.get("target_type") or "")
                        ui.label(e.get("result") or "—").classes(
                            f"text-xs px-1.5 py-0.5 rounded {res_cls} w-32 shrink-0 text-center font-medium truncate")
                        ui.label(e.get("ip_address") or "—").classes(
                            "text-xs font-mono w-32 shrink-0 text-gray-500")

            with pager_row:
                ui.button("◀ Trước",
                          on_click=lambda: asyncio.ensure_future(_load(page=_page[0] - 1)),
                ).classes("text-sm bg-gray-200 text-gray-700").set_enabled(page > 1)
                ui.label(f"Trang {page} / {pages}").classes("text-sm text-gray-600 px-2")
                ui.button("Sau ▶",
                          on_click=lambda: asyncio.ensure_future(_load(page=_page[0] + 1)),
                ).classes("text-sm bg-gray-200 text-gray-700").set_enabled(page < pages)

        async def _export():
            try:
                from datetime import date as _d
                content = await asyncio.to_thread(
                    api.download, "/api/admin/logs/audit/export",
                    {"method": _method[0], "q": _q[0]},
                )
                ui.download(content, f"nhat_ky_he_thong_{_d.today().strftime('%Y%m%d')}.xlsx")
            except Exception as e:
                _handle_api_error(e)

        with toolbar_row:
            # Nhãn nút = việc người dùng thấy, không phải tên phương thức HTTP.
            # "Cập nhật" cũ bị hiểu nhầm là nút làm mới trang → đổi thành "Sửa".
            ui.label("Lọc:").classes("text-sm text-gray-500")
            for m, lbl, tip in [
                ("",       "Tất cả",   "Xem mọi thao tác"),
                ("POST",   "Thêm mới", "Chỉ xem thao tác tạo mới dữ liệu"),
                ("PUT",    "Sửa",      "Chỉ xem thao tác sửa dữ liệu đã có"),
                ("DELETE", "Xóa",      "Chỉ xem thao tác xóa dữ liệu"),
            ]:
                ui.button(lbl,
                          on_click=lambda mm=m: asyncio.ensure_future(_load(method=mm, page=1))).classes(
                    "text-sm bg-gray-100 text-gray-700 hover:bg-gray-200").tooltip(tip)
            search_in = ui.input(placeholder="Tìm người / đường dẫn...").props("dense outlined clearable").classes("w-64")
            search_in.on("keydown.enter",
                         lambda: asyncio.ensure_future(_load(q=search_in.value or "", page=1)))
            ui.button("Tìm", icon="search",
                      on_click=lambda: asyncio.ensure_future(_load(q=search_in.value or "", page=1))).classes(
                "text-sm bg-gray-700 text-white")
            ui.button("Làm mới", icon="refresh",
                      on_click=lambda: asyncio.ensure_future(_load(page=1))).classes(
                "text-sm bg-gray-700 text-white").tooltip("Tải lại danh sách, giữ nguyên bộ lọc")
            ui.button("Xuất Excel", icon="download",
                      on_click=_export).classes(
                "text-sm bg-green-700 text-white").tooltip("Tải Excel toàn bộ nhật ký (theo bộ lọc hiện tại)")

        await _load(page=1)
