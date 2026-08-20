"""Trang Chấm 459901 — phân loại bút toán tài khoản trung gian 459901."""

import asyncio

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)
from backend.services.cham459901_service import classify_upload_filename

_POLL_INTERVAL = 1.0

_KIND_LABELS = {
    "zip":     ("GL02 (chính)",       "bg-red-100 text-red-700"),
    "hub_di":  ("HUB đi",             "bg-blue-100 text-blue-700"),
    "hub_den": ("HUB đến",            "bg-purple-100 text-purple-700"),
    "ton":     ("Tồn tháng trước",    "bg-yellow-100 text-yellow-700"),
    None:      ("Không nhận diện",    "bg-gray-100 text-gray-500"),
}


@ui.page("/cham_459901")
async def cham_459901_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.cham_459901"):
        ui.navigate.to("/home")
        return

    # ── State ─────────────────────────────────────────────────────────────────
    state = {
        "files":            {},     # {filename: bytes}
        "task_token":       None,
        "result":           None,
        "cancel_requested": False,  # bấm Dừng trong lúc đang tải file lên (chưa có task_token)
    }

    with ui.row().classes("w-full"):
        _sidebar("cham_459901")
        with _content_area():
            _page_header("Chấm 459901", "Phân loại bút toán tài khoản trung gian 459901")

            # ── Upload card ───────────────────────────────────────────────────
            with ui.card().classes("w-full p-5 mb-4"):
                ui.label("Tải lên file dữ liệu").classes(
                    "text-base font-semibold text-red-800 mb-1"
                )
                ui.label(
                    "Kéo-thả hoặc chọn nhiều file cùng lúc — hệ thống tự nhận diện: "
                    "GL02*.zip (bắt buộc), file HUB đi (Quay_danh sach...), "
                    "file HUB đến (Danh_sach...den) — 2 file HUB tùy chọn, thiếu thì bỏ qua "
                    "nhóm 1000 Hoàn trả. File tồn tháng trước (459_TON_T<n>.xlsx) — tùy chọn, "
                    "ghép vào dữ liệu tháng này để phân loại lại các giao dịch chưa xử lý xong."
                ).classes("text-xs text-gray-400 mb-3")

                file_list_area = ui.column().classes("w-full gap-0 mb-2")

                def _render_file_list():
                    file_list_area.clear()
                    with file_list_area:
                        if not state["files"]:
                            ui.label("Chưa chọn file nào").classes(
                                "text-xs text-gray-400 italic"
                            )
                            return
                        for fname in list(state["files"].keys()):
                            kind = classify_upload_filename(fname)
                            label, cls = _KIND_LABELS[kind]
                            with ui.row().classes(
                                "items-center gap-2 py-1 border-b border-gray-100 w-full"
                            ):
                                ui.label(label).classes(
                                    f"text-xs font-medium px-2 py-0.5 rounded {cls}"
                                )
                                ui.label(fname).classes("text-xs text-gray-700 flex-grow truncate")

                                def _make_del(fn: str):
                                    def _handler():
                                        state["files"].pop(fn, None)
                                        _render_file_list()
                                    return _handler

                                ui.button(icon="close").props(
                                    "flat dense round size=sm"
                                ).classes("text-red-400").tooltip("Bỏ file này").on(
                                    "click", _make_del(fname)
                                )

                _render_file_list()

                def on_upload(e):
                    state["files"][e.name] = e.content.read()
                    _render_file_list()

                uploader = ui.upload(
                    on_upload=on_upload,
                    auto_upload=True,
                    multiple=True,
                ).props(
                    'accept=".zip,.xlsx" flat dense label="Kéo-thả hoặc chọn file..."'
                ).classes("w-full mb-3")

                # ── Thanh tiến độ ─────────────────────────────────────────────
                progress_bar = ui.linear_progress(value=0).classes("w-full mb-1")
                progress_bar.set_visibility(False)
                progress_label = ui.label("").classes("text-xs text-gray-500 mb-3")
                progress_label.set_visibility(False)

                with ui.row().classes("items-center gap-3"):
                    process_btn = ui.button(
                        "Xử lý",
                        icon="play_arrow",
                    ).classes("bg-red-800 text-white")
                    cancel_btn = (
                        ui.button("Dừng", icon="stop")
                        .classes("bg-gray-500 text-white")
                    )
                    cancel_btn.set_visibility(False)

                if not api.has_feature("cham_459901.process"):
                    process_btn.props("disable")
                    process_btn.tooltip("Bạn không có quyền thực hiện thao tác này")

            # ── Kết quả ───────────────────────────────────────────────────────
            result_area = ui.column().classes("w-full")

            # ── Helpers & handlers ────────────────────────────────────────────
            def _reset_all():
                """Đặt lại toàn bộ UI về trạng thái chưa chọn file."""
                state["files"]      = {}
                state["task_token"] = None
                state["result"]     = None
                uploader.reset()
                _render_file_list()
                result_area.clear()

            def on_cancel_click():
                async def _do():
                    if not state["task_token"]:
                        # Chưa tải file lên xong (chưa có task_token) — ghi nhận yêu cầu,
                        # do_process() sẽ tự dừng ngay khi nhận được task_token.
                        state["cancel_requested"] = True
                        progress_label.set_text("Đang tải file lên — sẽ dừng ngay khi xong...")
                        return
                    try:
                        await asyncio.to_thread(
                            api.post, f'/api/cham459901/cancel/{state["task_token"]}'
                        )
                        progress_label.set_text("Đang dừng — chờ tiến trình kết thúc...")
                    except Exception as e:
                        if not _handle_api_error(e):
                            ui.notify(f"Lỗi khi dừng: {e}", type="negative")
                asyncio.create_task(_do())

            cancel_btn.on("click", on_cancel_click)

            async def do_process():
                if not state["files"]:
                    ui.notify("Vui lòng chọn file trước", type="warning")
                    return
                if not any(classify_upload_filename(f) == "zip" for f in state["files"]):
                    ui.notify("Chưa có file GL02*.zip trong danh sách đã chọn", type="warning")
                    return

                state["cancel_requested"] = False
                process_btn.props("loading disable")
                cancel_btn.set_visibility(True)
                result_area.clear()

                progress_bar.set_value(0)
                progress_label.set_text("0% — Đang tải file lên...")
                progress_bar.set_visibility(True)
                progress_label.set_visibility(True)

                files_payload = [(name, data) for name, data in state["files"].items()]

                try:
                    resp = await asyncio.to_thread(
                        api.post_multipart, "/api/cham459901/process", files_payload,
                    )
                    state["task_token"] = resp["task_token"]
                    unrecognized = resp.get("unrecognized") or []
                    if unrecognized:
                        ui.notify(
                            f"Không nhận diện được: {', '.join(unrecognized)} — đã bỏ qua các file này",
                            type="warning",
                        )
                    duplicates = resp.get("duplicates") or {}
                    if duplicates:
                        chi_tiet = "; ".join(f"{k}: {', '.join(v)}" for k, v in duplicates.items())
                        ui.notify(
                            f"Trùng loại file, chỉ dùng file cuối cùng — {chi_tiet}",
                            type="warning", timeout=0, close_button=True,
                        )
                    if resp.get("hub_partial"):
                        ui.notify(
                            "Chỉ tìm thấy 1/2 file HUB — cả 2 chân (HUB đi + HUB đến) đều bị bỏ qua, "
                            "nhóm 1000 Hoàn trả sẽ trống. Tải lại đủ cả 2 file để chấm 1000HT.",
                            type="warning", timeout=0, close_button=True,
                        )
                except Exception as e:
                    progress_bar.set_visibility(False)
                    progress_label.set_visibility(False)
                    cancel_btn.set_visibility(False)
                    process_btn.props(remove="loading disable")
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative")
                    return

                # Người dùng đã bấm Dừng trong lúc file còn đang tải lên — dừng ngay,
                # không để job chạy nền vô ích (xem on_cancel_click).
                if state["cancel_requested"]:
                    try:
                        await asyncio.to_thread(
                            api.post, f'/api/cham459901/cancel/{state["task_token"]}'
                        )
                    except Exception:
                        pass

                # ── Poll progress cho đến khi done ─────────────────────────────
                while True:
                    await asyncio.sleep(_POLL_INTERVAL)

                    try:
                        prog = await asyncio.to_thread(
                            api.get, f'/api/cham459901/progress/{state["task_token"]}'
                        )
                    except Exception:
                        continue

                    pct = prog.get("pct", 0)
                    progress_bar.set_value(pct / 100)
                    progress_label.set_text(f"{pct}% — {prog.get('msg', '')}")

                    if prog.get("done"):
                        progress_bar.set_visibility(False)
                        progress_label.set_visibility(False)
                        if prog.get("cancelled"):
                            ui.notify("Đã dừng theo yêu cầu.", type="info")
                            _reset_all()
                        elif prog.get("error"):
                            ui.notify(f"Lỗi xử lý: {prog['error']}", type="negative")
                        else:
                            state["result"] = prog["result"]
                            _render_result(prog["result"])
                        break

                cancel_btn.set_visibility(False)
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

            async def delete_result():
                r = state.get("result")
                if not r:
                    return
                try:
                    await asyncio.to_thread(api.delete, f'/api/cham459901/result/{r["token"]}')
                    ui.notify("Đã xóa kết quả trên server — có thể tải lại file để chấm lại.", type="positive")
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi xóa kết quả: {e}", type="negative")
                    return
                _reset_all()

            def _render_result(r: dict):
                labels = {
                    "huy":    ("Lệnh Hủy",         "text-red-700"),
                    "di":     ("Lệnh Đi",          "text-green-700"),
                    "ht1000": ("1000 Hoàn trả",    "text-blue-700"),
                    "ccn":    ("Chuyển chi nhánh", "text-purple-700"),
                    "ko":     ("Điện KO offline",  "text-teal-700"),
                    "can_cn": ("Cân CN",           "text-yellow-700"),
                    "khac":   ("GD khác",          "text-orange-700"),
                }
                with result_area:
                    with ui.card().classes("w-full p-5"):
                        with ui.row().classes("items-center justify-between w-full mb-2"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("check_circle", color="green").classes("text-xl")
                                ui.label(
                                    f"Xử lý hoàn tất trong {r.get('elapsed_s', '?')}s"
                                ).classes("font-semibold text-green-700")
                            del_btn = ui.button(
                                "Xóa kết quả", icon="delete_outline",
                            ).classes("bg-red-50 text-red-700 text-xs")
                            del_btn.on("click", lambda: asyncio.create_task(delete_result()))

                        if not r.get("hub_provided"):
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("info", color="orange").classes("text-lg")
                                ui.label(
                                    "Chưa có file HUB đi/đến — nhóm 1000 Hoàn trả bỏ trống, "
                                    "các giao dịch đó nằm trong GD khác."
                                ).classes("text-xs text-gray-600")

                        if r.get("ton_rows_added", 0) > 0:
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("info", color="blue").classes("text-lg")
                                ui.label(
                                    f"Đã gộp {r['ton_rows_added']:,} dòng tồn tháng trước "
                                    "vào dữ liệu chấm."
                                ).classes("text-xs text-gray-600")

                        with ui.grid(columns=3).classes("w-full gap-4 my-4"):
                            for ftype, (label, cls) in labels.items():
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
                                    dl_btn.on("click", _make_dl(ftype))

                        ui.separator().classes("my-2")
                        with ui.row().classes("gap-6 text-sm text-gray-600"):
                            ui.label(f"Tổng cộng: {r.get('total_rows', 0):,} dòng")
                            ui.label(f"Đã lọc bỏ: {r.get('filtered_rows', 0):,} dòng")

            process_btn.on("click", do_process)
