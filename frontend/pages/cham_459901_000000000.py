"""Trang Chấm TK 459901-1000-000000000 — Cân ITT / Điện KO offline / GD khác.

Anh em của `cham_459901.py` (TK 459901-1000-000007709): cùng khuôn trang, khác API + kết quả.
"""

import asyncio
import re
import unicodedata

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _require_auth, _handle_api_error,
)

_TEN_TK = "459901-1000-000000000"
_API = "/api/cham459901_000000000"

_POLL_INTERVAL = 1.0
_MAX_POLL_FAILS = 4  # ~4s liên tiếp lỗi mới báo — tránh báo nhầm khi mạng chập chờn

_KIND_LABELS = {
    "main": ("GL02 (chính)",    "bg-red-100 text-red-700"),
    "ton":  ("Tồn tháng trước", "bg-yellow-100 text-yellow-700"),
    None:   ("Không nhận diện", "bg-gray-100 text-gray-500"),
}

# Tên tải về theo loại kết quả — bản sao của `_TEN_TAI` ở backend/api/cham459901_000000000.py
_TEN_TAI = {
    "can_itt": "GD_can_ITT",
    "ko":      "GD_dien_KO_offline",
    "khac":    "GD_khac",
}


# Bản sao CHỈ ĐỂ HIỂN THỊ nhãn loại file trước khi tải lên. Logic phân loại THẬT nằm ở
# backend/services/cham459901_000000000_service.py — server tự phân loại lại khi nhận file.
# Không import thẳng module backend để khỏi kéo pandas + pyzipper vào tiến trình frontend.
# tests/test_classify_filename_frontend_backend_sync.py canh hai bản không trôi khỏi nhau.
_DUOI_EXCEL = ('.xlsx', '.xlsm', '.xlsb', '.xls')
_DUOI_HOP_LE = ('.zip',) + _DUOI_EXCEL


def _bo_dau(s: str) -> str:
    s = unicodedata.normalize('NFD', s.lower().replace('đ', 'd'))
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def _classify_upload_filename(filename: str) -> str | None:
    if filename.startswith('~$'):     # file khoá tạm của Office — xem la_tep_khoa_office() ở backend
        return None
    name = _bo_dau(filename)
    if not name.endswith(_DUOI_EXCEL):
        return None
    if '459' in name and (re.search(r'(?<![a-z])ton(?![a-z])', name)
                          or re.search(r'(?<![a-z])ma[\s_\-]*0(?!\d)', name)):
        return 'ton'
    return None


def _navy_header(title: str, subtitle: str = ""):
    """Thanh tiêu đề nền xanh navy đậm, chữ trắng — cùng banner với hai trang CITAD cuối ngày
    (doi_chieu_citad, doi_soat_citad) và Sổ trực; mỗi trang giữ bản riêng, không đụng shared.py.
    Thay hẳn `_page_header()` nên trang không còn dòng breadcrumb — giống các trang đó."""
    with ui.column().classes("w-full bg-blue-950 rounded-2xl px-6 py-4 mb-4 gap-0.5"):
        ui.label(title).classes("text-xl font-bold text-white tracking-wide")
        if subtitle:
            ui.label(subtitle).classes("text-blue-200 text-sm")


def _kind_for_display(fname: str) -> str | None:
    """Chỉ file tồn có mẫu tên riêng; GL02 chính nhận theo ĐUÔI FILE giống backend."""
    if fname.startswith('~$'):
        return None
    kind = _classify_upload_filename(fname)
    if kind is not None:
        return kind
    return "main" if fname.lower().endswith(_DUOI_HOP_LE) else None


@ui.page("/cham_459901_000000000")
async def cham_459901_000000000_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.cham_459901_000000000"):
        ui.navigate.to("/home")
        return

    # ── State ─────────────────────────────────────────────────────────────────
    state = {
        "files":            {},     # {filename: bytes}
        "task_token":       None,
        "result":           None,
        "cancel_requested": False,  # bấm Dừng trong lúc đang tải file lên (chưa có task_token)
    }

    _CLASSIFY_HINT = (
        "Hệ thống tự nhận diện: file GL02 (GL02_..._1000.zip hoặc Excel) — bắt buộc, "
        "nhiều file thì gộp. File tồn tháng trước (459_TON... hoặc 459-mã 0...) — tùy "
        "chọn, ghép vào dữ liệu tháng này để chấm lại các giao dịch chưa xử lý xong; "
        "thiếu file tồn thì vẫn chấm bình thường."
    )

    with ui.row().classes("w-full"):
        await _sidebar("cham_459901_000000000")
        with _content_area():
            _navy_header(
                f"CHẤM TK {_TEN_TK}",
                f"Phân loại bút toán TK {_TEN_TK}: GD cân ITT / Điện KO offline / GD khác",
            )

            with ui.row().classes("w-full gap-4 mb-4 items-stretch"):
                # ── Tải file lên (cách nạp dữ liệu duy nhất) ────────────────
                with ui.card().classes("flex-1 p-5"):
                    ui.label("Tải nhiều file lên").classes(
                        "text-sm font-semibold text-gray-700 mb-1"
                    )
                    ui.label(
                        "Kéo-thả hoặc chọn nhiều file cùng lúc — " + _CLASSIFY_HINT
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
                                kind = _kind_for_display(fname)
                                label, cls = _KIND_LABELS[kind]
                                with ui.row().classes(
                                    "items-center gap-2 py-1 border-b border-gray-100 w-full"
                                ):
                                    ui.label(label).classes(
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

                    uploader = ui.upload(
                        on_upload=on_upload,
                        auto_upload=True,
                        multiple=True,
                    ).props(
                        'accept=".zip,.xlsx" flat dense label="Kéo-thả hoặc chọn file..."'
                    ).classes("w-full")

            with ui.card().classes("w-full p-5 mb-4"):
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
                    # Cùng kiểu nút RESET của trang Đối soát CITAD (viền đỏ). Khoá trong lúc chạy: Reset
                    # giữa chừng làm trang mất task_token còn lượt nền vẫn chạy và chiếm cửa chốt của người khác
                    # — muốn dừng thì có nút "Dừng". Handler gắn sau, khi `_reset_all` đã được định nghĩa.
                    reset_btn = ui.button("Reset", icon="restart_alt").props("outline").classes("text-red-600")
                    reset_btn.tooltip("Xoá file đã chọn và kết quả trên màn hình để chấm lại từ đầu")

                if not api.has_feature("cham_459901_000000000.process"):
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

            def _ket_thuc_chay():
                """Trả các nút về trạng thái rảnh sau một lượt (xong, lỗi hoặc bị dừng)."""
                cancel_btn.set_visibility(False)
                process_btn.props(remove="loading disable")
                reset_btn.props(remove="disable")

            def do_reset():
                state["cancel_requested"] = False
                _reset_all()
                ui.notify("Đã reset — chọn file để chấm lại", type="info")

            def confirm_reset():
                if not state["files"] and not state["result"]:
                    ui.notify("Chưa có gì để reset.", type="info")
                    return
                with ui.dialog() as dlg, ui.card():
                    ui.label("Xác nhận reset?").classes("text-lg font-bold text-red-600")
                    ui.label(
                        "Các file đã chọn và kết quả đang hiện trên màn hình sẽ bị xoá để bắt đầu lại. "
                        "File đã tải xuống không bị ảnh hưởng. Kết quả lưu trên máy chủ tự dọn lúc 23h "
                        "(bấm \"Xóa kết quả\" nếu muốn xoá ngay)."
                    ).classes("text-sm text-gray-700")
                    with ui.row().classes("mt-3 gap-2 justify-end w-full"):
                        ui.button("Huỷ", on_click=dlg.close).props("dense outline")

                        def _confirm():
                            dlg.close()
                            do_reset()

                        ui.button("Reset", on_click=_confirm).classes("bg-red-600 text-white").props("dense")
                dlg.open()

            reset_btn.on("click", confirm_reset)

            # Gắn THẲNG hàm async, không bọc asyncio.create_task — xem docs/DESIGN.md
            # mục "Event handler async".
            async def on_cancel_click():
                if not state["task_token"]:
                    # Chưa tải file lên xong (chưa có task_token) — ghi nhận yêu cầu,
                    # do_process() sẽ tự dừng ngay khi nhận được task_token.
                    state["cancel_requested"] = True
                    progress_label.set_text("Đang tải file lên — sẽ dừng ngay khi xong...")
                    return
                try:
                    await asyncio.to_thread(
                        api.post, f'{_API}/cancel/{state["task_token"]}'
                    )
                    progress_label.set_text("Đang dừng — chờ tiến trình kết thúc...")
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi khi dừng: {e}", type="negative")

            cancel_btn.on("click", on_cancel_click)

            async def do_process():
                if not state["files"]:
                    ui.notify("Vui lòng chọn file", type="warning")
                    return
                if not any(
                    _kind_for_display(f) == "main" for f in state["files"]
                ):
                    ui.notify(
                        "Chưa có file GL02 (.zip hoặc Excel) trong danh sách đã chọn",
                        type="warning",
                    )
                    return

                # Không chặn — thiếu tồn vẫn chấm được — nhưng nói TRƯỚC khi chạy: quên file tồn
                # âm thầm làm kết quả lệch bản chấm đầy đủ (426/28/4 thay vì 428/30/6 ở tháng 8)
                if not any(_kind_for_display(f) == "ton" for f in state["files"]):
                    ui.notify(
                        "Chưa chọn file tồn tháng trước (459_TON… / 459-mã 0…) — vẫn chấm được, "
                        "nhưng giao dịch tồn từ kỳ trước sẽ không được tính.",
                        type="warning", timeout=8000,
                    )

                state["cancel_requested"] = False
                process_btn.props("loading disable")
                reset_btn.props("disable")
                cancel_btn.set_visibility(True)
                result_area.clear()

                progress_bar.set_value(0)
                progress_label.set_text("0% — Đang tải file lên...")
                progress_bar.set_visibility(True)
                progress_label.set_visibility(True)

                try:
                    resp = await asyncio.to_thread(
                        api.post_upload, f"{_API}/process",
                        files=[('files', (name, data, 'application/octet-stream'))
                               for name, data in state["files"].items()],
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
                except Exception as e:
                    progress_bar.set_visibility(False)
                    progress_label.set_visibility(False)
                    _ket_thuc_chay()
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative", timeout=0,
                                  close_button=True)
                    return

                # Người dùng đã bấm Dừng trong lúc file còn đang tải lên — dừng ngay,
                # không để job chạy nền vô ích (xem on_cancel_click).
                if state["cancel_requested"]:
                    try:
                        await asyncio.to_thread(
                            api.post, f'{_API}/cancel/{state["task_token"]}'
                        )
                    except Exception:
                        pass        # job có thể chưa kịp tạo — dọn dẹp thôi, không báo lỗi

                # ── Poll progress cho đến khi done ─────────────────────────────
                poll_fails = 0
                while True:
                    await asyncio.sleep(_POLL_INTERVAL)

                    try:
                        prog = await asyncio.to_thread(
                            api.get, f'{_API}/progress/{state["task_token"]}'
                        )
                    except Exception as e:
                        # Không nuốt SessionExpiredError: quay vòng vô hạn khi backend khởi động
                        # lại thì thanh tiến trình chạy mãi, không lỗi, không kết quả.
                        if _handle_api_error(e):
                            progress_bar.set_visibility(False)
                            progress_label.set_visibility(False)
                            _ket_thuc_chay()
                            return
                        poll_fails += 1
                        if poll_fails >= _MAX_POLL_FAILS:
                            progress_bar.set_visibility(False)
                            progress_label.set_visibility(False)
                            _ket_thuc_chay()
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
                        if prog.get("cancelled"):
                            ui.notify("Đã dừng theo yêu cầu.", type="info")
                            _reset_all()
                        elif prog.get("error"):
                            ui.notify(f"Lỗi xử lý: {prog['error']}", type="negative")
                        else:
                            state["result"] = prog["result"]
                            try:
                                _render_result(prog["result"])
                            except Exception as e:
                                # Lỗi dựng màn hình kết quả không được bỏ qua lặng lẽ (kết quả đã chạy xong ở máy chủ)
                                # và cũng không được làm kẹt nút Xử lý/Reset ở trạng thái khoá
                                ui.notify(f"Lỗi hiển thị kết quả: {e}", type="negative", timeout=0, close_button=True)
                        break

                _ket_thuc_chay()

            async def download_file(file_type: str):
                r = state.get("result")
                if not r:
                    return
                token        = r["token"]
                process_date = r.get("process_date", "")
                try:
                    data = await asyncio.to_thread(
                        api.get_bytes,
                        f"{_API}/download/{token}/{file_type}",
                    )
                    ui.download(
                        data, filename=f"{_TEN_TK}_{_TEN_TAI[file_type]}_{process_date}.xlsx",
                    )
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative")

            async def delete_result():
                r = state.get("result")
                if not r:
                    return
                try:
                    await asyncio.to_thread(api.delete, f'{_API}/result/{r["token"]}')
                    ui.notify("Đã xóa kết quả trên server — có thể tải lại file để chấm lại.", type="positive")
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi xóa kết quả: {e}", type="negative")
                    return
                _reset_all()

            def _render_result(r: dict):
                labels = {
                    "can_itt": ("GD cân ITT",      "text-green-700"),
                    "ko":      ("Điện KO offline", "text-teal-700"),
                    "khac":    ("GD khác",         "text-orange-700"),
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
                            del_btn.on("click", delete_result)

                        if r.get("ton_rows_added", 0) > 0:
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("info", color="blue").classes("text-lg")
                                ui.label(
                                    f"Đã gộp {r['ton_rows_added']:,} dòng tồn tháng trước "
                                    "vào dữ liệu chấm."
                                ).classes("text-xs text-gray-600")
                        elif r.get("ton_provided"):
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("warning", color="orange").classes("text-lg")
                                ui.label(
                                    f"File tồn đã chọn nhưng không có dòng nào của TK {_TEN_TK} "
                                    "— kiểm tra lại có đúng file tồn của tài khoản này không."
                                ).classes("text-xs text-gray-600")
                        else:
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("warning", color="orange").classes("text-lg")
                                ui.label(
                                    "KHÔNG có file tồn tháng trước — các giao dịch chưa xử lý xong từ kỳ "
                                    "trước không được tính, nên dòng đối ứng của chúng ở tháng này rơi "
                                    "vào GD khác và kết quả sẽ khác bản chấm có file tồn. "
                                    "Thêm file tồn (459_TON… / 459-mã 0…) rồi chạy lại nếu cần."
                                ).classes("text-xs text-gray-600")

                        # Cảnh báo dữ liệu vào từ backend (Excel bị cắt, dòng trùng, GL02 không có dòng nào của TK…)
                        for msg in r.get("canh_bao") or []:
                            with ui.row().classes("items-center gap-2 mb-2 no-wrap"):
                                ui.icon("warning", color="orange").classes("text-lg")
                                ui.label(msg).classes("text-xs text-gray-700 font-medium")

                        if r.get("ko_thieu_chuoi_rows", 0) > 0:
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("warning", color="orange").classes("text-lg")
                                ui.label(
                                    f"{r['ko_thieu_chuoi_rows']:,} dòng Điện KO offline chỉ khớp theo "
                                    "số tiền (Tổng Nợ = Tổng Có), không có chuỗi 'Remitting "
                                    "Amount:VND' — xem cột GHI_CHU để soát lại."
                                ).classes("text-xs text-gray-600")

                        if r.get("khac_nghi_ko_rows", 0) > 0:
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("warning", color="orange").classes("text-lg")
                                ui.label(
                                    f"{r['khac_nghi_ko_rows']:,} dòng GD khác có chuỗi 'Remitting "
                                    "Amount:VND' nhưng chưa khớp đủ cặp — cần chấm tay."
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
