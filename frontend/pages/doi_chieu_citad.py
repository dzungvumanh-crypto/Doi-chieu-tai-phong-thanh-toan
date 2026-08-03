"""Trang Đối chiếu CITAD (NHNN) ↔ PaymentHub (Agribank) — Phòng Thanh toán.

Port từ `citad-fixed/DoiChieuCITAD.py` (tkinter). Giữ nguyên mô hình dữ liệu
và công thức tính chênh lệch gốc:
  - gD[cong][cur][fk]  — 5 cổng CITAD × 3 loại tiền × 8 trường
  - phD[cur][fk]       — PaymentHub × 3 loại tiền × 8 trường
  - napas[fk] / ebank[fk] — bổ sung Napas/Ebanking
  - Tổng CITAD = tổng 5 cổng + Napas IH Đến (den_ih_m, den_ih_t)
  - Tổng PaymentHub = tổng 3 loại tiền của PaymentHub
  - Chênh lệch = Tổng CITAD − Tổng PaymentHub  (đúng theo `_calc()` gốc)

Nút "Nạp CITAD"/"Nạp PaymentHub" đọc buffer do Extension Chrome gửi lên
(xem `extension_citad/`) — thay vì poll timer như bản tkinter, người dùng
bấm nút để nạp giống hệt hành vi gốc. Buffer được tách theo `owner`
(username TTTT cấu hình trong Extension) nên nhiều người dùng chung backend
không ghi đè/xoá dữ liệu của nhau (khác bản gốc — bản gốc chạy 1 server
cục bộ/máy nên vốn chỉ có 1 người dùng).

Napas/Ebanking chỉ có 2 field "IH Đến — Món/Tiền" thực sự được dùng trong
`_calc()`/session/export ở bản gốc (đã kiểm tra `_calc()`, `_get_session_data`,
`_export_excel` trong `citad-fixed/DoiChieuCITAD.py` gốc) — UI chỉ hiện đúng
2 ô này, không vẽ 8 field × 2 dòng như bản gốc (grid gốc có 12/16 ô không hề
được đọc ở đâu, chỉ gây hiểu nhầm).
"""
import asyncio
import datetime
import json
from urllib.parse import quote

from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _require_auth, _handle_api_error

# Card kiểu "modern SaaS" RIÊNG cho trang này (icon trong khung màu + tiêu đề,
# không dùng banner phủ màu như `_card()` dùng chung ở frontend/shared.py —
# đó là component DÙNG CHUNG CHO CẢ APP, không đổi ở đây để tránh ảnh hưởng
# các trang khác; trang này tự định nghĩa card riêng thay vì import `_card`).
# Mỗi tuple: (nền icon, màu chữ/icon, viền dòng tiêu đề, nền mờ phủ CẢ card —
# đủ 8 màu để mỗi bảng nhỏ (PaymentHub + 5 Cổng CITAD) có 1 màu riêng, dễ
# phân biệt khi cuộn qua nhiều bảng liên tiếp giống hệt nhau về cấu trúc).
_ACCENT = {
    "blue": ("bg-blue-50", "text-blue-600", "border-blue-100", "bg-blue-50/40"),
    "indigo": ("bg-indigo-50", "text-indigo-600", "border-indigo-100", "bg-indigo-50/40"),
    "emerald": ("bg-emerald-50", "text-emerald-600", "border-emerald-100", "bg-emerald-50/40"),
    "amber": ("bg-amber-50", "text-amber-600", "border-amber-100", "bg-amber-50/40"),
    "rose": ("bg-rose-50", "text-rose-600", "border-rose-100", "bg-rose-50/40"),
    "cyan": ("bg-cyan-50", "text-cyan-600", "border-cyan-100", "bg-cyan-50/40"),
    "purple": ("bg-purple-50", "text-purple-600", "border-purple-100", "bg-purple-50/40"),
    "teal": ("bg-teal-50", "text-teal-600", "border-teal-100", "bg-teal-50/40"),
}


def _navy_header(title: str, subtitle: str = ""):
    """Thanh tiêu đề nền xanh navy đậm, chữ trắng — theo mẫu banner người
    dùng gửi (ảnh Kanban Board), thay cho `_page_header()` dùng chung ở
    frontend/shared.py (chỉ đổi RIÊNG ở trang này, không đụng shared.py)."""
    with ui.column().classes(
        "w-full bg-blue-950 rounded-2xl px-6 py-4 mb-4 gap-0.5"
    ):
        ui.label(title).classes("text-xl font-bold text-white tracking-wide")
        if subtitle:
            ui.label(subtitle).classes("text-blue-200 text-sm")


def _section_card(title: str, icon: str = "table_chart", accent: str = "blue"):
    bg, text, border, wash = _ACCENT.get(accent, _ACCENT["blue"])
    card = ui.card().classes(
        "w-full rounded-2xl border border-gray-200 shadow-sm hover:shadow-md "
        f"transition-shadow duration-200 {wash} p-0 overflow-hidden"
    )
    with card:
        with ui.row().classes(f"w-full items-center gap-3 px-5 py-4 border-b {border} bg-gray-50/60"):
            with ui.row().classes(f"items-center justify-center w-9 h-9 rounded-xl {bg} shrink-0"):
                ui.icon(icon).classes(f"{text} text-lg")
            ui.label(title).classes("font-semibold text-gray-800 text-[15px]")
    return card

# ID cố định của extension_citad — suy ra tất định từ khoá "key" gắn cứng
# trong extension_citad/manifest.json (không phụ thuộc máy/thư mục cài đặt
# lúc "Load unpacked"). Dùng để gọi chrome.runtime.sendMessage từ trang này
# sang extension qua "externally_connectable" (xem extension_citad/background.js).
# Nếu thay khoá "key" trong manifest.json thì PHẢI cập nhật lại hằng số này.
_EXTENSION_ID = "dhollmjgbbjdcedijlmklmknndcachjh"


def _date_picker_input(label: str, initial: str = None):
    """Ô nhập ngày dd/mm/yyyy kèm icon mở lịch chọn — QDate tự khoanh viền
    ngày hôm nay, không cần cấu hình thêm."""
    initial = initial or datetime.date.today().strftime('%d/%m/%Y')
    with ui.input(label, value=initial).props('dense outlined').classes('w-44') as date_input:
        with date_input.add_slot('append'):
            ui.icon('edit_calendar').on('click', lambda: menu.open()).classes('cursor-pointer')
        with ui.menu() as menu:
            ui.date(value=initial, mask='DD/MM/YYYY', on_change=menu.close).bind_value(date_input)
    return date_input


def _date_filter_input(label: str):
    """Ô lọc theo ngày — RỖNG mặc định (nghĩa là "không giới hạn"), khác
    `_date_picker_input` (luôn mặc định hôm nay). KHÔNG dùng cách tạo
    `_date_picker_input()` rồi gán `.value = ""` ngay sau đó — `ui.date`
    bên trong vẫn giữ giá trị khởi tạo "hôm nay" và đồng bộ ngược lại
    `date_input.value` qua `bind_value` theo chu kỳ, làm ô lọc âm thầm quay
    lại "hôm nay" sau vài trăm ms dù đã gán rỗng. Ở đây tạo `ui.date` không
    truyền `value=` ngay từ đầu nên cả 2 phía cùng rỗng, không có gì để
    đồng bộ ngược lại."""
    with ui.input(label, value="").props("dense outlined clearable").classes("w-44") as date_input:
        with date_input.add_slot("append"):
            ui.icon("edit_calendar").on("click", lambda: menu.open()).classes("cursor-pointer")
        with ui.menu() as menu:
            ui.date(mask="DD/MM/YYYY", on_change=menu.close).bind_value(date_input)
    return date_input

CONGS = [1, 9, 18, 17, 12]
# Mỗi cổng 1 màu riêng (xem `_ACCENT`) — chỉ để phân biệt trực quan giữa
# các bảng nhập liệu giống hệt nhau về cấu trúc, không mang ý nghĩa nghiệp vụ.
CONG_ACCENT = {1: "indigo", 9: "purple", 18: "rose", 17: "cyan", 12: "teal"}
CURS = ['VNĐ', 'USD', 'EUR']
FK = ['di_ih_m', 'di_ih_t', 'di_il_m', 'di_il_t', 'den_ih_m', 'den_ih_t', 'den_il_m', 'den_il_t']
FK_LBL = ['ĐI IH Món', 'ĐI IH Tiền', 'ĐI IL Món', 'ĐI IL Tiền',
          'ĐẾN IH Món', 'ĐẾN IH Tiền', 'ĐẾN IL Món', 'ĐẾN IL Tiền']


def nv(v):
    try:
        return float(str(v).replace(',', '').replace(' ', '')) if v not in (None, '') else 0.0
    except Exception:
        return 0.0


def fmt(v):
    v = nv(v)
    return '' if v == 0 else f'{int(v):,}'


@ui.page("/doi_chieu_citad")
def doi_chieu_citad_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.doi_chieu_citad"):
        ui.navigate.to("/home")
        return

    # Dữ liệu số (float) — nguồn sự thật để tính chênh lệch, tách khỏi text hiển thị trên ô nhập
    data = {
        "gD": {c: {u: {f: 0.0 for f in FK} for u in CURS} for c in CONGS},
        "phD": {u: {f: 0.0 for f in FK} for u in CURS},
        "napas": {"den_ih_m": 0.0, "den_ih_t": 0.0},
        "ebank": {"den_ih_m": 0.0, "den_ih_t": 0.0},
    }
    inputs = {
        "gE": {c: {u: {} for u in CURS} for c in CONGS},
        "phE": {u: {} for u in CURS},
        "napasE": {},
        "ebankE": {},
    }
    diff_labels = {"citad": {}, "phub": {}, "diff": {}}

    ngay_input = None
    lap_bang_input = None
    kiem_soat_input = None

    def _grid_cell_cls(row_idx: int, col_idx: int, n_rows: int, n_cols: int, extra: str = "") -> str:
        """Kẻ khung + chia dòng/cột cho `ui.grid`: border-r cho mọi cột trừ
        cột cuối, border-b cho mọi dòng trừ dòng cuối (đặt trên MỌI ô, kể cả
        ô chứa `ui.input`, để đồng bộ giao diện giữa các bảng nhập liệu và
        bảng chênh lệch — theo đúng yêu cầu). Dòng tiêu đề (row_idx=0) tô
        nền xanh dương — bỏ hẳn class màu chữ xám truyền vào qua `extra`
        (nếu có) rồi ép chữ trắng, thay vì nối thêm "text-white" phía sau
        (Tailwind không đảm bảo class nối sau luôn thắng class nối trước
        khi cùng set 1 thuộc tính — dễ ra chữ xám mờ trên nền xanh, khó đọc)."""
        if row_idx == 0:
            tokens = [t for t in extra.split() if not t.startswith("text-gray")]
            cls = " ".join(tokens) + " bg-blue-600 text-white py-2"
        else:
            cls = extra + " py-1.5"
        if col_idx < n_cols - 1:
            cls += " border-r border-gray-300 pr-2"
        if row_idx < n_rows - 1:
            cls += " border-b border-gray-300 pb-1"
        return cls

    def recalc():
        ci = {f: 0.0 for f in FK}
        for c in CONGS:
            for u in CURS:
                for f in FK:
                    ci[f] += data["gD"][c][u][f]
        # Chỉ cộng Napas, KHÔNG cộng Ebanking — đúng hành vi _calc() gốc,
        # xem ghi chú chi tiết trong doi_chieu_citad_service.py::build_xlsx.
        ci["den_ih_m"] += data["napas"]["den_ih_m"]
        ci["den_ih_t"] += data["napas"]["den_ih_t"]

        ph = {f: 0.0 for f in FK}
        for u in CURS:
            for f in FK:
                ph[f] += data["phD"][u][f]

        for f in FK:
            ci_val, ph_val = ci[f], ph[f]
            df_val = ci_val - ph_val
            diff_labels["citad"][f].text = fmt(ci_val) if ci_val else '—'
            diff_labels["phub"][f].text = fmt(ph_val) if ph_val else '—'
            if df_val == 0 and ci_val == 0 and ph_val == 0:
                diff_labels["diff"][f].text = '—'
                diff_labels["diff"][f].classes(remove='text-red-600 text-green-700')
            elif df_val == 0:
                diff_labels["diff"][f].text = '✓ 0'
                diff_labels["diff"][f].classes(remove='text-red-600', add='text-green-700')
            else:
                sign = '+' if df_val > 0 else ''
                diff_labels["diff"][f].text = f'{sign}{int(df_val):,}'
                diff_labels["diff"][f].classes(remove='text-green-700', add='text-red-600')

    def build_grid(container, entry_store: dict, data_store: dict, row_keys: list):
        with container:
            n_cols = len(FK) + 1
            n_rows = len(row_keys) + 1
            with ui.grid(columns=n_cols).classes("w-full gap-0 p-4"):
                ui.label("Loại tiền").classes(
                    _grid_cell_cls(0, 0, n_rows, n_cols, "text-sm font-bold text-gray-500 text-center")
                )
                for col_idx, lbl in enumerate(FK_LBL, start=1):
                    ui.label(lbl).classes(
                        _grid_cell_cls(0, col_idx, n_rows, n_cols, "text-sm font-bold text-gray-500 text-center")
                    )
                for row_idx, cur in enumerate(row_keys, start=1):
                    ui.label(cur).classes(
                        _grid_cell_cls(row_idx, 0, n_rows, n_cols, "text-sm font-bold self-center text-center")
                    )
                    entry_store[cur] = {}
                    for col_idx, fk in enumerate(FK, start=1):
                        def _on_change(e, _c=cur, _f=fk, _dd=data_store):
                            _dd[_c][_f] = nv(e.value)
                            recalc()
                        inp = ui.input(value='', on_change=_on_change).props(
                            'dense outlined input-class="text-right"'
                        ).classes(_grid_cell_cls(row_idx, col_idx, n_rows, n_cols, "w-full"))
                        inp.on('blur', lambda _, _i=inp: setattr(_i, 'value', fmt(_i.value)))
                        entry_store[cur][fk] = inp

    def build_napas_ebank_grid(container):
        """Chỉ 2 field IH Đến (Món/Tiền) — DUY NHẤT được dùng trong recalc()/
        session/export (xem docstring đầu file). 6 field còn lại của mỗi
        dòng KHÔNG có ô nhập (tránh ô "chết" không có tác dụng gì), nhưng
        vẫn vẽ ĐỦ 8 cột giống hệt FK_LBL của các bảng CITAD/PaymentHub phía
        trên — để cột "ĐẾN IH Món/Tiền" ở đây thẳng hàng đúng vị trí với
        cột cùng tên ở các bảng khác, đọc xuống dễ đối chiếu hơn."""
        with container:
            n_cols = len(FK) + 1
            n_rows = 3
            with ui.grid(columns=n_cols).classes("w-full gap-0 p-4"):
                ui.label("Loại tiền").classes(
                    _grid_cell_cls(0, 0, n_rows, n_cols, "text-sm font-bold text-gray-500 text-center")
                )
                for col_idx, lbl in enumerate(FK_LBL, start=1):
                    ui.label(lbl).classes(
                        _grid_cell_cls(0, col_idx, n_rows, n_cols, "text-sm font-bold text-gray-500 text-center")
                    )
                for row_idx, (label, store, entry_store) in enumerate([
                    ("Napas", data["napas"], inputs["napasE"]),
                    ("Ebanking", data["ebank"], inputs["ebankE"]),
                ], start=1):
                    ui.label(label).classes(
                        _grid_cell_cls(row_idx, 0, n_rows, n_cols, "text-sm font-bold self-center text-center")
                    )
                    for col_idx, fk in enumerate(FK, start=1):
                        cell_cls = _grid_cell_cls(row_idx, col_idx, n_rows, n_cols, "w-full")
                        if fk not in ("den_ih_m", "den_ih_t"):
                            # Cột không dùng — giữ ô trống để chiếm đúng bề rộng cột,
                            # không phải ô nhập (không có ý nghĩa nghiệp vụ ở đây).
                            # Tô nền xám nhạt để rõ ràng đây là ô "không dùng" có chủ
                            # đích, không phải lỗi giao diện làm mất ô.
                            ui.label("").classes(cell_cls + " bg-gray-50")
                            continue

                        def _on_change(e, _f=fk, _dd=store):
                            _dd[_f] = nv(e.value)
                            recalc()
                        inp = ui.input(value='', on_change=_on_change).props(
                            'dense outlined input-class="text-right"'
                        ).classes(cell_cls)
                        inp.on('blur', lambda _, _i=inp: setattr(_i, 'value', fmt(_i.value)))
                        entry_store[fk] = inp

    def apply_session_data(sess: dict):
        if not sess:
            return
        if sess.get("ngay"):
            ngay_input.value = sess["ngay"]
        lap_bang_input.value = sess.get("lap_bang", "")
        kiem_soat_input.value = sess.get("kiem_soat", "")
        gD = sess.get("gD", {})
        for c in CONGS:
            for u in CURS:
                for f in FK:
                    v = (gD.get(str(c), {}) or {}).get(u, {}).get(f, 0)
                    data["gD"][c][u][f] = nv(v)
                    inputs["gE"][c][u][f].value = fmt(v)
        phD = sess.get("phD", {})
        for u in CURS:
            for f in FK:
                v = (phD.get(u, {}) or {}).get(f, 0)
                data["phD"][u][f] = nv(v)
                inputs["phE"][u][f].value = fmt(v)
        # Napas/Ebanking chỉ có 2 field IH Đến trong session gốc (napas_m/napas_t)
        data["napas"]["den_ih_m"] = nv(sess.get("napas_m", 0))
        data["napas"]["den_ih_t"] = nv(sess.get("napas_t", 0))
        inputs["napasE"]["den_ih_m"].value = fmt(data["napas"]["den_ih_m"])
        inputs["napasE"]["den_ih_t"].value = fmt(data["napas"]["den_ih_t"])
        data["ebank"]["den_ih_m"] = nv(sess.get("ebank_m", 0))
        data["ebank"]["den_ih_t"] = nv(sess.get("ebank_t", 0))
        inputs["ebankE"]["den_ih_m"].value = fmt(data["ebank"]["den_ih_m"])
        inputs["ebankE"]["den_ih_t"].value = fmt(data["ebank"]["den_ih_t"])
        recalc()

    def get_session_payload() -> dict:
        gD = {str(c): {u: {f: data["gD"][c][u][f] for f in FK} for u in CURS} for c in CONGS}
        phD = {u: {f: data["phD"][u][f] for f in FK} for u in CURS}
        return {
            "ngay": ngay_input.value,
            "lap_bang": lap_bang_input.value,
            "kiem_soat": kiem_soat_input.value,
            "gD": gD,
            "phD": phD,
            "napas_m": data["napas"]["den_ih_m"],
            "napas_t": data["napas"]["den_ih_t"],
            "ebank_m": data["ebank"]["den_ih_m"],
            "ebank_t": data["ebank"]["den_ih_t"],
        }

    async def load_citad_buffer():
        try:
            items = await asyncio.to_thread(api.get, "/api/doi-chieu-citad/citad-buffer")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        if not items:
            ui.notify("Chưa có dữ liệu CITAD. Dùng Extension trên trang CITAD!", type="warning")
            return
        count = 0
        for item in items:
            cong = int(item.get("cong", 0) or 0)
            loai = item.get("loai", "")
            chieu = item.get("chieu", "")
            tien = item.get("tien", "VNĐ")
            so_mon = item.get("soMon", 0)
            so_tien = item.get("soTien", 0)
            if cong not in CONGS or tien not in CURS:
                continue
            fk_m, fk_t = f"{chieu}_{loai}_m", f"{chieu}_{loai}_t"
            if fk_m in FK:
                data["gD"][cong][tien][fk_m] = nv(so_mon)
                data["gD"][cong][tien][fk_t] = nv(so_tien)
                inputs["gE"][cong][tien][fk_m].value = fmt(so_mon)
                inputs["gE"][cong][tien][fk_t].value = fmt(so_tien)
                count += 1
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad/citad-buffer")
        except Exception:
            pass
        recalc()
        ui.notify(f"Đã nạp {count} mục từ CITAD", type="positive")

    async def load_phub_buffer():
        try:
            items = await asyncio.to_thread(api.get, "/api/doi-chieu-citad/paymenthub-buffer")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        if not items:
            ui.notify("Chưa có dữ liệu PaymentHub. Dùng Extension!", type="warning")
            return
        count = 0
        for item in items:
            loai, chieu = item.get("loai", ""), item.get("chieu", "")
            tien = item.get("tien", "VNĐ")
            so_mon, so_tien = item.get("soMon", 0), item.get("soTien", 0)
            src = item.get("source", "")
            if src == "napas":
                data["napas"]["den_ih_m"] = nv(so_mon)
                data["napas"]["den_ih_t"] = nv(so_tien)
                inputs["napasE"]["den_ih_m"].value = fmt(so_mon)
                inputs["napasE"]["den_ih_t"].value = fmt(so_tien)
                count += 1
                continue
            if tien not in CURS:
                continue
            fk_m, fk_t = f"{chieu}_{loai}_m", f"{chieu}_{loai}_t"
            if fk_m in FK:
                data["phD"][tien][fk_m] = nv(so_mon)
                data["phD"][tien][fk_t] = nv(so_tien)
                inputs["phE"][tien][fk_m].value = fmt(so_mon)
                inputs["phE"][tien][fk_t].value = fmt(so_tien)
                count += 1
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad/paymenthub-buffer")
        except Exception:
            pass
        recalc()
        ui.notify(f"Đã nạp {count} mục từ PaymentHub", type="positive")

    async def _save_session_now():
        try:
            await asyncio.to_thread(api.post, "/api/doi-chieu-citad/session", get_session_payload())
            ui.notify(f"Đã lưu ngày {ngay_input.value}", type="positive")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi lưu: {e}", type="negative")

    def do_save_session():
        # Lưu giờ ghi đè bản CHUNG của cả phòng cho ngày này (xem docstring
        # session_save trong service) — xác nhận trước khi ghi đè, tránh bấm
        # nhầm mất số liệu người khác vừa nhập.
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Xác nhận lưu đối chiếu ngày {ngay_input.value}?").classes("text-base font-bold")
            ui.label(
                "Đây là bản CHUNG của cả phòng cho ngày này — lưu sẽ GHI ĐÈ số liệu hiện "
                "có (nếu người khác đã lưu trước). Bản cũ vẫn xem lại được trong \"Lịch sử "
                "đối chiếu\"."
            ).classes("text-sm text-gray-500")
            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Huỷ", on_click=dialog.close).props("outline")

                async def _confirm():
                    dialog.close()
                    await _save_session_now()

                ui.button("Xác nhận lưu", icon="save", on_click=_confirm).classes(
                    "bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg"
                )
        dialog.open()

    async def _load_history_entry(history_id: int, ngay_hien_thi: str):
        """Tải đúng số liệu của 1 lần lưu cụ thể (không phải bản hiện hành)
        vào form, rồi chuyển sang tab "Đối chiếu" để xem/sửa tiếp."""
        try:
            sess = await asyncio.to_thread(api.get, f"/api/doi-chieu-citad/history-entry/{history_id}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi tải bản lịch sử: {e}", type="negative")
            return
        apply_session_data(sess)
        tabs.set_value(tab_doi_chieu)
        ui.notify(f"Đã tải bản lịch sử — ngày {ngay_hien_thi}", type="positive")

    def _render_history_entries(container, ngay: str, entries: list):
        """Danh sách từng lần lưu của 1 ngày — dùng chung cho tab Lịch sử
        (mở rộng tại chỗ khi bấm vào 1 ngày)."""
        with container:
            if not entries:
                ui.label("Chưa có ai lưu đối chiếu cho ngày này.").classes("text-sm text-gray-500 p-2")
                return
            with ui.column().classes("w-full border border-gray-200 rounded-xl gap-0 overflow-hidden"):
                for i, r in enumerate(entries, start=1):
                    is_last = i == len(entries)
                    with ui.row().classes(
                        "w-full items-center gap-0 px-2 py-1"
                        + ("" if is_last else " border-b border-gray-200")
                        + (" bg-emerald-50" if is_last else "")
                    ):
                        ui.label(str(i)).classes("text-xs text-gray-500 w-6 border-r border-gray-200 pr-2 mr-2")
                        ui.label(r["username"]).classes(
                            "text-sm font-bold flex-grow border-r border-gray-200 pr-2 mr-2"
                        )
                        ui.label(r["created_at"]).classes("text-xs text-gray-400 border-r border-gray-200 pr-2 mr-2")
                        if is_last:
                            ui.badge("Bản hiện hành").props('color="positive"').classes("mr-2")
                        ui.button(
                            icon="download",
                            on_click=lambda _, hid=r["id"], ng=ngay: _load_history_entry(hid, ng),
                        ).props("outline dense round size=sm").tooltip("Tải bản này")

    def _build_history_panel():
        """Tab "Lịch sử" — bảng TẤT CẢ các ngày đã có người chấm, lọc theo
        khoảng ngày, bấm 1 dòng để mở rộng tại chỗ xem chi tiết từng lần lưu
        của ngày đó (không dùng dialog — đúng pattern _build_history_panel
        của frontend/pages/swift_recon.py)."""
        with ui.row().classes("w-full items-end gap-3 flex-wrap mb-2"):
            tu_input = _date_filter_input("Từ ngày")
            den_input = _date_filter_input("Đến ngày")
            ui.button("Lọc", icon="filter_alt", on_click=lambda: load_days()).props("outline")

            async def clear_filter():
                tu_input.value = ""
                den_input.value = ""
                await load_days()

            ui.button("Xoá lọc", icon="clear", on_click=clear_filter).props("outline color=grey dense")

        days_area = ui.column().classes("w-full gap-1")

        async def load_days():
            days_area.clear()
            try:
                params = {}
                if tu_input.value:
                    params["tu_ngay"] = tu_input.value
                if den_input.value:
                    params["den_ngay"] = den_input.value
                rows = await asyncio.to_thread(api.get, "/api/doi-chieu-citad/reconciliation-days", params)
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi tải lịch sử: {e}", type="negative")
                return
            with days_area:
                if not rows:
                    msg = (
                        "Không có ngày nào trong khoảng lọc này — thử bấm \"Xoá lọc\" để xem tất cả."
                        if (tu_input.value or den_input.value)
                        else "Chưa có ngày nào được chấm."
                    )
                    ui.label(msg).classes("text-gray-400 p-4")
                    return
                with ui.column().classes("w-full border border-gray-200 rounded-xl gap-0 overflow-hidden"):
                    with ui.row().classes(
                        "w-full items-center gap-0 px-3 py-2 bg-blue-600 border-b border-gray-200 "
                        "text-xs font-semibold text-white"
                    ):
                        ui.label("Ngày").classes("w-28 border-r border-white/30 pr-2 mr-2")
                        ui.label("Người lưu sau cùng").classes("w-44 border-r border-white/30 pr-2 mr-2")
                        ui.label("Số lần lưu").classes("w-24 text-center border-r border-white/30 pr-2 mr-2")
                        ui.label("Cập nhật lúc").classes("flex-1")
                    for i, r in enumerate(rows, start=1):
                        _day_row(r, is_last=(i == len(rows)))

        def _day_row(r: dict, is_last: bool):
            ngay = r["ngay"]
            expanded = {"open": False}
            with ui.column().classes("w-full" + ("" if is_last else " border-b border-gray-200")):
                with ui.row().classes(
                    "w-full items-center gap-0 px-3 py-2 cursor-pointer hover:bg-gray-50"
                ) as row:
                    ui.label(ngay).classes("w-28 font-bold border-r border-gray-200 pr-2 mr-2")
                    ui.label(r["updated_by_username"] or "—").classes("w-44 border-r border-gray-200 pr-2 mr-2")
                    ui.label(str(r["so_lan_luu"])).classes(
                        "w-24 text-center border-r border-gray-200 pr-2 mr-2"
                    )
                    ui.label(r["updated_at"] or "").classes("flex-1 text-xs text-gray-400")
                    ui.icon("expand_more").classes("text-gray-500")
                detail_area = ui.column().classes("w-full pl-4")

                async def toggle_detail():
                    if expanded["open"]:
                        detail_area.clear()
                        expanded["open"] = False
                        return
                    try:
                        entries = await asyncio.to_thread(
                            api.get, f"/api/doi-chieu-citad/session/{quote(ngay, safe='')}/history"
                        )
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(f"Lỗi: {e}", type="negative")
                        return
                    expanded["open"] = True
                    _render_history_entries(detail_area, ngay, entries)

                row.on("click", toggle_detail)

        ui.timer(0.1, load_days, once=True)

    def do_reset():
        for c in CONGS:
            for u in CURS:
                for f in FK:
                    data["gD"][c][u][f] = 0.0
                    inputs["gE"][c][u][f].value = ''
        for u in CURS:
            for f in FK:
                data["phD"][u][f] = 0.0
                inputs["phE"][u][f].value = ''
        for f in ("den_ih_m", "den_ih_t"):
            data["napas"][f] = 0.0
            data["ebank"][f] = 0.0
            inputs["napasE"][f].value = ''
            inputs["ebankE"][f].value = ''
        recalc()
        ui.notify("Đã xoá toàn bộ dữ liệu", type="info")

    async def do_export():
        gD = {str(c): {u: {f: data["gD"][c][u][f] for f in FK} for u in CURS} for c in CONGS}
        phD = {u: {f: data["phD"][u][f] for f in FK} for u in CURS}
        payload = {
            "day_str": ngay_input.value,
            "sheet_name": (ngay_input.value or "Sheet1").replace("/", "_"),
            "lb": lap_bang_input.value,
            "ks": kiem_soat_input.value,
            "gD": gD,
            "phD": phD,
            "nm": data["napas"]["den_ih_m"],
            "nt": data["napas"]["den_ih_t"],
            "em": data["ebank"]["den_ih_m"],
            "et": data["ebank"]["den_ih_t"],
        }
        try:
            content = await asyncio.to_thread(api.post_download, "/api/doi-chieu-citad/export", payload)
            ui.download(content, f"Doi_chieu_CITAD_{payload['sheet_name']}.xlsx")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi xuất Excel: {e}", type="negative")

    # ── Kết nối Extension (mã kết nối cá nhân — xem docstring api/doi_chieu_citad.py) ──
    ext_status_label = None

    async def refresh_extension_status():
        try:
            status = await asyncio.to_thread(api.get, "/api/doi-chieu-citad/extension-token/status")
        except Exception:
            return
        if status.get("connected"):
            last = status.get("last_used_at") or "chưa dùng lần nào"
            ext_status_label.text = f"● Đã kết nối — lần dùng gần nhất: {last}"
            ext_status_label.classes(remove="bg-gray-100 text-gray-500", add="bg-emerald-50 text-emerald-700")
        else:
            ext_status_label.text = "○ Chưa kết nối Extension"
            ext_status_label.classes(remove="bg-emerald-50 text-emerald-700", add="bg-gray-100 text-gray-500")

    async def _try_auto_connect_extension(token: str) -> bool:
        """Gửi trực tiếp {server, token} vào extension qua
        chrome.runtime.sendMessage (chỉ hoạt động nếu extension_citad đã
        được cài — Chrome tự chặn theo whitelist origin khai trong
        manifest.json::externally_connectable, xem background.js). Trả về
        False (không throw) cho MỌI lý do thất bại — chưa cài extension,
        trình duyệt không phải Chrome/Edge, hoặc bị chặn — để luôn còn
        đường lùi là dán tay."""
        payload = json.dumps({"type": "SET_CONFIG", "server": api.BACKEND_URL, "token": token})
        js = f"""
            return await new Promise((resolve) => {{
                if (!(window.chrome && chrome.runtime && chrome.runtime.sendMessage)) {{
                    resolve({{ok: false, error: 'no_chrome_runtime'}});
                    return;
                }}
                try {{
                    chrome.runtime.sendMessage({_EXTENSION_ID!r}, {payload}, (response) => {{
                        if (chrome.runtime.lastError) {{
                            resolve({{ok: false, error: chrome.runtime.lastError.message}});
                        }} else {{
                            resolve(response || {{ok: false, error: 'empty_response'}});
                        }}
                    }});
                }} catch (e) {{
                    resolve({{ok: false, error: String(e)}});
                }}
            }});
        """
        try:
            result = await ui.run_javascript(js, timeout=3.0)
        except Exception:
            return False
        return bool(isinstance(result, dict) and result.get("ok"))

    async def do_create_extension_token():
        try:
            result = await asyncio.to_thread(api.post, "/api/doi-chieu-citad/extension-token", {})
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        token = result["token"]
        auto_ok = await _try_auto_connect_extension(token)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            if auto_ok:
                ui.label("✓ Đã tự động kết nối vào Extension").classes("text-lg font-bold text-green-700")
                ui.label(
                    "Mã kết nối mới đã được gửi thẳng vào Extension đang cài trên trình duyệt "
                    "này — không cần dán tay. Có thể dùng ngay các nút \"Lấy dữ liệu\" trên "
                    "trang CITAD/PaymentHub."
                ).classes("text-sm text-gray-500")
                ui.button("Đóng", on_click=dialog.close).classes(
                    "bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg mt-2"
                )
            else:
                ui.label("Mã kết nối Extension mới").classes("text-lg font-bold")
                ui.label(
                    "Không tự động kết nối được (chưa cài Extension trên trình duyệt này, hoặc "
                    "trình duyệt không hỗ trợ) — chỉ hiện mã ĐÚNG 1 LẦN, sao chép ngay, rồi bấm "
                    "icon Extension trên thanh công cụ Chrome → \"Tuỳ chọn\" → dán vào ô Mã kết "
                    "nối. Tạo mã mới sẽ tự động huỷ mã cũ."
                ).classes("text-sm text-gray-500")
                token_input = ui.input(value=token).props("readonly outlined dense").classes("w-full font-mono")
                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                    ui.button(
                        "Sao chép", icon="content_copy",
                        on_click=lambda: ui.run_javascript(
                            f"navigator.clipboard.writeText({token_input.value!r})"
                        ),
                    ).props("outline")
                    ui.button("Đóng", on_click=dialog.close).classes(
                        "bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg"
                    )
        dialog.open()
        await refresh_extension_status()

    async def do_revoke_extension_token():
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad/extension-token")
            ui.notify("Đã thu hồi mã kết nối", type="positive")
            await refresh_extension_status()
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")

    async def do_download_extension():
        try:
            content = await asyncio.to_thread(api.get_bytes, "/api/doi-chieu-citad/extension-download")
            ui.download(content, "extension_citad.zip")
            ui.notify(
                "Đã tải xong — giải nén rồi vào chrome://extensions, bật Developer mode, "
                "bấm Load unpacked và chọn thư mục vừa giải nén.",
                type="positive", multi_line=True, timeout=8000,
            )
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")

    with ui.row().classes("w-full"):
        _sidebar("doi_chieu_citad")
        with _content_area():
            _navy_header(
                "ĐỐI CHIẾU CITAD ↔ PAYMENTHUB",
                "Đối chiếu số liệu CITAD (NHNN) với PaymentHub (Agribank) theo từng ngày",
            )

            with ui.tabs().props(
                "active-color=indigo-600 indicator-color=indigo-600 align=left"
            ).classes("w-full border-b border-gray-200 mb-1") as tabs:
                tab_doi_chieu = ui.tab("Đối chiếu")
                tab_lich_su = ui.tab("Lịch sử")

            with ui.tab_panels(tabs, value=tab_doi_chieu).classes("w-full"):
                with ui.tab_panel(tab_doi_chieu):
                    with _section_card("Kết nối Extension (nạp số liệu tự động từ CITAD/PaymentHub)", icon="extension", accent="indigo"):
                        with ui.row().classes("w-full items-center gap-3 p-2 flex-wrap"):
                            ext_status_label = ui.label("Đang kiểm tra...").classes(
                                "text-xs font-medium px-3 py-1.5 rounded-full bg-gray-100 text-gray-500"
                            )
                            ui.button(
                                "Tải Extension (.zip)", icon="download", on_click=do_download_extension
                            ).props("outline")
                            ui.button(
                                "Tạo mã kết nối mới", icon="vpn_key", on_click=do_create_extension_token
                            ).props("outline")
                            ui.button("Thu hồi", icon="link_off", on_click=do_revoke_extension_token).props(
                                "outline color=red dense"
                            )
                        ui.label(
                            "Lần đầu dùng: (1) Tải Extension → giải nén → chrome://extensions → Developer mode → "
                            "Load unpacked, chọn thư mục vừa giải nén — bước này vẫn phải tự làm 1 lần, Chrome không "
                            "cho web tự cài extension. (2) Bấm \"Tạo mã kết nối mới\" ở trên — nếu Extension đã cài "
                            "trên đúng trình duyệt này, mã sẽ tự động được gửi thẳng vào Extension, không cần dán tay. "
                            "Chỉ khi không tự kết nối được (trình duyệt khác, hoặc Extension chưa cài) mới cần sao "
                            "chép và dán thủ công vào trang Tuỳ chọn của Extension như hướng dẫn hiện ra. Mỗi người tự "
                            "tạo 1 mã riêng, không dùng chung với người khác. Chi tiết trong file README.md nằm sẵn "
                            "trong bản .zip vừa tải."
                        ).classes("text-xs text-gray-500 px-2 -mt-2")
                        ui.timer(0.1, refresh_extension_status, once=True)

                    with ui.row().classes(
                        "w-full items-end gap-3 flex-wrap mb-2 bg-white rounded-2xl "
                        "border border-gray-200 shadow-sm p-4"
                    ):
                        ngay_input = _date_picker_input("Ngày")
                        lap_bang_input = ui.input("Lập bảng").props("dense outlined").classes("w-48")
                        kiem_soat_input = ui.input("Kiểm soát").props("dense outlined").classes("w-48")
                        ui.button("Nạp CITAD", icon="cloud_download", on_click=load_citad_buffer).props("outline").classes("rounded-lg")
                        ui.button("Nạp PaymentHub", icon="cloud_download", on_click=load_phub_buffer).props("outline").classes("rounded-lg")
                        ui.button("Lưu", icon="save", on_click=do_save_session).classes(
                            "bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg"
                        )
                        ui.button("Xoá", icon="delete", on_click=do_reset).props("outline color=red").classes("rounded-lg")
                        ui.button("Xuất Excel", icon="grid_on", on_click=do_export).classes(
                            "bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg"
                        )

                    with _section_card("PaymentHub – Agribank", icon="account_balance", accent="blue"):
                        build_grid(ui.column().classes("w-full"), inputs["phE"], data["phD"], CURS)

                    for cong in CONGS:
                        with _section_card(
                            f"Cổng {cong} – CITAD (NHNN)", icon="swap_horiz", accent=CONG_ACCENT.get(cong, "blue")
                        ):
                            build_grid(ui.column().classes("w-full"), inputs["gE"][cong], data["gD"][cong], CURS)

                    with _section_card("Napas / Ebanking (bổ sung)", icon="add_card", accent="amber"):
                        build_napas_ebank_grid(ui.column().classes("w-full"))

                    with _section_card("Bảng chênh lệch (CITAD − PaymentHub)", icon="balance", accent="emerald"):
                        n_cols = len(FK) + 1
                        n_rows = 4  # 1 dòng tiêu đề + CITAD/PaymentHub/CHÊNH LỆCH

                        with ui.grid(columns=n_cols).classes("w-full gap-0 p-4"):
                            ui.label("").classes(
                                _grid_cell_cls(0, 0, n_rows, n_cols, "text-sm font-bold text-gray-500 text-center")
                            )
                            for col_idx, lbl in enumerate(FK_LBL, start=1):
                                ui.label(lbl).classes(
                                    _grid_cell_cls(0, col_idx, n_rows, n_cols, "text-sm font-bold text-gray-500 text-center")
                                )
                            for row_idx, (key, label, color) in enumerate([
                                ("citad", "CITAD", "text-sky-600"),
                                ("phub", "PaymentHub", "text-purple-600"),
                                ("diff", "CHÊNH LỆCH", "text-red-600"),
                            ], start=1):
                                ui.label(label).classes(
                                    _grid_cell_cls(row_idx, 0, n_rows, n_cols, f"text-sm font-bold self-center {color}")
                                )
                                for col_idx, fk in enumerate(FK, start=1):
                                    lbl = ui.label("—").classes(
                                        _grid_cell_cls(row_idx, col_idx, n_rows, n_cols, "text-sm text-right self-center")
                                    )
                                    diff_labels[key][fk] = lbl

                    recalc()

                with ui.tab_panel(tab_lich_su):
                    ui.label(
                        "1 bản đối chiếu CHUNG cho cả phòng mỗi ngày — ai lưu sau cùng là bản hiện hành. "
                        "Bấm vào 1 ngày để xem từng lần lưu, bấm \"Tải\" trên 1 lần lưu để xem/khôi phục "
                        "đúng số liệu của lần đó."
                    ).classes("text-xs text-gray-500 mb-2")
                    _build_history_panel()
