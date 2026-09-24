"""Trang Giám sát hệ thống — nền tối, tổng quan tải / CSDL / ổ đĩa / sao lưu / nhật ký.

Hai nguyên tắc của trang này:

* **Ngưỡng do backend tính** (`backend/api/monitor.py::danh_gia`). Frontend chỉ vẽ —
  hai bảng ngưỡng ở hai nơi sẽ lệch nhau ngay lần sửa đầu tiên.
* **Biểu đồ chỉ ở chỗ dữ liệu có "hình"**: phần–toàn thể (ổ đĩa), diễn biến theo thời
  gian (nhật ký / đăng nhập theo giờ, độ phản hồi 5 phút). Một con số hiện tại thì đọc
  bằng số hoặc thanh mức, KHÔNG dựng biểu đồ một cột — xem card 159 Implementation-notes.

Màu lấy từ bảng màu đã kiểm cho **nền tối** (bước màu riêng cho nền tối, không phải lật
màu của nền sáng). Màu trạng thái luôn đi kèm chữ/nhãn, không bao giờ để màu nói một mình.
"""
import asyncio
import logging

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _require_auth, _handle_api_error

_log = logging.getLogger(__name__)

_LAM_MOI_GIAY = 30

# ── Màu nền tối ──
_NEN = "#0d0d0d"            # nền trang
_THE = "#1a1a19"            # nền thẻ = nền vùng vẽ biểu đồ
_VIEN = "rgba(255,255,255,0.10)"
_MUC1, _MUC2, _MO = "#ffffff", "#c3c2b7", "#898781"
_LUOI, _TRUC = "#2c2c2a", "#383835"
# Trạng thái (cố định, không bao giờ dùng làm màu "chuỗi thứ 4")
_TOT, _CANH, _LOI = "#0ca30c", "#fab219", "#d03b3b"
# Bốn ô màu phân loại đầu tiên — thứ tự này là cơ chế an toàn cho người mù màu, đừng đảo
_S1, _S2, _S3, _S4 = "#3987e5", "#d95926", "#199e70", "#c98500"
_S_KHAC = "#6b6a64"         # "Khác" — xám, không phải một hue mới
_S_TRONG = "#2c2c2a"        # phần còn trống: đường ray, không phải một hạng mục

_TONG_THE = {
    "tot":      ("check_circle", "Hệ thống hoạt động bình thường", _TOT),
    "canh_bao": ("warning",      "Có mục cần chú ý",               _CANH),
    "loi":      ("error",        "Có sự cố cần xử lý",             _LOI),
}


# ── Định dạng ──
def _dung_luong(b) -> str:
    if b is None:
        return "—"
    for don_vi in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or don_vi == "TB":
            return f"{b:.0f} {don_vi}" if don_vi in ("B", "KB") else f"{b:.1f} {don_vi}".replace(".", ",")
        b /= 1024


def _gb(b) -> float:
    """Byte → GB, 2 số lẻ. Giá trị đưa vào biểu đồ; số chính xác vẫn nằm ở các dòng số."""
    return round((b or 0) / 1024 ** 3, 2)


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


# ── Khối vẽ dùng chung ──
def _the(tieu_de: str, icon: str, rong: str = ""):
    khung = ui.element("div").classes("w-full rounded-xl overflow-hidden " + rong).style(
        f"background:{_THE}; border:1px solid {_VIEN}")
    with khung:
        with ui.row().classes("w-full items-center gap-2 px-4 py-2.5").style(
                f"background:rgba(255,255,255,0.04); border-bottom:1px solid {_VIEN}"):
            ui.icon(icon).classes("text-lg").style(f"color:{_MO}")
            ui.label(tieu_de).classes("font-semibold text-sm").style(f"color:{_MUC2}")
        return ui.column().classes("w-full px-4 py-3 gap-1.5")


def _dong(nhan: str, gia_tri: str, canh_bao: bool = False, goi_y: str = ""):
    with ui.row().classes("w-full items-baseline justify-between gap-3 no-wrap"):
        ui.label(nhan).classes("text-xs shrink-0").style(f"color:{_MO}")
        lbl = ui.label(gia_tri).classes("text-sm font-medium text-right").style(
            f"color:{_CANH if canh_bao else _MUC1}")
        if goi_y:
            lbl.tooltip(goi_y)


def _thanh_muc(ti_le: float, nhan: str, goi_y: str = ""):
    """Thanh mức: MỘT tỷ lệ so với trần. Đây là chỗ KHÔNG nên dựng biểu đồ — một con
    số so với hạn mức thì thanh mức đọc nhanh hơn mọi loại biểu đồ (và biểu đồ một cột
    là lỗi kinh điển). Dựng bằng div lồng thay vì ui.linear_progress: Quasar tô đường
    ray bằng chính màu chính ở độ mờ thấp, trên nền tối ra một dải gần như vô hình."""
    ti_le = max(0.0, min(1.0, ti_le))
    mau = _LOI if ti_le >= 0.9 else _CANH if ti_le >= 0.75 else _TOT
    # Nhãn ĐẶT TRÊN thanh: để dưới thì mắt gán nó cho thanh kế tiếp khi xếp nhiều thanh liền nhau
    with ui.column().classes("w-full gap-0.5 mt-1") as box:
        lbl = ui.label(nhan).classes("text-xs").style(f"color:{_MUC2}")
        if goi_y:
            lbl.tooltip(goi_y)
        with ui.element("div").classes("w-full rounded-full overflow-hidden").style(
                f"height:8px; background:{_LUOI}"):
            ui.element("div").classes("h-full rounded-full").style(
                f"width:{ti_le * 100:.1f}%; background:{mau}")
    return box


# ── Khuôn biểu đồ (ECharts) ──
def _khung_do(cao: int) -> dict:
    """Phần chung: nền trong suốt, trục/lưới lùi về sau, chữ theo mực của nền tối."""
    return {
        "backgroundColor": "transparent",
        "textStyle": {"color": _MUC2, "fontSize": 11},
        "grid": {"left": 4, "right": 8, "top": 8, "bottom": 4, "containLabel": True},
        "_cao": cao,
    }


def _ve_do(opt: dict):
    cao = opt.pop("_cao")
    ui.echart(opt).classes("w-full").style(f"height:{cao}px")


def _truc_gio(nhan: list[str]) -> dict:
    return {"type": "category", "data": nhan, "axisTick": {"show": False},
            "axisLine": {"lineStyle": {"color": _TRUC}},
            "axisLabel": {"color": _MO, "fontSize": 10, "interval": 2},
            "splitLine": {"show": False}}


def _truc_so(don_vi: str = "") -> dict:
    return {"type": "value", "minInterval": 1,
            "axisLabel": {"color": _MO, "fontSize": 10, "formatter": f"{{value}}{don_vi}"},
            "splitLine": {"lineStyle": {"color": _LUOI}}}


def _cot(ten: str, mau: str, so: list, xep: str | None = None) -> dict:
    """Cột mảnh, đầu cột bo 4px, khe 2px màu nền giữa các lớp xếp chồng."""
    s = {"name": ten, "type": "bar", "data": so, "barMaxWidth": 18,
         "itemStyle": {"color": mau, "borderRadius": [3, 3, 0, 0]}}
    if xep:
        s["stack"] = xep
        s["itemStyle"]["borderColor"] = _THE
        s["itemStyle"]["borderWidth"] = 1
    return s


def _chu_thich(ten: list[str]) -> dict:
    """Từ 2 chuỗi trở lên LUÔN có chú thích — không để màu tự nói tên chuỗi."""
    return {"data": ten, "bottom": 0, "itemHeight": 8, "itemWidth": 10,
            "textStyle": {"color": _MUC2, "fontSize": 11}}


# ── Các thẻ ──
def _ve(khung, d: dict):
    khung.clear()
    with khung:
        icon, tieu_de, mau = _TONG_THE.get(d.get("tong_the"), _TONG_THE["canh_bao"])
        with ui.column().classes("w-full rounded-xl px-4 py-3 gap-1").style(
                f"background:{_THE}; border:1px solid {mau}; border-left:4px solid {mau}"):
            with ui.row().classes("items-center gap-2"):
                ui.icon(icon).classes("text-2xl").style(f"color:{mau}")
                ui.label(tieu_de).classes("font-semibold").style(f"color:{_MUC1}")
            for c in d.get("canh_bao", []):
                m = _LOI if c["muc"] == "loi" else _CANH
                with ui.row().classes("items-center gap-2 ml-1"):
                    ui.icon("error" if c["muc"] == "loi" else "warning").classes("text-base").style(f"color:{m}")
                    ui.label(f"{c['nhom']}: {c['noi_dung']}").classes("text-sm").style(f"color:{_MUC2}")

        # Ba biểu đồ nhìn lại 24 giờ đặt NGAY dưới dải trạng thái: câu hỏi đầu tiên của
        # người mở trang là "hôm nay có lúc nào suýt hỏng không", không phải "ngay lúc này ra sao"
        _ve_lich_su(d)

        with ui.element("div").classes(
                "w-full grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4").style("align-items:start"):
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
        with ui.column().classes("w-full rounded-xl px-4 py-3 gap-1").style(
                f"background:{_THE}; border:1px solid {_LOI}; border-left:4px solid {_LOI}"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("error").classes("text-2xl").style(f"color:{_LOI}")
                ui.label("Không lấy được số liệu từ backend").classes("font-semibold").style(f"color:{_MUC1}")
            ui.label("Backend có thể đang tắt, quá tải hoặc lỗi. Trang sẽ tự thử lại.").classes(
                "text-sm").style(f"color:{_MUC2}")
            ui.label(str(e)[:300]).classes("text-xs break-all").style(f"color:{_MO}")


def _duong(ten: str, mau: str, so: list) -> dict:
    """Đường 2px, không chấm điểm (144 điểm mà chấm hết thì thành dải hạt).

    `connectNulls` để MẶC ĐỊNH (False): ô không có mẫu là backend lúc ấy không chạy,
    đường phải ĐỨT ở đó. Nối liền qua chỗ trống là vẽ ra một đoạn dữ liệu không hề tồn tại.
    """
    return {"name": ten, "type": "line", "data": so, "showSymbol": False, "smooth": False,
            "lineStyle": {"width": 2, "color": mau}, "itemStyle": {"color": mau}}


def _vach_nguong(muc: float, chu: str) -> dict:
    return {"silent": True, "symbol": "none",
            "lineStyle": {"color": _LOI, "type": "dashed", "width": 1},
            # insideEndTop: để mặc định thì chữ rơi ra ngoài mép phải và bị cắt
            "label": {"formatter": chu, "color": _LOI, "fontSize": 10, "position": "insideEndTop"},
            "data": [{"yAxis": muc}]}


_CACH_GIO_NHAN = 3      # ghi nhãn giờ cách nhau 3 tiếng


def _truc_luc(ls: list) -> dict:
    """Trục thời gian: chỉ ghi nhãn mỗi 3 giờ tròn.

    Ghi nhãn ở MỌI giờ tròn (24 nhãn trên ~430 px) thì chữ dính vào nhau thành một
    vệt "16:07:08:09:20:21…" không đọc được gì — ảnh chụp lần đầu đúng như vậy.
    """
    nhan = [o["luc"] if o["luc"].endswith(":00") and int(o["luc"][:2]) % _CACH_GIO_NHAN == 0 else ""
            for o in ls]
    return {"type": "category", "data": nhan,
            "axisTick": {"show": False}, "axisLine": {"lineStyle": {"color": _TRUC}},
            "axisLabel": {"color": _MO, "fontSize": 10, "interval": 0},
            "splitLine": {"show": False}}


def _do_24h(ls: list, chuoi: list, don_vi: str, tran: "float | None", vach: "tuple | None",
            an_nhan_y: bool = False, cao: int = 170):
    if vach:
        chuoi[0]["markLine"] = _vach_nguong(*vach)
    opt = _khung_do(cao)
    opt.update({
        "grid": {"left": 4, "right": 12, "top": 10, "bottom": 40, "containLabel": True},
        "tooltip": {"trigger": "axis", "backgroundColor": _THE, "borderColor": _VIEN,
                    "textStyle": {"color": _MUC1, "fontSize": 11}},
        "xAxis": _truc_luc(ls),
        # ECharts tự chèn dấu PHẨY hàng nghìn ("1,200 ms") mà không cho thay bằng hàm
        # JS qua NiceGUI — trong tiếng Việt dấu phẩy là dấu thập phân nên đọc thành 1,2 ms.
        # Với trục mili giây thì bỏ hẳn nhãn: vạch ngưỡng + câu chú dẫn + tooltip đã nói đủ.
        "yAxis": {**_truc_so(don_vi), **({"max": tran} if tran else {}),
                  **({"axisLabel": {"show": False}} if an_nhan_y else {})},
        "series": chuoi,
    })
    # Từ 2 chuỗi trở lên mới cần chú thích; một chuỗi thì tiêu đề thẻ đã gọi tên nó
    if len(chuoi) > 1:
        opt["legend"] = _chu_thich([s["name"] for s in chuoi])
    _ve_do(opt)


def _ve_lich_su(d: dict):
    """Ba biểu đồ nhìn lại 24 giờ — lý do tồn tại của cả bộ lấy mẫu nền.

    Người vận hành không ngồi canh 24/24: mở trang lúc 3h chiều mà RAM đang 40 % thì
    không có cách nào biết 10h sáng nó đã lên 93 %. Ba biểu đồ này trả lời đúng câu
    "trong một ngày qua đã có lúc nào cận ngưỡng chưa".
    """
    ls = d.get("lich_su")
    if not ls:
        with _the("Nhìn lại 24 giờ qua", "show_chart"):
            ui.label("Chưa có số liệu — bộ lấy mẫu bắt đầu ghi từ lúc backend khởi động, "
                     "mỗi phút một điểm.").classes("text-sm").style(f"color:{_MO}")
        return
    buoc = d.get("lich_su_buoc_phut", 10)

    def dinh(cot):
        return max((o[cot] for o in ls if o[cot] is not None), default=None)

    with ui.element("div").classes(
            "w-full grid grid-cols-1 xl:grid-cols-3 gap-4").style("align-items:start"):
        # 1) CPU + RAM: hai chuỗi CÙNG đơn vị % → chung một trục. Không bao giờ hai trục y.
        with _the("CPU & RAM máy chủ — 24 giờ", "memory"):
            _chu_dan(f"Cao nhất: CPU {_pt(dinh('cpu'))}, RAM {_pt(dinh('ram_pct'))}. "
                     f"Mỗi điểm là mức CAO NHẤT trong {buoc} phút.")
            _do_24h(ls, [_duong("CPU", _S1, [o["cpu"] for o in ls]),
                         _duong("RAM", _S2, [o["ram_pct"] for o in ls])],
                    " %", 100, (90, "ngưỡng 90 %"))

        # 2) Ba bể tài nguyên quy về % SỨC CHỨA của chính nó — nhờ vậy chung được một trục
        with _the("Mức dùng bể tài nguyên — 24 giờ", "speed"):
            _chu_dan("Tính theo phần trăm sức chứa của từng bể (luồng 40, kết nối 48, việc nặng 4). "
                     "Chạm 100 % là có người phải xếp hàng chờ.")
            _do_24h(ls, [_duong("Luồng xử lý", _S1, [o["luong_pct"] for o in ls]),
                         _duong("Kết nối CSDL", _S2, [o["csdl_pct"] for o in ls]),
                         _duong("Việc nặng", _S3, [o["nang_pct"] for o in ls])],
                    " %", 100, (90, "gần đầy"))

        # 3) Độ phản hồi: ms — đơn vị khác hẳn nên PHẢI là biểu đồ riêng
        with _the("Độ phản hồi của backend — 24 giờ", "timer"):
            _chu_dan(f"Lần đứng lâu nhất trong mỗi {buoc} phút. Cao nhất 24 giờ qua: "
                     f"{_so(dinh('loop_ms'))} ms. Dưới 100 ms là bình thường.")
            _do_24h(ls, [_duong("Đứng lâu nhất", _S1, [o["loop_ms"] for o in ls])],
                    " ms", None, (1000, "ngưỡng 1000 ms"), an_nhan_y=True)


def _chu_dan(chu: str):
    ui.label(chu).classes("text-xs leading-snug").style(f"color:{_MO}")


def _pt(v) -> str:
    return "—" if v is None else f"{v:g} %".replace(".", ",")


def _ve_may_chu(m: dict):
    with _the("Máy chủ", "dns"):
        _dong("Tên máy", m["ten_may"])
        _dong("Backend chạy được", _thoi_luong(m["chay_giay"]), goi_y=f"Khởi động lúc {_ngay_vn(m['chay_tu'])}")
        _dong("Python / PID", f"{m['python']} / {m['pid']}")
        _dong("RAM tiến trình backend", _dung_luong(m.get("ram_backend")),
              goi_y="Không gồm tiến trình con chạy đối chiếu")
        if m.get("cpu") is not None:
            _thanh_muc(m["cpu"] / 100, f"CPU cả máy: {m['cpu']} %".replace(".", ","),
                       goi_y="Đo trong 0,3 giây lúc mở/làm mới trang — là ảnh chụp, không phải trung bình cả ngày")
        ram = m.get("ram")
        if ram:
            dung = ram["tong"] - ram["con_trong"]
            _thanh_muc(dung / ram["tong"],
                       f"RAM máy: dùng {_dung_luong(dung)} / {_dung_luong(ram['tong'])} ({ram['phan_tram']} %)")


def _ve_tai(t: dict):
    """Bốn bể tài nguyên = bốn tỷ lệ so với trần → thanh mức, không phải biểu đồ."""
    with _the("Tải hiện tại", "speed"):
        if not t:
            ui.label("Không đọc được số liệu tải — xem app.log").classes("text-sm").style(f"color:{_LOI}")
            return
        _dong("Request đang xử lý", _so(t["dang_xu_ly"]))
        for nhan, dung, toi_da, cho, goi_y in (
            ("Luồng xử lý", t["luong_dung"], t["luong_toi_da"], t["luong_cho"],
             "Bể luồng chung của backend. Hết luồng là mọi người phải xếp hàng."),
            ("Kết nối CSDL", t["csdl_dang_muon"], t["csdl_toi_da"], t["csdl_xep_cong"],
             "Số kết nối tới cơ sở dữ liệu đang được mượn."),
            ("Việc nặng (xuất file…)", t["nang_dang_chay"], t["nang_toi_da"], t["nang_dang_cho"],
             "Sinh Word/Excel, giải nén — cố ý giới hạn để việc nhẹ không bị bỏ đói."),
        ):
            _thanh_muc(dung / toi_da if toi_da else 0,
                       f"{nhan}: {dung}/{toi_da}" + (f" · {cho} đang chờ" if cho else ""), goi_y=goi_y)
        _thanh_muc((t["hang_doi_nhat_ky"] / t["hang_doi_nhat_ky_toi_da"]) if t["hang_doi_nhat_ky_toi_da"] else 0,
                   f"Hàng đợi ghi nhật ký: {t['hang_doi_nhat_ky']}/{t['hang_doi_nhat_ky_toi_da']}",
                   goi_y="Tồn nhiều nghĩa là cơ sở dữ liệu đang ghi chậm")


def _ve_csdl_dia(c: dict, dia: dict):
    with _the("Cơ sở dữ liệu & ổ đĩa", "storage"):
        if c["ok"]:
            _dong("Truy vấn thử", f"đọc được · {c['ms']} ms".replace(".", ","))
        else:
            _dong("Truy vấn thử", "LỖI", canh_bao=True, goi_y=c.get("loi") or "")
        # Giữ NGUYÊN các dòng số: biểu đồ thành phần chỉ trả lời "cái gì chiếm chỗ",
        # còn số chính xác (và bản đọc được cho người dùng trình đọc) nằm ở đây
        _dong("File CSDL", _dung_luong(dia.get("csdl")))
        _dong("File WAL", _dung_luong(dia.get("wal")), goi_y="Nhật ký ghi trước của SQLite — tự thu về sau mỗi lần ghi")
        _dong("Bản sao lưu", _dung_luong(dia.get("sao_luu")))
        _dong("Nhật ký (logs/)", _dung_luong(dia.get("nhat_ky")))
        chi_tiet = ", ".join(f"{k.removeprefix('temp_')} {_dung_luong(v)}"
                             for k, v in dia.get("tam_chi_tiet", {}).items() if v)
        _dong("File tạm (data/temp_*)", _dung_luong(dia.get("tam")),
              goi_y=chi_tiet or "Trống — dọn lúc 23h hằng ngày")
        _ve_thanh_phan_dia(dia)


def _ve_thanh_phan_dia(dia: dict):
    """Ổ đĩa tách làm HAI câu hỏi, mỗi câu một hình đúng với nó.

    Bản đầu vẽ một cột xếp chồng "toàn bộ ổ đĩa": phần của Windows và phần còn trống
    chiếm 99 %, bốn mục của dự án gộp lại chỉ còn một vệt mỏng không đọc được gì — đúng
    cái bẫy phần–toàn thể khi các phần chênh nhau hàng trăm lần. Nay:
      1. Ổ còn bao nhiêu chỗ → thanh mức (một tỷ lệ so với trần).
      2. Dự án đang chiếm chỗ ở đâu → cột ngang so độ lớn, một màu, có nhãn số từng cột.
    """
    od = dia.get("o_dia")
    if not od or not od.get("tong"):
        ui.label("Không đọc được dung lượng ổ đĩa").classes("text-sm mt-1").style(f"color:{_CANH}")
        return
    da_dung = dia.get("da_dung", od["tong"] - od["con_trong"])
    _thanh_muc(da_dung / od["tong"],
               f"Ổ {od['o']}: đã dùng {_dung_luong(da_dung)} / {_dung_luong(od['tong'])}"
               f" · còn trống {_dung_luong(od['con_trong'])}",
               goi_y=f"Trong đó thứ khác trên ổ (Windows, phần mềm, dữ liệu ngoài dự án) "
                     f"chiếm {_dung_luong(dia.get('khac'))}")

    muc = [("File tạm", dia.get("tam")), ("Bản sao lưu", dia.get("sao_luu")),
           ("Nhật ký", dia.get("nhat_ky")), ("CSDL + WAL", (dia.get("csdl") or 0) + (dia.get("wal") or 0))]
    if not any(v for _, v in muc):
        return
    mb = [round((v or 0) / 1024 ** 2, 1) for _, v in muc]
    opt = _khung_do(20 + 26 * len(muc))
    opt.update({
        "grid": {"left": 4, "right": 64, "top": 4, "bottom": 4, "containLabel": True},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} MB",
                    "backgroundColor": _THE, "borderColor": _VIEN,
                    "textStyle": {"color": _MUC1, "fontSize": 11}},
        "xAxis": {"type": "value", "show": False},
        "yAxis": {"type": "category", "data": [t for t, _ in muc], "inverse": True,
                  "axisTick": {"show": False}, "axisLine": {"show": False},
                  "axisLabel": {"color": _MO, "fontSize": 11}},
        # MỘT chuỗi → một màu cho mọi cột. Tô đậm nhạt theo độ lớn là mã hoá hai lần
        # cùng một thông tin mà chiều dài cột đã nói rồi.
        "series": [{"type": "bar", "barMaxWidth": 12, "itemStyle": {"color": _S1, "borderRadius": [0, 3, 3, 0]},
                    "data": [{"value": v,
                              "label": {"show": True, "position": "right", "color": _MUC2, "fontSize": 11,
                                        "formatter": _dung_luong(b)}}
                             for v, (_, b) in zip(mb, muc)]}],
    })
    _ve_do(opt)


def _ve_sao_luu(bk: dict, dh: dict):
    with _the("Sao lưu & đồng hồ", "backup"):
        if bk.get("exists"):
            tuoi = bk.get("tuoi_gio")
            _dong("Sao lưu tự động gần nhất", bk["time"], canh_bao=tuoi is not None and tuoi >= 26)
            if tuoi is not None:
                _dong("Cách đây", f"{tuoi:g} giờ".replace(".", ","), canh_bao=tuoi >= 26)
                # Một tỷ lệ so với hạn 26 giờ — thanh mức, không biểu đồ
                _thanh_muc(tuoi / 26, "Mức trễ so với chu kỳ 24 giờ",
                           goi_y="Đầy thanh = đã quá 26 giờ không có bản sao lưu tự động nào")
            _dong("Số bản đang giữ", f"{bk.get('count', 0)}"
                  + (f" + {bk['count_thu_cong']} bản đặt tay" if bk.get("count_thu_cong") else ""))
        else:
            _dong("Sao lưu tự động", "chưa có bản nào", canh_bao=True)
        if not dh.get("enabled"):
            _dong("Đồng bộ giờ NTP", "đã tắt")
        elif dh.get("error"):
            _dong("Đồng bộ giờ NTP", "không kiểm tra được", goi_y=dh["error"])
        else:
            _dong("Lệch so với NTP", f"{dh['drift_seconds']} giây".replace(".", ","), canh_bao=not dh.get("ok"),
                  goi_y=f"Nguồn {dh['server']}, ngưỡng {dh.get('threshold')} giây")


def _ve_nguoi_dung(nd: dict):
    with _the("Người dùng (24 giờ qua)", "group"):
        _dong("Phiên đăng nhập còn hiệu lực", _so(nd.get("phien")))
        _dong("Đăng nhập thành công", _so(nd.get("dang_nhap_ok")))
        _dong("Đăng nhập thất bại", _so(nd.get("dang_nhap_sai")),
              canh_bao=(nd.get("dang_nhap_sai") or 0) >= 20)
        _dong("Tài khoản đang bị khoá tạm", _so(nd.get("bi_khoa")), canh_bao=bool(nd.get("bi_khoa")),
              goi_y="Khoá do nhập sai mật khẩu nhiều lần — tự mở sau thời gian khoá")
        _dong("Thao tác ghi dữ liệu", _so(nd.get("thao_tac")))
        _ve_dang_nhap_gio(nd.get("theo_gio"))
        if api.has_feature("menu.logs"):
            ui.link("Xem nhật ký đăng nhập →",
                    "/audit-logs?tab=dang-nhap&khoang=7&success=false").classes("text-xs mt-1").style(f"color:{_S1}")


def _ve_dang_nhap_gio(theo_gio):
    """Đăng nhập theo từng giờ — thấy giờ cao điểm, và thấy CỤM đăng nhập sai
    (dấu hiệu dò mật khẩu) mà con số tổng 24 giờ che mất."""
    if not theo_gio or not any(o["ok"] or o["sai"] for o in theo_gio):
        ui.label("Chưa có lượt đăng nhập nào trong 24 giờ").classes("text-xs mt-1").style(f"color:{_MO}")
        return
    opt = _khung_do(140)
    opt.update({
        "grid": {"left": 4, "right": 8, "top": 8, "bottom": 22, "containLabel": True},
        "tooltip": {"trigger": "axis", "backgroundColor": _THE, "borderColor": _VIEN,
                    "textStyle": {"color": _MUC1, "fontSize": 11}},
        "xAxis": _truc_gio([o["gio"] for o in theo_gio]),
        "yAxis": _truc_so(),
        "legend": _chu_thich(["Thành công", "Thất bại"]),
        "series": [_cot("Thành công", _TOT, [o["ok"] for o in theo_gio], "dn"),
                   _cot("Thất bại", _LOI, [o["sai"] for o in theo_gio], "dn")],
    })
    _ve_do(opt)


def _ve_doi_chieu(t: dict):
    with _the("Đối chiếu & dịch vụ nền", "compare_arrows"):
        if not t:
            ui.label("Không đọc được — xem app.log").classes("text-sm").style(f"color:{_LOI}")
            return
        ds = t.get("doi_chieu") or []
        _thanh_muc(len(ds) / t["doi_chieu_toi_da"] if t["doi_chieu_toi_da"] else 0,
                   f"Lượt đối chiếu đang chạy: {len(ds)}/{t['doi_chieu_toi_da']}",
                   goi_y=f"Ngân sách RAM cho các lượt chạy cùng lúc: "
                         f"{t['doi_chieu_ngan_sach_ram_gb']:g} GB".replace(".", ","))
        # Danh sách lượt đang chạy: văn bản, không biểu đồ — mỗi dòng là một sự việc
        # cụ thể (tên module, trạng thái, đã chạy bao lâu), không phải một con số để so
        for j in ds:
            tuoi = j.get("tuoi_giay")
            with ui.row().classes("items-center gap-2 ml-1"):
                ui.icon("sync").classes("text-sm").style(f"color:{_S1}")
                ui.label(f"{j.get('ten_module', j.get('module'))} — {j.get('status', '')}"
                         + (f" · {_thoi_luong(tuoi)}" if tuoi is not None else "")
                         ).classes("text-xs").style(f"color:{_MUC2}")
        _dong("Word nền (in đơn nghỉ phép)", "đang chạy" if t.get("word_nen") else "đang tắt",
              goi_y="Tự bật khi có người mở màn Nghỉ phép, tự tắt khi rảnh 15 phút")


def _ve_nhat_ky(nk: dict):
    with _the("Nhật ký ứng dụng (24 giờ qua)", "receipt_long"):
        if not nk.get("day_du", True):
            ui.label(f"⚠ Nhật ký đã xoay vòng hết — chỉ đếm được từ {_ngay_vn(nk.get('tu_luc'))}"
                     ).classes("text-xs").style(f"color:{_CANH}")
        with ui.row().classes("w-full gap-8 flex-wrap items-start"):
            # Ba con số headline: ô số, KHÔNG phải biểu đồ ba cột
            for nhan, so, mau in (("Lỗi", nk["loi"], _LOI),
                                  ("Cảnh báo", nk["canh_bao"], _CANH),
                                  ("Request chậm", nk["request_cham"], _MUC1)):
                with ui.column().classes("gap-0"):
                    ui.label(str(so)).classes("text-2xl font-semibold").style(
                        f"color:{mau if so else _MO}")
                    ui.label(nhan).classes("text-xs").style(f"color:{_MO}")
        _ve_nhat_ky_gio(nk.get("theo_gio"))
        if nk.get("loi_gan"):
            ui.label("Lỗi gần nhất").classes("text-xs font-semibold mt-2").style(f"color:{_MUC2}")
            for e in nk["loi_gan"]:
                with ui.row().classes("w-full items-start gap-2 no-wrap py-1").style(
                        f"border-bottom:1px solid {_LUOI}"):
                    ui.label(_ngay_vn(e["ts"])).classes("text-xs font-mono w-32 shrink-0").style(f"color:{_MO}")
                    ui.label(e["nguon"]).classes("text-xs font-mono w-40 shrink-0 truncate").style(f"color:{_MO}")
                    ui.label(e["msg"]).classes("text-xs flex-1 break-all").style(f"color:{_MUC2}")
        if api.has_feature("menu.logs"):
            ui.link("Xem lỗi hệ thống →", "/audit-logs?tab=loi&khoang=7").classes(
                "text-xs mt-1").style(f"color:{_S1}")


def _ve_nhat_ky_gio(theo_gio):
    """Lỗi/cảnh báo theo từng giờ — trả lời "dồn vào một lúc hay rải đều", điều mà
    con số tổng 24 giờ không nói được."""
    if not theo_gio:
        return
    if not any(o["loi"] or o["canh_bao"] for o in theo_gio):
        ui.label("Không có lỗi hay cảnh báo nào trong 24 giờ").classes("text-xs").style(f"color:{_MO}")
        return
    opt = _khung_do(150)
    opt.update({
        "grid": {"left": 4, "right": 8, "top": 8, "bottom": 22, "containLabel": True},
        "tooltip": {"trigger": "axis", "backgroundColor": _THE, "borderColor": _VIEN,
                    "textStyle": {"color": _MUC1, "fontSize": 11}},
        "xAxis": _truc_gio([o["gio"] for o in theo_gio]),
        "yAxis": _truc_so(),
        "legend": _chu_thich(["Lỗi", "Cảnh báo"]),
        "series": [_cot("Lỗi", _LOI, [o["loi"] for o in theo_gio], "nk"),
                   _cot("Cảnh báo", _CANH, [o["canh_bao"] for o in theo_gio], "nk")],
    })
    _ve_do(opt)


@ui.page("/monitor")
async def monitor_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.monitor"):
        ui.navigate.to("/home")
        return
    _ = await _sidebar("monitor")

    # Nền tối chỉ cho trang này. Không dùng _page_header(): tiêu đề của nó là chữ đỏ
    # đậm trên nền sáng, đặt lên nền tối thì gần như không đọc được.
    vung = _content_area()
    vung.classes(remove="bg-gray-50")
    vung.style(f"background:{_NEN}")
    with vung:
        with ui.column().classes("mb-4 gap-1"):
            ui.label("Giám sát hệ thống").classes("text-2xl font-bold").style(f"color:{_MUC1}")
            ui.label("Tổng quan tình trạng máy chủ — số liệu lấy trực tiếp từ backend"
                     ).classes("text-sm").style(f"color:{_MO}")

        with ui.row().classes("w-full items-center gap-3 mb-3"):
            # Nút và công tắc để tông trung tính: màu mặc định của Quasar là xanh dương —
            # trùng đúng màu đang dùng cho DỮ LIỆU trong biểu đồ, nhìn thành "nút cũng là một chuỗi số liệu"
            nut = ui.button("Làm mới", icon="refresh").props("outline color=grey-4").classes("text-sm")
            tu_dong = ui.switch(f"Tự làm mới mỗi {_LAM_MOI_GIAY} giây", value=True).props(
                "color=grey-6").classes("text-sm").style(f"color:{_MUC2}")
            luc_lbl = ui.label("Đang tải...").classes("text-xs").style(f"color:{_MO}")
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
