"""Trang lịch sử lỗi và cảnh báo hệ thống."""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error

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
    if not api.has_feature("menu.logs"):
        ui.navigate.to("/home")
        return
    _ = _sidebar("logs")

    with _content_area():
        _page_header("Lịch sử lỗi & cảnh báo", "Nhật ký ứng dụng — tối đa 50 bản ghi mỗi trang")

        _level: list = [""]
        _page:  list = [1]

        toolbar_row   = ui.row().classes("gap-2 mb-2 items-center flex-wrap")
        status_label  = ui.label("Đang tải...").classes("text-sm text-gray-500 mb-2")
        log_container = ui.column().classes("w-full gap-0")
        pager_row     = ui.row().classes("gap-2 mt-3 items-center justify-center")

        async def _load(level: str = "", page: int = 1):
            _level[0] = level
            _page[0]  = page
            status_label.set_text("Đang tải...")
            log_container.clear()
            pager_row.clear()
            try:
                data = await asyncio.to_thread(
                    api.get, "/api/admin/logs/", {"level": level, "page": page}
                )
            except Exception as e:
                status_label.set_text("Không thể tải log.")
                if _handle_api_error(e):
                    return
                return

            entries   = data.get("entries", []) if isinstance(data, dict) else []
            total     = data.get("total", 0) if isinstance(data, dict) else 0
            pages     = data.get("pages", 1) if isinstance(data, dict) else 1
            pg_size   = data.get("page_size", 50) if isinstance(data, dict) else 50
            start_idx = (page - 1) * pg_size + 1

            status_label.set_text(
                f"Trang {page}/{pages} — "
                f"Bản ghi {start_idx}–{min(start_idx + pg_size - 1, total)} / {total} (mới nhất trước)"
            )

            with log_container:
                if not entries:
                    ui.label("Không có bản ghi nào.").classes("text-gray-500 text-sm mt-4")
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
                        # Log nhiều dòng (traceback) chỉ khác ở chỗ giữ nguyên xuống dòng —
                        # `whitespace-pre-wrap` làm được việc đó trên chính ui.label, không cần
                        # thẻ <pre>. Bản cũ dùng ui.element("pre").set_text(): Element không có
                        # set_text (chỉ ui.label mới có) nên trang vỡ ĐÚNG LÚC có traceback để đọc.
                        if "\n" in msg:
                            ui.label(msg).classes(
                                "text-xs font-mono flex-1 whitespace-pre-wrap break-all text-gray-800 leading-5"
                            )
                        else:
                            ui.label(msg).classes("text-xs flex-1 break-all text-gray-800")

            # ── Phân trang ──────────────────────────────────────────────────────
            with pager_row:
                ui.button("◀ Trước",
                          on_click=lambda: asyncio.ensure_future(_load(_level[0], _page[0] - 1)),
                ).classes("text-sm bg-gray-200 text-gray-700").set_enabled(page > 1)
                ui.label(f"Trang {page} / {pages}").classes("text-sm text-gray-600 px-2")
                ui.button("Sau ▶",
                          on_click=lambda: asyncio.ensure_future(_load(_level[0], _page[0] + 1)),
                ).classes("text-sm bg-gray-200 text-gray-700").set_enabled(page < pages)

        # ── Gắn controls vào toolbar ────────────────────────────────────────────
        with toolbar_row:
            ui.button("↻ Làm mới", icon="refresh",
                      on_click=lambda: asyncio.ensure_future(_load(_level[0], 1))).classes(
                "bg-gray-700 text-white text-sm")
            ui.separator().props("vertical")
            for _code, _vn in [("", "Tất cả"), ("ERROR", "Lỗi"), ("WARNING", "Cảnh báo"), ("INFO", "Thông tin")]:
                ui.button(_vn,
                          on_click=lambda c=_code: asyncio.ensure_future(_load(c, 1))).classes(
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

            backup_info_label = ui.label("").classes("text-xs text-gray-500 ml-2")
            try:
                bk = await asyncio.to_thread(api.get, "/api/admin/logs/backup-info")
                if isinstance(bk, dict):
                    # Đếm riêng bản đặt tay: chúng KHÔNG bị dọn tự động nên nằm
                    # đó mãi, gộp chung vào số "bản" làm người xem tưởng backup
                    # tự động đang chạy dày hơn thực tế.
                    tay = bk.get("count_thu_cong") or 0
                    them = f" + {tay} bản đặt tay" if tay else ""
                    if bk.get("exists"):
                        backup_info_label.set_text(
                            f"Backup tự động gần nhất: {bk['time']} "
                            f"({bk.get('count', 1)} bản{them})"
                        )
                    else:
                        backup_info_label.set_text(f"Chưa có backup tự động{them}")
            except Exception:
                pass

            # ── Badge lệch giờ so với nguồn NTP ──────────────────────────────
            drift_badge = ui.label("").classes("text-xs px-2 py-0.5 rounded border ml-2")
            _base_cls = "text-xs px-2 py-0.5 rounded border ml-2"
            try:
                ts = await asyncio.to_thread(api.get, "/api/admin/logs/time-sync")
                if not isinstance(ts, dict) or not ts.get("enabled"):
                    txt, color = "Đồng bộ giờ: đã tắt", "bg-gray-100 text-gray-500 border-gray-300"
                elif ts.get("error"):
                    txt, color = f"Giờ chuẩn: không kiểm tra được ({ts['server']})", "bg-gray-100 text-gray-500 border-gray-300"
                    drift_badge.tooltip(ts["error"])
                elif ts.get("ok"):
                    txt, color = f"Giờ máy khớp NTP (lệch {ts['drift_seconds']}s)", "bg-green-100 text-green-700 border-green-300"
                else:
                    txt, color = f"⚠ Đồng hồ lệch {ts['drift_seconds']}s so với NTP {ts['server']}", "bg-red-100 text-red-700 border-red-300"
                    drift_badge.tooltip(f"Ngưỡng cho phép {ts.get('threshold')}s — kiểm tra đồng hồ máy chủ")
                drift_badge.classes(replace=f"{_base_cls} {color}")
                drift_badge.set_text(txt)
            except Exception:
                pass

        await _load("", 1)
