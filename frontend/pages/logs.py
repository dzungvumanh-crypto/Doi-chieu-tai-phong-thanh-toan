"""Trang nhật ký hệ thống."""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error

# ─── LOGS PAGE ───────────────────────────────────────────────────────────────
_LOG_LEVEL_CFG = {
    "ERROR":   ("Lỗi",       "bg-red-100 text-red-700 border-red-300"),
    "WARNING": ("Cảnh báo",  "bg-orange-100 text-orange-700 border-orange-300"),
    "INFO":    ("Thông tin", "bg-blue-100 text-blue-700 border-blue-300"),
    "DEBUG":   ("Debug",     "bg-gray-100 text-gray-500 border-gray-300"),
}


@ui.page("/logs")
async def logs_page():
    if not _require_auth():
        return
    user = api.get_current_user()
    if not user or user.get("role") not in ("admin", "giam_doc", "pho_giam_doc"):
        ui.navigate.to("/home")
        return
    _ = _sidebar("logs")

    with _content_area():
        _page_header("Nhật ký hệ thống", "Xem lịch sử lỗi và cảnh báo của ứng dụng")

        _level: list = [""]

        # ── Toolbar ────────────────────────────────────────────────────────────
        # (nút load được gắn sau khi _load được định nghĩa bên dưới)
        toolbar_row = ui.row().classes("gap-2 mb-2 items-center flex-wrap")
        status_label = ui.label("Đang tải...").classes("text-sm text-gray-500 mb-2")
        log_container = ui.column().classes("w-full gap-0")

        # ── Hàm load log ───────────────────────────────────────────────────────
        async def _load(level: str = ""):
            _level[0] = level
            status_label.set_text("Đang tải...")
            log_container.clear()
            try:
                data = await asyncio.to_thread(
                    api.get, "/api/admin/logs/", {"level": level, "limit": 500}
                )
            except Exception as e:
                status_label.set_text("Không thể tải log.")
                if _handle_api_error(e):
                    return
                return
            entries = data.get("entries", []) if isinstance(data, dict) else []
            total   = data.get("total", len(entries)) if isinstance(data, dict) else len(entries)
            status_label.set_text(f"Hiển thị {len(entries)} / {total} bản ghi (mới nhất trước)")

            with log_container:
                if not entries:
                    ui.label("Không có bản ghi nào.").classes("text-gray-400 text-sm mt-4")
                    return

                with ui.row().classes("w-full bg-gray-100 border-b border-gray-200 px-3 py-2 items-center gap-2"):
                    ui.label("Thời gian").classes("font-semibold text-gray-700 text-xs w-36 shrink-0")
                    ui.label("Mức độ").classes("font-semibold text-gray-700 text-xs w-24 shrink-0")
                    ui.label("Nguồn").classes("font-semibold text-gray-700 text-xs w-48 shrink-0")
                    ui.label("Nội dung").classes("font-semibold text-gray-700 text-xs flex-1")

                for e in entries:
                    lv  = e.get("level", "INFO")
                    lbl, badge_cls = _LOG_LEVEL_CFG.get(lv, (lv, "bg-gray-100 text-gray-500 border-gray-300"))
                    row_bg = "bg-red-50" if lv == "ERROR" else ("bg-orange-50" if lv == "WARNING" else "bg-white")
                    msg = e.get("msg", "")

                    with ui.row().classes(f"w-full {row_bg} border-b border-gray-100 px-3 py-1.5 items-start gap-2"):
                        ui.label(e.get("ts", "")).classes("text-xs font-mono w-36 shrink-0 text-gray-600 mt-0.5")
                        ui.label(lbl).classes(
                            f"text-xs font-medium px-2 py-0.5 rounded border {badge_cls} w-24 shrink-0 text-center mt-0.5"
                        )
                        ui.label(e.get("logger", "")).classes("text-xs font-mono w-48 shrink-0 text-gray-500 truncate mt-0.5")
                        if "\n" in msg:
                            ui.element("pre").classes(
                                "text-xs font-mono flex-1 whitespace-pre-wrap break-all text-gray-800 leading-5"
                            ).style("margin:0;background:transparent").set_text(msg)
                        else:
                            ui.label(msg).classes("text-xs flex-1 break-all text-gray-800")

        # ── Gắn nút vào toolbar ────────────────────────────────────────────────
        with toolbar_row:
            ui.button("↻ Làm mới", icon="refresh",
                      on_click=lambda: asyncio.ensure_future(_load(_level[0]))).classes(
                "bg-gray-700 text-white text-sm")
            ui.separator().props("vertical")
            for _code, _vn in [("", "Tất cả"), ("ERROR", "Lỗi"), ("WARNING", "Cảnh báo"), ("INFO", "Thông tin")]:
                ui.button(_vn,
                          on_click=lambda c=_code: asyncio.ensure_future(_load(c))).classes(
                    "text-sm bg-gray-100 text-gray-700 hover:bg-gray-200")
            ui.separator().props("vertical")

            async def _backup_db():
                try:
                    content = await asyncio.to_thread(api.download, "/api/admin/logs/backup")
                    from datetime import date as _dt
                    ui.download(content, f"ksnb_backup_{_dt.today().isoformat()}.db")
                    ui.notify("Đã tạo bản sao DB thành công!", type="positive")
                except Exception as e:
                    _handle_api_error(e)

            ui.button("Backup DB", icon="backup",
                      on_click=_backup_db).classes("bg-orange-600 text-white text-sm").tooltip(
                "Tải về bản sao cơ sở dữ liệu")

            # ── Thông tin backup tự động ──────────────────────────────────────
            backup_info_label = ui.label("").classes("text-xs text-gray-400 ml-2")
            try:
                bk = await asyncio.to_thread(api.get, "/api/admin/logs/backup-info")
                if isinstance(bk, dict) and bk.get("exists"):
                    backup_info_label.set_text(
                        f"Backup gần nhất: {bk['time']} ({bk.get('count',1)} bản)"
                    )
                else:
                    backup_info_label.set_text("Chưa có backup tự động")
            except Exception:
                pass

        await _load("")

        # ── Nhật ký đăng nhập ─────────────────────────────────────────────────
        ui.separator().classes("my-4")
        with ui.row().classes("items-center gap-3 mb-2"):
            ui.label("Nhật ký đăng nhập").classes("text-base font-bold text-gray-800")
            login_status_label = ui.label("").classes("text-sm text-gray-500")

        login_filter_ref: list = [""]
        login_container = ui.column().classes("w-full gap-0")

        async def _load_logins(success_filter: str = ""):
            login_filter_ref[0] = success_filter
            login_status_label.set_text("Đang tải...")
            login_container.clear()
            try:
                data = await asyncio.to_thread(
                    api.get, "/api/admin/logs/logins",
                    {"success": success_filter, "limit": 200},
                )
            except Exception:
                login_status_label.set_text("Không thể tải nhật ký đăng nhập.")
                return
            entries = data.get("entries", []) if isinstance(data, dict) else []
            total   = data.get("total", len(entries)) if isinstance(data, dict) else len(entries)
            login_status_label.set_text(f"{len(entries)} / {total} bản ghi")

            with login_container:
                if not entries:
                    ui.label("Không có bản ghi.").classes("text-gray-400 text-sm mt-2")
                    return
                with ui.row().classes("w-full bg-gray-100 border-b border-gray-200 px-3 py-2 items-center gap-2"):
                    ui.label("Thời gian").classes("font-semibold text-gray-700 text-xs w-36 shrink-0")
                    ui.label("Kết quả").classes("font-semibold text-gray-700 text-xs w-20 shrink-0")
                    ui.label("Username").classes("font-semibold text-gray-700 text-xs w-28 shrink-0")
                    ui.label("Họ và tên").classes("font-semibold text-gray-700 text-xs w-40 shrink-0")
                    ui.label("IP").classes("font-semibold text-gray-700 text-xs w-28 shrink-0")
                    ui.label("Chi tiết").classes("font-semibold text-gray-700 text-xs flex-1")
                for e in entries:
                    ok = e.get("success", False)
                    badge_cls = "bg-green-100 text-green-700" if ok else "bg-red-100 text-red-700"
                    badge_txt = "Thành công" if ok else "Thất bại"
                    with ui.row().classes("w-full bg-white border-b border-gray-100 px-3 py-1.5 items-center gap-2"):
                        ts = (e.get("created_at") or "")[:16].replace("T", " ")
                        ui.label(ts).classes("text-xs font-mono w-36 shrink-0 text-gray-600")
                        ui.label(badge_txt).classes(f"text-xs px-1.5 py-0.5 rounded {badge_cls} w-20 shrink-0 text-center")
                        ui.label(e.get("username", "")).classes("text-xs w-28 shrink-0 font-mono truncate")
                        ui.label(e.get("full_name") or "—").classes("text-xs w-40 shrink-0 truncate")
                        ui.label(e.get("ip_address") or "—").classes("text-xs font-mono w-28 shrink-0 text-gray-500")
                        ui.label(e.get("detail") or "").classes("text-xs flex-1 text-gray-500 truncate")

        async def _export_logins():
            try:
                from datetime import date as _d
                content = await asyncio.to_thread(
                    api.download, "/api/admin/logs/logins/export",
                    {"success": login_filter_ref[0]},
                )
                ui.download(content, f"nhat_ky_dang_nhap_{_d.today().strftime('%Y%m%d')}.xlsx")
            except Exception as e:
                _handle_api_error(e)

        with ui.row().classes("gap-2 mb-2 items-center"):
            for _sf, _lbl in [("", "Tất cả"), ("true", "Thành công"), ("false", "Thất bại")]:
                ui.button(_lbl,
                          on_click=lambda f=_sf: asyncio.ensure_future(_load_logins(f))).classes(
                    "text-sm bg-gray-100 text-gray-700 hover:bg-gray-200")
            ui.button("↻", icon="refresh",
                      on_click=lambda: asyncio.ensure_future(_load_logins(login_filter_ref[0]))).classes(
                "text-sm bg-gray-700 text-white")
            ui.button("Xuất Excel", icon="download",
                      on_click=_export_logins).classes(
                "text-sm bg-green-700 text-white").tooltip("Tải Excel nhật ký đăng nhập (theo bộ lọc hiện tại)")

        await _load_logins("")
