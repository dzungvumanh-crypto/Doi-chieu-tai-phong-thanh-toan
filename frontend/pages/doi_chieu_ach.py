"""Trang Đối chiếu ACH — GL02 (IPCAS/NPO) vs MIS PaymentHub.

Tải bộ file 1 ngày (GL02, GW, 2 ZIP MIS ĐI, 2 ZIP MIS ĐẾN, PDF sao kê) → hệ
thống đối chiếu 2 chiều ĐI/ĐẾN → file Excel nhiều sheet + CSV cho sheet lớn.

Mỗi file được đẩy sang backend NGAY khi chọn (không gom lại rồi gửi 1 lần) —
xem lý do ở docstring `backend/api/doi_chieu_ach.py`.
"""

import asyncio
import time

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)

# Một lần chạy thật mất 3–8 phút; để 1 giờ cho trường hợp dữ liệu rất lớn.
_MAX_POLL_SECONDS = 3600
_MAX_POLL_FAILS = 10
_POLL_INTERVAL = 1.5

# Yêu cầu đầu vào — khớp với pattern engine dùng để tìm file (xem engine.py)
_YEU_CAU = [
    ("gl02",    "File GL02 (GL02*.zip)",              1),
    ("gw",      "File GW (.xlsx)",                    1),
    ("mis_di",  "MIS chiều ĐI (*_DI_*.zip)",          2),
    ("mis_den", "MIS chiều ĐẾN (*_DEN_*.zip)",        2),
    ("pdf",     "Sao kê ACH (.pdf) — lấy số session", 1),
]


def _phan_loai(name: str) -> str | None:
    """Xếp file vào nhóm yêu cầu. Không khớp nhóm nào → None (backend bỏ qua)."""
    n = name.upper()
    if n.endswith(".PDF"):
        return "pdf"
    if n.endswith(".XLSX"):
        return "gw"
    if n.endswith(".ZIP"):
        if n.startswith("GL02"):
            return "gl02"
        if "_DI_" in n:
            return "mis_di"
        if "_DEN_" in n:
            return "mis_den"
    return None


def _co_nho(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


@ui.page("/doi_chieu_ach")
async def doi_chieu_ach_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.doi_chieu_ach"):
        ui.navigate.to("/home")
        return

    co_quyen_chay = api.has_feature("doi_chieu_ach.process")

    # ── State ────────────────────────────────────────────────────────────────
    # token: phiên xử lý trên backend, tạo khi tải file đầu tiên
    state = {
        "token": None, "files": [], "result": None,
        "dang_chay": False, "n_logs": 0, "lock": asyncio.Lock(),
    }

    with ui.row().classes("w-full"):
        _sidebar("doi_chieu_ach")
        with _content_area():
            _page_header(
                "Đối chiếu ACH",
                "Đối chiếu GL02 (IPCAS) với MIS PaymentHub — hai chiều ĐI và ĐẾN",
            )

            # ══ Card 1: Tải file ═════════════════════════════════════════════
            with ui.card().classes("w-full p-5 mb-4"):
                ui.label("Tải lên dữ liệu của ngày cần đối chiếu").classes(
                    "text-base font-semibold text-red-800 mb-1"
                )
                ui.label(
                    "Chọn (hoặc kéo thả) toàn bộ file của một ngày. Có thể chọn nhiều lần; "
                    "mỗi file được gửi lên máy chủ ngay khi chọn."
                ).classes("text-xs text-gray-500 mb-3")

                with ui.row().classes("w-full gap-6 items-start no-wrap"):
                    # ── Cột trái: uploader + danh sách file ──
                    with ui.column().classes("flex-1 gap-2"):
                        uploader = ui.upload(
                            multiple=True, auto_upload=True,
                            max_file_size=500_000_000,
                        ).props(
                            'accept=".zip,.xlsx,.pdf" flat dense '
                            'label="Chọn file (.zip, .xlsx, .pdf)"'
                        ).classes("w-full")
                        if not co_quyen_chay:
                            uploader.props("disable")

                        file_area = ui.column().classes("w-full gap-1")

                    # ── Cột phải: checklist yêu cầu ──
                    with ui.column().classes("w-72 shrink-0 gap-1"):
                        ui.label("Đã đủ file chưa?").classes("text-sm font-semibold text-gray-700")
                        check_area = ui.column().classes("w-full gap-0")

                ui.separator().classes("my-3")

                with ui.row().classes("w-full items-center gap-3"):
                    ngay_input = ui.input(
                        "Ngày đối chiếu",
                        placeholder="dd/mm/yyyy — để trống: tự lấy từ tên file PDF",
                    ).props("dense outlined").classes("w-80")

                    run_btn = ui.button("Chạy đối chiếu", icon="play_arrow").classes(
                        "bg-red-800 text-white"
                    )
                    cancel_btn = ui.button("Dừng", icon="stop").props("outline color=grey")
                    cancel_btn.set_visibility(False)

                    if not co_quyen_chay:
                        run_btn.props("disable")
                        run_btn.tooltip("Bạn không có quyền thực hiện thao tác này")

            # ══ Card 2: Tiến độ ══════════════════════════════════════════════
            progress_card = ui.card().classes("w-full p-5 mb-4")
            progress_card.set_visibility(False)
            with progress_card:
                progress_label = ui.label("").classes("text-sm font-medium text-gray-700 mb-1")
                progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full mb-3")
                with ui.expansion("Nhật ký xử lý", icon="terminal").classes("w-full"):
                    log_view = ui.log(max_lines=300).classes("w-full h-64 text-xs")

            # ══ Card 3: Kết quả ══════════════════════════════════════════════
            result_area = ui.column().classes("w-full")

            # ── Danh sách file & checklist ───────────────────────────────────
            def _ve_checklist():
                dem = {}
                for f in state["files"]:
                    if f["loai"]:
                        dem[f["loai"]] = dem.get(f["loai"], 0) + 1
                check_area.clear()
                with check_area:
                    for key, nhan, can in _YEU_CAU:
                        co = dem.get(key, 0)
                        du = co >= can
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.icon(
                                "check_circle" if du else "radio_button_unchecked",
                                color="green" if du else "grey",
                            ).classes("text-sm")
                            ui.label(f"{nhan} — {co}/{can}").classes(
                                f"text-xs {'text-green-700' if du else 'text-gray-500'}"
                            )

            def _ve_danh_sach():
                file_area.clear()
                with file_area:
                    if not state["files"]:
                        ui.label("Chưa có file nào").classes("text-xs text-gray-500 italic")
                    for f in state["files"]:
                        with ui.row().classes("items-center gap-2 w-full no-wrap"):
                            if f.get("dang_tai"):
                                ui.spinner(size="sm")
                                ui.label(f"Đang gửi {f['name']}...").classes(
                                    "text-xs text-orange-600 flex-1"
                                )
                            else:
                                ui.icon(
                                    "description" if f["loai"] else "help_outline",
                                    color="green" if f["loai"] else "orange",
                                ).classes("text-sm")
                                nhan = f"{f['name']} ({_co_nho(f['size'])})"
                                if not f["loai"]:
                                    nhan += " — không thuộc nhóm nào, sẽ bị bỏ qua"
                                ui.label(nhan).classes(
                                    f"text-xs flex-1 {'text-gray-700' if f['loai'] else 'text-orange-600'}"
                                )
                                if not state["dang_chay"] and co_quyen_chay:
                                    ui.button(
                                        icon="close",
                                        on_click=lambda _e=None, n=f["name"]: _xoa_file(n),
                                    ).props("dense flat round size=sm")
                _ve_checklist()

            # ── Tải 1 file lên backend ───────────────────────────────────────
            # Handler PHẢI đồng bộ và đọc e.content ngay dòng đầu: NiceGUI trả
            # response cho trình duyệt xong mới chạy handler bất đồng bộ, lúc đó
            # file tạm của request đã có thể bị đóng → đọc ra rỗng. Byte đọc được
            # giữ tạm trong entry["raw"] và được giải phóng ngay sau khi gửi xong.
            def _on_upload(e):
                if state["dang_chay"]:
                    ui.notify("Đang xử lý — không thêm file được nữa", type="warning")
                    return

                name = e.name
                if any(f["name"] == name for f in state["files"]):
                    ui.notify(f"'{name}' đã có trong danh sách", type="warning")
                    return

                entry = {
                    "name": name, "size": 0, "loai": _phan_loai(name),
                    "dang_tai": True, "raw": e.content.read(),
                }
                state["files"].append(entry)
                _ve_danh_sach()
                ui.timer(0.01, lambda: _gui_len_backend(entry), once=True)

            async def _gui_len_backend(entry: dict):
                name = entry["name"]
                try:
                    # Khoá: nhiều file tải song song, nếu không sẽ tạo nhiều phiên
                    async with state["lock"]:
                        if state["token"] is None:
                            resp = await asyncio.to_thread(api.post, "/api/doi_chieu_ach/session")
                            state["token"] = resp["token"]

                    resp = await asyncio.to_thread(
                        api.post_upload,
                        f"/api/doi_chieu_ach/upload/{state['token']}",
                        {"file": (name, entry["raw"], "application/octet-stream")},
                    )
                    entry["size"] = resp["size"]
                except Exception as ex:
                    if entry in state["files"]:
                        state["files"].remove(entry)
                    if not _handle_api_error(ex):
                        ui.notify(f"Lỗi gửi file {name}: {ex}", type="negative",
                                  multi_line=True, close_button=True)
                finally:
                    entry.pop("raw", None)
                    entry["dang_tai"] = False
                _ve_danh_sach()

            uploader.on_upload(_on_upload)

            async def _xoa_file(name: str):
                if state["token"]:
                    try:
                        await asyncio.to_thread(
                            api.delete, f"/api/doi_chieu_ach/upload/{state['token']}/{name}"
                        )
                    except Exception as ex:
                        if not _handle_api_error(ex):
                            ui.notify(f"Không xoá được trên máy chủ: {ex}", type="negative")
                        return
                state["files"] = [f for f in state["files"] if f["name"] != name]
                _ve_danh_sach()

            # ── Chạy ─────────────────────────────────────────────────────────
            def _thieu_gi() -> list[str]:
                dem = {}
                for f in state["files"]:
                    if f["loai"]:
                        dem[f["loai"]] = dem.get(f["loai"], 0) + 1
                return [nhan for key, nhan, can in _YEU_CAU if dem.get(key, 0) < can]

            async def do_run():
                if state["dang_chay"]:
                    return
                if not state["token"] or not state["files"]:
                    ui.notify("Vui lòng chọn file trước", type="warning")
                    return
                if any(f.get("dang_tai") for f in state["files"]):
                    ui.notify("Còn file đang gửi lên — chờ một chút", type="warning")
                    return

                thieu = _thieu_gi()
                if thieu:
                    ui.notify(
                        "Còn thiếu: " + "; ".join(thieu),
                        type="warning", multi_line=True, close_button=True,
                    )
                    return

                state["dang_chay"] = True
                state["result"] = None
                state["n_logs"] = 0
                result_area.clear()
                log_view.clear()
                progress_bar.set_value(0)
                progress_label.set_text("Đang gửi yêu cầu xử lý...")
                progress_card.set_visibility(True)
                run_btn.props("loading disable")
                cancel_btn.set_visibility(True)
                _ve_danh_sach()

                token = state["token"]
                try:
                    await asyncio.to_thread(
                        api.post, f"/api/doi_chieu_ach/start/{token}",
                        {"ngay_doi_chieu": (ngay_input.value or "").strip()},
                    )
                except Exception as ex:
                    _ket_thuc_chay()
                    if not _handle_api_error(ex):
                        ui.notify(f"Không bắt đầu được: {ex}", type="negative",
                                  multi_line=True, close_button=True)
                    return

                await _theo_doi(token)

            def _ket_thuc_chay():
                state["dang_chay"] = False
                run_btn.props(remove="loading disable")
                cancel_btn.set_visibility(False)
                _ve_danh_sach()

            async def _theo_doi(token: str):
                deadline = time.monotonic() + _MAX_POLL_SECONDS
                fails = 0
                while True:
                    await asyncio.sleep(_POLL_INTERVAL)

                    if time.monotonic() > deadline:
                        _ket_thuc_chay()
                        ui.notify(
                            "Quá thời gian chờ. Dữ liệu có thể quá lớn hoặc máy chủ đã khởi "
                            "động lại — hãy thử lại.",
                            type="negative", multi_line=True, close_button=True,
                        )
                        return

                    try:
                        prog = await asyncio.to_thread(
                            api.get, f"/api/doi_chieu_ach/progress/{token}"
                        )
                        fails = 0
                    except Exception as ex:
                        fails += 1
                        if fails < _MAX_POLL_FAILS:
                            continue
                        _ket_thuc_chay()
                        if not _handle_api_error(ex):
                            ui.notify(f"Mất liên lạc với máy chủ: {ex}", type="negative",
                                      multi_line=True, close_button=True)
                        return

                    # Chỉ đẩy các dòng log mới
                    logs = prog.get("logs") or []
                    for line in logs[state["n_logs"]:]:
                        log_view.push(line)
                    state["n_logs"] = len(logs)

                    pct = prog.get("pct", 0)
                    progress_bar.set_value(pct / 100)
                    progress_label.set_text(f"{pct}% — {prog.get('msg', '')}")

                    if prog.get("done"):
                        _ket_thuc_chay()
                        if prog.get("cancelled"):
                            # Huỷ là do người dùng bấm — báo bình thường, không đỏ
                            progress_label.set_text("Đã huỷ theo yêu cầu")
                            ui.notify("Đã dừng đối chiếu theo yêu cầu", type="info")
                        elif prog.get("error"):
                            progress_label.set_text(prog["error"])
                            ui.notify(f"Lỗi xử lý: {prog['error']}", type="negative",
                                      multi_line=True, close_button=True)
                        else:
                            state["result"] = prog["result"]
                            _ve_ket_qua(prog["result"])
                        return

            async def do_cancel():
                if not state["token"]:
                    return
                try:
                    await asyncio.to_thread(
                        api.post, f"/api/doi_chieu_ach/cancel/{state['token']}"
                    )
                    ui.notify("Đã gửi yêu cầu dừng — chờ bước hiện tại kết thúc",
                              type="info")
                except Exception as ex:
                    if not _handle_api_error(ex):
                        ui.notify(f"Không dừng được: {ex}", type="negative")

            # ── Kết quả ──────────────────────────────────────────────────────
            async def _tai_file(filename: str):
                try:
                    data = await asyncio.to_thread(
                        api.get_bytes,
                        f"/api/doi_chieu_ach/download/{state['token']}/{filename}",
                    )
                    ui.download(data, filename=filename)
                except Exception as ex:
                    if not _handle_api_error(ex):
                        ui.notify(f"Lỗi tải file: {ex}", type="negative")

            async def _tai_tat_ca():
                try:
                    data = await asyncio.to_thread(
                        api.get_bytes, f"/api/doi_chieu_ach/download-all/{state['token']}"
                    )
                    ui.download(data, filename="ket_qua_doi_chieu_ach.zip")
                except Exception as ex:
                    if not _handle_api_error(ex):
                        ui.notify(f"Lỗi tải file: {ex}", type="negative")

            def _ve_ket_qua(r: dict):
                s = r.get("summary", {})
                rows = [
                    {"ct": "Số giao dịch khớp",        "di": s.get("di_khop", 0),
                     "den": s.get("den_khop", 0)},
                    {"ct": "GL02 chưa khớp (NPO thừa)", "di": s.get("npo_di_thua", 0),
                     "den": s.get("npo_den_thua", 0)},
                    {"ct": "MIS chưa khớp",            "di": s.get("mis_di_thua", 0),
                     "den": s.get("mis_den_thua", 0)},
                    {"ct": "Timeout không kênh (TPAY)", "di": s.get("timeout", 0), "den": "—"},
                ]

                result_area.clear()
                with result_area:
                    with ui.card().classes("w-full p-5"):
                        with ui.row().classes("items-center gap-2 mb-1"):
                            ui.icon("check_circle", color="green").classes("text-xl")
                            ui.label("Đối chiếu hoàn tất").classes(
                                "font-semibold text-green-700"
                            )
                        ui.label(
                            f"Ngày {s.get('ngay_doi_chieu', '?')} · Session "
                            f"{s.get('session_id', '?')}"
                        ).classes("text-xs text-gray-500 mb-3")

                        ui.table(
                            columns=[
                                {"name": "ct",  "label": "Chỉ tiêu", "field": "ct", "align": "left"},
                                {"name": "di",  "label": "Chiều ĐI",  "field": "di"},
                                {"name": "den", "label": "Chiều ĐẾN", "field": "den"},
                            ],
                            rows=rows, row_key="ct",
                        ).classes("w-full mb-2")

                        if s.get("timeout"):
                            ui.label(
                                f"Có {s['timeout']:,} lệnh TPAY timeout không đi kênh "
                                f"(tổng {s.get('timeout_tien', 0):,} VND) — xem sheet "
                                f"TIMEOUT_KHONG_KENH."
                            ).classes("text-xs text-orange-700 mb-3")

                        ui.label("Tải kết quả").classes("font-semibold text-red-800 mb-2")
                        files = r.get("files", [])
                        for f in files:
                            with ui.row().classes("items-center gap-2 mb-1"):
                                ui.button(
                                    f"{f['name']} ({_co_nho(f['size'])})", icon="download",
                                    on_click=lambda _e=None, n=f["name"]: _tai_file(n),
                                ).props("outline dense").classes("text-xs")
                        if len(files) > 1:
                            ui.button(
                                "Tải tất cả (ZIP)", icon="folder_zip",
                                on_click=lambda _e=None: _tai_tat_ca(),
                            ).classes("bg-red-800 text-white mt-2")

                        ui.label(
                            "Sheet có trên 15.000 dòng được xuất riêng ra CSV. Mở CSV bằng "
                            "Excel > Data > Từ Văn bản/CSV, đừng double-click — double-click "
                            "sẽ mất số 0 đứng đầu ở cột TRACE, MSGSEQ."
                        ).classes("text-xs text-gray-500 mt-3")

                        ui.button(
                            "Chạy lần mới", icon="refresh",
                            on_click=lambda _e=None: _lam_moi(),
                        ).props("flat").classes("text-xs mt-2")

            def _lam_moi():
                state.update({"token": None, "files": [], "result": None, "n_logs": 0})
                result_area.clear()
                log_view.clear()
                progress_card.set_visibility(False)
                _ve_danh_sach()

            run_btn.on("click", do_run)
            cancel_btn.on("click", do_cancel)
            _ve_danh_sach()

    # Click vào bất kỳ đâu trong vùng upload (trừ nút) đều mở hộp chọn file
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
