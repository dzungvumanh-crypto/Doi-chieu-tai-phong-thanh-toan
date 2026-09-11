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
from decimal import Decimal

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


def _dec(v) -> Decimal:
    """Chuyển sang Decimal CHÍNH XÁC TUYỆT ĐỐI — cùng cơ chế/lý do với
    `_dec()` trong `frontend/pages/doi_chieu_citad.py` và `_dec()` trong
    `backend/services/doi_chieu_citad_nostro_service.py`: đi qua `str(v)`
    trước khi vào Decimal để tránh mở khai triển nhị phân của float. Dùng
    cho phép CỘNG DỒN 5 cổng ở `_compute_totals()` — cộng nhiều số thực có
    thể sinh dư nhị phân dù về bản chất đã khớp tuyệt đối (bug thật đã xảy
    ra ở module gốc Phòng Thanh toán 25/08/2026: hiện "+0,0078125" dù CITAD
    gốc cộng đúng khớp PaymentHub)."""
    try:
        return Decimal(str(v)) if v not in (None, '') else Decimal(0)
    except Exception:
        return Decimal(0)


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
    current_user = api.get_current_user() or {}
    current_staff_id = current_user.get("id")
    # "Xoá bảng của người khác" là QUYỀN (mã doi_chieu_citad_nostro.delete_any,
    # cấp qua Phân quyền theo nhóm) — KHÔNG hard-code role="admin" (review
    # PR #90, sai ở bản đầu, xem docs/DESIGN.md mục Phân quyền). api.has_feature()
    # đã tự cho admin qua ở dòng đầu (siêu quyền cố ý) nên không cần check
    # role riêng ở đây nữa.
    can_delete_any = api.has_feature("doi_chieu_citad_nostro.delete_any")
    # session_id: None = form chưa gắn với bảng nào đã lưu — Lưu tiếp theo sẽ
    # tạo bảng MỚI của chính người đang thao tác (nhiều người có thể có bảng
    # riêng cho cùng 1 kỳ, không ai ghi đè ai — xem
    # backend/services/doi_chieu_citad_nostro_service.py::session_save()).
    # Có giá trị = đang sửa tiếp ĐÚNG bảng đó.
    # "ky": kỳ của bảng ĐANG GẮN với session_id hiện tại — dùng để phát hiện
    # người dùng tự đổi ô ngày trong lúc còn gắn 1 bảng cũ (xem
    # _on_ky_changed() bên dưới, mirror _on_ngay_changed_sync() của PTT).
    view_state = {"readonly": False, "session_id": None, "created_by": None, "ky": None}

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
        """Cộng dồn bằng Decimal (`_dec()`), KHÔNG bằng float trực tiếp —
        cộng 5 cổng có thể sinh dư nhị phân dù về bản chất đã khớp tuyệt
        đối (xem docstring `_dec()` phía trên). Trả về Decimal — `recalc()`
        so `== 0`/`> 0` chính xác tuyệt đối, `fmt()` tự hoá float khi hiển
        thị (qua `nv()` roundtrip qua `str()`, không mất chính xác)."""
        ci = {loai: {"soMon": Decimal(0), "soTien": Decimal(0)} for loai in LOAI_CITAD}
        for c in CONGS:
            for loai in LOAI_CITAD:
                ci[loai]["soMon"] += _dec(data["cD"][c][loai]["soMon"])
                ci[loai]["soTien"] += _dec(data["cD"][c][loai]["soTien"])
        hub = {
            "gtt": {"soMon": _dec(data["phD"]["gtt"]["soMon"]), "soTien": _dec(data["phD"]["gtt"]["soTien"])},
            "gtc": {
                "soMon": _dec(data["phD"]["gtc_truoc"]["soMon"]) + _dec(data["phD"]["gtc_tu"]["soMon"]),
                "soTien": _dec(data["phD"]["gtc_truoc"]["soTien"]) + _dec(data["phD"]["gtc_tu"]["soTien"]),
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
        view_state["session_id"] = sess.get("_meta_session_id")
        view_state["created_by"] = sess.get("_meta_created_by")
        view_state["ky"] = sess.get("ky") or None
        _refresh_delete_btn()
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

    def _refresh_delete_btn():
        """Nút "Xoá bảng này" chỉ hiện khi ĐANG xem/sửa 1 bảng đã lưu
        (`session_id` khác None) VÀ (là chủ bảng HOẶC có quyền xoá bảng
        người khác) — đúng chính sách xoá đã chốt: chủ bảng tự xoá + admin
        (hoặc người được cấp mã delete_any) xoá được bất kỳ bảng nào."""
        can_delete = view_state["session_id"] is not None and (
            view_state["created_by"] == current_staff_id or can_delete_any
        )
        delete_btn.set_visibility(can_delete)

    def get_session_payload() -> dict:
        cD = {c: {loai: dict(data["cD"][c][loai]) for loai in LOAI_CITAD} for c in CONGS}
        phD = {r: dict(data["phD"][r]) for r in HUB_ROWS}
        return {
            "ky": f"{tu_ngay_input.value}-{den_ngay_input.value}",
            "lap_bang": lap_bang_input.value,
            "kiem_soat": kiem_soat_input.value,
            "cD": cD,
            "phD": phD,
            "session_id": view_state["session_id"],
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
            resp = await asyncio.to_thread(api.post, "/api/doi-chieu-citad-nostro/session", get_session_payload())
            ui.notify(f"Đã lưu kỳ {tu_ngay_input.value} - {den_ngay_input.value}", type="positive")
        except Exception as e:
            if _handle_api_error(e):
                return
            # review PR #90: TRƯỚC đây gỡ session_id ở đây cho MỌI lỗi (kể cả
            # lỗi mạng thoáng qua) — bấm Lưu lại sau 1 lỗi tạm thời sẽ ÂM THẦM
            # tạo bảng MỚI thay vì báo lại đúng lỗi cũ. api.post() không giữ
            # mã trạng thái HTTP tới tận đây (chỉ còn chuỗi thông báo — xem
            # frontend/api_client.py::_raise_http_error, gói mọi lỗi 4xx/5xx
            # thường thành Exception(str) đồng nhất) nên KHÔNG đoán mò 403/404
            # qua nội dung chuỗi (dễ vỡ nếu đổi câu chữ). Ca đáng lo nhất —
            # đổi ô ngày trong lúc còn gắn bảng cũ — đã chặn TRƯỚC khi gửi ở
            # _on_ky_changed() bên dưới, nên KHÔNG tự gỡ session_id ở đây nữa:
            # cứ báo lỗi thật, để nguyên trạng thái gắn, người dùng tự quyết
            # định (bấm lại/tải lại trang) thay vì âm thầm nhân bản bảng.
            ui.notify(f"Lỗi lưu: {e}", type="negative")
            return
        view_state["session_id"] = resp.get("session_id")
        view_state["created_by"] = current_staff_id
        view_state["ky"] = f"{tu_ngay_input.value}-{den_ngay_input.value}"
        _refresh_delete_btn()
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
            if view_state["session_id"] is None:
                ui.label(
                    "Sẽ tạo BẢNG MỚI cho kỳ này — không đụng tới bảng của người khác (nếu "
                    "có) đã chấm cùng kỳ. Xem tất cả các bảng của kỳ này ở tab \"Lịch sử\"."
                ).classes("text-sm text-gray-500")
            else:
                ui.label(
                    "Đang lưu tiếp vào bảng bạn đã tạo trước đó cho kỳ này — không ảnh "
                    "hưởng bảng của người khác."
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

    async def _delete_session_now():
        session_id = view_state["session_id"]
        try:
            await asyncio.to_thread(api.delete, f"/api/doi-chieu-citad-nostro/session-by-id/{session_id}")
            ui.notify("Đã xoá bảng.", type="positive")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi xoá: {e}", type="negative")
            return
        # Xoá xong: gỡ khỏi form (không còn bảng nào đang gắn), reset về
        # trắng để tránh hiểu nhầm đang xem dữ liệu của bảng vừa xoá.
        # apply_session_data() với dict trắng tự đặt lại session_id/created_by
        # về None (gọi kèm _refresh_delete_btn()) — không cần gán tay lại.
        _set_form_readonly(False)
        apply_session_data({"ky": "", "lap_bang": "", "kiem_soat": "", "cD": {}, "phD": {}})
        _own_sessions_state["checked_ky"] = None  # cho banner tự hỏi lại backend
        if history_refresh.get("fn"):
            await history_refresh["fn"]()

    def do_delete_session():
        session_id = view_state["session_id"]
        if session_id is None:
            return
        is_owner = view_state["created_by"] == current_staff_id
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            ui.label("Xoá bảng này?").classes("text-base font-bold text-red-700")
            # review PR #90: câu cũ nói "lịch sử vẫn còn ở tab Lịch sử" là SAI —
            # tab đó liệt kê THEO BẢNG, bảng mất thì không còn đường nào mở lại
            # lịch sử của nó (dữ liệu lịch sử thật ra vẫn nằm trong CSDL, mồ côi,
            # nhưng không có UI nào truy cập được — coi như mất với người dùng).
            if is_owner:
                msg = "Đây là bảng của bạn. Xoá xong KHÔNG hoàn tác được — kể cả lịch sử các lần lưu trước đó của bảng này cũng KHÔNG xem lại được nữa."
            else:
                msg = (
                    "Đây là bảng của NGƯỜI KHÁC — bạn đang xoá với quyền xoá bảng người khác. "
                    "Hành động này KHÔNG hoàn tác được, kể cả lịch sử các lần lưu trước đó."
                )
            ui.label(msg).classes("text-sm text-gray-500")
            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Huỷ", on_click=dialog.close).props("outline")

                async def _confirm():
                    dialog.close()
                    await _delete_session_now()

                ui.button("Xác nhận xoá", icon="delete", on_click=_confirm).classes(
                    "bg-red-600 hover:bg-red-700 text-white rounded-lg"
                )
        dialog.open()

    async def _load_history_entry(history_id: int, ky_hien_thi: str):
        """Xem ĐÚNG 1 lần lưu trong quá khứ (chỉ đọc) — dữ liệu snapshot,
        không phải trạng thái hiện tại của bảng. Khác `_load_session_by_id()`
        (tải bảng để SỬA TIẾP)."""
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

    async def _load_session_by_id(session_id: int, ky_hien_thi: str):
        """Tải TRẠNG THÁI HIỆN TẠI của 1 bảng cụ thể — sửa tiếp được nếu là
        chủ bảng (`created_by == current_staff_id`), chỉ xem được nếu không
        phải chủ (đọc chia sẻ toàn phòng, giống PTT — chỉ sửa/xoá mới giới
        hạn theo chủ bảng)."""
        try:
            sess = await asyncio.to_thread(api.get, f"/api/doi-chieu-citad-nostro/session-by-id/{session_id}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi tải bảng: {e}", type="negative")
            return
        if not sess:
            ui.notify("Bảng này đã bị xoá.", type="warning")
            return
        apply_session_data(sess)
        is_owner = view_state["created_by"] == current_staff_id
        _set_form_readonly(not is_owner)
        tabs.set_value(tab_doi_chieu)
        if is_owner:
            ui.notify(f"Đã tải bảng của bạn cho kỳ {ky_hien_thi} — sẵn sàng sửa tiếp", type="positive")
        else:
            ui.notify(f"Đang xem bảng của người khác (chỉ đọc) — kỳ {ky_hien_thi}", type="info")

    def _render_history_entries(container, session_id: int, ky: str, entries: list):
        """Tầng 3: từng lần lưu cụ thể của ĐÚNG 1 bảng (`session_id`) — chỉ
        xem (snapshot quá khứ), không phải tải để sửa tiếp (xem
        `_load_session_by_id()` ở tầng 2 cho việc đó)."""
        with container:
            if not entries:
                ui.label("Chưa có lần lưu nào.").classes("text-sm text-gray-500 p-2")
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
                            icon="visibility",
                            on_click=lambda _, hid=r["id"], k=ky: _load_history_entry(hid, k),
                        ).props("outline dense round size=sm").tooltip("Xem bản lưu này (chỉ đọc)")

    def _session_row(container, s: dict):
        """Tầng 2: 1 dòng/bảng (`session_id`) của 1 người, cho 1 kỳ — mirror
        _session_row của Phòng Thanh toán, bớt badge Chính thức/Tạm (Nostro
        không có khái niệm chốt bản cuối)."""
        with container:
            is_owner = s["created_by"] == current_staff_id
            with ui.row().classes(
                "w-full items-center gap-0 px-2 py-1.5 border-b border-gray-200 last:border-b-0"
            ):
                ui.icon("description").classes("text-gray-400 text-sm mr-2")
                name = s["created_by_name"] or s["created_by_username"] or "(không rõ)"
                ui.label(name + (" (bạn)" if is_owner else "")).classes(
                    "text-sm font-bold flex-grow border-r border-gray-200 pr-2 mr-2"
                )
                ui.label(f"{s['so_lan_luu']} lần lưu").classes(
                    "text-xs text-gray-500 border-r border-gray-200 pr-2 mr-2"
                )
                ui.label(s["updated_at"] or "").classes(
                    "text-xs text-gray-400 border-r border-gray-200 pr-2 mr-2"
                )
                ui.button(
                    "Tải để sửa tiếp" if is_owner else "Xem",
                    icon="edit" if is_owner else "visibility",
                    on_click=lambda _, sid=s["session_id"], k=s["ky"]: _load_session_by_id(sid, k),
                ).props("outline dense size=sm").classes("mr-2")
            entries_container = ui.column().classes("w-full pl-6 pb-2")

            async def _load_entries(sid=s["session_id"], k=s["ky"], cont=entries_container):
                cont.clear()
                try:
                    entries = await asyncio.to_thread(
                        api.get, f"/api/doi-chieu-citad-nostro/session-by-id/{sid}/history"
                    )
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi: {e}", type="negative")
                    return
                _render_history_entries(cont, sid, k, entries)

            ui.timer(0.1, _load_entries, once=True)

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
                rows = await asyncio.to_thread(
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
                if not rows:
                    ui.label("Chưa có kỳ đối chiếu nào được lưu.").classes("text-sm text-gray-500 p-2")
                # Tầng 1: gom theo kỳ — 1 kỳ giờ có thể có NHIỀU bảng (nhiều
                # người chấm riêng), khác trước đây (1 kỳ = 1 dòng).
                by_ky: dict[str, list] = {}
                for r in rows:
                    by_ky.setdefault(r["ky"], []).append(r)
                for ky, sessions in by_ky.items():
                    with ui.expansion(f"{ky} — {len(sessions)} bảng").classes(
                        "w-full border border-gray-200 rounded-xl"
                    ):
                        sessions_container = ui.column().classes("w-full p-2 gap-0")
                        for s in sessions:
                            _session_row(sessions_container, s)

        history_refresh["fn"] = load_history
        ui.timer(0.1, load_history, once=True)

    def _parse_ky_range_local(ky: str):
        """Bản rút gọn của `_parse_ky_range()` bên
        `backend/services/doi_chieu_citad_nostro_service.py` — dùng để tính
        cảnh báo chồng ngày NGAY TRÊN TRÌNH DUYỆT (không gọi thêm API) khi
        người dùng tick/bỏ tick bảng ở màn "Tổng hợp tháng"."""
        try:
            tu_s, den_s = ky.split("-", 1)
            tu = datetime.datetime.strptime(tu_s.strip(), "%d/%m/%Y")
            den = datetime.datetime.strptime(den_s.strip(), "%d/%m/%Y")
            return (tu, den) if tu <= den else (den, tu)
        except Exception:
            return None

    def _build_month_summary_panel():
        with ui.row().classes("w-full items-end gap-3 flex-wrap mb-2"):
            nam_input = ui.number("Năm", value=datetime.date.today().year, format="%.0f").props(
                "dense outlined"
            ).classes("w-28")
            thang_input = ui.number("Tháng", value=datetime.date.today().month, min=1, max=12, format="%.0f").props(
                "dense outlined"
            ).classes("w-24")
            ui.button("Tải danh sách bảng", icon="search", on_click=lambda: load_month()).props("outline")
            lb_thang_input = ui.input("Người lập bảng", value="").props("dense outlined").classes("w-52")
            ks_thang_input = ui.input("Người kiểm soát", value="").props("dense outlined").classes("w-52")

        missing_box = ui.column().classes("w-full")
        checklist_box = ui.column().classes("w-full gap-0 border border-gray-200 rounded-xl overflow-hidden")
        overlap_box = ui.column().classes("w-full")
        with ui.row().classes("w-full items-center gap-4 p-3 bg-amber-50 border border-amber-200 rounded-lg mt-2") as total_box:
            total_label = ui.label("Chưa tính tổng — tải danh sách bảng rồi tick chọn.").classes(
                "text-sm text-amber-800 flex-grow"
            )
            xuat_thang_btn = ui.button("Xuất Excel tháng", icon="download").props("outline")

        state = {"sessions": [], "checks": {}}  # session_id -> ui.checkbox

        def _recompute_overlap():
            overlap_box.clear()
            checked_ids = [sid for sid, cb in state["checks"].items() if cb.value]
            ranges = []
            for s in state["sessions"]:
                if s["session_id"] in checked_ids:
                    rng = _parse_ky_range_local(s["ky"])
                    if rng:
                        ranges.append((s["ky"], rng[0], rng[1]))
            chong = []
            for i in range(len(ranges)):
                for j in range(i + 1, len(ranges)):
                    _, s1, e1 = ranges[i]
                    _, s2, e2 = ranges[j]
                    if s1 <= e2 and s2 <= e1:
                        chong.append((ranges[i][0], ranges[j][0]))
            if chong:
                with overlap_box:
                    with ui.row().classes("w-full items-start gap-2 p-2 bg-red-50 border border-red-200 rounded-lg"):
                        ui.icon("warning").classes("text-red-600")
                        noi_dung = "; ".join(f"{a} ↔ {b}" for a, b in chong)
                        ui.label(f"⚠ Các bảng đang tick CHỒNG NGÀY nhau: {noi_dung} — có thể bị tính trùng.").classes(
                            "text-sm text-red-700"
                        )

        async def _recompute_total():
            checked_ids = [sid for sid, cb in state["checks"].items() if cb.value]
            if not checked_ids:
                total_label.text = "Chưa chọn bảng nào — tổng tháng = 0."
                return
            try:
                res = await asyncio.to_thread(
                    api.post, "/api/doi-chieu-citad-nostro/month-summary", {"session_ids": checked_ids}
                )
            except Exception as e:
                if _handle_api_error(e):
                    return
                total_label.text = f"Lỗi tính tổng: {e}"
                return
            ci, hub = res["ci"], res["hub"]
            parts = []
            for loai, ten in (("gtt", "GTT"), ("gtc", "GTC")):
                dfm = ci[loai]["soMon"] - hub[loai]["soMon"]
                dft = ci[loai]["soTien"] - hub[loai]["soTien"]
                khop = dfm == 0 and dft == 0
                dau = "✓" if khop else "⚠"
                parts.append(
                    f"{dau} {ten}: CITAD {fmt(ci[loai]['soMon'])}/{fmt(ci[loai]['soTien'])} — "
                    f"HUB {fmt(hub[loai]['soMon'])}/{fmt(hub[loai]['soTien'])} — "
                    f"Chênh lệch {fmt(dfm)}/{fmt(dft)}"
                )
            total_label.text = f"Đang tính trên {len(checked_ids)} bảng — " + "  |  ".join(parts)

        async def _on_check_change():
            _recompute_overlap()
            await _recompute_total()

        async def load_month():
            try:
                res = await asyncio.to_thread(
                    api.get, "/api/doi-chieu-citad-nostro/month-sessions",
                    params={"nam": int(nam_input.value), "thang": int(thang_input.value)},
                )
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi tải danh sách tháng: {e}", type="negative")
                return
            state["sessions"] = res["sessions"]
            state["checks"] = {}

            missing_box.clear()
            with missing_box:
                if res["missing_days"]:
                    with ui.row().classes("w-full items-start gap-2 p-2 bg-red-50 border border-red-200 rounded-lg mb-2"):
                        ui.icon("event_busy").classes("text-red-600")
                        ui.label(
                            f"⚠ Còn {len(res['missing_days'])} ngày CHƯA ai chấm trong tháng này — "
                            "cần chấm bù: " + ", ".join(res["missing_days"])
                        ).classes("text-sm text-red-700")
                else:
                    with ui.row().classes("w-full items-center gap-2 p-2 bg-emerald-50 border border-emerald-200 rounded-lg mb-2"):
                        ui.icon("check_circle").classes("text-emerald-600")
                        ui.label("Đã đủ bảng phủ hết mọi ngày trong tháng.").classes("text-sm text-emerald-700")

            checklist_box.clear()
            with checklist_box:
                if not res["sessions"]:
                    ui.label("Chưa có bảng nào cho tháng này.").classes("text-sm text-gray-500 p-3")
                for s in res["sessions"]:
                    with ui.row().classes(
                        "w-full items-center gap-2 px-3 py-1.5 border-b border-gray-200 last:border-b-0"
                    ):
                        # Truyền THẲNG hàm async, KHÔNG bọc asyncio.create_task —
                        # task mới không có slot stack của NiceGUI, ui.notify()
                        # bên trong sẽ ném RuntimeError âm thầm (xem review PR #90,
                        # mục "Event handler async" trong docs/DESIGN.md).
                        cb = ui.checkbox(value=True, on_change=_on_check_change)
                        state["checks"][s["session_id"]] = cb
                        name = s["created_by_name"] or s["created_by_username"] or "(không rõ)"
                        ui.label(f"{s['ky']} — {name}").classes("text-sm flex-grow")

            _recompute_overlap()
            await _recompute_total()

        async def _do_download_month_export():
            checked_ids = [sid for sid, cb in state["checks"].items() if cb.value]
            if not checked_ids:
                ui.notify("Chưa chọn bảng nào để xuất.", type="warning")
                return
            try:
                content = await asyncio.to_thread(
                    api.post_download, "/api/doi-chieu-citad-nostro/month-summary/export", {
                        "nam": int(nam_input.value), "thang": int(thang_input.value),
                        "session_ids": checked_ids,
                        "lb": lb_thang_input.value, "ks": ks_thang_input.value,
                    },
                )
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi xuất Excel tháng: {e}", type="negative")
                return
            fname = f"Tong_hop_thang_{int(thang_input.value):02d}.{int(nam_input.value)}.xlsx"
            ui.download(content, fname)

        xuat_thang_btn.on_click(_do_download_month_export)
        ui.timer(0.1, load_month, once=True)

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
                tab_tong_hop_thang = ui.tab("Tổng hợp tháng")
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

                            def _on_ky_changed():
                                """Người dùng tự gõ/đổi ô ngày trong lúc còn gắn 1
                                bảng cũ (`view_state["session_id"]` khác None) —
                                coi như bắt đầu bảng MỚI, gỡ gắn NGAY (không đợi
                                bấm Lưu mới phát hiện). Mirror
                                `_on_ngay_changed_sync()` của PTT
                                (`frontend/pages/doi_chieu_citad.py`). Review
                                PR #90: thiếu bước này khiến Lưu lần 1 (ky mới,
                                session_id cũ) ăn lỗi "kỳ không khớp", Lưu lần 2
                                mới vô tình tạo bảng mới — người dùng không biết
                                vì sao lần đầu lỗi."""
                                if view_state["session_id"] is None:
                                    return
                                ky_now = f"{tu_ngay_input.value}-{den_ngay_input.value}"
                                if ky_now != view_state.get("ky"):
                                    view_state["session_id"] = None
                                    view_state["created_by"] = None
                                    view_state["ky"] = None
                                    _refresh_delete_btn()
                                    ui.notify(
                                        "Đã đổi sang kỳ khác — lưu tiếp theo sẽ tạo bảng MỚI, "
                                        "không ghi đè bảng đang xem trước đó.",
                                        type="info",
                                    )

                            tu_ngay_input.on_value_change(_on_ky_changed)
                            den_ngay_input.on_value_change(_on_ky_changed)
                            with ui.row().classes("w-full items-center gap-2 px-4 pb-3"):
                                ui.icon("event_note").classes("text-indigo-600 text-sm")
                                ky_dang_cham_label = ui.label("").classes("text-sm font-bold text-indigo-700")

                            def _refresh_ky_label():
                                ky_dang_cham_label.text = (
                                    f"Kỳ đang chấm: {tu_ngay_input.value} – {den_ngay_input.value}  "
                                    f"— kiểm tra đúng khoảng ngày này trước khi Truy vấn trên CITAD/PaymentHub"
                                )

                            ui.timer(1.0, _refresh_ky_label)

                            with ui.row().classes(
                                "w-full items-center gap-2 mx-4 mb-3 p-2 bg-indigo-50 "
                                "border border-indigo-200 rounded-lg"
                            ) as own_sessions_banner:
                                ui.icon("info").classes("text-indigo-600")
                                own_sessions_label = ui.label("").classes("text-sm text-indigo-800 flex-grow")
                                own_sessions_btn = ui.button("Tải bảng gần nhất", icon="cloud_download").props(
                                    "outline dense"
                                )
                            own_sessions_banner.set_visibility(False)

                            _own_sessions_state = {"checked_ky": None, "latest_session_id": None, "ky": None}

                            async def _do_load_latest_own_session():
                                sid = _own_sessions_state["latest_session_id"]
                                k = _own_sessions_state["ky"]
                                if sid is not None:
                                    await _load_session_by_id(sid, k)

                            own_sessions_btn.on_click(_do_load_latest_own_session)

                            async def _check_own_sessions_banner():
                                if view_state["session_id"] is not None:
                                    own_sessions_banner.set_visibility(False)
                                    return
                                tu, den = (tu_ngay_input.value or "").strip(), (den_ngay_input.value or "").strip()
                                if not tu or not den:
                                    own_sessions_banner.set_visibility(False)
                                    return
                                ky_now = f"{tu}-{den}"
                                # Tránh gọi API lặp lại mỗi giây khi ky không đổi — chỉ hỏi
                                # lại backend khi người dùng thực sự đổi ngày.
                                if ky_now == _own_sessions_state["checked_ky"]:
                                    return
                                _own_sessions_state["checked_ky"] = ky_now
                                try:
                                    rows = await asyncio.to_thread(
                                        api.get, "/api/doi-chieu-citad-nostro/reconciliation-days",
                                        params={"tu_ngay": tu, "den_ngay": den},
                                    )
                                except Exception:
                                    return
                                mine = [r for r in rows if r["ky"] == ky_now and r["created_by"] == current_staff_id]
                                if not mine:
                                    own_sessions_banner.set_visibility(False)
                                    return
                                mine.sort(key=lambda r: r["updated_at"] or "", reverse=True)
                                latest = mine[0]
                                _own_sessions_state["latest_session_id"] = latest["session_id"]
                                _own_sessions_state["ky"] = ky_now
                                own_sessions_label.text = (
                                    f"Bạn đã có {len(mine)} bảng cho kỳ này — bấm để lưu tiếp bảng gần "
                                    "nhất, hoặc cứ nhập mới để tạo bảng độc lập."
                                )
                                own_sessions_banner.set_visibility(True)

                            ui.timer(2.0, _check_own_sessions_banner)

                        with _section_card("Chênh lệch CITAD − HUB", icon="difference", accent="amber") as diff_card:
                            build_diff_grid(diff_card)

                        with _section_card("5 cổng CITAD — Tra cứu dữ liệu", icon="account_balance_wallet", accent="indigo") as citad_card:
                            build_citad_grid(citad_card)

                        with _section_card("PaymentHub — Lập bảng kê phí chia sẻ CITAD", icon="hub", accent="emerald") as hub_card:
                            build_hub_grid(hub_card)

                        with ui.row().classes("w-full justify-end gap-2"):
                            delete_btn = ui.button("Xoá bảng này", icon="delete", on_click=do_delete_session).props(
                                "outline color=negative"
                            ).classes("rounded-lg")
                            ui.button("Xuất Excel", icon="download", on_click=_do_download_export).props("outline").classes("rounded-lg")
                            save_btn = ui.button("Lưu đối chiếu", icon="save", on_click=do_save_session).classes(
                                "bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg"
                            )
                    recalc()
                    _refresh_delete_btn()

                with ui.tab_panel(tab_lich_su):
                    with _section_card("Lịch sử đối chiếu", icon="history", accent="blue"):
                        with ui.column().classes("w-full gap-2 p-4"):
                            _build_history_panel()

                with ui.tab_panel(tab_tong_hop_thang):
                    with _section_card("Tổng hợp tháng", icon="calendar_view_month", accent="amber"):
                        with ui.column().classes("w-full gap-2 p-4"):
                            ui.label(
                                "Cộng dồn số liệu của các bảng (kỳ) trong 1 tháng thành báo cáo tháng — "
                                "bạn tự tick chọn bảng nào tính vào tổng (bỏ tick bảng nào bị trùng ngày "
                                "với bảng khác). Danh sách hiện TẤT CẢ bảng của cả phòng cho tháng đó, "
                                "không riêng bảng của bạn."
                            ).classes("text-sm text-gray-500")
                            _build_month_summary_panel()

                with ui.tab_panel(tab_extension):
                    with _section_card("Kết nối Extension Chrome", icon="extension", accent="rose"):
                        with ui.column().classes("w-full gap-3 p-4"):
                            ui.label(
                                "Extension \"CITAD - PaymentHub N&V\" — gói RIÊNG của Phòng QLTK Nostro, "
                                "Vostro, không chung với Extension của Phòng Thanh toán. Cần tải, cài đặt "
                                "(Load unpacked) VÀ tạo mã kết nối RIÊNG cho Extension này — mã này độc lập "
                                "hoàn toàn với mã của Phòng Thanh toán, dùng song song cả 2 Extension không "
                                "ảnh hưởng gì đến nhau."
                            ).classes("text-sm text-gray-500")
                            token_status_label = ui.label("Đang kiểm tra...").classes("font-bold")
                            with ui.row().classes("gap-2"):
                                ui.button("Tạo mã kết nối mới", icon="vpn_key", on_click=do_create_extension_token).props("outline")
                                ui.button("Thu hồi mã", icon="link_off", on_click=do_revoke_extension_token).props("outline color=negative")
                                ui.button("Tải Extension (.zip)", icon="download", on_click=do_download_extension).props("outline")
                            ui.timer(0.1, refresh_extension_status, once=True)
