"""Trang Chấm 459901 — phân loại bút toán tài khoản trung gian 459901."""

import asyncio

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)


@ui.page("/cham_459901")
async def cham_459901_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.cham_459901"):
        ui.navigate.to("/home")
        return

    # ── State ─────────────────────────────────────────────────────────────────
    state = {
        "file_bytes": None,
        "file_name":  "",
        "result":     None,
    }

    with ui.row().classes("w-full"):
        _sidebar("cham_459901")
        with _content_area():
            _page_header("Chấm 459901", "Phân loại bút toán tài khoản trung gian 459901")

            # ── Upload card ───────────────────────────────────────────────────
            with ui.card().classes("w-full p-5 mb-4"):
                ui.label("Tải lên file ZIP dữ liệu").classes(
                    "text-base font-semibold text-red-800 mb-3"
                )
                ui.label(
                    "File ZIP được mã hóa AES-256 — xuất từ hệ thống GL02."
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
                    on_upload=on_upload,
                    auto_upload=True,
                ).props('accept=".zip" flat dense label="Chọn file ZIP..."').classes("w-full mb-3")

                # ── Thanh tiến độ ─────────────────────────────────────────────
                progress_bar = ui.linear_progress(value=0).classes("w-full mb-1")
                progress_bar.set_visibility(False)
                progress_label = ui.label("").classes("text-xs text-gray-500 mb-3")
                progress_label.set_visibility(False)

                process_btn = ui.button(
                    "Xử lý",
                    icon="play_arrow",
                ).classes("bg-red-800 text-white")

                if not api.has_feature("cham_459901.process"):
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

                # Hiện thanh tiến độ
                progress_bar.set_value(0)
                progress_label.set_text("0% — Đang tải file lên...")
                progress_bar.set_visibility(True)
                progress_label.set_visibility(True)

                # ── Bước 1: Upload, nhận task_token ngay ──────────────────────
                try:
                    resp = await asyncio.to_thread(
                        api.post_upload,
                        "/api/cham459901/process",
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

                # ── Bước 2: Poll progress cho đến khi done ────────────────────
                while True:
                    await asyncio.sleep(1.0)
                    try:
                        prog = await asyncio.to_thread(
                            api.get, f"/api/cham459901/progress/{task_token}"
                        )
                    except Exception:
                        continue

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

            async def download_file(file_type: str):
                r = state.get("result")
                if not r:
                    return
                token        = r["token"]
                process_date = r.get("process_date", "")
                try:
                    data = await asyncio.to_thread(
                        api.get_bytes,
                        f"/api/cham459901/download/{token}/{file_type}",
                    )
                    ui.download(data, filename=f"459901_{file_type}_{process_date}.xlsx")
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative")

            def _render_result(r: dict):
                labels = {
                    "huy":  ("Lệnh Hủy",  "text-red-700",    "huy"),
                    "di":   ("Lệnh Đi",   "text-green-700",  "di"),
                    "khac": ("Lệnh Khác", "text-orange-700", "khac"),
                }
                with result_area:
                    with ui.card().classes("w-full p-5"):
                        with ui.row().classes("items-center gap-2 mb-4"):
                            ui.icon("check_circle", color="green").classes("text-xl")
                            ui.label(
                                f"Xử lý hoàn tất trong {r.get('elapsed_s', '?')}s"
                            ).classes("font-semibold text-green-700")

                        with ui.grid(columns=3).classes("w-full gap-4 mb-4"):
                            for ftype, (label, cls, code) in labels.items():
                                with ui.card().classes("p-4 text-center"):
                                    ui.label(label).classes(f"font-bold {cls} text-sm mb-1")
                                    ui.label(
                                        f"{r.get(ftype + '_rows', 0):,} dòng"
                                    ).classes("text-2xl font-bold text-gray-800 mb-3")
                                    dl_btn = ui.button(
                                        "Tải xuống",
                                        icon="download",
                                    ).classes("w-full bg-gray-700 text-white text-xs")
                                    # Closure trả async handler để NiceGUI giữ đúng client context
                                    def _make_dl(ft):
                                        async def _handler():
                                            await download_file(ft)
                                        return _handler
                                    dl_btn.on("click", _make_dl(code))

                        ui.separator().classes("my-2")
                        with ui.row().classes("gap-6 text-sm text-gray-600"):
                            ui.label(f"Tổng cộng: {r.get('total_rows', 0):,} dòng")
                            ui.label(f"Đã lọc bỏ: {r.get('filtered_rows', 0):,} dòng")

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
