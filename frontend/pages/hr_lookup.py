"""Tra cứu & Thống kê nhân sự.

Hai khối: danh sách cán bộ theo nhóm **tại một thời điểm** (phòng lấy từ lịch sử
đổi phòng, chức vụ/quy hoạch lấy từ quyết định còn hiệu lực tại ngày đó), và
thống kê nhân sự hiện tại theo phòng / giới tính / trình độ / độ tuổi / đã qua
chi nhánh.
"""
import asyncio
import datetime

from nicegui import ui

import frontend.api_client as api
from frontend.shared import (_content_area, _dmy, _handle_api_error, _iso_tu_dmy,
                             _o_chon_ngay, _page_header, _require_auth, _sidebar)

_CSS = """<style>
.hr-lk-table td { white-space: normal !important; }
.hr-lk-table thead th {
  position: sticky; top: 0; z-index: 2;
  background: #fef2f2; color: #7f1d1d; font-weight: 600;
}
.hr-lk-table .q-table__middle { max-height: calc(100vh - 340px); }
</style>"""

_COLS = [
    {"name": "employee_code", "label": "Mã cán bộ", "field": "employee_code",
     "align": "left", "sortable": True, "style": "width:110px"},
    {"name": "full_name", "label": "Họ và tên", "field": "full_name",
     "align": "left", "sortable": True, "style": "min-width:180px"},
    {"name": "department", "label": "Phòng", "field": "department",
     "align": "left", "sortable": True, "style": "min-width:180px"},
    {"name": "chuc_vu", "label": "Chức vụ", "field": "chuc_vu", "align": "left"},
    {"name": "quy_hoach", "label": "Quy hoạch", "field": "quy_hoach", "align": "left"},
    {"name": "gender", "label": "Giới tính", "field": "gender", "align": "center",
     "style": "width:90px"},
    {"name": "dob", "label": "Ngày sinh", "field": "dob_txt", "align": "center",
     "style": "width:110px"},
]


def _khoi_thong_ke(tieu_de: str, muc: list[dict], tong: int):
    with ui.card().classes("p-0 overflow-hidden min-w-[16rem] flex-1"):
        ui.label(tieu_de).classes(
            "w-full bg-red-50 px-3 py-2 font-semibold text-red-800 text-sm border-b border-red-100")
        with ui.column().classes("w-full p-3 gap-1"):
            if not muc:
                ui.label("Chưa có dữ liệu").classes("text-xs text-gray-500")
            for m in muc:
                ty_le = (m["so_luong"] / tong * 100) if tong else 0
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label(m["nhan"]).classes("text-sm flex-1 truncate")
                    ui.label(str(m["so_luong"])).classes("text-sm font-semibold text-red-800")
                    ui.label(f"{ty_le:.0f}%").classes("text-xs text-gray-500 w-10 text-right")
                ui.linear_progress(value=ty_le / 100, show_value=False, size="4px"
                                   ).props("color=red-7 track-color=red-1")


@ui.page("/hr_lookup")
async def hr_lookup_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.hr_lookup"):
        ui.navigate.to("/home")
        return

    await _sidebar("hr_lookup")
    ui.add_head_html(_CSS)

    try:
        meta, depts = await asyncio.gather(
            asyncio.to_thread(api.get, "/api/hr/meta"),
            asyncio.to_thread(api.get, "/api/departments/"),
            return_exceptions=True,
        )
    except Exception as e:              # pragma: no cover — lỗi mạng lúc mở trang
        _handle_api_error(e)
        return
    for r in (meta, depts):
        if isinstance(r, Exception):
            if _handle_api_error(r):
                return
            ui.notify(str(r), type="negative")
            return

    nhom_opts = meta["nhom_tra_cuu"]
    dept_opts = {None: "Tất cả phòng", **{d["id"]: d["name"] for d in depts}}
    co_xuat = api.has_feature("hr.export")

    with _content_area():
        _page_header("Tra cứu & Thống kê nhân sự",
                     "Danh sách cán bộ tại từng thời điểm và số liệu tổng hợp")

        with ui.row().classes("w-full items-end gap-3 mb-3 flex-wrap"):
            f_nhom = ui.select(nhom_opts, value="tat_ca", label="Nhóm").props(
                "dense outlined").classes("w-56")
            f_dept = ui.select(dept_opts, value=None, label="Phòng").props(
                "dense outlined").classes("w-56")
            f_ngay = _o_chon_ngay("Tại ngày")
            ui.button("Tra cứu", icon="search", on_click=lambda: tai()
                      ).props("no-caps").classes("bg-red-700 text-white px-3")

            async def xuat():
                try:
                    noi_dung = await asyncio.to_thread(
                        api.download, "/api/hr/export", _tham_so())
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(str(e), type="negative")
                    return
                ui.download(noi_dung,
                            f"danh_sach_can_bo_{datetime.date.today():%Y%m%d}.xlsx")

            if co_xuat:
                ui.button("Xuất Excel", icon="download", on_click=xuat
                          ).props("no-caps").classes("bg-green-700 text-white px-3")

        dem = ui.label("").classes("text-xs text-gray-500 mb-1")
        khung_bang = ui.column().classes("w-full")

        ui.label("Thống kê nhân sự hiện tại").classes(
            "text-lg font-bold text-red-900 mt-6 mb-2")
        khung_tk = ui.row().classes("w-full items-start gap-3 flex-wrap")

        def _tham_so() -> dict:
            p = {"nhom": f_nhom.value or "tat_ca", "as_of": _iso_tu_dmy(f_ngay.value)}
            if f_dept.value:
                p["department_id"] = f_dept.value
            return p

        async def tai():
            try:
                rows = await asyncio.to_thread(api.get, "/api/hr/directory", _tham_so())
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            dem.text = (f"{len(rows)} cán bộ — {nhom_opts[f_nhom.value or 'tat_ca']}, "
                        f"tại ngày {f_ngay.value}")
            khung_bang.clear()
            with khung_bang:
                if not rows:
                    ui.label("Không có cán bộ nào khớp điều kiện").classes(
                        "text-gray-500 text-center py-8 w-full")
                    return
                dong = []
                for r in rows:
                    d = {k: (r.get(k) or "—") for k in
                         ("employee_code", "full_name", "department", "chuc_vu",
                          "quy_hoach", "gender")}
                    d["id"] = r["staff_id"]
                    d["dob_txt"] = _dmy(str(r["dob"])[:10]) if r.get("dob") else "—"
                    dong.append(d)
                ui.table(columns=_COLS, rows=dong, row_key="id",
                         pagination={"rowsPerPage": 0}).props(
                    'bordered dense flat separator="cell"').classes("w-full hr-lk-table")

        async def tai_thong_ke():
            try:
                tk = await asyncio.to_thread(api.get, "/api/hr/stats")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            khung_tk.clear()
            with khung_tk:
                _khoi_thong_ke(f"Theo phòng ({tk['tong']} cán bộ)", tk["theo_phong"], tk["tong"])
                _khoi_thong_ke("Theo giới tính", tk["theo_gioi"], tk["tong"])
                _khoi_thong_ke("Theo trình độ", tk["theo_trinh_do"], tk["tong"])
                _khoi_thong_ke("Theo độ tuổi", tk["theo_tuoi"], tk["tong"])
                _khoi_thong_ke("Đã qua chi nhánh", tk["qua_chi_nhanh"], tk["tong"])

        await tai()
        await tai_thong_ke()
