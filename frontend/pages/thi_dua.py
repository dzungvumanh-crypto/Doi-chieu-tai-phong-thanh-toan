"""Thi đua khen thưởng — Phòng Tổng hợp.

4 tab cấp 1 (bản đầu 6 tab → gộp còn 3 theo yêu cầu "nhiều tab quá, cho gọn
lại" → tách "Thông tin" thành 2 theo yêu cầu "chia ra 1 tab cá nhân, 1 tab
đơn vị"). "Cá nhân"/"Tra cứu, thống kê" chứa nhiều khu vực xếp dọc, cuộn
trong cùng một tab (`_section_title()` vẽ tiêu đề từng khu vực):

- **Tổng quan** (mặc định khi mở trang) — ô số + danh sách "gần đây", khuôn tile
  màu của trang chủ (`dashboard.py`).
- **Đơn vị** — 1 khu vực: danh hiệu đơn vị (toàn Trung tâm / từng phòng), có
  nút "Nhập từ Excel" (nhập lô, xem trước rồi mới ghi) cho đơn vị đang theo
  dõi thủ công bằng Excel trước khi có hệ thống.
- **Cá nhân** — 2 khu vực: danh hiệu cá nhân theo cấp (Đảng / chuyên môn /
  công đoàn), sáng kiến cá nhân kèm file quyết định — cả hai cũng có nút
  "Nhập từ Excel" như trên.
- **Tra cứu, thống kê** — 2 khu vực: bảng tổng hợp danh hiệu đơn vị/cá nhân
  theo năm, bảng tổng hợp sáng kiến theo cá nhân.

Mọi danh sách hiển thị dạng LƯỚI THẺ (card grid), không dùng `ui.table` — theo
yêu cầu người dùng ("chỉ muốn kiểu bố cục card lưới thay cho bảng"), xem
`_luoi_the()`/`_the_ban_ghi()`. Tông màu chủ đạo của riêng module này là CAM
(đổi từ xanh lá cũ ngày 2026-09-18, theo yêu cầu người dùng "cho giống trang
Xếp loại lao động" — xem `frontend/pages/xep_loai.py` cho khuôn gốc: banner
cam đầu trang, thẻ "dịch vụ" icon tròn cam ở tab Tổng quan, nút đặc/nhạt cùng
một tông cam) — chỉ áp dụng cho nội dung tự vẽ trong trang này (banner, tab,
thẻ, nút, tiêu đề khu vực); không đổi `_page_header()`/`_sidebar()` dùng chung
toàn hệ thống (vẫn đỏ, vì đó là theme chung của mọi trang khác).

Mỗi khu vực có 2 tầng lọc: bộ lọc SERVER-SIDE cũ (Năm/Cán bộ — nút "Lọc" gọi
lại API) và bộ lọc CLIENT-SIDE mới (Đơn vị/Cấp/Loại + ô Tìm kiếm tự do — lọc
tức thời trên dữ liệu đã tải, không gọi lại API) theo yêu cầu người dùng
("thêm bộ lọc search theo các tiêu chí"). Khuôn: mỗi khu vực giữ `du_lieu`
(snapshot đầy đủ lần tải gần nhất) + `ve_lai()` (lọc `du_lieu` rồi vẽ lại lưới
thẻ) — `tai()` giờ chỉ gọi API rồi gọi `ve_lai()`; ô lọc mới gắn
`on_value_change=lambda: ve_lai()`.
"""
import asyncio
import contextlib
import datetime

from nicegui import ui

import frontend.api_client as api
from frontend.shared import (
    _content_area, _dmy, _handle_api_error, _iso_tu_dmy, _o_chon_ngay,
    _page_header, _require_auth, _sidebar,
)

TOAN_TRUNG_TAM = "Toàn Trung tâm"
_CAP_OPTS = {"dang": "Đảng", "chuyen_mon": "Chuyên môn", "cong_doan": "Công đoàn"}

# ── Màu — riêng module này, không đụng theme chung ───────────────────────────
# Nút của NiceGUI tự gắn sẵn "bg-primary" (mặc định #5898D4, cả dự án chưa gọi
# ui.colors() để đổi) — lớp đó nằm SAU trong stylesheet nên thắng mọi lớp
# Tailwind bg-* tự khai cùng cấp cụ thể (đã kiểm bằng getComputedStyle, thấy
# y hệt ở nút "Tạo báo cáo" của th_reports.py vốn đã có sẵn, không phải lỗi
# trang này). Muốn nút thật sự đổi màu phải dùng prop `color=` của Quasar
# (cơ chế màu riêng của component, không phải class CSS ngoài).
_MAU_LOC = "color=orange-6"
_MAU_LUU = "color=orange-8"
_MAU_EXCEL = "color=orange-9"
# Toàn bộ ô nhập/lọc trong trang này dùng chung khung viền bo tròn (theo yêu
# cầu người dùng "đóng ô vào viền bo tròn") thay vì kiểu gạch chân mặc định
# của Quasar.
_O_NHAP = "outlined dense rounded"


def _o(v):
    return v if v not in (None, "") else "—"


def _section_title(ten: str, icon: str):
    """Tiêu đề một khu vực cuộn trong tab gộp (Thông tin / Tra cứu, thống kê)."""
    with ui.row().classes("items-center gap-2 mb-3"):
        ui.icon(icon).classes("text-orange-800 text-xl")
        ui.label(ten).classes("text-lg font-bold text-orange-900")


def _luoi_the():
    """Container lưới thẻ đáp ứng theo bề rộng màn hình — 1 cột trên điện
    thoại, 2 cột màn vừa, 3 cột màn rộng."""
    return ui.element("div").classes("grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 w-full")


def _khung_loc():
    """Khung bọc các hàng bộ lọc — tách biệt trực quan khỏi lưới thẻ bên dưới
    (yêu cầu người dùng: "đóng khung riêng cho các bộ lọc"). Nền cam rất
    nhạt (không trùng nền trắng của `_the_ban_ghi()`) để mắt phân biệt ngay
    đâu là vùng lọc, đâu là vùng dữ liệu."""
    return ui.card().classes(
        "w-full gap-3 p-4 mb-4 rounded-xl border border-orange-100 shadow-sm bg-orange-50/60")


@contextlib.contextmanager
def _the_ban_ghi(on_edit=None, on_del=None, on_file=None, has_file: bool = False):
    """Một thẻ trong lưới — dải nút Sửa/Xoá/Tải file nổi góc trên bên phải,
    nội dung bên trong do nơi gọi tự vẽ (dùng `with _the_ban_ghi(...): ...`).

    `on_edit`/`on_del`/`on_file` là handler 0 tham số (dùng khuôn tham số mặc
    định `lambda x=gia_tri: ...` để khoá giá trị đúng lúc lặp — NiceGUI xem
    tham số có default là KHÔNG bắt buộc nên gọi handler không kèm đối số sự
    kiện, xem `nicegui/events.py::handle_event()`)."""
    co_nut = bool(on_file or on_edit or on_del)
    with ui.card().classes(
        "w-full p-4 pr-2 gap-1 rounded-xl border border-t-4 border-t-orange-400 shadow-sm "
        "hover:shadow-md transition-shadow relative"
    ) as the:
        if co_nut:
            with ui.row().classes("absolute top-2 right-2 gap-0.5 z-10"):
                if on_file and has_file:
                    ui.button(icon="download", on_click=on_file).props(
                        f"dense flat round size=sm {_MAU_EXCEL}")
                if on_edit:
                    ui.button(icon="edit", on_click=on_edit).props(
                        f"dense flat round size=sm {_MAU_LUU}")
                if on_del:
                    ui.button(icon="delete", on_click=on_del).props(
                        "dense flat round size=sm color=negative")
        with ui.column().classes("gap-1" + (" pr-16" if co_nut else "")):
            yield the


def _chip(ten: str, mau: str = "orange"):
    ui.label(ten).classes(
        f"text-xs font-bold text-white bg-{mau}-700 rounded-full px-2 py-0.5 inline-block w-fit")


async def _xac_nhan_xoa(mo_ta: str) -> bool:
    with ui.dialog() as hoi, ui.card():
        ui.label(f"Xoá {mo_ta}?").classes("font-semibold")
        with ui.row().classes("justify-end gap-2 w-full mt-2"):
            ui.button("Huỷ", on_click=lambda: hoi.submit(False)).props("flat no-caps")
            ui.button("Xoá", on_click=lambda: hoi.submit(True)).props("no-caps color=negative")
    return bool(await hoi)


def _nam_hien_tai() -> int:
    return datetime.date.today().year


def _mo_nhap_excel(ten: str, duong_dan: str, tai_lai):
    """Dialog nhập lô từ Excel dùng chung cho 3 khu vực nhập liệu — tải mẫu,
    xem trước (dry_run), rồi nhập thật. Khuôn `_render_preview()` của
    `frontend/pages/staff.py:187-240`."""
    state = {"bytes": None, "name": None}

    with ui.dialog() as hop, ui.card().classes("w-full max-w-lg"):
        ui.label(f"Nhập {ten} từ Excel").classes("text-lg font-bold text-orange-900")
        ui.label("Tải file mẫu, điền dữ liệu theo đúng tên cột rồi tải lên lại."
                  ).classes("text-sm text-gray-600")

        async def tai_mau():
            try:
                raw = await asyncio.to_thread(api.download, f"{duong_dan}/import-template")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            ui.download(raw, f"mau_{ten.lower().replace(' ', '_')}.xlsx")

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
                    f"{duong_dan}/import?dry_run={'true' if dry_run else 'false'}",
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
            ui.button("Xem trước", icon="preview", on_click=lambda: goi(True)).props(
                f"no-caps {_MAU_EXCEL}")
            ui.button("Nhập vào hệ thống", icon="upload", on_click=lambda: goi(False)
                      ).props(f"no-caps {_MAU_LUU}")
    hop.open()


# ── Tab 0: Tổng quan ──────────────────────────────────────────────────────────
# Banner + thẻ "dịch vụ" — khuôn y hệt `frontend/pages/xep_loai.py::_hero_banner()`
# / `_the_dich_vu()` (đổi tên/nội dung cho đúng module này), theo yêu cầu người
# dùng "cho giống trang Xếp loại lao động".
def _hero_banner():
    with ui.element("div").classes(
        "w-full rounded-2xl bg-gradient-to-r from-orange-600 to-orange-500 text-white "
        "px-6 py-6 mb-4 flex items-center justify-between gap-4 flex-wrap shadow-sm"):
        with ui.column().classes("gap-1"):
            ui.label("Thi đua khen thưởng — Phòng Tổng hợp").classes("text-xl font-bold")
            ui.label("Danh hiệu thi đua đơn vị, cá nhân và sáng kiến được công nhận "
                      "— nhập tay hoặc nhập lô từ Excel").classes("text-orange-50 text-sm")
        with ui.element("div").classes(
            "w-16 h-16 rounded-full bg-white/15 flex items-center justify-center shrink-0"):
            ui.icon("military_tech").classes("text-3xl text-white")


def _the_dich_vu(icon: str, so: int, nhan: str, noi_bat: bool = False):
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


async def _tab_tong_quan():
    """Trả về hàm `tai()` để trang chính gọi lại mỗi khi người dùng quay lại
    tab này — tab_panels dựng UI một lần lúc mở trang, không tự nạp lại số
    liệu khi sửa dữ liệu ở tab "Thông tin" rồi bấm sang "Tổng quan" nếu không
    có bước này (phát hiện khi tự kiểm bằng trình duyệt thật)."""
    khung = ui.column().classes("w-full gap-4")

    async def tai():
        try:
            tong_hop, sang_kien = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/thi-dua/stats/tong-hop"),
                asyncio.to_thread(api.get, "/api/thi-dua/stats/sang-kien"),
            )
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            tong_hop, sang_kien = [], []

        so_don_vi = sum(1 for r in tong_hop if r["loai"] == "Đơn vị")
        so_ca_nhan = sum(1 for r in tong_hop if r["loai"] == "Cá nhân")
        so_sang_kien = len(sang_kien)

        khung.clear()
        with khung:
            with ui.row().classes("w-full gap-3 flex-wrap"):
                _the_dich_vu("emoji_events", so_don_vi, "Danh hiệu đơn vị")
                _the_dich_vu("military_tech", so_ca_nhan, "Danh hiệu cá nhân")
                _the_dich_vu("lightbulb", so_sang_kien, "Sáng kiến cá nhân")
                _the_dich_vu("summarize", so_don_vi + so_ca_nhan + so_sang_kien, "Tổng cộng",
                             noi_bat=True)

            with ui.row().classes("w-full gap-4 items-start flex-wrap"):
                with ui.column().classes("flex-1 min-w-[20rem]"):
                    with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden"):
                        with ui.row().classes("w-full bg-orange-50 px-4 py-3 border-b border-orange-100"):
                            ui.label("Danh hiệu gần đây").classes("font-semibold text-orange-900")
                        with ui.column().classes("w-full p-3 gap-2"):
                            gan_day = tong_hop[:8]
                            if not gan_day:
                                ui.label("Chưa có dữ liệu").classes("text-xs text-gray-500 px-1")
                            for r in gan_day:
                                with ui.row().classes(
                                    "w-full items-center gap-2 border-b border-gray-100 pb-2 last:border-0"):
                                    ui.icon("emoji_events" if r["loai"] == "Đơn vị" else "military_tech"
                                            ).classes("text-orange-600 text-lg")
                                    with ui.column().classes("gap-0 flex-1 min-w-0"):
                                        ui.label(r["danh_hieu"]).classes("text-sm font-medium truncate")
                                        ui.label(f"{r['loai']} — {r['doi_tuong'] or '—'}").classes(
                                            "text-xs text-gray-500 truncate")
                                    ui.label(str(r["year"])).classes(
                                        "text-xs font-semibold text-orange-700 bg-orange-50 rounded-full px-2 py-0.5")
                with ui.column().classes("flex-1 min-w-[20rem]"):
                    with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden"):
                        with ui.row().classes("w-full bg-orange-50 px-4 py-3 border-b border-orange-100"):
                            ui.label("Sáng kiến gần đây").classes("font-semibold text-orange-900")
                        with ui.column().classes("w-full p-3 gap-2"):
                            gan_day_sk = sang_kien[:8]
                            if not gan_day_sk:
                                ui.label("Chưa có dữ liệu").classes("text-xs text-gray-500 px-1")
                            for r in gan_day_sk:
                                with ui.row().classes(
                                    "w-full items-center gap-2 border-b border-gray-100 pb-2 last:border-0"):
                                    ui.icon("lightbulb").classes("text-amber-600 text-lg")
                                    with ui.column().classes("gap-0 flex-1 min-w-0"):
                                        ui.label(r["ten_sang_kien"]).classes("text-sm font-medium truncate")
                                        ui.label(r["doi_tuong"] or "—").classes(
                                            "text-xs text-gray-500 truncate")
                                    ui.label(str(r["year"])).classes(
                                        "text-xs font-semibold text-orange-700 bg-orange-50 rounded-full px-2 py-0.5")

    await tai()
    return tai


# ── Khu vực 1: Danh hiệu đơn vị ───────────────────────────────────────────────
async def _tab_don_vi(dept_opts: dict, can_manage: bool):
    ban_ghi: dict = {}
    goi_y: list = []
    du_lieu: list = []   # snapshot đầy đủ của lần tải gần nhất — lọc thêm (Đơn vị,
    # Tìm kiếm) chạy tại chỗ trên đây, không gọi lại API mỗi lần gõ/chọn.

    def ve_lai():
        tim = (o_tim.value or "").strip().lower()
        dv = f_dept.value
        hien = [
            r for r in du_lieu
            if (dv == "__all__" or r["department_id"] == dv)
            and (not tim or tim in r["danh_hieu"].lower() or tim in r["co_quan_ban_hanh"].lower())
        ]
        khung.clear()
        with khung:
            if not du_lieu:
                ui.label("Chưa có danh hiệu đơn vị nào.").classes("text-gray-500 py-6 text-center w-full")
                return
            if not hien:
                ui.label("Không có danh hiệu nào khớp bộ lọc.").classes(
                    "text-gray-500 py-6 text-center w-full")
                return
            with _luoi_the():
                for r in hien:
                    with _the_ban_ghi(
                        on_edit=(lambda rid=r["id"]: mo_form(ban_ghi[rid])) if can_manage else None,
                        on_del=(lambda rid=r["id"]: xoa(rid)) if can_manage else None,
                    ):
                        with ui.row().classes("items-center gap-2"):
                            _chip(str(r["year"]))
                            ui.label(r["department_name"]).classes("text-xs text-gray-500 truncate")
                        ui.label(r["danh_hieu"]).classes(
                            "text-base font-semibold text-gray-800 leading-snug")
                        ui.label(f"QĐ {r['so_quyet_dinh']} · {r['ngay_qd_txt']}").classes(
                            "text-xs text-gray-500")
                        if r["co_quan_ban_hanh"] != "—":
                            ui.label(r["co_quan_ban_hanh"]).classes("text-xs text-gray-400")

    async def tai():
        params = {"year": int(f_year.value)} if f_year.value else {}
        try:
            rows, gy = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/thi-dua/don-vi", params),
                asyncio.to_thread(api.get, "/api/thi-dua/danh-hieu-goi-y", {"loai": "don_vi"}),
            )
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ban_ghi.clear()
        ban_ghi.update({r["id"]: r for r in rows})
        goi_y[:] = gy
        du_lieu[:] = [{
            "id": r["id"], "year": r["year"], "department_id": r["department_id"],
            "department_name": r["department_name"],
            "danh_hieu": r["danh_hieu"], "so_quyet_dinh": _o(r["so_quyet_dinh"]),
            "ngay_qd_txt": _dmy(r["ngay_quyet_dinh"]) if r.get("ngay_quyet_dinh") else "—",
            "co_quan_ban_hanh": _o(r["co_quan_ban_hanh"]),
        } for r in rows]
        ve_lai()

    async def xoa(rid: int):
        if not await _xac_nhan_xoa("danh hiệu này"):
            return
        try:
            await asyncio.to_thread(api.delete, f"/api/thi-dua/don-vi/{rid}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.notify("Đã xoá", type="positive")
        await tai()

    def mo_form(item: dict | None):
        with ui.dialog() as hop, ui.card().classes("w-full max-w-xl"):
            ui.label(("Sửa" if item else "Thêm") + " danh hiệu đơn vị").classes(
                "text-lg font-bold text-orange-900")
            with ui.grid(columns=2).classes("w-full gap-3"):
                o_year = ui.number(label="Năm", value=(item or {}).get("year") or _nam_hien_tai(),
                                    min=2000, max=2100, format="%d").props(_O_NHAP)
                o_dept = ui.select(dept_opts, label="Đơn vị", with_input=True,
                                    value=(item or {}).get("department_id")
                                    ).classes("min-w-[12rem]").props(_O_NHAP)
                o_danh_hieu = ui.input("Tên danh hiệu", value=(item or {}).get("danh_hieu") or "",
                                        autocomplete=goi_y).classes("col-span-2 w-full").props(_O_NHAP)
                o_so_qd = ui.input("Số quyết định", value=(item or {}).get("so_quyet_dinh") or ""
                                    ).props(_O_NHAP)
                o_ngay_qd = _o_chon_ngay(
                    "Ngày quyết định",
                    initial=_dmy((item or {}).get("ngay_quyet_dinh") or "") or None
                    ).props("rounded")
                o_co_quan = ui.input("Cơ quan ban hành",
                                      value=(item or {}).get("co_quan_ban_hanh") or "").classes(
                    "col-span-2 w-full").props(_O_NHAP)
            o_ghi_chu = ui.textarea("Ghi chú", value=(item or {}).get("ghi_chu") or "").classes(
                "w-full").props(_O_NHAP)

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Đóng", on_click=hop.close).props("flat no-caps")

                async def luu():
                    if not o_danh_hieu.value.strip():
                        ui.notify("Nhập tên danh hiệu", type="warning")
                        return
                    body = {
                        "year": int(o_year.value),
                        "department_id": int(o_dept.value) if o_dept.value is not None else None,
                        "danh_hieu": o_danh_hieu.value,
                        "so_quyet_dinh": o_so_qd.value or None,
                        "ngay_quyet_dinh": _iso_tu_dmy(o_ngay_qd.value) if o_ngay_qd.value else None,
                        "co_quan_ban_hanh": o_co_quan.value or None,
                        "ghi_chu": o_ghi_chu.value or None,
                    }
                    path = f"/api/thi-dua/don-vi/{item['id']}" if item else "/api/thi-dua/don-vi"
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
                    ui.button("Lưu", icon="save", on_click=luu).props(f"no-caps {_MAU_LUU}")
        hop.open()

    with _khung_loc():
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_year = ui.number(label="Năm (để trống = tất cả)", format="%d", min=2000, max=2100
                                ).classes("w-56").props(_O_NHAP)
            ui.button("Lọc", icon="search", on_click=lambda: tai()).props(f"no-caps {_MAU_LOC}")
            if can_manage:
                ui.button("Thêm danh hiệu", icon="add", on_click=lambda: mo_form(None)
                          ).props(f"no-caps {_MAU_LUU}")
                ui.button("Nhập từ Excel", icon="upload_file", on_click=lambda: _mo_nhap_excel(
                    "danh hiệu đơn vị", "/api/thi-dua/don-vi", tai)
                          ).props(f"no-caps {_MAU_EXCEL}")
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_dept = ui.select({"__all__": "Tất cả đơn vị", **dept_opts}, label="Đơn vị",
                                value="__all__", with_input=True).classes("w-56").props(_O_NHAP
                                ).on_value_change(lambda: ve_lai())
            o_tim = ui.input("Tìm kiếm", placeholder="Tên danh hiệu, cơ quan ban hành..."
                              ).props(f"clearable {_O_NHAP}").classes("w-72").on_value_change(lambda: ve_lai())

    khung = ui.column().classes("w-full")
    await tai()


# ── Khu vực 2: Danh hiệu cá nhân ──────────────────────────────────────────────
async def _tab_ca_nhan(staff_opts: dict, can_manage: bool):
    ban_ghi: dict = {}
    goi_y: list = []
    du_lieu: list = []

    def ve_lai():
        tim = (o_tim.value or "").strip().lower()
        cap = f_cap.value
        hien = [
            r for r in du_lieu
            if (cap == "__all__" or r["cap"] == cap)
            and (not tim or tim in r["danh_hieu"].lower() or tim in r["staff_name"].lower())
        ]
        khung.clear()
        with khung:
            if not du_lieu:
                ui.label("Chưa có danh hiệu cá nhân nào.").classes("text-gray-500 py-6 text-center w-full")
                return
            if not hien:
                ui.label("Không có danh hiệu nào khớp bộ lọc.").classes(
                    "text-gray-500 py-6 text-center w-full")
                return
            with _luoi_the():
                for r in hien:
                    with _the_ban_ghi(
                        on_edit=(lambda rid=r["id"]: mo_form(ban_ghi[rid])) if can_manage else None,
                        on_del=(lambda rid=r["id"]: xoa(rid)) if can_manage else None,
                    ):
                        with ui.row().classes("items-center gap-2"):
                            _chip(str(r["year"]))
                            _chip(r["cap_nhan"], mau="gray")
                        ui.label(r["staff_name"]).classes("text-sm font-medium text-gray-700")
                        ui.label(r["danh_hieu"]).classes(
                            "text-base font-semibold text-gray-800 leading-snug")
                        ui.label(f"QĐ {r['so_quyet_dinh']} · {r['ngay_qd_txt']}").classes(
                            "text-xs text-gray-500")

    async def tai():
        params = {}
        if f_year.value:
            params["year"] = int(f_year.value)
        if f_staff.value:
            params["staff_id"] = int(f_staff.value)
        try:
            rows, gy = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/thi-dua/ca-nhan", params),
                asyncio.to_thread(api.get, "/api/thi-dua/danh-hieu-goi-y", {"loai": "ca_nhan"}),
            )
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ban_ghi.clear()
        ban_ghi.update({r["id"]: r for r in rows})
        goi_y[:] = gy
        du_lieu[:] = [{
            "id": r["id"], "year": r["year"], "staff_name": r["staff_name"] or "—",
            "cap": r["cap"], "cap_nhan": r["cap_nhan"], "danh_hieu": r["danh_hieu"],
            "so_quyet_dinh": _o(r["so_quyet_dinh"]),
            "ngay_qd_txt": _dmy(r["ngay_quyet_dinh"]) if r.get("ngay_quyet_dinh") else "—",
        } for r in rows]
        ve_lai()

    async def xoa(rid: int):
        if not await _xac_nhan_xoa("danh hiệu này"):
            return
        try:
            await asyncio.to_thread(api.delete, f"/api/thi-dua/ca-nhan/{rid}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.notify("Đã xoá", type="positive")
        await tai()

    def mo_form(item: dict | None):
        with ui.dialog() as hop, ui.card().classes("w-full max-w-xl"):
            ui.label(("Sửa" if item else "Thêm") + " danh hiệu cá nhân").classes(
                "text-lg font-bold text-orange-900")
            with ui.grid(columns=2).classes("w-full gap-3"):
                o_staff = ui.select(staff_opts, label="Cán bộ", with_input=True,
                                     value=(str(item["staff_id"]) if item else None)
                                     ).classes("col-span-2 w-full").props(_O_NHAP)
                o_year = ui.number(label="Năm", value=(item or {}).get("year") or _nam_hien_tai(),
                                    min=2000, max=2100, format="%d").props(_O_NHAP)
                o_cap = ui.select(_CAP_OPTS, label="Cấp", value=(item or {}).get("cap") or "dang"
                                   ).props(_O_NHAP)
                o_danh_hieu = ui.input("Tên danh hiệu", value=(item or {}).get("danh_hieu") or "",
                                        autocomplete=goi_y).classes("col-span-2 w-full").props(_O_NHAP)
                o_so_qd = ui.input("Số quyết định", value=(item or {}).get("so_quyet_dinh") or ""
                                    ).props(_O_NHAP)
                o_ngay_qd = _o_chon_ngay(
                    "Ngày quyết định",
                    initial=_dmy((item or {}).get("ngay_quyet_dinh") or "") or None
                    ).props("rounded")
                o_co_quan = ui.input("Cơ quan ban hành",
                                      value=(item or {}).get("co_quan_ban_hanh") or "").classes(
                    "col-span-2 w-full").props(_O_NHAP)
            o_ghi_chu = ui.textarea("Ghi chú", value=(item or {}).get("ghi_chu") or "").classes(
                "w-full").props(_O_NHAP)

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Đóng", on_click=hop.close).props("flat no-caps")

                async def luu():
                    if not o_staff.value:
                        ui.notify("Chọn cán bộ", type="warning")
                        return
                    if not o_danh_hieu.value.strip():
                        ui.notify("Nhập tên danh hiệu", type="warning")
                        return
                    body = {
                        "staff_id": int(o_staff.value),
                        "year": int(o_year.value),
                        "cap": o_cap.value,
                        "danh_hieu": o_danh_hieu.value,
                        "so_quyet_dinh": o_so_qd.value or None,
                        "ngay_quyet_dinh": _iso_tu_dmy(o_ngay_qd.value) if o_ngay_qd.value else None,
                        "co_quan_ban_hanh": o_co_quan.value or None,
                        "ghi_chu": o_ghi_chu.value or None,
                    }
                    path = f"/api/thi-dua/ca-nhan/{item['id']}" if item else "/api/thi-dua/ca-nhan"
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
                    ui.button("Lưu", icon="save", on_click=luu).props(f"no-caps {_MAU_LUU}")
        hop.open()

    with _khung_loc():
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_year = ui.number(label="Năm (để trống = tất cả)", format="%d", min=2000, max=2100
                                ).classes("w-56").props(_O_NHAP)
            f_staff = ui.select({None: "Tất cả cán bộ", **staff_opts}, label="Cán bộ",
                                 with_input=True, value=None).classes("w-56").props(_O_NHAP)
            ui.button("Lọc", icon="search", on_click=lambda: tai()).props(f"no-caps {_MAU_LOC}")
            if can_manage:
                ui.button("Thêm danh hiệu", icon="add", on_click=lambda: mo_form(None)
                          ).props(f"no-caps {_MAU_LUU}")
                ui.button("Nhập từ Excel", icon="upload_file", on_click=lambda: _mo_nhap_excel(
                    "danh hiệu cá nhân", "/api/thi-dua/ca-nhan", tai)
                          ).props(f"no-caps {_MAU_EXCEL}")
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_cap = ui.select({"__all__": "Tất cả cấp", **_CAP_OPTS}, label="Cấp",
                               value="__all__").classes("w-40").props(_O_NHAP
                               ).on_value_change(lambda: ve_lai())
            o_tim = ui.input("Tìm kiếm", placeholder="Tên danh hiệu, cán bộ..."
                              ).props(f"clearable {_O_NHAP}").classes("w-72").on_value_change(lambda: ve_lai())

    khung = ui.column().classes("w-full")
    await tai()


# ── Khu vực 3: Sáng kiến cá nhân ──────────────────────────────────────────────
_FILE_ACCEPT = ".pdf,.doc,.docx,.jpg,.jpeg,.png"


async def _tab_sang_kien(staff_opts: dict, can_manage: bool):
    ban_ghi: dict = {}
    du_lieu: list = []

    def ve_lai():
        tim = (o_tim.value or "").strip().lower()
        hien = [
            r for r in du_lieu
            if not tim or tim in r["ten_sang_kien"].lower() or tim in r["staff_name"].lower()
        ]
        khung.clear()
        with khung:
            if not du_lieu:
                ui.label("Chưa có sáng kiến nào.").classes("text-gray-500 py-6 text-center w-full")
                return
            if not hien:
                ui.label("Không có sáng kiến nào khớp bộ lọc.").classes(
                    "text-gray-500 py-6 text-center w-full")
                return
            with _luoi_the():
                for r in hien:
                    with _the_ban_ghi(
                        on_edit=(lambda rid=r["id"]: mo_form(ban_ghi[rid])) if can_manage else None,
                        on_del=(lambda rid=r["id"]: xoa(rid)) if can_manage else None,
                        on_file=(lambda rid=r["id"]: tai_file_rid(rid)),
                        has_file=r["has_file"],
                    ):
                        with ui.row().classes("items-center gap-2"):
                            _chip(str(r["year"]))
                            if r["has_file"]:
                                ui.icon("attach_file").classes("text-orange-700 text-sm")
                        ui.label(r["staff_name"]).classes("text-sm font-medium text-gray-700")
                        ui.label(r["ten_sang_kien"]).classes(
                            "text-base font-semibold text-gray-800 leading-snug")
                        ui.label(f"QĐ {r['so_quyet_dinh']} · {r['ngay_qd_txt']}").classes(
                            "text-xs text-gray-500")

    async def tai():
        params = {}
        if f_year.value:
            params["year"] = int(f_year.value)
        if f_staff.value:
            params["staff_id"] = int(f_staff.value)
        try:
            rows = await asyncio.to_thread(api.get, "/api/thi-dua/sang-kien", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ban_ghi.clear()
        ban_ghi.update({r["id"]: r for r in rows})
        du_lieu[:] = [{
            "id": r["id"], "year": r["year"], "staff_name": r["staff_name"] or "—",
            "ten_sang_kien": r["ten_sang_kien"], "so_quyet_dinh": _o(r["so_quyet_dinh"]),
            "ngay_qd_txt": _dmy(r["ngay_quyet_dinh"]) if r.get("ngay_quyet_dinh") else "—",
            "has_file": bool(r["has_file"]),
        } for r in rows]
        ve_lai()

    async def tai_file_rid(rid: int):
        await tai_file(ban_ghi[rid])

    async def tai_file(item: dict):
        try:
            raw = await asyncio.to_thread(api.download, f"/api/thi-dua/sang-kien/{item['id']}/file")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.download(raw, item.get("file_name") or "quyet_dinh")

    async def xoa(rid: int):
        if not await _xac_nhan_xoa("sáng kiến này (kèm file quyết định)"):
            return
        try:
            await asyncio.to_thread(api.delete, f"/api/thi-dua/sang-kien/{rid}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.notify("Đã xoá", type="positive")
        await tai()

    def mo_form(item: dict | None):
        cho_tai = {"bytes": None, "name": None, "type": None}
        co_file = bool((item or {}).get("has_file"))

        with ui.dialog() as hop, ui.card().classes("w-full max-w-xl"):
            ui.label(("Sửa" if item else "Thêm") + " sáng kiến cá nhân").classes(
                "text-lg font-bold text-orange-900")
            with ui.grid(columns=2).classes("w-full gap-3"):
                o_staff = ui.select(staff_opts, label="Cán bộ", with_input=True,
                                     value=(str(item["staff_id"]) if item else None)
                                     ).classes("col-span-2 w-full").props(_O_NHAP)
                o_year = ui.number(label="Năm", value=(item or {}).get("year") or _nam_hien_tai(),
                                    min=2000, max=2100, format="%d").props(_O_NHAP)
                o_ngay_qd = _o_chon_ngay(
                    "Ngày quyết định",
                    initial=_dmy((item or {}).get("ngay_quyet_dinh") or "") or None
                    ).props("rounded")
                o_ten = ui.input("Tên sáng kiến", value=(item or {}).get("ten_sang_kien") or ""
                                  ).classes("col-span-2 w-full").props(_O_NHAP)
                o_so_qd = ui.input("Số quyết định", value=(item or {}).get("so_quyet_dinh") or ""
                                    ).props(_O_NHAP)
                o_co_quan = ui.input("Cơ quan công nhận",
                                      value=(item or {}).get("co_quan_cong_nhan") or "").props(_O_NHAP)
            o_ghi_chu = ui.textarea("Ghi chú", value=(item or {}).get("ghi_chu") or "").classes(
                "w-full").props(_O_NHAP)

            ui.separator().classes("my-2")
            ui.label(f"File quyết định ({_FILE_ACCEPT.replace(',', ', ')} — tối đa 15 MB)"
                     ).classes("font-semibold text-sm text-orange-800")
            khung_file = ui.column().classes("w-full gap-1")

            def ve_file():
                khung_file.clear()
                with khung_file:
                    if co_file:
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.icon("description").classes("text-orange-700")
                            ui.label(item.get("file_name") or "quyết định").classes(
                                "text-sm flex-1 truncate")

                            async def tai_ve():
                                await tai_file(item)

                            ui.button(icon="download", on_click=tai_ve).props(
                                "dense flat round size=sm")

                            if can_manage:
                                async def xoa_file():
                                    nonlocal co_file
                                    try:
                                        await asyncio.to_thread(
                                            api.delete, f"/api/thi-dua/sang-kien/{item['id']}/file")
                                    except Exception as e:
                                        if _handle_api_error(e):
                                            return
                                        ui.notify(str(e), type="negative")
                                        return
                                    co_file = False
                                    ui.notify("Đã xoá file", type="positive")
                                    ve_file()

                                ui.button(icon="delete", on_click=xoa_file).props(
                                    "dense flat round size=sm color=negative")
                    elif cho_tai["bytes"]:
                        with ui.row().classes("items-center gap-2 w-full"):
                            ui.icon("upload_file").classes("text-amber-600")
                            ui.label(f"{cho_tai['name']} — chờ lưu").classes("text-sm flex-1 truncate")

                            def bo():
                                cho_tai.update(bytes=None, name=None, type=None)
                                ve_file()

                            ui.button(icon="close", on_click=bo).props(
                                "dense flat round size=sm color=negative")
                    else:
                        ui.label("Chưa có file").classes("text-xs text-gray-500")

                    if can_manage and not co_file:
                        async def nhan_tep(e):
                            cho_tai.update(bytes=e.content.read(), name=e.name, type=e.type)
                            ve_file()

                        ui.upload(label="Chọn file", auto_upload=True, on_upload=nhan_tep
                                  ).props(f'accept="{_FILE_ACCEPT}" flat').classes("w-full")

            ve_file()

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Đóng", on_click=hop.close).props("flat no-caps")

                async def luu():
                    if not o_staff.value:
                        ui.notify("Chọn cán bộ", type="warning")
                        return
                    if not o_ten.value.strip():
                        ui.notify("Nhập tên sáng kiến", type="warning")
                        return
                    body = {
                        "staff_id": int(o_staff.value),
                        "year": int(o_year.value),
                        "ten_sang_kien": o_ten.value,
                        "so_quyet_dinh": o_so_qd.value or None,
                        "ngay_quyet_dinh": _iso_tu_dmy(o_ngay_qd.value) if o_ngay_qd.value else None,
                        "co_quan_cong_nhan": o_co_quan.value or None,
                        "ghi_chu": o_ghi_chu.value or None,
                    }
                    path = f"/api/thi-dua/sang-kien/{item['id']}" if item else "/api/thi-dua/sang-kien"
                    goi = api.put if item else api.post
                    try:
                        ket = await asyncio.to_thread(goi, path, body)
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(str(e), type="negative")
                        return
                    new_id = item["id"] if item else ket["id"]
                    if cho_tai["bytes"]:
                        try:
                            await asyncio.to_thread(
                                api.post_upload, f"/api/thi-dua/sang-kien/{new_id}/file",
                                {"file": (cho_tai["name"], cho_tai["bytes"],
                                          cho_tai["type"] or "application/octet-stream")})
                        except Exception as e:
                            if _handle_api_error(e):
                                return
                            ui.notify(f"Đã lưu sáng kiến, nhưng chưa đính kèm được file: {e}",
                                      type="warning", timeout=6000)
                            hop.close()
                            await tai()
                            return
                    hop.close()
                    ui.notify("Đã lưu", type="positive")
                    await tai()

                if can_manage:
                    ui.button("Lưu", icon="save", on_click=luu).props(f"no-caps {_MAU_LUU}")
        hop.open()

    with _khung_loc():
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_year = ui.number(label="Năm (để trống = tất cả)", format="%d", min=2000, max=2100
                                ).classes("w-56").props(_O_NHAP)
            f_staff = ui.select({None: "Tất cả cán bộ", **staff_opts}, label="Cán bộ",
                                 with_input=True, value=None).classes("w-56").props(_O_NHAP)
            ui.button("Lọc", icon="search", on_click=lambda: tai()).props(f"no-caps {_MAU_LOC}")
            if can_manage:
                ui.button("Thêm sáng kiến", icon="add", on_click=lambda: mo_form(None)
                          ).props(f"no-caps {_MAU_LUU}")
                ui.button("Nhập từ Excel", icon="upload_file", on_click=lambda: _mo_nhap_excel(
                    "sáng kiến cá nhân", "/api/thi-dua/sang-kien", tai)
                          ).props(f"no-caps {_MAU_EXCEL}")
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            o_tim = ui.input("Tìm kiếm", placeholder="Tên sáng kiến, cán bộ..."
                              ).props(f"clearable {_O_NHAP}").classes("w-72").on_value_change(lambda: ve_lai())

    khung = ui.column().classes("w-full")
    await tai()


# ── Khu vực 4: Tổng hợp theo năm ──────────────────────────────────────────────
async def _tab_tong_hop(co_export: bool):
    du_lieu: list = []

    def ve_lai():
        tim = (o_tim.value or "").strip().lower()
        loai = f_loai.value
        hien = [
            r for r in du_lieu
            if (loai == "__all__" or r["loai"] == loai)
            and (not tim or tim in r["danh_hieu"].lower() or tim in (r["doi_tuong"] or "").lower())
        ]
        khung.clear()
        with khung:
            if not du_lieu:
                ui.label("Không có dữ liệu.").classes("text-gray-500 py-6 text-center w-full")
                return
            if not hien:
                ui.label("Không có dòng nào khớp bộ lọc.").classes(
                    "text-gray-500 py-6 text-center w-full")
                return
            with _luoi_the():
                for r in hien:
                    with _the_ban_ghi():
                        with ui.row().classes("items-center gap-2"):
                            _chip(str(r["year"]))
                            _chip(r["loai"], mau=("gray" if r["loai"] == "Đơn vị" else "slate"))
                            if r.get("cap_nhan"):
                                _chip(r["cap_nhan"], mau="gray")
                        ui.label(r["doi_tuong"] or "—").classes("text-sm font-medium text-gray-700")
                        ui.label(r["danh_hieu"]).classes(
                            "text-base font-semibold text-gray-800 leading-snug")
                        ui.label(f"QĐ {_o(r.get('so_quyet_dinh'))} · "
                                 f"{_dmy(r['ngay_quyet_dinh']) if r.get('ngay_quyet_dinh') else '—'}"
                                 ).classes("text-xs text-gray-500")
                        if r.get("co_quan_ban_hanh"):
                            ui.label(r["co_quan_ban_hanh"]).classes("text-xs text-gray-400")

    async def tai():
        params = {"year": int(f_year.value)} if f_year.value else {}
        try:
            rows = await asyncio.to_thread(api.get, "/api/thi-dua/stats/tong-hop", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        du_lieu[:] = rows
        ve_lai()

    async def xuat():
        params = {"year": int(f_year.value)} if f_year.value else {}
        try:
            raw = await asyncio.to_thread(api.download, "/api/thi-dua/export/tong-hop", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.download(raw, f"tong_hop_thi_dua_{int(f_year.value) if f_year.value else 'tat_ca'}.xlsx")

    with _khung_loc():
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_year = ui.number(label="Năm (để trống = tất cả)", format="%d", min=2000, max=2100
                                ).classes("w-56").props(_O_NHAP)
            ui.button("Lọc", icon="search", on_click=lambda: tai()).props(f"no-caps {_MAU_LOC}")
            if co_export:
                ui.button("Xuất Excel", icon="download", on_click=xuat).props(f"no-caps {_MAU_EXCEL}")
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_loai = ui.select({"__all__": "Tất cả loại", "Đơn vị": "Đơn vị", "Cá nhân": "Cá nhân"},
                                label="Loại", value="__all__").classes("w-40").props(_O_NHAP
                                ).on_value_change(lambda: ve_lai())
            o_tim = ui.input("Tìm kiếm", placeholder="Tên danh hiệu, đơn vị/cán bộ..."
                              ).props(f"clearable {_O_NHAP}").classes("w-72").on_value_change(lambda: ve_lai())

    khung = ui.column().classes("w-full")
    await tai()
    return tai


# ── Khu vực 5: Sáng kiến theo cá nhân ─────────────────────────────────────────
async def _tab_sk_stats(staff_opts: dict, co_export: bool):
    du_lieu: list = []

    def ve_lai():
        tim = (o_tim.value or "").strip().lower()
        hien = [
            r for r in du_lieu
            if not tim or tim in r["ten_sang_kien"].lower() or tim in (r["doi_tuong"] or "").lower()
        ]
        khung.clear()
        with khung:
            if not du_lieu:
                ui.label("Không có dữ liệu.").classes("text-gray-500 py-6 text-center w-full")
                return
            if not hien:
                ui.label("Không có sáng kiến nào khớp bộ lọc.").classes(
                    "text-gray-500 py-6 text-center w-full")
                return
            with _luoi_the():
                for r in hien:
                    with _the_ban_ghi():
                        with ui.row().classes("items-center gap-2"):
                            _chip(str(r["year"]))
                            if r.get("has_file"):
                                ui.icon("attach_file").classes("text-orange-700 text-sm")
                        ui.label(r["doi_tuong"] or "—").classes("text-sm font-medium text-gray-700")
                        ui.label(r["ten_sang_kien"]).classes(
                            "text-base font-semibold text-gray-800 leading-snug")
                        ui.label(f"QĐ {_o(r.get('so_quyet_dinh'))} · "
                                 f"{_dmy(r['ngay_quyet_dinh']) if r.get('ngay_quyet_dinh') else '—'}"
                                 ).classes("text-xs text-gray-500")
                        if r.get("co_quan_cong_nhan"):
                            ui.label(r["co_quan_cong_nhan"]).classes("text-xs text-gray-400")

    async def tai():
        params = {}
        if f_staff.value:
            params["staff_id"] = int(f_staff.value)
        if f_year.value:
            params["year"] = int(f_year.value)
        try:
            rows = await asyncio.to_thread(api.get, "/api/thi-dua/stats/sang-kien", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        du_lieu[:] = rows
        ve_lai()

    async def xuat():
        params = {}
        if f_staff.value:
            params["staff_id"] = int(f_staff.value)
        if f_year.value:
            params["year"] = int(f_year.value)
        try:
            raw = await asyncio.to_thread(api.download, "/api/thi-dua/export/sang-kien", params)
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(str(e), type="negative")
            return
        ui.download(raw, f"sang_kien_ca_nhan_{int(f_year.value) if f_year.value else 'tat_ca'}.xlsx")

    with _khung_loc():
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            f_staff = ui.select({None: "Tất cả cán bộ", **staff_opts}, label="Cán bộ",
                                 with_input=True, value=None).classes("w-56").props(_O_NHAP)
            f_year = ui.number(label="Năm (để trống = tất cả)", format="%d", min=2000, max=2100
                                ).classes("w-56").props(_O_NHAP)
            ui.button("Lọc", icon="search", on_click=lambda: tai()).props(f"no-caps {_MAU_LOC}")
            if co_export:
                ui.button("Xuất Excel", icon="download", on_click=xuat).props(f"no-caps {_MAU_EXCEL}")
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            o_tim = ui.input("Tìm kiếm", placeholder="Tên sáng kiến, cán bộ..."
                              ).props(f"clearable {_O_NHAP}").classes("w-72").on_value_change(lambda: ve_lai())

    khung = ui.column().classes("w-full")
    await tai()
    return tai


# ── Trang chính ───────────────────────────────────────────────────────────────
@ui.page("/thi_dua")
async def thi_dua_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.thi_dua"):
        ui.navigate.to("/home")
        return

    try:
        depts, staff_list = await asyncio.gather(
            asyncio.to_thread(api.get, "/api/departments/"),
            asyncio.to_thread(api.get, "/api/staff/", {"active_only": True}),
        )
    except Exception as e:
        if _handle_api_error(e):
            return
        ui.notify(str(e), type="negative")
        return

    # Đơn vị + cán bộ lấy đúng nguồn dữ liệu của "Quản lý nhân sự"
    # (`/api/departments/`, `/api/staff/` — cùng bảng `departments`/`user_tttt`
    # mà hồ sơ nhân sự khoá theo `staff_id`). Loại tài khoản quản trị viên khỏi
    # danh sách chọn cán bộ, khớp đúng quy ước "Quản lý nhân sự" — tài khoản hệ
    # thống không có hồ sơ, không nhận danh hiệu/sáng kiến cá nhân
    # (`hr_service.ROLES_KHONG_HO_SO`).
    dept_name_by_id = {d["id"]: d["name"] for d in depts}
    dept_opts = {None: TOAN_TRUNG_TAM, **dept_name_by_id}
    staff_opts = {
        str(p["id"]): (p["full_name"] + (f" — {dept_name_by_id[p['department_id']]}"
                                          if p.get("department_id") in dept_name_by_id else ""))
        for p in staff_list if p.get("role") not in ("admin", "admin_l2")
    }

    co_unit   = api.has_feature("thi_dua.manage_unit")
    co_indiv  = api.has_feature("thi_dua.manage_individual")
    co_init   = api.has_feature("thi_dua.manage_initiative")
    co_export = api.has_feature("thi_dua.export")

    with ui.row().classes("w-full"):
        await _sidebar("thi_dua")
        with _content_area():
            _page_header("Thi đua khen thưởng",
                         "Danh hiệu thi đua đơn vị, cá nhân và sáng kiến được công nhận")
            _hero_banner()

            with ui.tabs().props("active-color=orange-8 indicator-color=orange-8").classes("mb-3") as tabs:
                tab_tongquan = ui.tab("tongquan", label="Tổng quan",           icon="dashboard")
                tab_donvi    = ui.tab("donvi",    label="Đơn vị",             icon="emoji_events")
                tab_canhan   = ui.tab("canhan",   label="Cá nhân",            icon="military_tech")
                tab_tracuu   = ui.tab("tracuu",   label="Tra cứu, thống kê",  icon="query_stats")

            with ui.tab_panels(tabs, value=tab_tongquan).classes("w-full"):
                with ui.tab_panel(tab_tongquan):
                    tai_tong_quan = await _tab_tong_quan()

                with ui.tab_panel(tab_donvi):
                    _section_title("Danh hiệu đơn vị", "emoji_events")
                    await _tab_don_vi(dept_opts, co_unit)

                with ui.tab_panel(tab_canhan):
                    _section_title("Danh hiệu cá nhân", "military_tech")
                    await _tab_ca_nhan(staff_opts, co_indiv)
                    ui.separator().classes("my-6")
                    _section_title("Sáng kiến cá nhân", "lightbulb")
                    await _tab_sang_kien(staff_opts, co_init)

                with ui.tab_panel(tab_tracuu):
                    _section_title("Tổng hợp theo năm", "summarize")
                    tai_tong_hop = await _tab_tong_hop(co_export)
                    ui.separator().classes("my-6")
                    _section_title("Sáng kiến theo cá nhân", "person_search")
                    tai_sk_stats = await _tab_sk_stats(staff_opts, co_export)

            async def _khi_doi_tab(e):
                # tab_panels dựng UI 1 lần lúc mở trang — quay lại "Tổng quan"
                # hay "Tra cứu, thống kê" sau khi vừa sửa dữ liệu ở tab "Thông
                # tin" phải nạp lại số liệu, không thì hiện số/dòng cũ (bắt
                # được khi tự kiểm trình duyệt: thêm danh hiệu ở "Thông tin"
                # rồi sang tab khác không kịp thấy dữ liệu mới).
                if e.value == "tongquan":
                    await tai_tong_quan()
                elif e.value == "tracuu":
                    await tai_tong_hop()
                    await tai_sk_stats()

            tabs.on_value_change(_khi_doi_tab)
