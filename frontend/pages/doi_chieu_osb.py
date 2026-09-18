"""Trang Đối chiếu OSB — GL02 (IPCAS) <-> OSB chi tiết hạch toán, tài khoản trung gian OSB."""

import asyncio

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

_POLL_INTERVAL = 1.0
_MAX_POLL_FAILS = 4  # ~4s liên tiếp lỗi mới báo — tránh báo nhầm khi mạng chập chờn

# Chỉ 519910 đang có dữ liệu thật xác nhận (xem backend/services/doi_chieu_osb/config.py::
# TAI_KHOAN) — dropdown TĨNH, không gọi API riêng để liệt kê (module chỉ có 1 TK, chưa đáng
# thêm 1 endpoint chỉ để trả về 1 phần tử). Thêm TK mới thì thêm cả ở đây LẪN TAI_KHOAN.
_TAI_KHOAN_OPTIONS = {"519910": "519910"}


def _yyyymmdd_tu_dmy(s: str) -> str | None:
    """Mirror `doi_chieu_song_phuong.py::_yyyymmdd_tu_dmy` — chuyển "dd/mm/yyyy" (giá trị
    `ui.date`) sang "YYYYMMDD" (định dạng API cần)."""
    parts = s.strip().split("/")
    if len(parts) != 3:
        return None
    d, m, y = parts
    if not (d.isdigit() and m.isdigit() and y.isdigit()):
        return None
    return f"{y}{m.zfill(2)}{d.zfill(2)}"


@ui.page("/doi_chieu_osb")
async def doi_chieu_osb_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.doi_chieu_osb"):
        ui.navigate.to("/home")
        return

    # ── State ─────────────────────────────────────────────────────────────────
    state = {
        "files": {},       # {filename: bytes}
        "task_token": None,
        "result": None,
    }

    with ui.row().classes("w-full"):
        await _sidebar("doi_chieu_osb")
        with _content_area():
            _page_header(
                "Đối chiếu OSB",
                "GL02 (IPCAS) <-> OSB chi tiết hạch toán — tài khoản trung gian OSB",
            )

            with ui.card().classes("w-full p-5 mb-4"):
                with ui.row().classes("gap-3 items-end mb-3"):
                    with ui.input(
                        label="Ngày đối chiếu", placeholder="dd/mm/yyyy",
                    ).props("outlined dense").classes("w-44") as ngay_input:
                        with ui.menu().props("no-parent-event") as ngay_menu:
                            ui.date(mask="DD/MM/YYYY").props(
                                'first-day-of-week="1"'
                            ).bind_value(ngay_input)
                        with ngay_input.add_slot("append"):
                            ui.icon("event").on("click", ngay_menu.open).classes(
                                "cursor-pointer text-gray-500"
                            )
                    ma_tk_select = ui.select(
                        _TAI_KHOAN_OPTIONS,
                        label="Tài khoản trung gian",
                        value="519910",
                    ).props("outlined dense").classes("w-52")

                ui.label(
                    "Kéo-thả đúng 1 file .zip (GL02) + file(s) .xlsx (OSB chi tiết hạch toán, "
                    "thường 2 file/ngày)."
                ).classes("text-xs text-gray-400 mb-3")

                file_list_area = ui.column().classes("w-full gap-0 mb-2")

                def _kind_for_display(fname: str) -> str:
                    low = fname.lower()
                    if low.endswith(".zip"):
                        return "GL02"
                    if low.endswith(".xlsx"):
                        return "OSB"
                    return "?"

                def _render_file_list():
                    file_list_area.clear()
                    with file_list_area:
                        if not state["files"]:
                            ui.label("Chưa chọn file nào").classes(
                                "text-xs text-gray-400 italic"
                            )
                            return
                        for fname in list(state["files"].keys()):
                            kind = _kind_for_display(fname)
                            cls = {
                                "GL02": "bg-red-100 text-red-700",
                                "OSB": "bg-blue-100 text-blue-700",
                                "?": "bg-gray-100 text-gray-500",
                            }[kind]
                            with ui.row().classes(
                                "items-center gap-2 py-1 border-b border-gray-100 w-full"
                            ):
                                ui.label(kind).classes(
                                    f"text-xs font-medium px-2 py-0.5 rounded {cls}"
                                )
                                ui.label(fname).classes(
                                    "text-xs text-gray-700 flex-grow truncate"
                                )

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

                ui.upload(
                    on_upload=on_upload,
                    auto_upload=True,
                    multiple=True,
                ).props(
                    'accept=".zip,.xlsx" flat dense label="Kéo-thả hoặc chọn file..."'
                ).classes("w-full")

            with ui.card().classes("w-full p-5 mb-4"):
                progress_bar = ui.linear_progress(value=0).classes("w-full mb-1")
                progress_bar.set_visibility(False)
                progress_label = ui.label("").classes("text-xs text-gray-500 mb-3")
                progress_label.set_visibility(False)

                process_btn = ui.button("Chạy", icon="play_arrow").classes(
                    "bg-red-800 text-white"
                )
                if not api.has_feature("doi_chieu_osb.process"):
                    process_btn.props("disable")
                    process_btn.tooltip("Bạn không có quyền thực hiện thao tác này")

            result_area = ui.column().classes("w-full")

            # ── Helpers & handlers ────────────────────────────────────────────
            # Gắn THẲNG hàm async, KHÔNG bọc asyncio.create_task — xem docs/DESIGN.md mục
            # "Event handler async": task mới có ngăn xếp slot rỗng nên ui.notify/ui.navigate
            # trong nhánh lỗi ném RuntimeError, im lặng không có traceback.
            async def do_process():
                ngay = _yyyymmdd_tu_dmy(ngay_input.value or "")
                ma_tk = ma_tk_select.value
                if not ngay:
                    ui.notify("Ngày đối chiếu chưa hợp lệ — bấm icon lịch để chọn.",
                              type="warning")
                    return
                if not ma_tk:
                    ui.notify("Chưa chọn tài khoản trung gian.", type="warning")
                    return
                if not any(f.lower().endswith(".zip") for f in state["files"]):
                    ui.notify("Chưa có file GL02 (.zip) trong danh sách đã chọn",
                              type="warning")
                    return
                if not any(f.lower().endswith(".xlsx") for f in state["files"]):
                    ui.notify("Chưa có file OSB (.xlsx) trong danh sách đã chọn",
                              type="warning")
                    return

                process_btn.props("loading disable")
                result_area.clear()

                progress_bar.set_value(0)
                progress_label.set_text("0% — Đang tải file lên...")
                progress_bar.set_visibility(True)
                progress_label.set_visibility(True)

                try:
                    resp = await asyncio.to_thread(
                        api.post_upload, "/api/doi_chieu_osb/process",
                        files=[('files', (name, data, 'application/octet-stream'))
                               for name, data in state["files"].items()],
                        data={"ma_tk": ma_tk, "ngay": ngay},
                    )
                    state["task_token"] = resp["task_token"]
                except Exception as e:
                    progress_bar.set_visibility(False)
                    progress_label.set_visibility(False)
                    process_btn.props(remove="loading disable")
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative", timeout=0,
                                  close_button=True)
                    return

                # ── Poll progress cho đến khi done ─────────────────────────────
                poll_fails = 0
                while True:
                    await asyncio.sleep(_POLL_INTERVAL)

                    try:
                        prog = await asyncio.to_thread(
                            api.get, f'/api/doi_chieu_osb/progress/{state["task_token"]}'
                        )
                    except Exception as e:
                        if _handle_api_error(e):
                            progress_bar.set_visibility(False)
                            progress_label.set_visibility(False)
                            process_btn.props(remove="loading disable")
                            return
                        poll_fails += 1
                        if poll_fails >= _MAX_POLL_FAILS:
                            progress_bar.set_visibility(False)
                            progress_label.set_visibility(False)
                            process_btn.props(remove="loading disable")
                            ui.notify(
                                "Mất kết nối tới máy chủ hoặc job đã hết hạn (có thể do "
                                "backend khởi động lại) — không rõ đã xử lý xong hay chưa. "
                                "Vui lòng kiểm tra lại và chạy lại nếu cần.",
                                type="negative", timeout=0, close_button=True,
                            )
                            return
                        continue
                    poll_fails = 0

                    pct = prog.get("pct", 0)
                    progress_bar.set_value(pct / 100)
                    progress_label.set_text(f"{pct}% — {prog.get('msg', '')}")

                    if prog.get("done"):
                        progress_bar.set_visibility(False)
                        progress_label.set_visibility(False)
                        if prog.get("error"):
                            ui.notify(f"Lỗi xử lý: {prog['error']}", type="negative",
                                      timeout=0, close_button=True)
                        else:
                            state["result"] = prog["result"]
                            _render_result(prog["result"])
                        break

                process_btn.props(remove="loading disable")

            async def download_zip():
                r = state.get("result")
                if not r:
                    return
                try:
                    data = await asyncio.to_thread(
                        api.get_bytes, f"/api/doi_chieu_osb/download/{r['token']}",
                    )
                    ui.download(data, filename=f"doi_chieu_osb_{r['ma_tk']}_{r['ngay']}.zip")
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative")

            def _render_result(r: dict):
                canh_bao = r.get("canh_bao") or {}
                with result_area:
                    with ui.card().classes("w-full p-5"):
                        with ui.row().classes("items-center gap-2 mb-2"):
                            ui.icon("check_circle", color="green").classes("text-xl")
                            ui.label(
                                f"Xử lý hoàn tất trong {r.get('elapsed_s', '?')}s"
                            ).classes("font-semibold text-green-700")

                        with ui.grid(columns=2).classes("w-full gap-4 my-4"):
                            with ui.card().classes("p-4 text-center"):
                                ui.label("Chênh lệch Nợ").classes(
                                    "font-bold text-red-700 text-sm mb-1"
                                )
                                ui.label(
                                    f"GL02: {r.get('no_gl02_rows', 0):,} dòng · "
                                    f"OSB: {r.get('no_osb_rows', 0):,} dòng"
                                ).classes("text-lg font-bold text-gray-800")
                            with ui.card().classes("p-4 text-center"):
                                ui.label("Chênh lệch Có").classes(
                                    "font-bold text-blue-700 text-sm mb-1"
                                )
                                ui.label(
                                    f"GL02: {r.get('co_gl02_rows', 0):,} dòng · "
                                    f"OSB: {r.get('co_osb_rows', 0):,} dòng"
                                ).classes("text-lg font-bold text-gray-800")

                        if canh_bao.get("remark_ngan"):
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("warning", color="orange").classes("text-lg")
                                ui.label(
                                    f"{canh_bao['remark_ngan']:,} dòng GL02 có REMARK < 7 ký "
                                    "tự — rủi ro khoá rỗng, kiểm tra lại nếu bất thường."
                                ).classes("text-xs text-gray-600")
                        if canh_bao.get("nhom_huy_qua_2"):
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("warning", color="orange").classes("text-lg")
                                ui.label(
                                    f"{canh_bao['nhom_huy_qua_2']:,} nhóm OSB có >2 dòng cùng "
                                    "Mã giao dịch, tổng tiền = 0 — CỐ Ý không đánh dấu Hủy, "
                                    "cần chấm tay."
                                ).classes("text-xs text-gray-600")

                        ui.button(
                            "Tải kết quả (.zip)", icon="download",
                        ).classes("bg-gray-700 text-white mt-2").on("click", download_zip)

            process_btn.on("click", do_process)
