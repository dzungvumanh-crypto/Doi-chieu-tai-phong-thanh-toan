"""Trang Đối chiếu điện SWIFT (SAA <-> Màn hình quản lý điện) — Phòng Swift.

Giao diện khớp tính năng với bản web gốc (web_app.py):
  - 4 tab: 1. Điện đến / 2. Điện đi / 3. Kết quả đối chiếu điện đến / 4. Kết quả đối chiếu điện đi
  - Mỗi tab kết quả có 2 bộ lọc độc lập: theo Trạng thái, theo Loại điện (multi-select)
  - Mỗi chiều có 3 nút xuất Excel: Tổng hợp / Chi tiết lệch / Bản ghi đang lọc

Dữ liệu (merged view) được backend trả về nguyên trong response JSON và giữ
trong `state` của phiên làm việc (còn sống khi tab trình duyệt còn mở) — lọc
/hiển thị làm bằng Python thuần ngay tại đây, KHÔNG gọi lại backend mỗi lần
đổi bộ lọc. Chỉ gọi backend khi: đối chiếu, và khi xuất Excel.
"""
import asyncio
from collections import Counter

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _card,
    _require_auth, _handle_api_error,
)

def _filter_options(direction: str):
    """Giống hệt DirectionState.filter_options() bản gốc — tự biết ONLY_A/ONLY_B
    bên nào là SAA/QL theo từng chiều. 'Khớp khoá, chưa ACK' chỉ áp dụng điện đi."""
    if direction == "den":
        return [
            ("Khớp khoá", "MATCHED"),
            ("Chỉ có ở QL (không có ở SAA)", "ONLY_B"),
            ("Chỉ có ở SAA (không có ở QL)", "ONLY_A"),
        ]
    return [
        ("Khớp khoá + đã Ack", "MATCHED"),
        ("Khớp khoá nhưng chưa Ack", "MATCHED_NOT_ACK"),
        ("Chỉ có ở QL (không có ở SAA)", "ONLY_A"),
        ("Chỉ có ở SAA (không có ở QL)", "ONLY_B"),
    ]


def _status_to_label(direction: str) -> dict:
    """status code (MATCHED/ONLY_A/...) -> nhãn tiếng Việt ĐÚNG theo chiều —
    dùng để hiển thị cột 'Trạng thái', khác _filter_options ở chỗ đây là
    ánh xạ ngược (status -> label) thay vì (label -> status)."""
    return {status: label for label, status in _filter_options(direction)}



@ui.page("/swift_recon")
def swift_recon_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.swift_recon"):
        ui.navigate.to("/home")
        return

    # CSS để header cột (Trạng thái, QL__..., SAA__...) LUÔN HIỂN THỊ khi kéo
    # thanh cuộn DỌC xuống (sticky header) — port nguyên từ web_app.py gốc.
    ui.add_head_html("""
    <style>
    .sticky-header-table .q-table__middle { max-height: 65vh; }
    .sticky-header-table thead tr th {
        position: sticky; top: 0; z-index: 2;
        background: #305496 !important; color: white !important;
    }
    .sticky-header-table td, .sticky-header-table th { white-space: nowrap; }
    </style>
    """)

    # State giữ file bytes + kết quả đối chiếu của TỪNG CHIỀU riêng biệt,
    # y hệt 2 DirectionState (DEN, DI) độc lập trong bản gốc.
    state = {
        "den": {"a_bytes": None, "a_name": "", "b_bytes": None, "b_name": "",
                "summary": None, "records": None, "total_matched": 0, "total_diff": 0},
        "di":  {"a_bytes": None, "a_name": "", "b_bytes": None, "b_name": "",
                "summary": None, "records": None, "total_matched": 0, "total_diff": 0},
    }
    renderers = {}  # direction -> hàm render lại tab kết quả
    history_refresh = {"fn": None}  # sẽ được _build_history_panel gán vào — gọi lại mỗi khi đối chiếu xong

    with ui.row().classes("w-full"):
        _sidebar("swift_recon")
        with _content_area():
            _page_header(
                "Đối chiếu điện SWIFT",
                "Đối chiếu điện đến / điện đi giữa hệ thống SAA và Màn hình quản lý điện",
            )
            ui.label(
                "Lịch sử đối chiếu được lưu trong cơ sở dữ liệu chung của hệ thống — xem tab \"Lịch sử\"."
            ).classes("text-gray-500 text-xs -mt-4 mb-3")

            with ui.tabs().classes("w-full") as tabs:
                tab_den_in = ui.tab("1. Điện đến")
                tab_di_in = ui.tab("2. Điện đi")
                tab_den_out = ui.tab("3. Kết quả đối chiếu điện đến")
                tab_di_out = ui.tab("4. Kết quả đối chiếu điện đi")
                tab_hist = ui.tab("Lịch sử")

            with ui.tab_panels(tabs, value=tab_den_in).classes("w-full"):
                _build_input_panel(tab_den_in, "den", "Điện đến",
                                    "File SAA điện đến", "File Quản lý điện đến",
                                    state, tabs, tab_den_out, renderers, history_refresh)
                _build_input_panel(tab_di_in, "di", "Điện đi",
                                    "File Quản lý điện đi", "File SAA điện đi",
                                    state, tabs, tab_di_out, renderers, history_refresh)
                _build_result_panel(tab_den_out, "den", "điện đến", state, renderers)
                _build_result_panel(tab_di_out, "di", "điện đi", state, renderers)
                _build_history_panel(tab_hist, history_refresh)


def _build_input_panel(tab, direction, title, label_a, label_b, state, tabs, result_tab, renderers, history_refresh):
    source_a = "SAA_DEN" if direction == "den" else "QL_DI"
    source_b = "QL_DEN" if direction == "den" else "SAA_DI"

    with ui.tab_panel(tab):
        with _card(f"Tải lên file — {title}"):
            with ui.grid(columns=2).classes("w-full gap-6 p-4"):
                with ui.column().classes("gap-1"):
                    ui.label(label_a).classes("text-sm font-medium")
                    status_a = ui.label("❌ Chưa có file hợp lệ nào được nạp").classes("text-red-600 text-xs")
                    ui.upload(
                        auto_upload=True, max_file_size=20_000_000,
                        on_upload=lambda e: _on_file_upload(e, "a", source_a, status_a),
                    ).props('accept=".xls,.xlsx,.zip" flat dense label="Chọn file"').classes("w-full")
                with ui.column().classes("gap-1"):
                    ui.label(label_b).classes("text-sm font-medium")
                    status_b = ui.label("❌ Chưa có file hợp lệ nào được nạp").classes("text-red-600 text-xs")
                    ui.upload(
                        auto_upload=True, max_file_size=20_000_000,
                        on_upload=lambda e: _on_file_upload(e, "b", source_b, status_b),
                    ).props('accept=".xls,.xlsx,.zip" flat dense label="Chọn file"').classes("w-full")

            ui.label(
                "Nếu file .xls xuất ra bị lỗi 'Không tìm thấy <table>' (file thực chất chỉ là khung dẫn "
                "tới file khác trong thư mục '..._files' đi kèm): nén (zip) CẢ file .xls VÀ thư mục "
                "'..._files' cạnh nó lại rồi tải file .zip lên."
            ).classes("text-gray-500 text-xs px-4 -mt-2")

            async def _on_file_upload(e, which, source, status_label):
                d = state[direction]
                fname = e.name
                raw = e.content.read()
                if which == "a":
                    d["a_bytes"], d["a_name"] = raw, fname
                else:
                    d["b_bytes"], d["b_name"] = raw, fname
                status_label.text = f"⏳ Đang kiểm tra {fname}..."
                status_label.classes(remove="text-red-600 text-green-700", add="text-orange-600")
                try:
                    result = await asyncio.to_thread(
                        api.post_upload, "/api/swift-recon/parse-preview",
                        {"file": (fname, raw, "application/octet-stream")}, {"source": source},
                    )
                    status_label.text = f"✅ Đang dùng để đối chiếu: {fname} ({result['rows']} dòng)"
                    status_label.classes(remove="text-red-600 text-orange-600", add="text-green-700")
                    ui.notify(f"Đã nạp {result['rows']} dòng từ {fname}", type="positive")
                except Exception as ex:
                    if which == "a":
                        d["a_bytes"] = None
                    else:
                        d["b_bytes"] = None
                    status_label.text = f"❌ {fname} — lỗi, KHÔNG được dùng: {ex}"
                    status_label.classes(remove="text-orange-600 text-green-700", add="text-red-600")
                    ui.notify(f"Lỗi đọc file {fname}: {ex}", type="negative", multi_line=True, timeout=0, close_button=True)

            msg_area = ui.column().classes("px-4")
            btn = ui.button(f"Đối chiếu {title.lower()}", icon="compare_arrows").classes("bg-red-800 text-white m-4")

            async def do_reconcile():
                d = state[direction]
                if not d["a_bytes"] or not d["b_bytes"]:
                    ui.notify("Vui lòng nạp đủ 2 file hợp lệ trước khi đối chiếu", type="warning")
                    return
                btn.props("loading")
                msg_area.clear()
                try:
                    endpoint = f"/api/swift-recon/reconcile-{direction}"
                    if direction == "den":
                        files = {
                            "saa_file": (d["a_name"], d["a_bytes"], "application/octet-stream"),
                            "ql_file": (d["b_name"], d["b_bytes"], "application/octet-stream"),
                        }
                    else:
                        files = {
                            "ql_file": (d["a_name"], d["a_bytes"], "application/octet-stream"),
                            "saa_file": (d["b_name"], d["b_bytes"], "application/octet-stream"),
                        }
                    data = await asyncio.to_thread(api.post_upload, endpoint, files)
                    d["summary"] = data["summary"]
                    d["records"] = data["records"]
                    d["total_matched"] = data["total_matched"]
                    d["total_diff"] = data["total_diff"]
                    with msg_area:
                        ui.label("Đối chiếu xong — xem kết quả ở tab tương ứng.").classes("text-green-700")
                    if not data.get("history_saved", True):
                        ui.notify(
                            f"Đối chiếu xong nhưng LƯU LỊCH SỬ bị lỗi: {data.get('history_error')}",
                            type="warning", multi_line=True, timeout=0, close_button=True,
                        )
                    elif history_refresh.get("fn"):
                        await history_refresh["fn"]()  # làm mới tab Lịch sử ngay, không cần load lại trang
                    if direction in renderers:
                        renderers[direction]()
                    tabs.set_value(result_tab)
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    with msg_area:
                        ui.label(f"Lỗi đối chiếu: {e}").classes("text-red-600")
                finally:
                    btn.props(remove="loading")

            btn.on("click", do_reconcile)


def _build_result_panel(tab, direction, chieu_ten, state, renderers):
    with ui.tab_panel(tab):
        note_area = ui.column().classes("w-full")
        filter_row = ui.row().classes("w-full items-center gap-3 flex-wrap")
        table_area = ui.column().classes("w-full")
        export_row = ui.row().classes("gap-3 mt-3")

        current_view = {"records": None, "columns": None}
        selects = {"status": None, "msgtype": None}

        def render():
            d = state[direction]
            note_area.clear()
            filter_row.clear()
            table_area.clear()
            with note_area:
                if d["records"] is None:
                    ui.label(
                        f"Chưa có dữ liệu — vui lòng đối chiếu ở tab '{chieu_ten}' trước."
                    ).classes("text-gray-500")
                    return
                ui.label(f"Đã đối chiếu xong: {len(d['records'])} điện.").classes("text-green-700")
                ui.label(
                    f"Khớp: {d['total_matched']} — Chênh lệch/cần kiểm tra: {d['total_diff']}"
                ).classes("text-gray-700")
                with ui.row().classes("gap-x-4 gap-y-1 flex-wrap mt-1"):
                    status_counts = Counter(r.get("_status") for r in d["records"])
                    for label, status in _filter_options(direction):
                        ui.label(f"• {label}: {status_counts.get(status, 0)}").classes("text-xs text-gray-500")

            if d["records"] is None:
                return

            options = _filter_options(direction)
            status_labels = [lbl for lbl, _ in options]
            label_to_status = dict(options)
            status_to_label = _status_to_label(direction)
            msg_types = sorted({str(r.get("_msg_type") or "").strip() for r in d["records"]} - {""})

            CHECK_PREFIX = "✅ "
            LOADING_PREFIX = "⏳ "

            def _base_label(label: str) -> str:
                for p in (CHECK_PREFIX, LOADING_PREFIX):
                    if label.startswith(p):
                        return label[len(p):]
                return label

            def render_table():
                table_area.clear()
                selected_status = {
                    label_to_status[_base_label(v)] for v in (selects["status"].value or [])
                    if _base_label(v) in label_to_status
                }
                selected_msgtypes = {_base_label(v) for v in (selects["msgtype"].value or [])}
                view = [
                    r for r in d["records"]
                    if r.get("_status") in selected_status
                    and str(r.get("_msg_type") or "").strip() in selected_msgtypes
                ]
                with table_area:
                    ui.label(f"Hiển thị {len(view)}/{len(d['records'])} dòng theo bộ lọc hiện tại.") \
                        .classes("text-gray-500 text-sm mb-1")
                    if not view:
                        current_view["records"], current_view["columns"] = [], []
                        return
                    raw_cols = [k for k in view[0].keys() if not k.startswith("_")]
                    display_cols = ["STT", "Trạng thái"] + raw_cols
                    rows = []
                    for i, r in enumerate(view, start=1):
                        row = {k: r.get(k) for k in raw_cols}
                        row["STT"] = i
                        row["Trạng thái"] = status_to_label.get(r.get("_status"), r.get("_status"))
                        rows.append(row)
                    cols = [{"name": c, "label": c, "field": c, "align": "left", "sortable": True} for c in display_cols]
                    with ui.table(columns=cols, rows=rows, row_key="STT").classes("w-full sticky-header-table"):
                        pass
                    current_view["records"], current_view["columns"] = rows, display_cols

            async def on_filter_change():
                """Giống hệt bản gốc: giá trị đang chọn ở CẢ 2 ô lọc lập tức
                hiện ⏳ (đang tải), giữ 0.3s để người dùng kịp thấy, sau khi
                bảng đã hiển thị đúng kết quả mới đổi thành ✅ (đã tải xong)."""
                sel_status = {_base_label(v) for v in (selects["status"].value or [])}
                sel_msgtypes = {_base_label(v) for v in (selects["msgtype"].value or [])}

                selects["status"].set_options(
                    [f"{LOADING_PREFIX}{l}" if l in sel_status else l for l in status_labels],
                    value=[f"{LOADING_PREFIX}{l}" for l in sel_status],
                )
                selects["msgtype"].set_options(
                    [f"{LOADING_PREFIX}{l}" if l in sel_msgtypes else l for l in msg_types],
                    value=[f"{LOADING_PREFIX}{l}" for l in sel_msgtypes],
                )

                await asyncio.sleep(0.3)
                render_table()

                selects["status"].set_options(
                    [f"{CHECK_PREFIX}{l}" if l in sel_status else l for l in status_labels],
                    value=[f"{CHECK_PREFIX}{l}" for l in sel_status],
                )
                selects["msgtype"].set_options(
                    [f"{CHECK_PREFIX}{l}" if l in sel_msgtypes else l for l in msg_types],
                    value=[f"{CHECK_PREFIX}{l}" for l in sel_msgtypes],
                )

            with filter_row:
                ui.label("Lọc theo trạng thái:").classes("text-sm text-gray-600")
                selects["status"] = ui.select(
                    options=[f"{CHECK_PREFIX}{l}" for l in status_labels],
                    value=[f"{CHECK_PREFIX}{l}" for l in status_labels],
                    multiple=True,
                ).props("use-chips dense").classes("min-w-[320px]")
                selects["status"].on("update:model-value", lambda e: on_filter_change())

                async def status_select_all():
                    selects["status"].set_value([f"{CHECK_PREFIX}{l}" for l in status_labels])
                    await on_filter_change()

                async def status_deselect_all():
                    selects["status"].set_value([])
                    await on_filter_change()

                ui.button(icon="done_all", on_click=status_select_all) \
                    .props("dense flat round").tooltip("Chọn tất cả trạng thái")
                ui.button(icon="remove_done", on_click=status_deselect_all) \
                    .props("dense flat round").tooltip("Bỏ chọn tất cả trạng thái")

                ui.label("Lọc theo loại điện:").classes("text-sm text-gray-600 ml-4")
                selects["msgtype"] = ui.select(
                    options=[f"{CHECK_PREFIX}{l}" for l in msg_types],
                    value=[f"{CHECK_PREFIX}{l}" for l in msg_types],
                    multiple=True,
                ).props("use-chips dense").classes("min-w-[200px]")
                selects["msgtype"].on("update:model-value", lambda e: on_filter_change())

                async def msgtype_select_all():
                    selects["msgtype"].set_value([f"{CHECK_PREFIX}{l}" for l in msg_types])
                    await on_filter_change()

                async def msgtype_deselect_all():
                    selects["msgtype"].set_value([])
                    await on_filter_change()

                ui.button(icon="done_all", on_click=msgtype_select_all) \
                    .props("dense flat round").tooltip("Chọn tất cả loại điện")
                ui.button(icon="remove_done", on_click=msgtype_deselect_all) \
                    .props("dense flat round").tooltip("Bỏ chọn tất cả loại điện")

                async def reset_filter():
                    selects["status"].set_value([f"{CHECK_PREFIX}{l}" for l in status_labels])
                    selects["msgtype"].set_value([f"{CHECK_PREFIX}{l}" for l in msg_types])
                    await on_filter_change()

                ui.button("Bỏ lọc", on_click=reset_filter).props("outline dense")

            render_table()

        async def do_export_summary():
            d = state[direction]
            if d["summary"] is None:
                ui.notify("Vui lòng đối chiếu trước khi xuất file.", type="warning")
                return
            files = _files_for_export(state, direction)
            try:
                content = await asyncio.to_thread(api.post_upload_bytes, "/api/swift-recon/export-summary", files)
                ui.download(content, f"Tong_hop_doi_chieu_Dien{direction.upper()}.xlsx")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi: {e}", type="negative")

        async def do_export_diff():
            d = state[direction]
            if d["records"] is None:
                ui.notify("Vui lòng đối chiếu trước khi xuất file.", type="warning")
                return
            files = _files_for_export(state, direction)
            try:
                content = await asyncio.to_thread(api.post_upload_bytes, "/api/swift-recon/export-diff", files)
                ui.download(content, f"Chi_tiet_lech_doi_chieu_Dien{direction.upper()}.xlsx")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi: {e}", type="negative")

        async def do_export_filtered():
            if not current_view["records"]:
                ui.notify("Không có bản ghi nào đang hiển thị theo bộ lọc hiện tại để xuất.", type="warning")
                return
            try:
                payload = {
                    "columns": current_view["columns"],
                    "records": current_view["records"],
                    "filename": f"Ban_ghi_dang_loc_Dien{direction.upper()}.xlsx",
                }
                content = await asyncio.to_thread(api.post_download, "/api/swift-recon/export-filtered", payload)
                ui.download(content, payload["filename"])
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi: {e}", type="negative")

        with export_row:
            ui.button(f"Xuất Excel Tổng hợp — {chieu_ten}", icon="summarize", on_click=do_export_summary) \
                .classes("bg-red-800 text-white")
            ui.button(f"Xuất Excel Chi tiết lệch — {chieu_ten}", icon="fact_check", on_click=do_export_diff) \
                .classes("bg-red-800 text-white")
            ui.button(f"Xuất Excel bản ghi đang lọc — {chieu_ten}", icon="filter_alt", on_click=do_export_filtered) \
                .props("outline")

        renderers[direction] = render
        render()


def _files_for_export(state: dict, direction: str) -> dict:
    """Chỉ gửi đúng cặp file của CHIỀU đang xuất (không gộp cả 2 chiều)."""
    d = state[direction]
    if not d["a_bytes"] or not d["b_bytes"]:
        return {}
    if direction == "den":
        return {
            "saa_den": (d["a_name"], d["a_bytes"], "application/octet-stream"),
            "ql_den": (d["b_name"], d["b_bytes"], "application/octet-stream"),
        }
    return {
        "ql_di": (d["a_name"], d["a_bytes"], "application/octet-stream"),
        "saa_di": (d["b_name"], d["b_bytes"], "application/octet-stream"),
    }


def _build_history_panel(tab, history_refresh):
    """Tab Lịch sử — HOÀN TOÀN ĐỘC LẬP với 2 tab "Kết quả đối chiếu điện đến/đi"
    (không đọc/ghi chung state, không chuyển tab). Xem chi tiết mở ngay bên
    trong tab này. Tự làm mới ngay khi có 1 lần đối chiếu mới thành công
    (qua history_refresh["fn"]) — không cần load lại trang."""
    with ui.tab_panel(tab):
        hist_area = ui.column().classes("w-full gap-2")

        async def load_history():
            hist_area.clear()
            try:
                rows = await asyncio.to_thread(api.get, "/api/swift-recon/history")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi: {e}", type="negative")
                return
            with hist_area:
                if not rows:
                    ui.label("Chưa có lịch sử đối chiếu nào").classes("text-gray-400 p-4")
                    return

                with ui.row().classes(
                    "w-full items-center gap-3 px-3 py-2 bg-gray-100 rounded text-xs font-semibold text-gray-600"
                ):
                    ui.label("Thời gian").classes("w-36")
                    ui.label("Chiều").classes("w-20")
                    ui.label("Người thực hiện").classes("w-32")
                    ui.label("SL SAA").classes("w-14 text-center")
                    ui.label("SL QL").classes("w-14 text-center")
                    ui.label("Khớp").classes("w-14 text-center")
                    ui.label("Lệch").classes("w-14 text-center")
                    ui.label("Thao tác").classes("flex-1")

                for r in rows:
                    _history_row(r)

        def _history_row(r: dict):
            history_id = r["id"]
            is_den = r["recon_type"] == "den"
            name_a = "SAA" if is_den else "QL"
            name_b = "QL" if is_den else "SAA"
            detail_area = ui.column().classes("w-full")  # khu xem chi tiết CỦA RIÊNG dòng này
            expanded = {"open": False}

            async def xem_chi_tiet():
                """Mở/đóng bảng chi tiết ngay dưới dòng này — dữ liệu riêng,
                không đụng đến state của tab Kết quả đối chiếu."""
                if expanded["open"]:
                    detail_area.clear()
                    expanded["open"] = False
                    return
                try:
                    detail = await asyncio.to_thread(api.get, f"/api/swift-recon/history/{history_id}")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi: {e}", type="negative")
                    return
                expanded["open"] = True
                records = detail["merged_records"]
                status_to_label = _status_to_label(detail["recon_type"])
                with detail_area:
                    if not records:
                        ui.label("Không có bản ghi chi tiết").classes("text-gray-400 text-sm p-2")
                        return
                    raw_cols = [k for k in records[0].keys() if not k.startswith("_")]
                    display_cols = ["STT", "Trạng thái"] + raw_cols
                    rows_disp = []
                    for i, rec in enumerate(records, start=1):
                        row = {k: rec.get(k) for k in raw_cols}
                        row["STT"] = i
                        row["Trạng thái"] = status_to_label.get(rec.get("_status"), rec.get("_status"))
                        rows_disp.append(row)
                    cols = [{"name": c, "label": c, "field": c, "align": "left", "sortable": True} for c in display_cols]
                    with ui.table(columns=cols, rows=rows_disp, row_key="STT").classes("w-full sticky-header-table"):
                        pass

            async def dl_summary():
                try:
                    content = await asyncio.to_thread(
                        api.get_bytes, f"/api/swift-recon/history/{history_id}/export-summary"
                    )
                    ui.download(content, f"Tong_hop_lichsu_{history_id}.xlsx")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi: {e}", type="negative")

            async def dl_diff():
                try:
                    content = await asyncio.to_thread(
                        api.get_bytes, f"/api/swift-recon/history/{history_id}/export-diff"
                    )
                    ui.download(content, f"Chi_tiet_lech_lichsu_{history_id}.xlsx")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi: {e}", type="negative")

            async def dl_raw(side: str, label: str):
                try:
                    content = await asyncio.to_thread(
                        api.get_bytes, f"/api/swift-recon/history/{history_id}/export-raw",
                        {"side": side},
                    )
                    ui.download(content, f"DuLieu_{label}_lichsu_{history_id}.xlsx")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi: {e}", type="negative")

            with ui.column().classes("w-full border-b border-gray-100"):
                with ui.row().classes("w-full items-center gap-3 px-3 py-2 text-sm"):
                    ui.label(str(r["recon_date"])[:16]).classes("w-36")
                    ui.label("Điện đến" if is_den else "Điện đi").classes("w-20")
                    ui.label(r.get("performed_by") or "").classes("w-32")
                    ui.label(str(r["total_saa"])).classes("w-14 text-center")
                    ui.label(str(r["total_ql"])).classes("w-14 text-center")
                    ui.label(str(r["total_matched"])).classes("w-14 text-center text-green-700")
                    ui.label(str(r["total_diff"])).classes("w-14 text-center text-red-600")
                    with ui.row().classes("flex-1 gap-2 flex-wrap"):
                        ui.button("Xem chi tiết", icon="visibility", on_click=xem_chi_tiet) \
                            .props("dense outline size=sm").classes("text-blue-700")
                        ui.button("Excel Tổng hợp", icon="summarize", on_click=dl_summary).props("dense outline size=sm")
                        ui.button("Excel Chi tiết lệch", icon="fact_check", on_click=dl_diff).props("dense outline size=sm")
                        ui.button(f"File {name_a} gốc", icon="description",
                                  on_click=lambda: dl_raw("a", name_a)).props("dense flat size=sm")
                        ui.button(f"File {name_b} gốc", icon="description",
                                  on_click=lambda: dl_raw("b", name_b)).props("dense flat size=sm")

        history_refresh["fn"] = load_history
        ui.timer(0.1, load_history, once=True)
