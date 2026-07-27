"""Trang Đối soát lệnh CITAD (NHNN) ↔ IPCAS (Agribank) — Phòng Thanh toán.

Port từ `citad-fixed/DoiSoatCITAD.py` (tkinter, 1 màn hình không tab).
Bám sát pattern `frontend/pages/swift_recon.py`: upload nhiều file (CITAD,
IPCAS, Hub ngoại tệ) → gọi backend đối soát trong RAM → giữ kết quả trong
`state` của phiên làm việc → lọc/hiển thị bằng Python thuần, KHÔNG gọi lại
backend mỗi lần đổi bộ lọc — chỉ gọi backend khi: đối soát, và khi xuất Excel.

4 nhóm lọc (map từ radio button gốc `all/only_citad/only_ipcas/lech_trang_thai`)
+ ô tìm kiếm tự do trên mọi cột (giống thanh search gốc).
"""
import asyncio
import datetime

from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _card, _require_auth, _handle_api_error


def _date_picker_input(label: str, initial: str = None):
    """Ô nhập ngày dd/mm/yyyy kèm icon mở lịch chọn — QDate tự khoanh viền
    ngày hôm nay, không cần cấu hình thêm."""
    initial = initial or datetime.date.today().strftime('%d/%m/%Y')
    with ui.input(label, value=initial).props('dense outlined').classes('w-44') as date_input:
        with date_input.add_slot('append'):
            ui.icon('edit_calendar').on('click', lambda: menu.open()).classes('cursor-pointer')
    with ui.menu() as menu:
        ui.date(value=initial, mask='DD/MM/YYYY').bind_value(date_input)
    return date_input

STATUS_LBL = {
    "only_citad": "Chỉ CITAD", "only_ipcas": "Chỉ IPCAS",
    "only_hub": "Chỉ Hub", "lech_trang_thai": "Lệch TT", "both": "Khớp",
}
STATUS_COLOR = {
    "only_citad": "text-red-600", "only_ipcas": "text-blue-600",
    "only_hub": "text-blue-600", "lech_trang_thai": "text-orange-600", "both": "text-green-700",
}

FILTERS = [
    ("Tất cả", None),
    ("Chỉ CITAD", ("only_citad",)),
    ("Chỉ Agribank (IPCAS/Hub)", ("only_ipcas", "only_hub")),
    ("Lệch trạng thái", ("lech_trang_thai",)),
]

DISPLAY_COLS = [
    ("stt", "STT"), ("status_lbl", "Kết quả"), ("loai", "Loại GD"), ("chieu_lbl", "Chiều"),
    ("so_gd", "Số GD (CITAD)"), ("key_agri", "Key Agribank"), ("dich_vu", "Dịch vụ"),
    ("so_tien", "Số tiền"), ("loai_tien", "Loại tiền"), ("ngay", "Ngày GD"),
    ("nh_nhan", "Ngân hàng"), ("trang_thai", "Trạng thái"),
]


@ui.page("/doi_soat_citad")
def doi_soat_citad_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.doi_soat_citad"):
        ui.navigate.to("/home")
        return

    state = {
        "citad_files": [],   # list[(filename, bytes)]
        "ipcas_files": [],
        "hub_files": [],
        "lech": None,        # list[dict] sau khi đối soát
        "n_khop": 0,
        "ngay_cham": "",
    }
    history_refresh = {"fn": None}

    with ui.row().classes("w-full"):
        _sidebar("doi_soat_citad")
        with _content_area():
            _page_header(
                "Đối soát CITAD ↔ IPCAS",
                "Đối soát lệnh chuyển tiền giữa CITAD (NHNN) và IPCAS (Agribank) theo ngày chấm",
            )

            with ui.tabs().classes("w-full") as tabs:
                tab_input = ui.tab("1. Tải file & Đối soát")
                tab_result = ui.tab("2. Kết quả")
                tab_hist = ui.tab("Lịch sử")

            with ui.tab_panels(tabs, value=tab_input).classes("w-full"):
                _build_input_panel(tab_input, state, tabs, tab_result, history_refresh)
                _build_result_panel(tab_result, state)
                _build_history_panel(tab_hist, history_refresh)


def _build_input_panel(tab, state, tabs, result_tab, history_refresh):
    with ui.tab_panel(tab):
        with _card("Ngày chấm"):
            with ui.row().classes("m-4"):
                ngay_input = _date_picker_input("Ngày chấm")

        with _card("Tải lên file"):
            with ui.grid(columns=3).classes("w-full gap-6 p-4"):
                _upload_column("File CITAD (.xls/.xlsx/.zip)", ".xls,.xlsx,.zip", state, "citad_files")
                _upload_column("File IPCAS (.csv/.txt/.zip)", ".csv,.txt,.zip", state, "ipcas_files")
                _upload_column("File Hub ngoại tệ (.xls/.xlsx, tuỳ chọn)", ".xls,.xlsx", state, "hub_files")

        msg_area = ui.column().classes("px-4")
        btn = ui.button("Bắt đầu đối soát", icon="compare_arrows").classes("bg-red-800 text-white m-4")

        async def do_reconcile():
            if not state["citad_files"] or not state["ipcas_files"]:
                ui.notify("Cần ít nhất 1 file CITAD và 1 file IPCAS", type="warning")
                return
            if not ngay_input.value:
                ui.notify("Vui lòng nhập ngày chấm", type="warning")
                return
            btn.props("loading")
            msg_area.clear()
            try:
                files = []
                for fname, raw in state["citad_files"]:
                    files.append(("citad_files", (fname, raw, "application/octet-stream")))
                for fname, raw in state["ipcas_files"]:
                    files.append(("ipcas_files", (fname, raw, "application/octet-stream")))
                for fname, raw in state["hub_files"]:
                    files.append(("hub_files", (fname, raw, "application/octet-stream")))
                data = await asyncio.to_thread(
                    api.post_upload, "/api/doi-soat-citad/reconcile", files, {"ngay_cham": ngay_input.value}
                )
                state["lech"] = data["lech"]
                state["n_khop"] = data["n_khop"]
                state["ngay_cham"] = ngay_input.value
                with msg_area:
                    ui.label("Đối soát xong — xem kết quả ở tab tương ứng.").classes("text-green-700")
                if not data.get("history_saved", True):
                    ui.notify(
                        f"Đối soát xong nhưng LƯU LỊCH SỬ bị lỗi: {data.get('history_error')}",
                        type="warning", multi_line=True, timeout=0, close_button=True,
                    )
                elif history_refresh.get("fn"):
                    await history_refresh["fn"]()
                if "render" in state:
                    state["render"]()
                tabs.set_value(result_tab)
            except Exception as e:
                if _handle_api_error(e):
                    return
                with msg_area:
                    ui.label(f"Lỗi đối soát: {e}").classes("text-red-600")
            finally:
                btn.props(remove="loading")

        btn.on("click", do_reconcile)


def _upload_column(label, accept, state, key):
    with ui.column().classes("gap-1"):
        ui.label(label).classes("text-sm font-medium")
        status = ui.label("Chưa chọn file nào").classes("text-gray-500 text-xs")

        def on_upload(e):
            state[key].append((e.name, e.content.read()))
            status.text = f"Đã chọn {len(state[key])} file: " + ", ".join(n for n, _ in state[key])
            status.classes(remove="text-gray-500", add="text-green-700")

        ui.upload(multiple=True, auto_upload=True, on_upload=on_upload).props(
            f'accept="{accept}" flat dense label="Chọn file"'
        ).classes("w-full")

        def clear():
            state[key] = []
            status.text = "Chưa chọn file nào"
            status.classes(remove="text-green-700", add="text-gray-500")

        ui.button("Xoá file đã chọn", on_click=clear).props("dense outline size=sm")


def _build_result_panel(tab, state):
    with ui.tab_panel(tab):
        stats_area = ui.row().classes("w-full gap-3 flex-wrap mb-3")
        filter_row = ui.row().classes("w-full items-center gap-3 flex-wrap")
        table_area = ui.column().classes("w-full")
        export_row = ui.row().classes("gap-3 mt-3")

        current_view = {"rows": None}
        search_input = {"widget": None}
        active_filter = {"idx": 0}

        def render():
            stats_area.clear()
            filter_row.clear()
            table_area.clear()
            export_row.clear()

            lech = state["lech"]
            with stats_area:
                if lech is None:
                    ui.label("Chưa có dữ liệu — vui lòng đối soát ở tab '1. Tải file & Đối soát' trước.").classes(
                        "text-gray-500"
                    )
                    return
                n_khop = state["n_khop"]
                n_only_citad = sum(1 for r in lech if r.get("status") == "only_citad")
                n_only_agri = sum(1 for r in lech if r.get("status") in ("only_ipcas", "only_hub"))
                n_lech_tt = sum(1 for r in lech if r.get("status") == "lech_trang_thai")
                n_total = n_khop + len(lech)
                for lbl, val, color in [
                    ("TỔNG LỆNH", n_total, "text-gray-800"),
                    ("KHỚP", n_khop, "text-green-700"),
                    ("CHỈ CITAD", n_only_citad, "text-red-600"),
                    ("CHỈ AGRIBANK", n_only_agri, "text-blue-600"),
                    ("LỆCH TRẠNG THÁI", n_lech_tt, "text-orange-600"),
                ]:
                    with ui.card().classes("px-4 py-2"):
                        ui.label(lbl).classes("text-xs text-gray-500")
                        ui.label(f"{val:,}").classes(f"text-xl font-bold {color}")

            if lech is None:
                return

            with filter_row:
                for i, (lbl, _statuses) in enumerate(FILTERS):
                    def _select(i=i):
                        active_filter["idx"] = i
                        render_table()
                    ui.button(lbl, on_click=_select).props(
                        f"{'unelevated' if active_filter['idx'] == i else 'outline'} dense"
                    )
                search_input["widget"] = ui.input("Tìm kiếm...").props("dense outlined clearable").classes("w-64")
                search_input["widget"].on("update:model-value", lambda e: render_table())

            def render_table():
                table_area.clear()
                _, statuses = FILTERS[active_filter["idx"]]
                view = lech if statuses is None else [r for r in lech if r.get("status") in statuses]
                q = (search_input["widget"].value or "").strip().lower() if search_input["widget"] else ""
                rows = []
                for i, r in enumerate(view, start=1):
                    row = {
                        "stt": i,
                        "status_lbl": STATUS_LBL.get(r.get("status"), r.get("status")),
                        "loai": (r.get("loai") or "").upper(),
                        "chieu_lbl": "Đi" if r.get("chieu") == "di" else "Đến",
                        "so_gd": r.get("so_gd") or "",
                        "key_agri": r.get("key_agri") or "",
                        "dich_vu": r.get("dich_vu") or "",
                        "so_tien": r.get("so_tien") or 0,
                        "loai_tien": r.get("loai_tien") or "VNĐ",
                        "ngay": r.get("ngay") or "",
                        "nh_nhan": r.get("nh_nhan") or "",
                        "trang_thai": r.get("trang_thai") or "",
                    }
                    if q and q not in " ".join(str(v).lower() for v in row.values()):
                        continue
                    rows.append(row)
                with table_area:
                    ui.label(f"Hiển thị {len(rows)}/{len(view)} dòng theo bộ lọc hiện tại.").classes(
                        "text-gray-500 text-sm mb-1"
                    )
                    cols = [
                        {"name": k, "label": lbl, "field": k, "align": "right" if k == "so_tien" else "left", "sortable": True}
                        for k, lbl in DISPLAY_COLS
                    ]
                    with ui.table(columns=cols, rows=rows, row_key="stt").classes("w-full"):
                        pass
                    current_view["rows"] = rows

            render_table()

            async def do_export():
                try:
                    payload = {"ngay_cham": state["ngay_cham"], "n_khop": state["n_khop"], "lech": state["lech"]}
                    content = await asyncio.to_thread(api.post_download, "/api/doi-soat-citad/export", payload)
                    ui.download(content, f"DoiSoat_CITAD_IPCAS_{state['ngay_cham'].replace('/', '-')}.xlsx")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi: {e}", type="negative")

            with export_row:
                ui.button("Xuất Excel", icon="grid_on", on_click=do_export).classes("bg-red-800 text-white")

        state["render"] = render
        render()


def _build_history_panel(tab, history_refresh):
    with ui.tab_panel(tab):
        hist_area = ui.column().classes("w-full gap-2")

        async def load_history():
            hist_area.clear()
            try:
                rows = await asyncio.to_thread(api.get, "/api/doi-soat-citad/history")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi: {e}", type="negative")
                return
            with hist_area:
                if not rows:
                    ui.label("Chưa có lịch sử đối soát nào").classes("text-gray-400 p-4")
                    return
                with ui.row().classes(
                    "w-full items-center gap-3 px-3 py-2 bg-gray-100 rounded text-xs font-semibold text-gray-600"
                ):
                    ui.label("Thời gian").classes("w-36")
                    ui.label("Ngày chấm").classes("w-24")
                    ui.label("Người thực hiện").classes("w-32")
                    ui.label("Khớp").classes("w-16 text-center")
                    ui.label("Lệch").classes("w-16 text-center")
                    ui.label("Thao tác").classes("flex-1")
                for r in rows:
                    _history_row(r)

        def _history_row(r: dict):
            history_id = r["id"]
            detail_area = ui.column().classes("w-full")
            expanded = {"open": False}

            async def xem_chi_tiet():
                if expanded["open"]:
                    detail_area.clear()
                    expanded["open"] = False
                    return
                try:
                    detail = await asyncio.to_thread(api.get, f"/api/doi-soat-citad/history/{history_id}")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi: {e}", type="negative")
                    return
                expanded["open"] = True
                records = detail["lech_records"]
                with detail_area:
                    if not records:
                        ui.label("Không có lệnh lệch nào (khớp 100%)").classes("text-gray-400 text-sm p-2")
                        return
                    cols = [
                        {"name": k, "label": lbl, "field": k, "align": "left", "sortable": True}
                        for k, lbl in [("status", "Trạng thái"), ("so_gd", "Số GD"), ("key_agri", "Key Agribank"),
                                       ("so_tien", "Số tiền"), ("ngay", "Ngày"), ("nh_nhan", "Ngân hàng")]
                    ]
                    rows = [
                        {
                            "status": STATUS_LBL.get(rec.get("status"), rec.get("status")),
                            "so_gd": rec.get("so_gd"), "key_agri": rec.get("key_agri"),
                            "so_tien": rec.get("so_tien"), "ngay": rec.get("ngay"), "nh_nhan": rec.get("nh_nhan"),
                        }
                        for rec in records
                    ]
                    with ui.table(columns=cols, rows=rows, row_key="so_gd").classes("w-full"):
                        pass

            async def dl_excel():
                try:
                    content = await asyncio.to_thread(api.get_bytes, f"/api/doi-soat-citad/history/{history_id}/export")
                    ui.download(content, f"DoiSoat_CITAD_IPCAS_lichsu_{history_id}.xlsx")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi: {e}", type="negative")

            with ui.column().classes("w-full border-b border-gray-100"):
                with ui.row().classes("w-full items-center gap-3 px-3 py-2 text-sm"):
                    ui.label(str(r["recon_date"])[:16]).classes("w-36")
                    ui.label(r["ngay_cham"]).classes("w-24")
                    ui.label(r.get("performed_by") or "").classes("w-32")
                    ui.label(str(r["n_khop"])).classes("w-16 text-center text-green-700")
                    ui.label(str(r["n_lech"])).classes("w-16 text-center text-red-600")
                    with ui.row().classes("flex-1 gap-2 flex-wrap"):
                        ui.button("Xem chi tiết", icon="visibility", on_click=xem_chi_tiet).props(
                            "dense outline size=sm"
                        ).classes("text-blue-700")
                        ui.button("Tải Excel", icon="grid_on", on_click=dl_excel).props("dense outline size=sm")

        history_refresh["fn"] = load_history
        ui.timer(0.1, load_history, once=True)
