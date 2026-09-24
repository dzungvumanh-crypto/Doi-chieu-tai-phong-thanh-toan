"""Trang Giám sát hệ thống — tổng quan tải, CSDL, ổ đĩa, sao lưu, nhật ký, người dùng.

Chỉ hiển thị: mọi ngưỡng và câu cảnh báo do backend tính (backend/api/monitor.py::danh_gia),
frontend không tự phán — tránh hai bảng ngưỡng lệch nhau.
"""
import asyncio
import logging

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error

_log = logging.getLogger(__name__)

_LAM_MOI_GIAY = 30

_TONG_THE = {
    "tot":      ("check_circle", "Hệ thống hoạt động bình thường", "bg-green-50 border-green-300 text-green-800"),
    "canh_bao": ("warning",      "Có mục cần chú ý",               "bg-orange-50 border-orange-300 text-orange-800"),
    "loi":      ("error",        "Có sự cố cần xử lý",             "bg-red-50 border-red-300 text-red-800"),
}
_MUC = {
    "loi":      ("error",   "text-red-600"),
    "canh_bao": ("warning", "text-orange-500"),
}


# ── Định dạng ──
def _dung_luong(b) -> str:
    if b is None:
        return "—"
    for don_vi in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or don_vi == "TB":
            return f"{b:.0f} {don_vi}" if don_vi in ("B", "KB") else f"{b:.1f} {don_vi}".replace(".", ",")
        b /= 1024


def _thoi_luong(giay: int) -> str:
    ngay, du = divmod(int(giay), 86400)
    gio, du = divmod(du, 3600)
    phut = du // 60
    if ngay:
        return f"{ngay} ngày {gio} giờ"
    if gio:
        return f"{gio} giờ {phut} phút"
    return f"{phut} phút"


def _so(x) -> str:
    return "—" if x is None else str(x)


def _ngay_vn(ts: str | None) -> str:
    """'2026-09-22 10:05:00' → '10:05 22/09/2026'."""
    if not ts or len(ts) < 16:
        return ts or "—"
    return f"{ts[11:16]} {ts[8:10]}/{ts[5:7]}/{ts[:4]}"


# ── Khối vẽ ──
def _the(tieu_de: str, icon: str):
    with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden border border-gray-200"):
        with ui.row().classes("w-full bg-red-50 px-4 py-2.5 border-b border-red-100 items-center gap-2"):
            ui.icon(icon).classes("text-red-700 text-lg")
            ui.label(tieu_de).classes("font-semibold text-red-800 text-sm")
        return ui.column().classes("w-full px-4 py-3 gap-1.5")


def _dong(nhan: str, gia_tri: str, canh_bao: bool = False, goi_y: str = ""):
    with ui.row().classes("w-full items-baseline justify-between gap-3 no-wrap"):
        ui.label(nhan).classes("text-xs text-gray-500 shrink-0")
        lbl = ui.label(gia_tri).classes(
            "text-sm font-medium text-right " + ("text-orange-600" if canh_bao else "text-gray-800"))
        if goi_y:
            lbl.tooltip(goi_y)


def _thanh(ti_le: float, nhan: str):
    """Thanh phần trăm đã dùng — đỏ từ 90 %, cam từ 75 %."""
    mau = "red" if ti_le >= 0.9 else "orange" if ti_le >= 0.75 else "green"
    with ui.column().classes("w-full gap-0.5 mt-1"):
        ui.linear_progress(value=ti_le, show_value=False, size="8px", color=mau).classes("rounded")
        ui.label(nhan).classes("text-xs text-gray-500")


def _ve(khung, d: dict):
    khung.clear()
    with khung:
        # ── Tổng thể + danh sách cảnh báo ──
        icon, tieu_de, cls = _TONG_THE.get(d.get("tong_the"), _TONG_THE["canh_bao"])
        with ui.column().classes(f"w-full border rounded-xl px-4 py-3 gap-1 {cls}"):
            with ui.row().classes("items-center gap-2"):
                ui.icon(icon).classes("text-2xl")
                ui.label(tieu_de).classes("font-semibold")
            for c in d.get("canh_bao", []):
                ic, mau = _MUC.get(c["muc"], _MUC["canh_bao"])
                with ui.row().classes("items-center gap-2 ml-1"):
                    ui.icon(ic).classes(f"text-base {mau}")
                    ui.label(f"{c['nhom']}: {c['noi_dung']}").classes("text-sm text-gray-800")

        with ui.element("div").classes("w-full grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"):
            _ve_may_chu(d["may_chu"])
            _ve_tai(d["tai"] or {})
            _ve_csdl_dia(d["csdl"], d["dia"])
            _ve_sao_luu(d["sao_luu"], d["dong_ho"])
            _ve_nguoi_dung(d["nguoi_dung"])
            _ve_doi_chieu(d["tai"] or {})
        _ve_nhat_ky(d["nhat_ky"])


def _ve_loi(khung, e: Exception):
    khung.clear()
    with khung:
        with ui.column().classes("w-full border rounded-xl px-4 py-3 gap-1 bg-red-50 border-red-300 text-red-800"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("error").classes("text-2xl")
                ui.label("Không lấy được số liệu từ backend").classes("font-semibold")
            ui.label("Backend có thể đang tắt, quá tải hoặc lỗi. Trang sẽ tự thử lại.").classes("text-sm text-gray-800")
            ui.label(str(e)[:300]).classes("text-xs text-gray-600 break-all")


def _ve_may_chu(m: dict):
    with _the("Máy chủ", "dns"):
        _dong("Tên máy", m["ten_may"])
        _dong("Backend chạy được", _thoi_luong(m["chay_giay"]), goi_y=f"Khởi động lúc {_ngay_vn(m['chay_tu'])}")
        _dong("Python / PID", f"{m['python']} / {m['pid']}")
        if m.get("cpu") is not None:
            _dong("CPU cả máy", f"{m['cpu']} %", canh_bao=m["cpu"] >= 90)
        _dong("RAM tiến trình backend", _dung_luong(m.get("ram_backend")),
              goi_y="Không gồm tiến trình con chạy đối chiếu")
        ram = m.get("ram")
        if ram:
            dung = ram["tong"] - ram["con_trong"]
            _thanh(dung / ram["tong"], f"RAM máy: dùng {_dung_luong(dung)} / {_dung_luong(ram['tong'])}")


def _ve_tai(t: dict):
    with _the("Tải hiện tại", "speed"):
        if not t:
            ui.label("Không đọc được số liệu tải — xem app.log").classes("text-sm text-red-600")
            return
        _dong("Request đang xử lý", _so(t["dang_xu_ly"]))
        _dong("Luồng xử lý", f"{t['luong_dung']}/{t['luong_toi_da']}" + (f" · chờ {t['luong_cho']}" if t["luong_cho"] else ""),
              canh_bao=bool(t["luong_cho"]))
        _dong("Kết nối CSDL", f"{t['csdl_dang_muon']}/{t['csdl_toi_da']}" + (f" · chờ {t['csdl_xep_cong']}" if t["csdl_xep_cong"] else ""),
              canh_bao=bool(t["csdl_xep_cong"]))
        _dong("Việc nặng (xuất file…)", f"{t['nang_dang_chay']}/{t['nang_toi_da']}" + (f" · chờ {t['nang_dang_cho']}" if t["nang_dang_cho"] else ""))
        if t.get("loop_chan_max_ms") is None:
            _dong("Độ phản hồi (1 phút)", "không đo")
        else:
            _dong("Đứng lâu nhất (1 phút)", f"{t['loop_chan_max_ms']} ms", canh_bao=t["loop_chan_max_ms"] >= 1000,
                  goi_y="Khoảng thời gian dài nhất backend không phản hồi được ai. Dưới 100 ms là bình thường.")
            _dong("Tổng thời gian trễ (1 phút)", f"{t['loop_tre_tong_ms']} ms",
                  goi_y="Cộng dồn các lần backend phải chờ. Lớn mà 'đứng lâu nhất' nhỏ: đang chạy đối chiếu nặng.")
        _dong("Hàng đợi ghi nhật ký", f"{t['hang_doi_nhat_ky']}/{t['hang_doi_nhat_ky_toi_da']}")


def _ve_csdl_dia(c: dict, dia: dict):
    with _the("Cơ sở dữ liệu & ổ đĩa", "storage"):
        if c["ok"]:
            _dong("Truy vấn thử", f"đọc được · {c['ms']} ms")
        else:
            _dong("Truy vấn thử", "LỖI", canh_bao=True, goi_y=c.get("loi") or "")
        _dong("File CSDL", _dung_luong(dia.get("csdl")))
        _dong("File WAL", _dung_luong(dia.get("wal")), goi_y="Nhật ký ghi trước của SQLite — tự thu về sau mỗi lần ghi")
        _dong("Bản sao lưu", _dung_luong(dia.get("sao_luu")))
        _dong("Nhật ký (logs/)", _dung_luong(dia.get("nhat_ky")))
        chi_tiet = ", ".join(f"{k.removeprefix('temp_')} {_dung_luong(v)}" for k, v in dia.get("tam_chi_tiet", {}).items() if v)
        _dong("File tạm (data/temp_*)", _dung_luong(dia.get("tam")), goi_y=chi_tiet or "Trống — dọn lúc 23h hằng ngày")
        od = dia.get("o_dia")
        if od and od["tong"]:
            dung = od["tong"] - od["con_trong"]
            _thanh(dung / od["tong"], f"Ổ {od['o']}: còn trống {_dung_luong(od['con_trong'])} / {_dung_luong(od['tong'])}")


def _ve_sao_luu(bk: dict, dh: dict):
    with _the("Sao lưu & đồng hồ", "backup"):
        if bk.get("exists"):
            tuoi = bk.get("tuoi_gio")
            _dong("Sao lưu tự động gần nhất", bk["time"], canh_bao=tuoi is not None and tuoi >= 26)
            if tuoi is not None:
                _dong("Cách đây", f"{tuoi:g} giờ".replace(".", ","), canh_bao=tuoi >= 26)
            _dong("Số bản đang giữ", f"{bk.get('count', 0)}" + (f" + {bk['count_thu_cong']} bản đặt tay" if bk.get("count_thu_cong") else ""))
        else:
            _dong("Sao lưu tự động", "chưa có bản nào", canh_bao=True)
        if not dh.get("enabled"):
            _dong("Đồng bộ giờ NTP", "đã tắt")
        elif dh.get("error"):
            _dong("Đồng bộ giờ NTP", "không kiểm tra được", goi_y=dh["error"])
        else:
            _dong("Lệch so với NTP", f"{dh['drift_seconds']} giây", canh_bao=not dh.get("ok"),
                  goi_y=f"Nguồn {dh['server']}, ngưỡng {dh.get('threshold')} giây")


def _ve_nguoi_dung(nd: dict):
    with _the("Người dùng (24 giờ qua)", "group"):
        _dong("Phiên đăng nhập còn hiệu lực", _so(nd.get("phien")))
        _dong("Đăng nhập thành công", _so(nd.get("dang_nhap_ok")))
        _dong("Đăng nhập thất bại", _so(nd.get("dang_nhap_sai")), canh_bao=(nd.get("dang_nhap_sai") or 0) >= 20)
        _dong("Tài khoản đang bị khoá tạm", _so(nd.get("bi_khoa")), canh_bao=bool(nd.get("bi_khoa")),
              goi_y="Khoá do nhập sai mật khẩu nhiều lần — tự mở sau thời gian khoá")
        _dong("Thao tác ghi dữ liệu", _so(nd.get("thao_tac")))
        if api.has_feature("menu.logs"):
            ui.link("Xem nhật ký đăng nhập →", "/audit-logs?tab=dang-nhap&khoang=7&success=false").classes("text-xs text-red-700 mt-1")


def _ve_doi_chieu(t: dict):
    with _the("Đối chiếu & dịch vụ nền", "compare_arrows"):
        if not t:
            ui.label("Không đọc được — xem app.log").classes("text-sm text-red-600")
            return
        ds = t.get("doi_chieu") or []
        _dong("Lượt đối chiếu đang chạy", f"{len(ds)}/{t['doi_chieu_toi_da']}",
              goi_y=f"Ngân sách RAM cho các lượt chạy cùng lúc: {t['doi_chieu_ngan_sach_ram_gb']:g} GB".replace(".", ","))
        for j in ds:
            tuoi = j.get("tuoi_giay")
            with ui.row().classes("items-center gap-2 ml-1"):
                ui.icon("sync").classes("text-sm text-blue-600")
                ui.label(f"{j.get('ten_module', j.get('module'))} — {j.get('status', '')}"
                         + (f" · {_thoi_luong(tuoi)}" if tuoi is not None else "")).classes("text-xs text-gray-700")
        _dong("Word nền (in đơn nghỉ phép)", "đang chạy" if t.get("word_nen") else "đang tắt",
              goi_y="Tự bật khi có người mở màn Nghỉ phép, tự tắt khi rảnh 15 phút")


def _ve_nhat_ky(nk: dict):
    with _the("Nhật ký ứng dụng (24 giờ qua)", "receipt_long"):
        if not nk.get("day_du", True):
            ui.label(f"⚠ Nhật ký đã xoay vòng hết — chỉ đếm được từ {_ngay_vn(nk.get('tu_luc'))}").classes(
                "text-xs text-orange-600")
        with ui.row().classes("w-full gap-6 flex-wrap"):
            for nhan, so, mau in (("Lỗi", nk["loi"], "text-red-600"),
                                  ("Cảnh báo", nk["canh_bao"], "text-orange-500"),
                                  ("Request chậm", nk["request_cham"], "text-gray-700")):
                with ui.column().classes("gap-0"):
                    ui.label(str(so)).classes(f"text-2xl font-semibold {mau if so else 'text-gray-400'}")
                    ui.label(nhan).classes("text-xs text-gray-500")
        if nk.get("loi_gan"):
            ui.label("Lỗi gần nhất").classes("text-xs font-semibold text-gray-600 mt-2")
            for e in nk["loi_gan"]:
                with ui.row().classes("w-full items-start gap-2 no-wrap border-b border-gray-100 py-1"):
                    ui.label(_ngay_vn(e["ts"])).classes("text-xs font-mono text-gray-500 w-32 shrink-0")
                    ui.label(e["nguon"]).classes("text-xs font-mono text-gray-500 w-40 shrink-0 truncate")
                    ui.label(e["msg"]).classes("text-xs text-gray-800 flex-1 break-all")
        if api.has_feature("menu.logs"):
            ui.link("Xem lỗi hệ thống →", "/audit-logs?tab=loi&khoang=7").classes("text-xs text-red-700 mt-1")


@ui.page("/monitor")
async def monitor_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.monitor"):
        ui.navigate.to("/home")
        return
    _ = await _sidebar("monitor")

    with _content_area():
        _page_header("Giám sát hệ thống", "Tổng quan tình trạng máy chủ — số liệu lấy trực tiếp từ backend")

        with ui.row().classes("w-full items-center gap-3 mb-3"):
            nut = ui.button("Làm mới", icon="refresh").classes("bg-gray-700 text-white text-sm")
            tu_dong = ui.switch(f"Tự làm mới mỗi {_LAM_MOI_GIAY} giây", value=True).classes("text-sm")
            luc_lbl = ui.label("Đang tải...").classes("text-xs text-gray-500")
        khung = ui.column().classes("w-full gap-4")

        dang_tai = [False]

        async def _tai():
            if dang_tai[0]:
                return          # lượt trước chưa xong (backend đo CPU + quét nhật ký) — không chồng lượt
            dang_tai[0] = True
            try:
                d = await asyncio.to_thread(api.get, "/api/admin/monitor/overview")
            except Exception as e:
                if _handle_api_error(e):
                    return
                _log.warning("Không tải được số liệu giám sát", exc_info=True)
                # XOÁ bản vẽ cũ: để nguyên là banner xanh lần trước nằm đó đúng lúc backend hỏng
                _ve_loi(khung, e)
                luc_lbl.set_text("")
                return
            finally:
                dang_tai[0] = False
            _ve(khung, d)
            luc_lbl.set_text(f"Cập nhật lúc {(d.get('luc') or '')[11:19]}")

        nut.on_click(_tai)
        # immediate=True (mặc định): lượt tải đầu chạy ngay khi trang kết nối — trang mở
        # không phải chờ backend đo CPU + quét nhật ký
        dong_ho = ui.timer(_LAM_MOI_GIAY, _tai)
        tu_dong.bind_value_to(dong_ho, "active")
