"""Trang Đối chiếu CITAD (NHNN) ↔ PaymentHub (Agribank) — Phòng QLTK Nostro, Vostro.

Trang SONG SONG, độc lập với `frontend/pages/doi_chieu_citad.py` (Phòng
Thanh toán) — mô phỏng đúng quy ước bố cục/UI (`_navy_header`, `_section_card`,
nút "Nạp CITAD"/"Nạp PaymentHub" đọc buffer Extension, tab "Lịch sử", xuất
Excel) nhưng dữ liệu/công thức khác hẳn, xem
`backend/services/doi_chieu_citad_nostro_service.py`:
  - cD[cong]["gtt"|"gtc"] = {soMon, soTien} — 5 cổng CITAD, trang "Tra cứu
    dữ liệu", chỉ chiều Đi, chỉ giao dịch thành công.
  - phD["gtt"|"gtc_truoc"|"gtc_tu"] = {soMon, soTien} — PaymentHub, trang
    "Lập bảng kê phí chia sẻ CITAD", dòng Tổng cộng.
  - Tổng CITAD = cộng 5 cổng (riêng gtt/gtc). Tổng HUB(gtc) = gtc_truoc + gtc_tu.
  - Chênh lệch = Tổng CITAD − Tổng HUB (1 cặp mỗi loại gtt/gtc).

Extension Chrome là gói RIÊNG (`extension_citad_nv/`, không chung với
`extension_citad/` của Phòng Thanh toán) — endpoint mã kết nối/tải .zip gọi
qua `/api/doi-chieu-citad-nostro/extension-token*`, `/extension-download`,
`/extension-version` (khai báo riêng trong `backend/api/doi_chieu_citad_nostro.py`,
chỉ dùng CHUNG cơ chế token ở tầng service — xem docstring ở đó).
"""
import asyncio
import datetime
import json
from urllib.parse import quote

from nicegui import ui
from starlette.requests import Request as _StarletteRequest
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _require_auth, _handle_api_error

# ID cố định của extension_citad_nv — suy ra tất định từ khoá "key" gắn cứng
# trong extension_citad_nv/manifest.json (không phụ thuộc máy/thư mục cài
# đặt lúc "Load unpacked"). KHÁC _EXTENSION_ID của extension_citad (Phòng
# Thanh toán) — 2 gói Extension riêng, 2 khoá riêng, 2 ID riêng. Nếu thay
# khoá "key" trong manifest.json thì PHẢI tính lại ID này (SHA-256 của DER
# public key, lấy 16 byte đầu, mỗi nibble ánh xạ 0-15 -> 'a'-'p').
_EXTENSION_ID = "khkonpnidmecnmmhohlmjamfolkpaeko"

_ACCENT = {
    "blue": ("bg-blue-50", "text-blue-600", "border-blue-100", "bg-blue-50/40"),
    "indigo": ("bg-indigo-50", "text-indigo-600", "border-indigo-100", "bg-indigo-50/40"),
    "emerald": ("bg-emerald-50", "text-emerald-600", "border-emerald-100", "bg-emerald-50/40"),
    "amber": ("bg-amber-50", "text-amber-600", "border-amber-100", "bg-amber-50/40"),
    "rose": ("bg-rose-50", "text-rose-600", "border-rose-100", "bg-rose-50/40"),
}


def _navy_header(title: str, subtitle: str = ""):
    with ui.column().classes("w-full bg-blue-950 rounded-2xl px-6 py-4 mb-4 gap-0.5"):
        ui.label(title).classes("text-xl font-bold text-white tracking-wide")
        if subtitle:
            ui.label(subtitle).classes("text-blue-200 text-sm")


def _section_card(title: str, icon: str = "table_chart", accent: str = "blue"):
    bg, text, border, wash = _ACCENT.get(accent, _ACCENT["blue"])
    card = ui.card().classes(
        f"w-full rounded-2xl border border-gray-200 shadow-sm hover:shadow-md "
        f"transition-shadow duration-200 {wash} p-0 overflow-hidden"
    )
    with card:
        with ui.row().classes(f"w-full items-center gap-3 px-5 py-4 border-b {border} bg-gray-50/60"):
            with ui.row().classes(f"items-center justify-center w-9 h-9 rounded-xl {bg} shrink-0"):
                ui.icon(icon).classes(f"{text} text-lg")
            ui.label(title).classes("font-semibold text-gray-800 text-[15px]")
    return card


def _date_picker_input(label: str, initial: str = None):
    initial = initial or datetime.date.today().strftime('%d/%m/%Y')
    with ui.input(label, value=initial).props('dense outlined').classes('w-44') as date_input:
        with date_input.add_slot('append'):
            ui.icon('edit_calendar').on('click', lambda: menu.open()).classes('cursor-pointer')
        with ui.menu() as menu:
            ui.date(value=initial, mask='DD/MM/YYYY', on_change=menu.close).bind_value(date_input)
    return date_input


def _date_filter_input(label: str):
    with ui.input(label, value="").props("dense outlined clearable").classes("w-44") as date_input:
        with date_input.add_slot("append"):
            ui.icon("edit_calendar").on("click", lambda: menu.open()).classes("cursor-pointer")
        with ui.menu() as menu:
            ui.date(mask="DD/MM/YYYY", on_change=menu.close).bind_value(date_input)
    return date_input


CONGS = ["1", "9", "12", "17", "18"]
# Giữ ĐỒNG BỘ với CONG_LABEL trong backend/schemas/doi_chieu_citad_nostro.py
# (báo cáo Excel dùng bản bên đó) — frontend không import được schema backend.
CONG_LABEL = {"1": "Cổng 001", "9": "Cổng CITAD (9)", "12": "Cổng 9212", "17": "Cổng 7917", "18": "Cổng 4818"}
LOAI_CITAD = ["gtt", "gtc"]
LOAI_LBL = {"gtt": "Giá trị Thấp", "gtc": "Giá trị Cao"}
HUB_ROWS = ["gtt", "gtc_truoc", "gtc_tu"]
HUB_LBL = {"gtt": "GTT", "gtc_truoc": "GTC — Trước 15h30", "gtc_tu": "GTC — Từ 15h30"}


def nv(v):
    try:
        return float(str(v).replace(',', '').replace(' ', '')) if v not in (None, '') else 0.0
    except Exception:
        return 0.0


def fmt(v):
    v = nv(v)
    if v == 0:
        return ''
    if v == int(v):
        return f'{int(v):,}'
    return f'{v:,.2f}'


_CELL_DATA_BG = "bg-red-200"


def _apply_cell_bg(inp):
    if inp.value:
        inp.classes(add=_CELL_DATA_BG)
    else:
        inp.classes(remove=_CELL_DATA_BG)


def _set_input(inp, value):
    inp.value = value
    _apply_cell_bg(inp)


@ui.page("/doi_chieu_citad_nostro")
async def doi_chieu_citad_nostro_page(request: _StarletteRequest):
    if not _require_auth():
        return
    if not api.has_feature("menu.doi_chieu_citad_nostro"):
        ui.navigate.to("/home")
        return

    history_refresh = {"fn": None}
    view_state = {"readonly": False}

    data = {
        "cD": {c: {loai: {"soMon": 0.0, "soTien": 0.0} for loai in LOAI_CITAD} for c in CONGS},
        "phD": {r: {"soMon": 0.0, "soTien": 0.0} for r in HUB_ROWS},
    }
    inputs = {
        "cE": {c: {loai: {} for loai in LOAI_CITAD} for c in CONGS},
        "phE": {r: {} for r in HUB_ROWS},
    }
    tong_labels = {"citad": {}, "hub": {}, "diff": {}}

    tu_ngay_input = None
    den_ngay_input = None
    lap_bang_input = None
    kiem_soat_input = None

    def _compute_totals():
        ci = {loai: {"soMon": 0.0, "soTien": 0.0} for loai in LOAI_CITAD}
        for c in CONGS:
            for loai in LOAI_CITAD:
                ci[loai]["soMon"] += data["cD"][c][loai]["soMon"]
                ci[loai]["soTien"] += data["cD"][c][loai]["soTien"]
        hub = {
            "gtt": dict(data["phD"]["gtt"]),
            "gtc": {
                "soMon": data["phD"]["gtc_truoc"]["soMon"] + data["phD"]["gtc_tu"]["soMon"],
                "soTien": data["phD"]["gtc_truoc"]["soTien"] + data["phD"]["gtc_tu"]["soTien"],
            },
        }
        return ci, hub

    def recalc():
        ci, hub = _compute_totals()
        for loai in LOAI_CITAD:
            for fld in ("soMon", "soTien"):
                ci_val, hub_val = ci[loai][fld], hub[loai][fld]
                tong_labels["citad"][(loai, fld)].text = fmt(ci_val) if ci_val else '—'
                tong_labels["hub"][(loai, fld)].text = fmt(hub_val) if hub_val else '—'
                df_val = ci_val - hub_val
                lbl = tong_labels["diff"][(loai, fld)]
                if df_val == 0 and ci_val == 0 and hub_val == 0:
                    lbl.text = '—'
                    lbl.classes(remove='text-red-600 text-green-700')
                elif df_val == 0:
                    lbl.text = '✓ 0'
                    lbl.classes(remove='text-red-600', add='text-green-700')
                else:
                    sign = '+' if df_val > 0 else ''
                    lbl.text = f'{sign}{fmt(df_val)}'
                    lbl.classes(remove='text-green-700', add='text-red-600')

    def build_citad_grid(container):
        with container:
            n_cols = 5  # Cổng | GTT Số món | GTT Số tiền | GTC Số món | GTC Số tiền
            with ui.grid(columns=n_cols).classes("w-full gap-0 p-4"):
                header_cls = "bg-blue-600 text-white text-sm font-bold text-center py-2 border-r border-blue-700"
                ui.label("Cổng CITAD").classes(header_cls)
                ui.label("GTT - Số món").classes(header_cls)
                ui.label("GTT - Số tiền").classes(header_cls)
                ui.label("GTC - Số món").classes(header_cls)
                ui.label("GTC - Số tiền").classes(header_cls + " border-r-0")
                for c in CONGS:
                    ui.label(CONG_LABEL[c]).classes(
                        "text-sm font-bold flex items-center justify-center py-1.5 "
                        "border-r border-b border-gray-300"
                    )
                    for loai in LOAI_CITAD:
                        for fld, fld_lbl in (("soMon", "m"), ("soTien", "t")):
                            def _on_change(e, _c=c, _l=loai, _f=fld):
                                data["cD"][_c][_l][_f] = nv(e.value)
                                _apply_cell_bg(e.sender)
                                recalc()
                            inp = ui.input(value='', on_change=_on_change).props(
                                'dense outlined input-class="text-right"'
                            ).classes("w-full border-r border-b border-gray-300 py-1.5")
                            inp.on('blur', lambda _, _i=inp: _set_input(_i, fmt(_i.value)))
                            inputs["cE"][c][loai][fld] = inp
                # Dòng Tổng cộng — chỉ hiển thị (label), không phải input.
                ui.label("Tổng cộng 5 cổng").classes(
                    "text-sm font-bold flex items-center justify-center py-1.5 bg-blue-50"
                )
                for loai in LOAI_CITAD:
                    for fld in ("soMon", "soTien"):
                        lbl = ui.label('—').classes(
                            "text-sm font-bold flex items-center justify-end pr-2 py-1.5 bg-blue-50"
                        )
                        tong_labels["citad"][(loai, fld)] = lbl

    def build_hub_grid(container):
        with container:
            with ui.grid(columns=3).classes("w-full gap-0 p-4"):
                header_cls = "bg-emerald-600 text-white text-sm font-bold text-center py-2 border-r border-emerald-700"
                ui.label("Khối HUB").classes(header_cls)
                ui.label("Số món").classes(header_cls)
                ui.label("Số tiền").classes(header_cls + " border-r-0")
                for r in HUB_ROWS:
                    ui.label(HUB_LBL[r]).classes(
                        "text-sm font-bold flex items-center justify-center py-1.5 "
                        "border-r border-b border-gray-300"
                    )
                    for fld in ("soMon", "soTien"):
                        def _on_change(e, _r=r, _f=fld):
                            data["phD"][_r][_f] = nv(e.value)
                            _apply_cell_bg(e.sender)
                            recalc()
                        inp = ui.input(value='', on_change=_on_change).props(
                            'dense outlined input-class="text-right"'
                        ).classes("w-full border-r border-b border-gray-300 py-1.5")
                        inp.on('blur', lambda _, _i=inp: _set_input(_i, fmt(_i.value)))
                        inputs["phE"][r][fld] = inp
                ui.label("Tổng HUB (GTT)").classes("text-sm font-bold flex items-center justify-center py-1.5 bg-emerald-50")
                for fld in ("soMon", "soTien"):
                    lbl = ui.label('—').classes("text-sm font-bold flex items-center justify-end pr-2 py-1.5 bg-emerald-50")
                    tong_labels["hub"][("gtt", fld)] = lbl
                ui.label("Tổng HUB (GTC = Trước+Từ 15h30)").classes("text-sm font-bold flex items-center justify-center py-1.5 bg-emerald-50")
                for fld in ("soMon", "soTien"):
                    lbl = ui.label('—').classes("text-sm font-bold flex items-center justify-end pr-2 py-1.5 bg-emerald-50")
                    tong_labels["hub"][("gtc", fld)] = lbl

    def build_diff_grid(container):
        with container:
            with ui.grid(columns=5).classes("w-full gap-0 p-4"):
                header_cls = "bg-amber-600 text-white text-sm font-bold text-center py-2 border-r border-amber-700"
                ui.label("Chênh lệch").classes(header_cls)
                ui.label("GTT - Số món").classes(header_cls)
                ui.label("GTT - Số tiền").classes(header_cls)
                ui.label("GTC - Số món").classes(header_cls)
                ui.label("GTC - Số tiền").classes(header_cls + " border-r-0")
                ui.label("CITAD − HUB").classes(
                    "text-sm font-bold flex items-center justify-center py-1.5 border-r border-gray-300 bg-amber-50"
                )
                for loai in LOAI_CITAD:
                    for fld in ("soMon", "soTien"):
                        lbl = ui.label('—').classes(
                            "text-sm font-bold flex items-center justify-end pr-2 py-1.5 border-r border-gray-300 bg-amber-50"
                        )
                        tong_labels["diff"][(loai, fld)] = lbl

    def apply_session_data(sess: dict):
        tu_ngay, den_ngay = "", ""
        ky = sess.get("ky", "")
        if "-" in ky:
            tu_ngay, den_ngay = ky.split("-", 1)
        if tu_ngay:
            tu_ngay_input.value = tu_ngay
        if den_ngay:
            den_ngay_input.value = den_ngay
        lap_bang_input.value = sess.get("lap_bang", "") or ""
        kiem_soat_input.value = sess.get("kiem_soat", "") or ""
        cD = sess.get("cD", {}) or {}
        for c in CONGS:
            cd = cD.get(c, {}) or {}
            for loai in LOAI_CITAD:
                src = cd.get(loai, {}) or {}
                for fld in ("soMon", "soTien"):
                    v = nv(src.get(fld, 0))
                    data["cD"][c][loai][fld] = v
                    _set_input(inputs["cE"][c][loai][fld], fmt(v))
        phD = sess.get("phD", {}) or {}
        for r in HUB_ROWS:
            src = phD.get(r, {}) or {}
            for fld in ("soMon", "soTien"):
                v = nv(src.get(fld, 0))
                data["phD"][r][fld] = v
                _set_input(inputs["phE"][r][fld], fmt(v))
        recalc()

    def _set_form_readonly(readonly: bool):
        """Khoá/mở các ô nhập tay khi xem 1 bản từ tab "Lịch sử" (chỉ xem,
        không cho sửa/lưu đè nội dung đã chấm) và khi bấm "Quay lại chỉnh
        sửa". Khoá bằng prop `readonly` của Quasar trên TỪNG ô nhập — chặn
        gõ thật ở phía trình duyệt, không chỉ ẩn nút Lưu. Các ô "Tổng cộng"/
        "Tổng HUB"/"Chênh lệch" là `ui.label` (không phải input) nên KHÔNG
        cần khoá — không có cách nào sửa tay được từ đầu (chỉ do
        `recalc()` tính lại)."""
        view_state["readonly"] = readonly
        all_inputs = [tu_ngay_input, den_ngay_input, lap_bang_input, kiem_soat_input]
        for c in CONGS:
            for loai in LOAI_CITAD:
                for fld in ("soMon", "soTien"):
                    all_inputs.append(inputs["cE"][c][loai][fld])
        for r in HUB_ROWS:
            for fld in ("soMon", "soTien"):
                all_inputs.append(inputs["phE"][r][fld])
        for inp in all_inputs:
            if readonly:
                inp.props("readonly")
            else:
                inp.props(remove="readonly")
        readonly_banner.set_visibility(readonly)
        save_btn.set_visibility(not readonly)
        nap_citad_btn.set_visibility(not readonly)
        nap_ph_btn.set_visibility(not readonly)

    def _exit_readonly_view():
        _set_form_readonly(False)
        ui.notify("Đã thoát chế độ xem — sẵn sàng nhập mới", type="info")

    def get_session_payload() -> dict:
        cD = {c: {loai: dict(data["cD"][c][loai]) for loai in LOAI_CITAD} for c in CONGS}
        phD = {r: dict(data["phD"][r]) for r in HUB_ROWS}
        return {
            "ky": f"{tu_ngay_input.value}-{den_ngay_input.value}",
            "lap_bang": lap_bang_input.value,
            "kiem_soat": kiem_soat_input.value,
            "cD": cD,
            "phD": phD,
        }

    async def load_citad_buffer():
        try:
            items = await asyncio.to_thread(api.get, "/api/doi-chieu-citad-nostro/citad-buffer")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        if not items:
            ui.notify("Chưa có dữ liệu CITAD. Dùng Extension trên trang Tra cứu dữ liệu CITAD!", type="warning")
            return
        count = 0
        for item in items:
            cong = str(item.get("cong", ""))
            loai = item.get("loai", "")
            so_mon, so_tien = item.get("soMon", 0), item.get("soTien", 0)
            if cong not in CONGS or loai not in LOAI_CITAD:
                continue
            data["cD"][cong][loai]["soMon"] = nv(so_mon)
            data["cD"][cong][loai]["soTien"] = nv(so_tien)
            _set_input(inputs["cE"][cong][loai]["soMon"], fmt(so_mon))
            _set_input(inputs["cE"][cong][loai]["soTien"], fmt(so_tien))
            count += 1
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad-nostro/citad-buffer")
        except Exception:
            pass
        recalc()
        ui.notify(f"Đã nạp {count} mục từ CITAD", type="positive")

    async def load_phub_buffer():
        try:
            items = await asyncio.to_thread(api.get, "/api/doi-chieu-citad-nostro/paymenthub-buffer")
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
            loai = item.get("loai", "")
            so_mon, so_tien = item.get("soMon", 0), item.get("soTien", 0)
            if loai not in HUB_ROWS:
                continue
            data["phD"][loai]["soMon"] = nv(so_mon)
            data["phD"][loai]["soTien"] = nv(so_tien)
            _set_input(inputs["phE"][loai]["soMon"], fmt(so_mon))
            _set_input(inputs["phE"][loai]["soTien"], fmt(so_tien))
            count += 1
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad-nostro/paymenthub-buffer")
        except Exception:
            pass
        recalc()
        ui.notify(f"Đã nạp {count} mục từ PaymentHub", type="positive")

    async def _save_session_now():
        try:
            await asyncio.to_thread(api.post, "/api/doi-chieu-citad-nostro/session", get_session_payload())
            ui.notify(f"Đã lưu kỳ {tu_ngay_input.value} - {den_ngay_input.value}", type="positive")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi lưu: {e}", type="negative")
            return
        if history_refresh.get("fn"):
            await history_refresh["fn"]()

    async def do_save_session():
        if view_state["readonly"]:
            ui.notify("Đang ở chế độ chỉ xem — bấm \"Quay lại chỉnh sửa\" trước khi lưu", type="warning")
            return
        # Chặn sớm ở đây cho người dùng thấy lỗi ngay tại ô ngày; backend vẫn
        # kiểm lại lần nữa (svc.normalize_ky) vì đây chỉ là lớp tiện dụng.
        if not (tu_ngay_input.value or "").strip() or not (den_ngay_input.value or "").strip():
            ui.notify("Chưa nhập đủ Từ ngày và Đến ngày của kỳ đối chiếu", type="warning")
            return
        ky = f"{tu_ngay_input.value}-{den_ngay_input.value}"
        try:
            check = await asyncio.to_thread(
                api.get, "/api/doi-chieu-citad-nostro/period-check",
                params={"tu_ngay": tu_ngay_input.value, "den_ngay": den_ngay_input.value, "exclude_ky": ky},
            )
        except Exception:
            check = {"overlaps": [], "gap_before": None}  # không chặn lưu nếu API kiểm tra lỗi

        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            ui.label(f"Xác nhận lưu đối chiếu kỳ {tu_ngay_input.value} - {den_ngay_input.value}?").classes("text-base font-bold")
            ui.label(
                "Đây là bản CHUNG của cả phòng cho kỳ này — lưu sẽ GHI ĐÈ số liệu hiện "
                "có (nếu người khác đã lưu trước). Bản cũ vẫn xem lại được trong \"Lịch sử đối chiếu\"."
            ).classes("text-sm text-gray-500")
            if check.get("overlaps"):
                with ui.row().classes("w-full items-start gap-2 mt-2 p-2 bg-red-50 border border-red-200 rounded-lg"):
                    ui.icon("warning").classes("text-red-600")
                    ui.label(
                        "⚠ Kỳ này CHỒNG NGÀY với kỳ đã lưu trước: " + ", ".join(check["overlaps"]) +
                        " — có thể bị tính trùng số liệu."
                    ).classes("text-sm text-red-700")
            gap = check.get("gap_before")
            if gap:
                with ui.row().classes("w-full items-start gap-2 mt-2 p-2 bg-amber-50 border border-amber-200 rounded-lg"):
                    ui.icon("info").classes("text-amber-600")
                    ui.label(
                        f"⚠ Có khoảng HỞ {gap['so_ngay']} ngày ({gap['tu_ngay']} - {gap['den_ngay']}) "
                        "chưa được chấm giữa kỳ liền trước và kỳ này."
                    ).classes("text-sm text-amber-700")
            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Huỷ", on_click=dialog.close).props("outline")

                async def _confirm():
                    dialog.close()
                    await _save_session_now()

                ui.button("Xác nhận lưu", icon="save", on_click=_confirm).classes(
                    "bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg"
                )
        dialog.open()

    async def _load_history_entry(history_id: int, ky_hien_thi: str):
        try:
            sess = await asyncio.to_thread(api.get, f"/api/doi-chieu-citad-nostro/history-entry/{history_id}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi tải bản lịch sử: {e}", type="negative")
            return
        apply_session_data(sess)
        _set_form_readonly(True)
        tabs.set_value(tab_doi_chieu)
        ui.notify(f"Đang xem bản lịch sử (chỉ đọc) — kỳ {ky_hien_thi}", type="positive")

    def _render_history_entries(container, ky: str, entries: list):
        with container:
            if not entries:
                ui.label("Chưa có ai lưu đối chiếu cho kỳ này.").classes("text-sm text-gray-500 p-2")
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
                        ui.label(r["username"]).classes("text-sm font-bold flex-grow border-r border-gray-200 pr-2 mr-2")
                        ui.label(r["created_at"]).classes("text-xs text-gray-400 border-r border-gray-200 pr-2 mr-2")
                        if is_last:
                            ui.badge("Bản hiện hành").props('color="positive"').classes("mr-2")
                        ui.button(
                            icon="download",
                            on_click=lambda _, hid=r["id"], k=ky: _load_history_entry(hid, k),
                        ).props("outline dense round size=sm").tooltip("Tải bản này")

    def _build_history_panel():
        with ui.row().classes("w-full items-end gap-3 flex-wrap mb-2"):
            tu_input = _date_filter_input("Từ ngày")
            den_input = _date_filter_input("Đến ngày")
            nguoi_input = ui.input("Tên người chấm", value="").props("dense outlined clearable").classes("w-52")
            ui.button("Tìm", icon="search", on_click=lambda: load_history()).props("outline")

            async def clear_filter():
                tu_input.value = ""
                den_input.value = ""
                nguoi_input.value = ""
                await load_history()

            ui.button("Xoá lọc", icon="clear", on_click=clear_filter).props("outline color=grey dense")

        list_container = ui.column().classes("w-full gap-1")

        async def load_history():
            try:
                days = await asyncio.to_thread(
                    api.get, "/api/doi-chieu-citad-nostro/reconciliation-days",
                    params={"tu_ngay": tu_input.value or None, "den_ngay": den_input.value or None,
                            "nguoi_cham": nguoi_input.value or None},
                )
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi tải lịch sử: {e}", type="negative")
                return
            list_container.clear()
            with list_container:
                if not days:
                    ui.label("Chưa có kỳ đối chiếu nào được lưu.").classes("text-sm text-gray-500 p-2")
                for d in days:
                    with ui.expansion(
                        f"{d['ky']} — {d['created_by_name'] or d['created_by_username'] or '(không rõ)'} "
                        f"({d['so_lan_luu']} lần lưu)"
                    ).classes("w-full border border-gray-200 rounded-xl"):
                        entries_container = ui.column().classes("w-full p-2")

                        async def _load_entries(ky=d["ky"], cont=entries_container):
                            cont.clear()
                            try:
                                entries = await asyncio.to_thread(
                                    api.get, f"/api/doi-chieu-citad-nostro/session/{quote(ky, safe='')}/history"
                                )
                            except Exception as e:
                                if _handle_api_error(e):
                                    return
                                ui.notify(f"Lỗi: {e}", type="negative")
                                return
                            _render_history_entries(cont, ky, entries)

                        ui.timer(0.1, _load_entries, once=True)

        history_refresh["fn"] = load_history
        ui.timer(0.1, load_history, once=True)

    async def _do_download_export():
        try:
            content = await asyncio.to_thread(
                api.post_download, "/api/doi-chieu-citad-nostro/export", {
                    "tu_ngay": tu_ngay_input.value, "den_ngay": den_ngay_input.value,
                    "sheet_name": f"{tu_ngay_input.value}_{den_ngay_input.value}".replace("/", "."),
                    "lb": lap_bang_input.value, "ks": kiem_soat_input.value,
                    "cD": {c: {loai: dict(data["cD"][c][loai]) for loai in LOAI_CITAD} for c in CONGS},
                    "phD": {r: dict(data["phD"][r]) for r in HUB_ROWS},
                },
            )
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi xuất Excel: {e}", type="negative")
            return
        fname = f"Doi_chieu_CITAD_PaymentHub_Nostro_{tu_ngay_input.value}_{den_ngay_input.value}.xlsx".replace("/", ".")
        ui.download(content, fname)

    async def refresh_extension_status():
        try:
            status = await asyncio.to_thread(api.get, "/api/doi-chieu-citad-nostro/extension-token/status")
        except Exception:
            return
        if status.get("connected"):
            token_status_label.text = f"Đã kết nối — tạo lúc {status.get('created_at') or '?'}"
            token_status_label.classes(remove="text-red-600", add="text-emerald-700")
        else:
            token_status_label.text = "Chưa kết nối Extension"
            token_status_label.classes(remove="text-emerald-700", add="text-red-600")

    async def _try_auto_connect_extension(token: str) -> bool:
        """Gửi trực tiếp {server, token} vào extension_citad_nv qua
        chrome.runtime.sendMessage (chỉ hoạt động nếu extension đã được cài
        — Chrome tự chặn theo whitelist origin khai trong
        extension_citad_nv/manifest.json::externally_connectable). Trả về
        False (không throw) cho MỌI lý do thất bại — chưa cài extension,
        trình duyệt không phải Chromium, hoặc bị chặn — để luôn còn đường
        lùi là dán tay qua trang Tuỳ chọn (options.html). Cùng cơ chế với
        `frontend/pages/doi_chieu_citad.py::_try_auto_connect_extension`,
        chỉ khác `_EXTENSION_ID` (2 gói Extension riêng, 2 ID riêng)."""
        js = f"""
            return await new Promise((resolve) => {{
                if (!(window.chrome && chrome.runtime && chrome.runtime.sendMessage)) {{
                    resolve({{ok: false, error: 'no_chrome_runtime'}});
                    return;
                }}
                try {{
                    chrome.runtime.sendMessage({_EXTENSION_ID!r}, {{
                        type: 'SET_CONFIG',
                        server: window.location.origin,
                        token: {json.dumps(token)},
                    }}, (response) => {{
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
            result = await asyncio.to_thread(api.post, "/api/doi-chieu-citad-nostro/extension-token", {})
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
                    "Extension \"CITAD - PaymentHub N&V\" đã nhận cấu hình tự động — không cần dán tay."
                ).classes("text-sm text-gray-500")
            else:
                ui.label("Mã kết nối mới — CHỈ hiện đúng 1 lần").classes("text-base font-bold")
                ui.label(
                    "Không tự kết nối được (Extension chưa cài, hoặc trình duyệt không hỗ trợ) — "
                    "dán mã này vào trang Tuỳ chọn (options) của Extension \"CITAD - PaymentHub N&V\" "
                    "(gói Extension RIÊNG của Phòng QLTK Nostro, Vostro — không phải Extension của "
                    "Phòng Thanh toán)."
                ).classes("text-sm text-gray-500")
                ui.input(value=token).props("readonly outlined dense").classes("w-full font-mono")
            ui.button("Đóng", on_click=lambda: (dialog.close(), refresh_extension_status())).classes("mt-2")
        dialog.open()

    async def do_revoke_extension_token():
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad-nostro/extension-token")
            ui.notify("Đã thu hồi mã kết nối", type="positive")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        await refresh_extension_status()

    async def do_download_extension():
        try:
            content = await asyncio.to_thread(api.get_bytes, "/api/doi-chieu-citad-nostro/extension-download")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        ui.download(content, "extension_citad_nv.zip")

    with ui.row().classes("w-full"):
        await _sidebar("doi_chieu_citad_nostro")
        with _content_area():
            _navy_header(
                "ĐỐI CHIẾU CITAD - PAYMENTHUB",
                "Phòng Quản lý tài khoản Nostro, Vostro — chiều Đi, giao dịch thành công",
            )

            with ui.tabs().props(
                "active-color=indigo-600 indicator-color=indigo-600 align=left"
            ).classes("w-full border-b border-gray-200 mb-1") as tabs:
                tab_doi_chieu = ui.tab("Đối chiếu")
                tab_lich_su = ui.tab("Lịch sử")
                tab_extension = ui.tab("Kết nối Extension")

            with ui.tab_panels(tabs, value=tab_doi_chieu).classes("w-full"):
                with ui.tab_panel(tab_doi_chieu):
                    with ui.column().classes("w-full gap-4"):
                        with ui.row().classes("w-full items-center gap-2 p-2 bg-amber-50 border border-amber-200 rounded-lg") as readonly_banner:
                            ui.icon("visibility").classes("text-amber-700")
                            ui.label("Đang xem bản LỊCH SỬ (chỉ đọc)").classes("text-amber-800 font-bold")
                            ui.button("Quay lại chỉnh sửa", on_click=_exit_readonly_view).props("outline dense")
                        readonly_banner.set_visibility(False)

                        with _section_card("Kỳ đối chiếu", icon="calendar_month", accent="indigo"):
                            with ui.row().classes("w-full items-end gap-3 p-4 flex-wrap"):
                                tu_ngay_input = _date_picker_input("Từ ngày")
                                den_ngay_input = _date_picker_input("Đến ngày")
                                lap_bang_input = ui.input("Người lập bảng", value="").props("dense outlined").classes("w-52")
                                kiem_soat_input = ui.input("Người kiểm soát", value="").props("dense outlined").classes("w-52")
                                nap_citad_btn = ui.button("Nạp CITAD", icon="cloud_download", on_click=load_citad_buffer).props("outline").classes("rounded-lg")
                                nap_ph_btn = ui.button("Nạp PaymentHub", icon="cloud_download", on_click=load_phub_buffer).props("outline").classes("rounded-lg")
                            with ui.row().classes("w-full items-center gap-2 px-4 pb-3"):
                                ui.icon("event_note").classes("text-indigo-600 text-sm")
                                ky_dang_cham_label = ui.label("").classes("text-sm font-bold text-indigo-700")

                            def _refresh_ky_label():
                                ky_dang_cham_label.text = (
                                    f"Kỳ đang chấm: {tu_ngay_input.value} – {den_ngay_input.value}  "
                                    f"— kiểm tra đúng khoảng ngày này trước khi Truy vấn trên CITAD/PaymentHub"
                                )

                            ui.timer(1.0, _refresh_ky_label)

                        with _section_card("Chênh lệch CITAD − HUB", icon="difference", accent="amber") as diff_card:
                            build_diff_grid(diff_card)

                        with _section_card("5 cổng CITAD — Tra cứu dữ liệu", icon="account_balance_wallet", accent="indigo") as citad_card:
                            build_citad_grid(citad_card)

                        with _section_card("PaymentHub — Lập bảng kê phí chia sẻ CITAD", icon="hub", accent="emerald") as hub_card:
                            build_hub_grid(hub_card)

                        with ui.row().classes("w-full justify-end gap-2"):
                            ui.button("Xuất Excel", icon="download", on_click=_do_download_export).props("outline").classes("rounded-lg")
                            save_btn = ui.button("Lưu đối chiếu", icon="save", on_click=do_save_session).classes(
                                "bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg"
                            )
                    recalc()

                with ui.tab_panel(tab_lich_su):
                    with _section_card("Lịch sử đối chiếu", icon="history", accent="blue"):
                        with ui.column().classes("w-full gap-2 p-4"):
                            _build_history_panel()

                with ui.tab_panel(tab_extension):
                    with _section_card("Kết nối Extension Chrome", icon="extension", accent="rose"):
                        with ui.column().classes("w-full gap-3 p-4"):
                            ui.label(
                                "Extension \"CITAD - PaymentHub N&V\" — gói RIÊNG của Phòng QLTK Nostro, "
                                "Vostro, không chung với Extension của Phòng Thanh toán. Cần tải và cài "
                                "đặt (Load unpacked) riêng, nhưng có thể dùng lại cùng 1 mã kết nối nếu "
                                "đã tạo cho module kia (mã xác thực theo người dùng, không theo Extension)."
                            ).classes("text-sm text-gray-500")
                            token_status_label = ui.label("Đang kiểm tra...").classes("font-bold")
                            with ui.row().classes("gap-2"):
                                ui.button("Tạo mã kết nối mới", icon="vpn_key", on_click=do_create_extension_token).props("outline")
                                ui.button("Thu hồi mã", icon="link_off", on_click=do_revoke_extension_token).props("outline color=negative")
                                ui.button("Tải Extension (.zip)", icon="download", on_click=do_download_extension).props("outline")
                            ui.timer(0.1, refresh_extension_status, once=True)
