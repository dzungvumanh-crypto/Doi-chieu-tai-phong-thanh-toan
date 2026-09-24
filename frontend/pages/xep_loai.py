"""Xếp loại lao động — Phòng Tổng hợp.

Ba tab cấp 1:
- **Tổng quan** — ô số theo từng loại + danh sách gần đây.
- **Nhập xếp loại** — danh sách + Thêm/Sửa/Xoá + "Nhập từ Excel" (nhập lô, xem
  trước rồi mới ghi, theo yêu cầu người dùng "nhập thủ công hoặc insert file").
- **Tra cứu, thống kê** — 2 khu vực: bảng tổng hợp theo Trung tâm/phòng (pivot
  theo mức xếp loại) và tra cứu 5 năm liên tiếp của một cán bộ.

`loai` (Xếp loại lao động / Kết quả phiếu tín nhiệm / Xếp loại quý Cấp ủy) chỉ
hợp với một số `ky` nhất định và mỗi loại có thang `ket_qua` cố định riêng —
_KY_HOP_LE/_KET_QUA_THEO_LOAI phải khớp `backend/schemas/xep_loai.py`. Đổi một
bên mà quên bên kia là validate phía sau chặn giá trị phía trước vừa cho chọn.

Tông màu CAM (theo ảnh mẫu người dùng gửi: banner cam + thẻ dịch vụ trắng viền
cam) chỉ áp dụng cho phần nội dung trang này tự vẽ (banner, tab, khung lọc, nút,
thẻ) — không đổi `_page_header()`/`_sidebar()` dùng chung toàn hệ thống. Chip
`ket_qua` KHÔNG theo tông cam — giữ nguyên bảng màu ngữ nghĩa xanh lá/xanh
dương/vàng/đỏ (_MAU_KET_QUA) vì đó là tín hiệu xếp loại thật, đổi sang cam sẽ
làm mất luôn ý nghĩa "tốt/xấu" mà người xem cần thấy ngay.
"""
import asyncio
import datetime

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _content_area, _handle_api_error, _page_header, _require_auth, _sidebar

_LOAI_OPTS = {
    "lao_dong":  "Xếp loại lao động",
    "tin_nhiem": "Kết quả phiếu tín nhiệm",
    "cap_uy":    "Xếp loại quý — Cấp ủy",
}
_KY_LABEL = {"nam": "Năm", "quy": "Quý"}
_KY_HOP_LE = {"lao_dong": ["nam", "quy"], "tin_nhiem": ["nam"], "cap_uy": ["quy"]}
_QUY_OPTS = {1: "Quý 1", 2: "Quý 2", 3: "Quý 3", 4: "Quý 4"}

_MUC_LAO_DONG = ["Hoàn thành xuất sắc nhiệm vụ", "Hoàn thành tốt nhiệm vụ",
                 "Hoàn thành nhiệm vụ", "Không hoàn thành nhiệm vụ"]
_MUC_TIN_NHIEM = ["Tín nhiệm cao", "Tín nhiệm", "Tín nhiệm thấp"]
_KET_QUA_THEO_LOAI = {"lao_dong": _MUC_LAO_DONG, "tin_nhiem": _MUC_TIN_NHIEM, "cap_uy": _MUC_LAO_DONG}

# Chỉ hai loại xếp THEO NĂM mới tra cứu được liên tiếp nhiều năm — Cấp ủy chỉ
# có dữ liệu theo quý (backend/api/xep_loai.py::_ca_nhan_data chỉ đọc ky='nam').
_LOAI_5_NAM = {"lao_dong": "Xếp loại lao động", "tin_nhiem": "Kết quả phiếu tín nhiệm"}

_MAU_KET_QUA = {
    "Hoàn thành xuất sắc nhiệm vụ": "green", "Tín nhiệm cao": "green",
    "Hoàn thành tốt nhiệm vụ": "blue", "Tín nhiệm": "blue",
    "Hoàn thành nhiệm vụ": "amber", "Tín nhiệm thấp": "amber",
    "Không hoàn thành nhiệm vụ": "red",
}

# Nhãn chức danh, chức vụ KHÔNG khai ở đây — lấy từ `chuc_vu_opts` trong
# response của GET /api/xep-loai/stats/tong-quan (backend đọc từ
# backend.services.hr_service.NHAN_CHUC_VU, nguồn duy nhất của nhãn này). Nạp
# một lần lúc mở trang trong xep_loai_page(), truyền xuống _tab_nhap() — khai
# một bản riêng ở đây từng khiến 3 nơi (module Nhân sự, backend, frontend
# trang này) phải sửa tay đồng bộ mà không có gì báo khi lệch nhau (phát hiện
# qua review PR #120).
_NHOM_THEO_OPTS = {"phong": "Phòng ban", "chuc_vu": "Chức danh, chức vụ"}

# ── Nút — tông cam xuyên suốt trang (đặc/viền, không thêm hue thứ hai) ────────
_NUT_CHINH = "no-caps color=orange-8"     # Lưu / Thêm — hành động ghi dữ liệu
_NUT_LOC   = "no-caps outline color=orange-8"  # Lọc / Xem / Tra cứu / Excel


def _o(v):
    return v if v not in (None, "") else "—"


def _nam_hien_tai() -> int:
    return datetime.date.today().year


def _ky_text(r: dict) -> str:
    return f"Quý {r['quy']}/{r['nam']}" if r.get("quy") else str(r["nam"])


def _luoi_the():
    return ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 w-full")


def _khung_loc():
    # Viền đậm hơn (border-2 + màu cam đậm hơn) — theo yêu cầu người dùng
    # "đóng viền đậm khung lọc để phân biệt với phần dữ liệu ở dưới".
    return ui.card().classes(
        "w-full gap-3 p-4 mb-4 rounded-xl border-2 border-orange-300 shadow-sm bg-orange-50/60")


def _chip(ten: str, mau: str = "gray"):
    ui.label(ten).classes(
        f"text-xs font-bold text-white bg-{mau}-600 rounded-full px-2 py-0.5 inline-block w-fit")


def _the_ban_ghi():
    # Viền đậm hơn (border-2 + orange-200 quanh thẻ, orange-500 cạnh trên) —
    # theo yêu cầu người dùng, viền cũ (border 1px xám mặc định) nhìn quá mờ.
    return ui.card().classes(
        "w-full p-4 pr-2 gap-1 rounded-xl border-2 border-orange-200 "
        "border-t-4 border-t-orange-500 shadow-sm hover:shadow-md transition-shadow relative")


def _hero_banner():
    """Banner đầu trang — khuôn theo ảnh mẫu người dùng gửi (nền cam, tiêu đề +
    mô tả ngắn bên trái, icon tròn bên phải). Thuần trang trí, không phụ thuộc
    dữ liệu nên vẽ một lần, không cần nạp lại theo tab."""
    with ui.element("div").classes(
        "w-full rounded-2xl bg-gradient-to-r from-orange-600 to-orange-500 text-white "
        "px-6 py-6 mb-4 flex items-center justify-between gap-4 flex-wrap shadow-sm"):
        with ui.column().classes("gap-1"):
            ui.label("Xếp loại lao động — Phòng Tổng hợp").classes("text-xl font-bold")
            ui.label("Xếp loại lao động, kết quả phiếu tín nhiệm và xếp loại quý Cấp ủy "
                      "— nhập tay hoặc nhập lô từ Excel").classes("text-orange-50 text-sm")
        with ui.element("div").classes(
            "w-16 h-16 rounded-full bg-white/15 flex items-center justify-center shrink-0"):
            ui.icon("grade").classes("text-3xl text-white")


def _the_dich_vu(icon: str, so, nhan: str, noi_bat: bool = False):
    """Thẻ số liệu kiểu "dịch vụ" của ảnh mẫu — icon tròn trên đầu, số/nhãn ở
    dưới, nền trắng viền cam nhạt (thẻ nổi bật thì đảo nền cam/chữ trắng)."""
    with ui.element("div").classes(
        ("bg-orange-600" if noi_bat else "bg-white") +
        " flex-1 min-w-[10rem] rounded-xl shadow-sm border border-orange-100 "
        "flex flex-col items-center justify-center gap-2 py-5 px-3"):
        with ui.element("div").classes(
            ("bg-white/20" if noi_bat else "bg-orange-50") +
            " w-12 h-12 rounded-full flex items-center justify-center"):
            ui.icon(icon).classes(("text-white" if noi_bat else "text-orange-600") + " text-2xl")
        ui.label(str(so)).classes(
            ("text-white" if noi_bat else "text-gray-800") + " text-2xl font-bold leading-none")
        ui.label(nhan).classes(
            ("text-orange-50" if noi_bat else "text-gray-500") + " text-xs text-center")


async def _xac_nhan_xoa(mo_ta: str) -> bool:
    with ui.dialog() as hoi, ui.card():
        ui.label(f"Xoá {mo_ta}?").classes("font-semibold")
        with ui.row().classes("justify-end gap-2 w-full mt-2"):
            ui.button("Huỷ", on_click=lambda: hoi.submit(False)).props("flat no-caps")
            ui.button("Xoá", on_click=lambda: hoi.submit(True)).props("no-caps color=negative")
    return bool(await hoi)


def _tuy_chinh_theo_loai(loai: str, o_ky, o_ket_qua, o_quy, giu_gia_tri: bool = False):
    """Bó hẹp lựa chọn `ky`/`ket_qua` theo đúng `loai` — gọi lại mỗi khi đổi
    loại xếp loại, và một lần lúc dựng dialog để khớp giá trị ban đầu.

    `ket_qua` KHÔNG được tự chọn phần tử đầu danh sách khi không giữ giá trị
    cũ — phần tử đầu của mọi thang trong _KET_QUA_THEO_LOAI luôn là mức TỐT
    NHẤT ("Hoàn thành xuất sắc..."/"Tín nhiệm cao"). Nếu ở đây mặc định chọn
    sẵn, người nhập thêm mới hoặc vừa đổi loại xếp loại mà không để ý ô này sẽ
    vô tình lưu nhầm mức tốt nhất cho một bản ghi chưa hề được đánh giá — sai
    lệch dữ liệu nhân sự thật mà không có lỗi nào báo. Để trống bắt buộc người
    nhập tự chọn (chặn ở `luu()` nếu bỏ trống)."""
    ky_hop_le = _KY_HOP_LE[loai]
    ky_gia_tri = o_ky.value if (giu_gia_tri and o_ky.value in ky_hop_le) else ky_hop_le[0]
    o_ky.set_options({k: _KY_LABEL[k] for k in ky_hop_le}, value=ky_gia_tri)

    muc = _KET_QUA_THEO_LOAI[loai]
    ket_qua_gia_tri = o_ket_qua.value if (giu_gia_tri and o_ket_qua.value in muc) else None
    o_ket_qua.set_options(muc, value=ket_qua_gia_tri)

    o_quy.set_visibility(o_ky.value == "quy")


# ── Tab 0: Tổng quan ──────────────────────────────────────────────────────────
async def _tab_tong_quan():
    khung = ui.column().classes("w-full gap-4")

    async def tai():
        try:
            # Đếm + 8 dòng gần nhất tính sẵn ở server (/stats/tong-quan) — không
            # kéo nguyên bảng về đây rồi đếm bằng Python nữa (phát hiện qua
            # review PR #120: vài trăm cán bộ × nhiều kỳ/năm là hàng nghìn dòng
            # mỗi năm, mở trang sẽ chậm dần theo thời gian).
            data = await asyncio.to_thread(api.get, "/api/xep-loai/stats/tong-quan")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            data = {"dem": {k: 0 for k in _LOAI_OPTS}, "gan_day": []}

        dem = data["dem"]
        gan_day = data["gan_day"]
        tong_so = sum(dem.values())

        icon_theo_loai = {"lao_dong": "workspace_premium", "tin_nhiem": "how_to_vote", "cap_uy": "groups"}

        khung.clear()
        with khung:
            with ui.row().classes("w-full gap-3 flex-wrap"):
                for k, ten in _LOAI_OPTS.items():
                    _the_dich_vu(icon_theo_loai[k], dem[k], ten)
                _the_dich_vu("summarize", tong_so, "Tổng cộng", noi_bat=True)

            with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden"):
                with ui.row().classes("w-full bg-orange-50 px-4 py-3 border-b border-orange-100"):
                    ui.label("Cập nhật gần đây").classes("font-semibold text-orange-900")
                with ui.column().classes("w-full p-3 gap-2"):
                    if not gan_day:
                        ui.label("Chưa có dữ liệu").classes("text-xs text-gray-500 px-1")
                    for r in gan_day:
                        with ui.row().classes(
                            "w-full items-center gap-2 border-b border-gray-100 pb-2 last:border-0"):
                            ui.icon("grade").classes("text-orange-600 text-lg")
                            with ui.column().classes("gap-0 flex-1 min-w-0"):
                                ui.label(f"{r['staff_name'] or '—'} — {_LOAI_OPTS[r['loai']]}").classes(
                                    "text-sm font-medium truncate")
                                ui.label(r["ket_qua"]).classes("text-xs text-gray-500 truncate")
                            ui.label(_ky_text(r)).classes(
                                "text-xs font-semibold text-orange-700 bg-orange-50 rounded-full px-2 py-0.5")

    await tai()
    return tai


# ── Tab 1: Nhập xếp loại ──────────────────────────────────────────────────────
def _mo_nhap_excel(tai_lai):
    state = {"bytes": None, "name": None}

    with ui.dialog() as hop, ui.card().classes("w-full max-w-lg"):
        ui.label("Nhập xếp loại lao động từ Excel").classes("text-lg font-bold")
        ui.label("Tải file mẫu, điền dữ liệu theo đúng tên cột rồi tải lên lại."
                  ).classes("text-sm text-gray-600")

        async def tai_mau():
            try:
                raw = await asyncio.to_thread(api.download, "/api/xep-loai/import-template")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            ui.download(raw, "mau_xep_loai_lao_dong.xlsx")

        ui.button("Tải file mẫu", icon="description", on_click=tai_mau).props("flat no-caps")

        ket_qua = ui.column().classes("w-full")

        def nhan_tep(e):
            state["bytes"] = e.content.read()
            state["name"] = e.name
            ket_qua.clear()

        ui.upload(label="Chọn file Excel đã điền", auto_upload=True, on_upload=nhan_tep
                  ).props('accept=".xlsx,.xlsm" flat').classes("w-full")

        async def goi(dry_run: bool):
            if not state["bytes"]:
                ui.notify("Chọn file trước", type="warning")
                return
            try:
                kq = await asyncio.to_thread(
                    api.post_upload,
                    f"/api/xep-loai/import?dry_run={'true' if dry_run else 'false'}",
                    {"file": (state["name"], state["bytes"], "application/octet-stream")})
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            ket_qua.clear()
            with ket_qua:
                ui.label(f"Tổng {kq['tong_dong']} dòng dữ liệu — "
                         f"{'sẽ thêm' if dry_run else 'đã thêm'} {kq['da_them']}, "
                         f"lỗi {len(kq['loi'])}.").classes("text-sm font-medium")
                for l in kq["loi"][:10]:
                    ui.label(f"Dòng {l['dong']}: {l['ly_do']}").classes("text-xs text-red-700")
                if len(kq["loi"]) > 10:
                    ui.label(f"… và {len(kq['loi']) - 10} lỗi khác").classes("text-xs text-gray-500")
            if not dry_run and kq["da_them"]:
                ui.notify(f"Đã thêm {kq['da_them']} dòng", type="positive")
                await tai_lai()

        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("Đóng", on_click=hop.close).props("flat no-caps")
            ui.button("Xem trước", icon="preview", on_click=lambda: goi(True)).props(_NUT_LOC)
            ui.button("Nhập vào hệ thống", icon="upload", on_click=lambda: goi(False)
                      ).props(_NUT_CHINH)
    hop.open()


async def _tab_nhap(dept_opts: dict, staff_opts: dict, chuc_vu_opts: dict, can_manage: bool):
    ban_ghi: dict = {}

    def ve(rows: list):
        khung.clear()
        with khung:
            if not rows:
                ui.label("Chưa có bản ghi xếp loại nào khớp bộ lọc."
                          ).classes("text-gray-500 py-6 text-center w-full")
                return
            with _luoi_the():
                for r in rows:
                    with _the_ban_ghi():
                        if can_manage:
                            with ui.row().classes("absolute top-2 right-2 gap-0.5 z-10"):
                                ui.button(icon="edit", on_click=lambda rid=r["id"]: mo_form(ban_ghi[rid])
                                          ).props("dense flat round size=sm color=orange-8")
                                ui.button(icon="delete", on_click=lambda rid=r["id"]: xoa(rid)
                                          ).props("dense flat round size=sm color=negative")
                        with ui.column().classes("gap-1" + (" pr-16" if can_manage else "")):
                            with ui.row().classes("items-center gap-2"):
                                _chip(_ky_text(r), mau="orange")
                                _chip(_LOAI_OPTS[r["loai"]], mau="gray")
                            ui.label(r["staff_name"] or "—").classes("text-sm font-medium text-gray-700")
                            ui.label(f"{r['department_name']} — {r['chuc_vu_ten']}").classes(
                                "text-xs text-gray-500")
                            _chip(r["ket_qua"], mau=_MAU_KET_QUA.get(r["ket_qua"], "gray"))
                            if r.get("ghi_chu"):
                                ui.label(r["ghi_chu"]).classes("text-xs text-gray-400")

    async def tai():
        params = {}
        if f_staff.value:
            params["staff_id"] = int(f_staff.value)
        if f_dept.value:
            params["department_id"] = int(f_dept.value)
        if f_chuc_vu.value:
            params["chuc_vu"] = f_chuc_vu.value
        if f_loai.value:
            params["loai"] = f_loai.value
        if f_ky.value:
            params["ky"] = f_ky.value
        if f_nam.value:
            params["nam"] = int(f_nam.value)
        if f_ky.value == "quy" and f_quy.value:
            params["quy"] = int(f_quy.value)
        try:
            rows = await asyncio.to_thread(api.get, "/api/xep-loai", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ban_ghi.clear()
        ban_ghi.update({r["id"]: r for r in rows})
        ve(rows)

    async def xoa(rid: int):
        if not await _xac_nhan_xoa("bản ghi xếp loại này"):
            return
        try:
            await asyncio.to_thread(api.delete, f"/api/xep-loai/{rid}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.notify("Đã xoá", type="positive")
        await tai()

    def mo_form(item: dict | None):
        with ui.dialog() as hop, ui.card().classes("w-full max-w-xl"):
            ui.label(("Sửa" if item else "Thêm") + " xếp loại lao động").classes("text-lg font-bold")
            with ui.grid(columns=2).classes("w-full gap-3"):
                # Sửa bản ghi cũ thì KHOÁ cán bộ, không cho đổi người — xếp
                # loại là dữ liệu lịch sử (xem comment ở active_only=False phía
                # dưới), đổi sang người khác coi như gán nhầm lịch sử của người
                # cũ cho người mới. `staff_opts` không chứa cán bộ đã xoá mềm
                # (staff.py::list_staff loại cứng is_deleted, không phụ thuộc
                # active_only) nên phải tự thêm tạm 1 mục hiển thị đúng tên,
                # không thì ô chọn hiện trống dù đã khoá.
                staff_id_str = str(item["staff_id"]) if item else None
                o_staff_opts = staff_opts
                if item and staff_id_str not in staff_opts:
                    o_staff_opts = {**staff_opts, staff_id_str: item.get("staff_name") or "—"}
                o_staff = ui.select(o_staff_opts, label="Cán bộ", with_input=True,
                                     value=staff_id_str
                                     ).classes("col-span-2 w-full").props("outlined dense")
                if item:
                    o_staff.props("disable")
                o_loai = ui.select(_LOAI_OPTS, label="Loại xếp loại",
                                    value=(item or {}).get("loai") or "lao_dong"
                                    ).classes("col-span-2 w-full").props("outlined dense")
                o_nam = ui.number(label="Năm", value=(item or {}).get("nam") or _nam_hien_tai(),
                                   min=2000, max=2100, format="%d").props("outlined dense")
                o_ky = ui.select({}, label="Kỳ").props("outlined dense")
                o_quy = ui.select(_QUY_OPTS, label="Quý", value=(item or {}).get("quy")
                                   ).props("outlined dense")
                o_ket_qua = ui.select([], label="Kết quả"
                                       ).classes("col-span-2 w-full").props("outlined dense")
            o_ghi_chu = ui.textarea("Ghi chú", value=(item or {}).get("ghi_chu") or ""
                                     ).classes("w-full").props("outlined dense")

            if item:
                o_ky.value = item["ky"]
                o_ket_qua.value = item["ket_qua"]
            _tuy_chinh_theo_loai(o_loai.value, o_ky, o_ket_qua, o_quy, giu_gia_tri=bool(item))
            o_loai.on_value_change(lambda: _tuy_chinh_theo_loai(o_loai.value, o_ky, o_ket_qua, o_quy))
            o_ky.on_value_change(lambda: o_quy.set_visibility(o_ky.value == "quy"))

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Đóng", on_click=hop.close).props("flat no-caps")

                async def luu():
                    if not o_staff.value:
                        ui.notify("Chọn cán bộ", type="warning")
                        return
                    if not o_ket_qua.value:
                        ui.notify("Chọn kết quả", type="warning")
                        return
                    body = {
                        "staff_id": int(o_staff.value),
                        "loai": o_loai.value,
                        "ky": o_ky.value,
                        "nam": int(o_nam.value),
                        "quy": int(o_quy.value) if o_ky.value == "quy" and o_quy.value else None,
                        "ket_qua": o_ket_qua.value,
                        "ghi_chu": o_ghi_chu.value or None,
                    }
                    path = f"/api/xep-loai/{item['id']}" if item else "/api/xep-loai"
                    goi = api.put if item else api.post
                    try:
                        await asyncio.to_thread(goi, path, body)
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(str(e), type="negative")
                        return
                    hop.close()
                    ui.notify("Đã lưu", type="positive")
                    await tai()

                if can_manage:
                    ui.button("Lưu", icon="save", on_click=luu).props(_NUT_CHINH)
        hop.open()

    async def xoa_loc():
        f_staff.value = None
        f_dept.value = None
        f_chuc_vu.value = None
        f_loai.value = None
        f_ky.value = None
        f_nam.value = None
        f_quy.value = None
        await tai()

    with _khung_loc():
        # Lưới cột đều nhau (không dùng width cố định riêng lẻ từng ô) — trước
        # đây mỗi ô một width khác nhau (w-40/w-56) khiến hàng 2 lệch hàng 1, và
        # ô "Chức danh, chức vụ" hẹp hơn nội dung "Tất cả chức danh, chức vụ"
        # nên chữ vỡ dòng (theo phản hồi người dùng).
        with ui.element("div").classes(
            "grid grid-cols-2 sm:grid-cols-4 gap-3 w-full"):
            f_staff = ui.select({None: "Tất cả cán bộ", **staff_opts}, label="Cán bộ",
                                 with_input=True, value=None).classes("w-full").props("outlined dense")
            f_dept = ui.select({None: "Tất cả phòng", **dept_opts}, label="Phòng",
                                with_input=True, value=None).classes("w-full").props("outlined dense")
            f_chuc_vu = ui.select({None: "Tất cả chức vụ", **chuc_vu_opts},
                                   label="Chức danh, chức vụ", value=None
                                   ).classes("w-full").props("outlined dense")
            f_loai = ui.select({None: "Tất cả loại", **_LOAI_OPTS}, label="Loại xếp loại",
                                value=None).classes("w-full").props("outlined dense")
            f_ky = ui.select({None: "Tất cả kỳ", **_KY_LABEL}, label="Kỳ", value=None
                              ).classes("w-full").props("outlined dense")
            f_nam = ui.number(label="Năm (để trống = tất cả)", format="%d", min=2000, max=2100,
                               value=_nam_hien_tai()).classes("w-full").props("outlined dense")
            f_quy = ui.select({None: "Tất cả quý", **_QUY_OPTS}, label="Quý", value=None
                               ).classes("w-full").props("outlined dense")
        with ui.row().classes("w-full items-center gap-2 flex-wrap mt-3"):
            ui.button("Lọc", icon="search", on_click=lambda: tai()).props(_NUT_LOC)
            ui.button("Xoá lọc", icon="filter_alt_off", on_click=lambda: xoa_loc()).props(
                "no-caps flat")
            if can_manage:
                ui.button("Thêm xếp loại", icon="add", on_click=lambda: mo_form(None)
                          ).props(_NUT_CHINH)
                ui.button("Nhập từ Excel", icon="upload_file", on_click=lambda: _mo_nhap_excel(tai)
                          ).props(_NUT_LOC)

    khung = ui.column().classes("w-full")
    await tai()


# ── Tab 2, khu vực 1: Bảng tổng hợp theo Trung tâm/phòng ─────────────────────
async def _tab_tong_hop(co_export: bool):
    async def tai():
        if not f_nam.value:
            ui.notify("Nhập năm", type="warning")
            return
        params = {"loai": f_loai.value, "nam": int(f_nam.value), "ky": f_ky.value,
                  "nhom_theo": f_nhom.value}
        if f_ky.value == "quy":
            if not f_quy.value:
                ui.notify("Chọn quý", type="warning")
                return
            params["quy"] = int(f_quy.value)
        try:
            data = await asyncio.to_thread(api.get, "/api/xep-loai/stats/tong-hop", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return

        ten_cot_nhom = _NHOM_THEO_OPTS[f_nhom.value]
        columns = [{"name": "nhom", "label": ten_cot_nhom, "field": "nhom", "align": "left"}]
        for i, cat in enumerate(data["categories"]):
            columns.append({"name": f"c{i}", "label": cat, "field": f"c{i}", "align": "center"})
        columns.append({"name": "total", "label": "Tổng", "field": "total", "align": "center"})

        table_rows = []
        for r in data["rows"]:
            row = {"nhom": r["nhom"], "total": r["total"]}
            row.update({f"c{i}": r["counts"].get(cat, 0) for i, cat in enumerate(data["categories"])})
            table_rows.append(row)
        trow = {"nhom": "TỔNG CỘNG", "total": data["tong"]["total"]}
        trow.update({f"c{i}": data["tong"]["counts"].get(cat, 0)
                     for i, cat in enumerate(data["categories"])})
        table_rows.append(trow)

        khung.clear()
        with khung:
            # So tong["total"], KHÔNG phải rows rỗng — _tong_hop_data() liệt kê
            # sẵn mọi phòng/chức vụ với đếm 0 nên rows không bao giờ rỗng, điều
            # kiện cũ là mã chết và hiện bảng toàn số 0 thay vì báo "chưa có
            # dữ liệu" (phát hiện qua review PR #120).
            if not data["tong"]["total"]:
                ui.label("Không có dữ liệu cho kỳ đã chọn.").classes(
                    "text-gray-500 py-6 text-center w-full")
                return
            ui.table(columns=columns, rows=table_rows, row_key="nhom").classes("w-full")

    async def xuat():
        if not f_nam.value:
            ui.notify("Nhập năm", type="warning")
            return
        params = {"loai": f_loai.value, "nam": int(f_nam.value), "ky": f_ky.value,
                  "nhom_theo": f_nhom.value}
        if f_ky.value == "quy":
            if not f_quy.value:
                ui.notify("Chọn quý", type="warning")
                return
            params["quy"] = int(f_quy.value)
        try:
            raw = await asyncio.to_thread(api.download, "/api/xep-loai/export/tong-hop", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.download(raw, f"tong_hop_xep_loai_{f_nhom.value}_{f_loai.value}_{int(f_nam.value)}.xlsx")

    def _doi_loai():
        ky_hop_le = _KY_HOP_LE[f_loai.value]
        f_ky.set_options({k: _KY_LABEL[k] for k in ky_hop_le}, value=ky_hop_le[0])
        f_quy.set_visibility(f_ky.value == "quy")

    with _khung_loc():
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_loai = ui.select(_LOAI_OPTS, label="Loại xếp loại", value="lao_dong"
                                ).classes("w-56").props("outlined dense")
            f_nhom = ui.select(_NHOM_THEO_OPTS, label="Nhóm theo", value="phong"
                                ).classes("w-56").props("outlined dense")
            f_nam = ui.number(label="Năm", value=_nam_hien_tai(), min=2000, max=2100, format="%d"
                               ).classes("w-40").props("outlined dense")
            f_ky = ui.select(_KY_LABEL, label="Kỳ").classes("w-40").props("outlined dense")
            f_quy = ui.select(_QUY_OPTS, label="Quý").classes("w-40").props("outlined dense")
            ui.button("Xem", icon="search", on_click=lambda: tai()).props(_NUT_CHINH)
            if co_export:
                ui.button("Xuất Excel", icon="download", on_click=xuat).props(_NUT_LOC)
        f_loai.on_value_change(lambda: _doi_loai())
        f_ky.on_value_change(lambda: f_quy.set_visibility(f_ky.value == "quy"))

    _doi_loai()
    khung = ui.column().classes("w-full")
    await tai()
    return tai


# ── Tab 2, khu vực 2: Tra cứu 5 năm liên tiếp của cán bộ ─────────────────────
async def _tab_ca_nhan_tra_cuu(staff_opts: dict, co_export: bool):
    async def tra_cuu():
        if not f_staff.value:
            ui.notify("Chọn cán bộ", type="warning")
            return
        params = {"staff_id": int(f_staff.value), "loai": f_loai.value}
        if f_den_nam.value:
            params["den_nam"] = int(f_den_nam.value)
        try:
            data = await asyncio.to_thread(api.get, "/api/xep-loai/stats/ca-nhan", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return

        khung.clear()
        with khung:
            ui.label(f"{data['staff_name']} — {_LOAI_OPTS[data['loai']]} "
                      f"({data['tu_nam']}-{data['den_nam']})").classes("font-semibold text-gray-800 mb-2")
            with _luoi_the():
                for r in data["nam_theo_thu_tu"]:
                    with _the_ban_ghi():
                        _chip(str(r["nam"]), mau="orange")
                        if r["ket_qua"]:
                            _chip(r["ket_qua"], mau=_MAU_KET_QUA.get(r["ket_qua"], "gray"))
                            if r.get("ghi_chu"):
                                ui.label(r["ghi_chu"]).classes("text-xs text-gray-400")
                        else:
                            ui.label("Chưa có dữ liệu").classes("text-sm text-gray-400 italic")

    async def xuat():
        if not f_staff.value:
            ui.notify("Chọn cán bộ", type="warning")
            return
        params = {"staff_id": int(f_staff.value), "loai": f_loai.value}
        if f_den_nam.value:
            params["den_nam"] = int(f_den_nam.value)
        try:
            raw = await asyncio.to_thread(api.download, "/api/xep-loai/export/ca-nhan", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.download(raw, "xep_loai_ca_nhan.xlsx")

    with _khung_loc():
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_staff = ui.select(staff_opts, label="Cán bộ", with_input=True
                                 ).classes("w-64").props("outlined dense")
            f_loai = ui.select(_LOAI_5_NAM, label="Loại xếp loại", value="lao_dong"
                                ).classes("w-56").props("outlined dense")
            f_den_nam = ui.number(label="Đến năm", value=_nam_hien_tai(), min=2000, max=2100,
                                   format="%d").classes("w-32").props("outlined dense")
            ui.button("Tra cứu", icon="search", on_click=lambda: tra_cuu()).props(_NUT_CHINH)
            if co_export:
                ui.button("Xuất Excel", icon="download", on_click=xuat).props(_NUT_LOC)

    khung = ui.column().classes("w-full")
    with khung:
        ui.label("Chọn cán bộ rồi bấm Tra cứu.").classes("text-gray-500 py-6 text-center w-full")


# ── Trang chính ───────────────────────────────────────────────────────────────
@ui.page("/xep_loai")
async def xep_loai_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.xep_loai"):
        ui.navigate.to("/home")
        return

    try:
        depts, staff_list = await asyncio.gather(
            asyncio.to_thread(api.get, "/api/departments/"),
            # active_only=False — bản xếp loại là dữ liệu LỊCH SỬ, người đã nghỉ/
            # bị khoá tài khoản vẫn cần tra cứu được ("5 năm liên tiếp" mới đúng
            # lúc cần tìm cả người cũ) và cần hiện đúng tên khi sửa bản ghi cũ của
            # họ — active_only=True trước đây làm dropdown "Cán bộ" trống trơn ở
            # cả hai trường hợp mà không báo lỗi gì.
            asyncio.to_thread(api.get, "/api/staff/", {"active_only": False}),
        )
    except Exception as e:
        if _handle_api_error(e):
            return
        ui.notify(str(e), type="negative")
        return

    # Chỉ cần chuc_vu_opts ở đây (nhãn tĩnh, nạp 1 lần) — dem/gan_day tab Tổng
    # quan tự tải riêng vì cần làm mới mỗi lần quay lại tab đó. Tách riêng try
    # để lỗi ở lệnh gọi này (vd. DB bận) chỉ làm ô lọc "Chức danh, chức vụ"
    # thiếu nhãn, không kéo sập cả trang vốn không cần dữ liệu này để mở.
    try:
        tong_quan = await asyncio.to_thread(api.get, "/api/xep-loai/stats/tong-quan")
        chuc_vu_opts = tong_quan["chuc_vu_opts"]
    except Exception as e:
        if _handle_api_error(e):
            return
        chuc_vu_opts = {}

    dept_name_by_id = {d["id"]: d["name"] for d in depts}
    dept_opts = dict(dept_name_by_id)
    staff_opts = {
        str(p["id"]): (p["full_name"]
                        + (f" — {dept_name_by_id[p['department_id']]}"
                           if p.get("department_id") in dept_name_by_id else "")
                        + ("" if p.get("is_active", True) else " (đã nghỉ/khoá)"))
        for p in staff_list if p.get("role") not in ("admin", "admin_l2")
    }

    can_manage = api.has_feature("xep_loai.manage")
    can_export = api.has_feature("xep_loai.export")

    with ui.row().classes("w-full"):
        await _sidebar("xep_loai")
        with _content_area():
            _page_header("Xếp loại lao động",
                         "Xếp loại lao động, kết quả phiếu tín nhiệm và xếp loại quý Cấp ủy")
            _hero_banner()

            with ui.tabs().props("active-color=orange-8 indicator-color=orange-8").classes("mb-3") as tabs:
                tab_tongquan = ui.tab("tongquan", label="Tổng quan", icon="dashboard")
                tab_nhap     = ui.tab("nhap",     label="Nhập xếp loại", icon="edit_note")
                tab_tracuu   = ui.tab("tracuu",   label="Tra cứu, thống kê", icon="query_stats")

            with ui.tab_panels(tabs, value=tab_tongquan).classes("w-full"):
                with ui.tab_panel(tab_tongquan):
                    tai_tong_quan = await _tab_tong_quan()

                with ui.tab_panel(tab_nhap):
                    await _tab_nhap(dept_opts, staff_opts, chuc_vu_opts, can_manage)

                with ui.tab_panel(tab_tracuu):
                    ui.label("Bảng tổng hợp theo Trung tâm/phòng").classes(
                        "text-lg font-bold text-gray-800 mb-2")
                    tai_tong_hop = await _tab_tong_hop(can_export)
                    ui.separator().classes("my-6")
                    ui.label("Tra cứu nhiều năm liên tiếp của cán bộ").classes(
                        "text-lg font-bold text-gray-800 mb-2")
                    await _tab_ca_nhan_tra_cuu(staff_opts, can_export)

            async def _khi_doi_tab(e):
                if e.value == "tongquan":
                    await tai_tong_quan()
                elif e.value == "tracuu":
                    await tai_tong_hop()

            tabs.on_value_change(_khi_doi_tab)
