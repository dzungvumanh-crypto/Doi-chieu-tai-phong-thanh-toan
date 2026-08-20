"""Trang Đối chiếu Song phương — định tuyến lệnh IPCAS theo ngân hàng + chiều.

Upload ZIP (mã hóa AES) → định tuyến 4 NH × 2 chiều (ĐẾN/ĐI) → 8 file CSV.
"""

import asyncio
import time

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

# Tiến độ xử lý lưu trong bộ nhớ backend: backend restart là mất sạch, poll sẽ
# 404 mãi mãi. Hai mốc dừng dưới đây để nút không kẹt "đang xử lý" vĩnh viễn.
_MAX_POLL_SECONDS = 900   # 15 phút — dài hơn mọi file thực tế
_MAX_POLL_FAILS = 10      # số lần lỗi liên tiếp thì bỏ cuộc


@ui.page("/doi_chieu_song_phuong")
async def doi_chieu_song_phuong_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.doi_chieu_song_phuong"):
        ui.navigate.to("/home")
        return

    # ── State ─────────────────────────────────────────────────────────────────
    state = {"file_bytes": None, "file_name": "", "result": None}

    with ui.row().classes("w-full"):
        await _sidebar("doi_chieu_song_phuong")
        with _content_area():
            _page_header(
                "Đối chiếu Song phương",
                "Phân loại lệnh IPCAS theo ngân hàng và chiều giao dịch (ĐẾN / ĐI)",
            )

            # ── Upload card ───────────────────────────────────────────────────
            with ui.card().classes("w-full p-5 mb-4"):
                ui.label("Tải lên file ZIP dữ liệu IPCAS").classes(
                    "text-base font-semibold text-red-800 mb-3"
                )
                ui.label(
                    "File ZIP mã hóa AES-256 — xuất từ IPCAS. "
                    "Hệ thống định tuyến 4 ngân hàng đối chiếu: "
                    "Vietinbank (201), BIDV (202), Vietcombank (203), MBBank (311)."
                ).classes("text-xs text-gray-500 mb-4")

                file_label = ui.label("Chưa chọn file").classes(
                    "text-xs text-gray-500 italic mb-2"
                )

                def on_upload(e):
                    state["file_bytes"] = e.content.read()
                    state["file_name"]  = e.name
                    file_label.set_text(f"Đã chọn: {e.name}")
                    file_label.classes(remove="text-gray-500 italic", add="text-green-700 font-medium")

                uploader = ui.upload(
                    on_upload=on_upload, auto_upload=True,
                ).props('accept=".zip" flat dense label="Chọn file ZIP..."').classes("w-full mb-3")

                progress_bar = ui.linear_progress(value=0).classes("w-full mb-1")
                progress_bar.set_visibility(False)
                progress_label = ui.label("").classes("text-xs text-gray-500 mb-3")
                progress_label.set_visibility(False)

                process_btn = ui.button("Xử lý", icon="play_arrow").classes(
                    "bg-red-800 text-white"
                )
                if not api.has_feature("doi_chieu_song_phuong.process"):
                    process_btn.props("disable")
                    process_btn.tooltip("Bạn không có quyền thực hiện thao tác này")

            # ── Kết quả ───────────────────────────────────────────────────────
            result_area = ui.column().classes("w-full")

            # ── Handlers ──────────────────────────────────────────────────────
            async def do_process():
                if not state["file_bytes"]:
                    ui.notify("Vui lòng chọn file ZIP trước", type="warning")
                    return

                process_btn.props("loading disable")
                result_area.clear()
                progress_bar.set_value(0)
                progress_label.set_text("0% — Đang tải file lên...")
                progress_bar.set_visibility(True)
                progress_label.set_visibility(True)

                # ── Bước 1: upload, nhận task_token ──────────────────────────
                try:
                    resp = await asyncio.to_thread(
                        api.post_upload,
                        "/api/doi_chieu_song_phuong/process",
                        {"file": (state["file_name"], state["file_bytes"], "application/zip")},
                    )
                    task_token = resp["task_token"]
                except Exception as e:
                    progress_bar.set_visibility(False)
                    progress_label.set_visibility(False)
                    process_btn.props(remove="loading disable")
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative")
                    return

                # ── Bước 2: poll progress ────────────────────────────────────
                deadline = time.monotonic() + _MAX_POLL_SECONDS
                fails = 0
                while True:
                    await asyncio.sleep(1.0)

                    if time.monotonic() > deadline:
                        progress_bar.set_visibility(False)
                        progress_label.set_visibility(False)
                        ui.notify(
                            "Quá thời gian chờ xử lý. File có thể quá lớn hoặc máy chủ đã "
                            "khởi động lại — hãy thử lại.",
                            type="negative", multi_line=True, close_button=True,
                        )
                        break

                    try:
                        prog = await asyncio.to_thread(
                            api.get, f"/api/doi_chieu_song_phuong/progress/{task_token}"
                        )
                        fails = 0
                    except Exception as e:
                        fails += 1
                        if fails < _MAX_POLL_FAILS:
                            continue
                        progress_bar.set_visibility(False)
                        progress_label.set_visibility(False)
                        if not _handle_api_error(e):
                            ui.notify(
                                f"Mất liên lạc với máy chủ khi theo dõi tiến độ: {e}",
                                type="negative", multi_line=True, close_button=True,
                            )
                        break

                    pct = prog.get("pct", 0)
                    progress_bar.set_value(pct / 100)
                    progress_label.set_text(f"{pct}% — {prog.get('msg', '')}")

                    if prog.get("done"):
                        progress_bar.set_visibility(False)
                        progress_label.set_visibility(False)
                        if prog.get("error"):
                            ui.notify(f"Lỗi xử lý: {prog['error']}", type="negative")
                        else:
                            state["result"] = prog["result"]
                            _render_result(prog["result"])
                        break

                process_btn.props(remove="loading disable")

            async def download_file(file_key: str):
                r = state.get("result")
                if not r:
                    return
                token = r["token"]
                date  = r.get("process_date", "")
                try:
                    data = await asyncio.to_thread(
                        api.get_bytes,
                        f"/api/doi_chieu_song_phuong/download/{token}/{file_key}",
                    )
                    ui.download(data, filename=f"{file_key}_{date}.csv")
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative")

            def _render_result(r: dict):
                # index rows theo (ma_nh, chieu) để dựng nút tải
                rows_by_key = {f["file_key"]: f["rows"] for f in r.get("files", [])}

                with result_area:
                    with ui.card().classes("w-full p-5"):
                        with ui.row().classes("items-center gap-2 mb-4"):
                            ui.icon("check_circle", color="green").classes("text-xl")
                            ui.label(
                                f"Xử lý hoàn tất trong {r.get('elapsed_s', '?')}s "
                                f"— {r.get('total_rows', 0):,} dòng"
                            ).classes("font-semibold text-green-700")

                        # ── Bảng thống kê ─────────────────────────────────────
                        columns = [
                            {"name": "ma_nh",  "label": "Mã NH",     "field": "ma_nh",  "align": "left"},
                            {"name": "ten_nh", "label": "Ngân hàng", "field": "ten_nh", "align": "left"},
                            {"name": "den",    "label": "Lệnh ĐẾN",  "field": "so_lenh_den"},
                            {"name": "di",     "label": "Lệnh ĐI",   "field": "so_lenh_di"},
                            {"name": "tong",   "label": "Tổng",      "field": "tong"},
                        ]
                        ui.table(columns=columns, rows=r.get("stats", []),
                                 row_key="ma_nh").classes("w-full mb-4")

                        # ── Nút tải 8 file (mỗi NH 1 hàng: ĐẾN + ĐI) ─────────
                        ui.label("Tải file CSV").classes("font-semibold text-red-800 mb-2")
                        for s in r.get("stats", []):
                            ma = s["ma_nh"]
                            with ui.row().classes("w-full items-center gap-3 mb-2"):
                                ui.label(f'{ma} · {s["ten_nh"]}').classes(
                                    "text-sm font-medium w-40 shrink-0"
                                )
                                for chieu, tag, cls in (
                                    ("DEN", "ĐẾN", "text-blue-700"),
                                    ("DI",  "ĐI",  "text-green-700"),
                                ):
                                    key  = f"{ma}_{chieu}"
                                    rows = rows_by_key.get(key, 0)
                                    btn  = ui.button(
                                        f"{tag} ({rows:,})", icon="download",
                                    ).props("outline dense").classes(f"{cls} text-xs")

                                    def _make_dl(k):
                                        async def _handler():
                                            await download_file(k)
                                        return _handler
                                    btn.on("click", _make_dl(key))

            process_btn.on("click", do_process)

    # Click bất kỳ đâu trong vùng upload (trừ button) đều mở file picker
    await ui.context.client.connected()
    await ui.run_javascript(f'''
        setTimeout(function() {{
            var el = document.getElementById("c{uploader.id}");
            if (!el) return;
            var inp = el.querySelector('input[type="file"]');
            if (!inp) return;
            el.style.cursor = 'pointer';
            el.addEventListener('click', function(e) {{
                if (!e.target.closest('button')) inp.click();
            }});
        }}, 200);
    ''')
