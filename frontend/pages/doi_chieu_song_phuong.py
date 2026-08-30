"""Trang Đối chiếu Song phương — 3 thẻ: Phân loại dữ liệu | Đối chiếu đến | Đối chiếu đi.

Gộp từ 3 trang riêng (`doi_chieu_song_phuong_kenh.py`, `doi_chieu_song_phuong_core.py` — đã xoá)
thành 1 trang, 1 menu, 1 feature-code `menu.doi_chieu_song_phuong` duy nhất. Quyết định 2026-08-28:
người dùng role `admin_l2` KHÔNG được RBAC bypass như `admin` cấp 1 (`backend/core/deps.py`,
`require_feature()` chỉ bỏ qua check khi `role == StaffRole.ADMIN`) — mỗi trang mới thêm `menu.*`
riêng phải được admin cấp 1 gán thủ công qua `group_features`, dễ bị bỏ sót khiến trang "vô hình"
dù họ đã có quyền `menu.doi_chieu_song_phuong` gốc. Gộp 1 flag để tránh lặp lại vấn đề này.

"Đối chiếu đến" — quyết định 2026-08-28 (đợt 2): KHÔNG phải 2 tính năng độc lập (Kênh↔Hub +
Hub↔Core) xếp cạnh nhau, mà là 1 chu trình khép kín — người dùng đưa 1 thư mục gốc + ngày + ngân
hàng, hệ thống tự chạy Kênh↔Hub rồi Hub↔Core nối tiếp, 1 job/1 kết quả cuối (đúng model ACH:
nhiều pha bên trong, gộp báo cáo). Gọi `/api/doi_chieu_song_phuong_kenh_core/*`
(`doi_chieu_song_phuong_kenh_core_service.py`) — thay hẳn 2 endpoint riêng cũ. "Đối chiếu đi":
backend chưa code (đã hoãn 2 lần) — chỉ có khung thẻ ghi chú "chưa triển khai".

Quyền BẤM CHẠY của "Đối chiếu đến" gộp thành 1 action `doi_chieu_song_phuong_kenh_core.process`
(trước đây 2 action riêng cho kênh/core — không còn ý nghĩa vì không thể bấm chạy riêng từng
chân nữa). Quyền XEM trang vẫn dùng chung `menu.doi_chieu_song_phuong`.
"""

import asyncio

from nicegui import ui
import frontend.api_client as api
import frontend.ui_kit as ui_kit
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)
from frontend.job_runner import build_source_input

_POLL_INTERVAL = 1.5      # giây — dùng chung cho mọi job nền trong trang


# ─── Thẻ 1 — Phân loại dữ liệu (IPCAS/GL02) ────────────────────────────────────
def _tab_phan_loai():
    """2 chế độ nhập liệu (giống module Chấm ACH) — quyết định 2026-08-28 sau phản hồi
    "upload 1 file/lần rất khó dùng" khi cần xử lý nhiều ngày: tải nhiều file ZIP cùng lúc,
    hoặc chỉ 1 thư mục server chứa nhiều ZIP. Cả 2 chạy tuần tự qua job nền
    (`svc.start_batch`/`start_batch_folder`), mỗi ZIP vẫn ra kết quả độc lập (8 file CSV,
    4 NH × 2 chiều) — không đổi business logic `process_zip()`."""
    ui.label(
        "Phân loại lệnh IPCAS theo ngân hàng và chiều giao dịch (ĐẾN / ĐI)"
    ).classes("text-sm text-gray-500 mb-4")

    state = {"files": {}, "mode": "folder", "job_id": None, "log_pos": 0,
              "timer": None, "running": False}

    with ui.card().classes("w-full p-5 mb-4"):
        ui.label("Nguồn dữ liệu").classes("text-base font-semibold text-red-800 mb-3")
        ui.label(
            "File ZIP mã hóa AES-256 — xuất từ IPCAS, mỗi file 1 ngày. Hệ thống định tuyến "
            "4 ngân hàng đối chiếu: Vietinbank (201), BIDV (202), Vietcombank (203), "
            "MBBank (311). Chọn được nhiều ngày cùng lúc — xử lý tuần tự, không giới hạn 1 file."
        ).classes("text-xs text-gray-500 mb-3")

        folder_input = build_source_input(
            state,
            accept=".zip",
            upload_label="Chọn file ZIP (có thể chọn nhiều)...",
            folder_hint=(
                "Thư mục chứa nhiều file ZIP IPCAS (mỗi file 1 ngày) — xử lý tuần tự toàn bộ."
            ),
            folder_placeholder="Ví dụ: D:\\DoiChieuSongPhuong\\IPCAS",
        )

        with ui.row().classes("gap-3 mt-4"):
            btn_run = ui.button("Xử lý", icon="play_arrow",
                                color="red-8").classes("font-semibold")
            if not api.has_feature("doi_chieu_song_phuong.process"):
                btn_run.props("disable")
                btn_run.tooltip("Bạn không có quyền thực hiện thao tác này")
            btn_cancel = ui.button("Dừng", icon="stop_circle",
                                   color="grey-6").classes("font-semibold")
            btn_cancel.set_visibility(False)

    with ui.card().classes("w-full p-0 mb-4"):
        with ui.row().classes("w-full bg-gray-800 px-4 py-2 rounded-t items-center gap-2"):
            ui.icon("terminal").classes("text-green-400 text-sm")
            ui.label("Log xử lý").classes("text-xs font-semibold text-green-300")
            spinner = ui.spinner("dots", size="xs", color="green")
            spinner.set_visibility(False)

        log_area = ui.column().classes(
            "w-full bg-gray-900 font-mono text-xs text-green-200 "
            "p-3 overflow-y-auto max-h-72 min-h-24 gap-0"
        )
        with log_area:
            ui.label('Sẵn sàng. Chọn nguồn dữ liệu và bấm "Xử lý".').classes("text-gray-500")

    result_area = ui.column().classes("w-full")

    def _append_log(msg: str):
        with log_area:
            ui.label(msg).classes("leading-tight")

    def _clear_log():
        log_area.clear()

    async def download_file(token: str, file_key: str, ngay: str):
        try:
            data = await asyncio.to_thread(
                api.get_bytes,
                f"/api/doi_chieu_song_phuong/download/{token}/{file_key}",
            )
            ui.download(data, filename=f"{file_key}_{ngay}.csv")
        except Exception as e:
            if not _handle_api_error(e):
                ui.notify(f"Lỗi tải file: {e}", type="negative")

    def _render_one_result(r: dict):
        """1 kết quả process_zip() (đã kèm 'source_name') — hoặc 1 lỗi ('error')."""
        source_name = r.get("source_name", "?")
        if r.get("error"):
            with ui.card().classes("w-full p-4 mb-2 bg-red-50 border border-red-400"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("error", color="red").classes("text-xl")
                    ui.label(f"{source_name} — LỖI: {r['error']}").classes(
                        "text-sm text-red-800"
                    )
            return

        rows_by_key = {f["file_key"]: f["rows"] for f in r.get("files", [])}
        with ui.expansion(source_name, value=True).classes("w-full border rounded mb-2"):
            ui.label(
                f"Xử lý xong trong {r.get('elapsed_s', '?')}s "
                f"— {r.get('total_rows', 0):,} dòng"
            ).classes("text-sm text-green-700 mb-2")

            columns = [
                {"name": "ma_nh", "label": "Mã NH", "field": "ma_nh", "align": "left"},
                {"name": "ten_nh", "label": "Ngân hàng", "field": "ten_nh", "align": "left"},
                {"name": "den", "label": "Lệnh ĐẾN", "field": "so_lenh_den"},
                {"name": "di", "label": "Lệnh ĐI", "field": "so_lenh_di"},
                {"name": "tong", "label": "Tổng", "field": "tong"},
            ]
            ui.table(columns=columns, rows=r.get("stats", []),
                     row_key="ma_nh").classes("w-full mb-3")

            for s in r.get("stats", []):
                ma = s["ma_nh"]
                with ui.row().classes("w-full items-center gap-3 mb-2"):
                    ui.label(f'{ma} · {s["ten_nh"]}').classes(
                        "text-sm font-medium w-40 shrink-0"
                    )
                    for chieu, tag, cls in (
                        ("DEN", "ĐẾN", "text-blue-700"),
                        ("DI", "ĐI", "text-green-700"),
                    ):
                        key = f"{ma}_{chieu}"
                        rows = rows_by_key.get(key, 0)
                        btn = ui.button(
                            f"{tag} ({rows:,})", icon="download",
                        ).props("outline dense").classes(f"{cls} text-xs")

                        def _make_dl(k=key, tok=r["token"], ngay=r.get("process_date", "")):
                            async def _handler():
                                await download_file(tok, k, ngay)
                            return _handler
                        btn.on("click", _make_dl())

    def _show_results(results: list[dict]):
        result_area.clear()
        with result_area:
            if not results:
                return
            ui.label(f"Kết quả ({len(results)} file)").classes(
                "text-base font-semibold text-red-800 mb-2"
            )
            for r in results:
                _render_one_result(r)

    async def _poll():
        if not state["job_id"]:
            return
        try:
            res = await asyncio.to_thread(
                api.get,
                f"/api/doi_chieu_song_phuong/poll/{state['job_id']}",
                params={"since": state["log_pos"]},
            )
        except Exception as e:
            if _handle_api_error(e):
                return
            return

        new_logs = res.get("logs", [])
        for line in new_logs:
            _append_log(line)
        state["log_pos"] += len(new_logs)

        status = res.get("status", "")
        if status in ("done", "error", "cancelled"):
            spinner.set_visibility(False)
            btn_cancel.set_visibility(False)
            btn_run.set_visibility(True)
            state["running"] = False
            if state["timer"]:
                state["timer"].cancel()
                state["timer"] = None

            if status == "done":
                _show_results(res.get("results", []))
                ui.notify("Hoàn thành! Tải file kết quả bên dưới.", type="positive")
            elif status == "error":
                ui.notify(f"Lỗi: {res.get('error', '')}", type="negative", timeout=0)
            elif status == "cancelled":
                ui.notify("Đã dừng theo yêu cầu.", type="warning")

    async def on_run():
        if state["running"]:
            return
        if state["mode"] == "upload" and not state["files"]:
            ui.notify("Chưa chọn file nào.", type="warning")
            return
        if state["mode"] == "folder" and not (folder_input.value or "").strip():
            ui.notify("Chưa nhập đường dẫn thư mục.", type="warning")
            return

        _clear_log()
        result_area.clear()
        btn_run.set_visibility(False)
        btn_cancel.set_visibility(True)
        spinner.set_visibility(True)
        state["running"] = True
        state["log_pos"] = 0

        try:
            if state["mode"] == "upload":
                _append_log(f"Đang tải {len(state['files'])} file lên...")
                res = await asyncio.to_thread(
                    api.post_multipart,
                    "/api/doi_chieu_song_phuong/start_batch",
                    files=[(name, data) for name, data in state["files"].items()],
                )
            else:
                folder_path = folder_input.value.strip()
                _append_log(f"Thư mục: {folder_path}")
                res = await asyncio.to_thread(
                    api.post,
                    "/api/doi_chieu_song_phuong/start_folder",
                    {"folder_path": folder_path},
                )
        except Exception as e:
            spinner.set_visibility(False)
            btn_cancel.set_visibility(False)
            btn_run.set_visibility(True)
            state["running"] = False
            if not _handle_api_error(e):
                ui.notify(str(e), type="negative")
            return

        state["job_id"] = res.get("job_id")
        _append_log(f"Job ID: {state['job_id']}")
        state["timer"] = ui.timer(_POLL_INTERVAL, _poll)

    async def on_cancel():
        if not state["job_id"]:
            return
        try:
            await asyncio.to_thread(
                api.post, f"/api/doi_chieu_song_phuong/cancel/{state['job_id']}"
            )
            _append_log("[Yêu cầu dừng đã gửi — chờ xử lý xong file hiện tại...]")
        except Exception as e:
            ui.notify(str(e), type="negative")

    btn_run.on("click", on_run)
    btn_cancel.on("click", on_cancel)


# ─── Thẻ 2 — Đối chiếu đến: Kênh↔Hub + Hub↔Core chạy tự động nối tiếp ──────────
def _tab_doi_chieu_den():
    """Chu trình khép kín (quyết định 2026-08-28): người dùng đưa 1 thư mục gốc + ngày +
    ngân hàng, hệ thống tự chạy Kênh↔Hub rồi Hub↔Core, chỉ 1 job/1 kết quả cuối — đúng model
    ACH (nhiều pha bên trong, gộp báo cáo). Kết quả vẫn nhiều file tải về, chỉ gộp chung 1 khu."""
    _STAGE_LABELS = ["Kênh↔Hub", "Hub↔Core", "Hoàn tất"]
    state = {"job_id": None, "log_pos": 0, "timer": None, "running": False,
              "mode": "folder", "files": {}}

    ui.label(
        "Chạy tự động nối tiếp Kênh↔Hub rồi Hub↔Core cho 1 ngân hàng — 1 lần bấm, 1 kết quả "
        "cuối (chỉ làm chiều ĐẾN)."
    ).classes("text-sm text-gray-500 mb-4")

    with ui.card().classes("w-full p-4 mb-4 bg-yellow-50 border border-yellow-400"):
        with ui.row().classes("items-start gap-2"):
            ui.icon("info", color="amber-700").classes("text-xl mt-0.5")
            ui.label(
                "Kênh↔Hub: đối chiếu HUB nội bộ với kênh song phương ngân hàng đối tác — 3 đơn "
                "vị (202,SPRT), (203,SPRT), (202,SPT), NH 203 chưa có SP THƯỜNG. "
                "Hub↔Core: đối chiếu HUB với hạch toán CORE/GL02 (cửa sổ T-3..T+3) — dùng "
                "CSV đã phân loại sẵn (\"{ma_nh}_DEN.csv\") nếu có, không thì tự giải mã GL02. "
                "Mỗi lần chạy chỉ 1 ngân hàng (giới hạn RAM — mỗi NH phải giải mã lại GL02 từ "
                "đầu nếu chưa có CSV) — muốn đủ 4 NH thì bấm chạy 4 lần. Lỗi 1 bước không chặn "
                "bước còn lại."
            ).classes("text-sm text-amber-900")

    with ui.card().classes("w-full p-5 mb-4"):
        ui.label("Nguồn dữ liệu").classes("text-base font-semibold text-red-800 mb-3")

        folder_input = build_source_input(
            state,
            accept=".zip,.xlsx,.csv",
            upload_label="Chọn file (có thể chọn nhiều)...",
            upload_hint=(
                "Chọn cùng lúc: 1-2 file HUB (.zip), 1-3 file kênh (.xlsx), 1 file GL02 (.zip) "
                "hoặc CSV đã phân loại, OSB (.xlsx, nếu có) — giữ nguyên tên file gốc."
            ),
            folder_hint=(
                "Thư mục chứa các thư mục con theo ngày (VD 21.8, 22.8...) — đủ HUB, kênh, "
                "CORE/GL02 (hoặc CSV đã phân loại), OSB (nếu có)."
            ),
            folder_placeholder="Ví dụ: D:\\DoiChieuSongPhuong\\dữ liệu",
        )

        with ui.row().classes("gap-3 mt-3 items-end"):
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
            ma_nh_select = ui.select(
                {"201": "201 — Vietinbank", "202": "202 — BIDV",
                 "203": "203 — Vietcombank", "311": "311 — MBBank"},
                label="Ngân hàng", value="202",
            ).props("outlined dense").classes("w-52")

        with ui.row().classes("gap-3 mt-4"):
            btn_run = ui.button("Chạy đối chiếu", icon="play_arrow",
                                color="red-8").classes("font-semibold")
            if not api.has_feature("doi_chieu_song_phuong_kenh_core.process"):
                btn_run.props("disable")
                btn_run.tooltip("Bạn không có quyền thực hiện thao tác này")
            btn_cancel = ui.button("Dừng", icon="stop_circle",
                                   color="grey-6").classes("font-semibold")
            btn_cancel.set_visibility(False)

        stepper_box = ui.column().classes("w-full mt-4")
        stepper_box.set_visibility(False)
        with stepper_box:
            ui_kit.stepper(_STAGE_LABELS, 0)

    with ui.card().classes("w-full p-0 mb-4"):
        with ui.row().classes("w-full bg-gray-800 px-4 py-2 rounded-t items-center gap-2"):
            ui.icon("terminal").classes("text-green-400 text-sm")
            ui.label("Log xử lý").classes("text-xs font-semibold text-green-300")
            spinner = ui.spinner("dots", size="xs", color="green")
            spinner.set_visibility(False)

        log_area = ui.column().classes(
            "w-full bg-gray-900 font-mono text-xs text-green-200 "
            "p-3 overflow-y-auto max-h-72 min-h-24 gap-0"
        )
        with log_area:
            ui.label('Sẵn sàng. Chọn nguồn dữ liệu + ngày + ngân hàng rồi bấm "Chạy đối chiếu".').classes(
                "text-gray-500"
            )

    result_card = ui.card().classes("w-full p-5")
    result_card.set_visibility(False)

    def _append_log(msg: str):
        with log_area:
            ui.label(msg).classes("leading-tight")

    def _clear_log():
        log_area.clear()

    def _update_stepper(stage: int):
        stepper_box.set_visibility(True)
        stepper_box.clear()
        with stepper_box:
            ui_kit.stepper(_STAGE_LABELS, stage)

    def _render_kenh_hub(kq: dict | None):
        with ui.expansion("Kênh ↔ Hub", value=True).classes("w-full border rounded mb-2"):
            if kq is None:
                ui.label("Không có kết quả — xem log (thiếu file, hoặc lỗi riêng bước này).").classes(
                    "text-sm text-orange-700"
                )
                return
            chenh_lech = kq.get("chenh_lech", {})
            if chenh_lech:
                columns = [
                    {"name": "dv", "label": "Đơn vị", "field": "dv", "align": "left"},
                    {"name": "trang_thai", "label": "Trạng thái", "field": "trang_thai"},
                    {"name": "chenh_mon", "label": "Chênh số món", "field": "chenh_mon"},
                    {"name": "chenh_tien", "label": "Chênh số tiền (đồng)", "field": "chenh_tien"},
                ]
                rows = []
                for k, v in chenh_lech.items():
                    cm, ct = v["chenh_so_mon"], v["chenh_so_tien"]
                    rows.append({
                        "dv": k,
                        "trang_thai": "Đã cân khớp" if cm == 0 and ct == 0 else "Chưa cân khớp",
                        "chenh_mon": f"{cm:+,}",
                        "chenh_tien": f"{ct:+,}",
                    })
                ui.table(columns=columns, rows=rows, row_key="dv").classes("w-full mb-2")
            canh_bao = kq.get("canh_bao", [])
            if canh_bao:
                with ui.card().classes("w-full p-3 bg-red-50 border border-red-400"):
                    ui.label("⚠ Cảnh báo trạng thái chỉ-hub ngoài dự kiến:").classes(
                        "text-sm font-semibold text-red-800"
                    )
                    for cb in canh_bao:
                        ui.label(f"{cb['don_vi']}: {cb['trang_thai']}").classes(
                            "text-xs text-red-700"
                        )

    def _render_hub_core(kq: dict | None):
        with ui.expansion("Hub ↔ Core", value=True).classes("w-full border rounded mb-2"):
            if kq is None:
                ui.label("Không có kết quả — xem log (thiếu file, hoặc lỗi riêng bước này).").classes(
                    "text-sm text-orange-700"
                )
                return
            ui.label(
                f"CORE: {kq.get('so_dong_core', 0):,} dòng — HUB: {kq.get('so_dong_hub', 0):,} dòng"
            ).classes("text-sm mb-2")
            columns = [
                {"name": "nhan", "label": "Nhãn KETQUADOICHIEU", "field": "nhan", "align": "left"},
                {"name": "core", "label": "Số dòng CORE", "field": "core"},
                {"name": "hub", "label": "Số dòng HUB", "field": "hub"},
            ]
            phan_bo_core = kq.get("phan_bo_core", {})
            phan_bo_hub = kq.get("phan_bo_hub", {})
            nhan_set = sorted(set(phan_bo_core) | set(phan_bo_hub))
            rows = [
                {"nhan": n, "core": phan_bo_core.get(n, 0), "hub": phan_bo_hub.get(n, 0)}
                for n in nhan_set
            ]
            ui.table(columns=columns, rows=rows, row_key="nhan").classes("w-full")

    def _show_results(res: dict):
        result_card.set_visibility(True)
        result_card.clear()
        with result_card:
            ui.label("Kết quả").classes("text-base font-semibold text-red-800 mb-3")
            with ui.row().classes("items-center gap-2 mb-3"):
                ui.icon("check_circle", color="green").classes("text-xl")
                ui.label(
                    f"Ngày đối chiếu: {res.get('ngay', '?')} — Ngân hàng: {res.get('ma_nh', '?')}"
                ).classes("font-semibold text-green-700")

            ket_qua = res.get("ket_qua", {})
            _render_kenh_hub(ket_qua.get("kenh_hub"))
            _render_hub_core(ket_qua.get("hub_core"))

            ui.label("Tải file kết quả").classes("font-semibold text-red-800 mb-2 mt-2")
            with ui.row().classes("flex-wrap gap-3"):
                for fname in res.get("files", []):
                    url = f"/api/doi_chieu_song_phuong_kenh_core/download/{state['job_id']}/{fname}"

                    async def _tai_ket_qua(u=url, name=fname):
                        try:
                            content = await asyncio.to_thread(api.download, u)
                        except Exception as e:
                            if not _handle_api_error(e):
                                ui.notify(str(e), type="negative")
                            return
                        ui.download(content, name)

                    ui.button(fname, icon="table_chart", color="green-7").on(
                        "click", _tai_ket_qua
                    ).classes("text-xs")

    async def _poll():
        if not state["job_id"]:
            return
        try:
            res = await asyncio.to_thread(
                api.get,
                f"/api/doi_chieu_song_phuong_kenh_core/poll/{state['job_id']}",
                params={"since": state["log_pos"]},
            )
        except Exception as e:
            if _handle_api_error(e):
                return
            return

        new_logs = res.get("logs", [])
        for line in new_logs:
            _append_log(line)
        state["log_pos"] += len(new_logs)
        _update_stepper(res.get("stage", 0))

        status = res.get("status", "")
        if status in ("done", "error", "cancelled"):
            spinner.set_visibility(False)
            btn_cancel.set_visibility(False)
            btn_run.set_visibility(True)
            state["running"] = False
            if state["timer"]:
                state["timer"].cancel()
                state["timer"] = None

            if status == "done":
                _show_results(res)
                ui.notify("Hoàn thành! Tải file kết quả bên dưới.", type="positive")
            elif status == "error":
                ui.notify(f"Lỗi: {res.get('error', '')}", type="negative", timeout=0)
            elif status == "cancelled":
                ui.notify("Đã dừng theo yêu cầu.", type="warning")

    def _yyyymmdd_tu_dmy(s: str) -> str | None:
        parts = s.strip().split("/")
        if len(parts) != 3:
            return None
        d, m, y = parts
        if not (d.isdigit() and m.isdigit() and y.isdigit()):
            return None
        return f"{y}{m.zfill(2)}{d.zfill(2)}"

    async def on_run():
        if state["running"]:
            return
        ngay = _yyyymmdd_tu_dmy(ngay_input.value or "")
        ma_nh = ma_nh_select.value
        if not ngay:
            ui.notify("Ngày đối chiếu chưa hợp lệ — bấm icon lịch để chọn.", type="warning")
            return
        if not ma_nh:
            ui.notify("Chưa chọn ngân hàng.", type="warning")
            return
        if state["mode"] == "upload" and not state["files"]:
            ui.notify("Chưa chọn file nào.", type="warning")
            return
        if state["mode"] == "folder" and not (folder_input.value or "").strip():
            ui.notify("Chưa nhập đường dẫn thư mục.", type="warning")
            return

        _clear_log()
        result_card.set_visibility(False)
        btn_run.set_visibility(False)
        btn_cancel.set_visibility(True)
        spinner.set_visibility(True)
        state["running"] = True
        state["log_pos"] = 0
        _update_stepper(0)

        try:
            if state["mode"] == "upload":
                _append_log(f"Đang tải {len(state['files'])} file lên — Ngày: {ngay} — NH: {ma_nh}")
                res = await asyncio.to_thread(
                    api.post_multipart,
                    "/api/doi_chieu_song_phuong_kenh_core/start_upload",
                    files=[(name, data) for name, data in state["files"].items()],
                    data={"ngay": ngay, "ma_nh": ma_nh},
                )
            else:
                folder_path = folder_input.value.strip()
                _append_log(f"Thư mục: {folder_path} — Ngày: {ngay} — NH: {ma_nh}")
                res = await asyncio.to_thread(
                    api.post,
                    "/api/doi_chieu_song_phuong_kenh_core/start_folder",
                    {"folder_path": folder_path, "ngay": ngay, "ma_nh": ma_nh},
                )
        except Exception as e:
            spinner.set_visibility(False)
            btn_cancel.set_visibility(False)
            btn_run.set_visibility(True)
            state["running"] = False
            if not _handle_api_error(e):
                ui.notify(str(e), type="negative")
            return

        state["job_id"] = res.get("job_id")
        _append_log(f"Job ID: {state['job_id']}")
        state["timer"] = ui.timer(_POLL_INTERVAL, _poll)

    async def on_cancel():
        if not state["job_id"]:
            return
        try:
            await asyncio.to_thread(
                api.post, f"/api/doi_chieu_song_phuong_kenh_core/cancel/{state['job_id']}"
            )
            _append_log("[Yêu cầu dừng đã gửi — chờ xử lý xong bước hiện tại...]")
        except Exception as e:
            ui.notify(str(e), type="negative")

    btn_run.on("click", on_run)
    btn_cancel.on("click", on_cancel)


# ─── Thẻ 3 — Đối chiếu đi (chưa triển khai) ─────────────────────────────────────
def _tab_doi_chieu_di():
    with ui.card().classes("w-full p-6 bg-gray-50 border border-gray-300"):
        with ui.row().classes("items-start gap-3"):
            ui.icon("construction", color="grey-6").classes("text-2xl mt-0.5")
            with ui.column().classes("gap-1"):
                ui.label("Đối chiếu chiều ĐI — chưa triển khai").classes(
                    "text-base font-semibold text-gray-700"
                )
                ui.label(
                    "Kênh↔Hub và Hub↔Core chiều đi đã có đặc tả nghiệp vụ nhưng chưa code "
                    "backend — dự kiến làm ở đợt tiếp theo."
                ).classes("text-sm text-gray-500")


# ─── Trang chính — page shell 3 thẻ ─────────────────────────────────────────────
@ui.page("/doi_chieu_song_phuong")
async def doi_chieu_song_phuong_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.doi_chieu_song_phuong"):
        ui.navigate.to("/home")
        return

    with ui.row().classes("w-full"):
        _sidebar("doi_chieu_song_phuong")
        with _content_area():
            _page_header(
                "Đối chiếu Song phương",
                "Phân loại IPCAS · Đối chiếu Kênh-Hub-Core chiều đến/đi",
            )

            with ui.tabs().props(
                "active-color=indigo-600 indicator-color=indigo-600 align=left"
            ).classes("w-full border-b border-gray-200 mb-4") as tabs:
                tab_phan_loai = ui.tab("Phân loại dữ liệu")
                tab_den = ui.tab("Đối chiếu đến")
                tab_di = ui.tab("Đối chiếu đi")

            with ui.tab_panels(tabs, value=tab_phan_loai).classes("w-full"):
                with ui.tab_panel(tab_phan_loai):
                    _tab_phan_loai()
                with ui.tab_panel(tab_den):
                    _tab_doi_chieu_den()
                with ui.tab_panel(tab_di):
                    _tab_doi_chieu_di()
