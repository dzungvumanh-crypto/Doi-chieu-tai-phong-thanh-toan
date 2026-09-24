"""Phần dùng chung của 4 tab Nhật ký hệ thống: bộ lọc ngày, thẻ lọc, phân trang, khung tab."""
import datetime as _dt
import json
import re
from urllib.parse import urlencode

from nicegui import ui

from frontend.shared import _dmy, _iso_tu_dmy, _o_chon_ngay_trong

DUONG_DAN = "/audit-logs"

KHOANG = {"hom_nay": "Hôm nay", "7": "7 ngày", "30": "30 ngày",
          "tat_ca": "Tất cả", "tuy_chon": "Tuỳ chọn…"}
_SO_NGAY = {"hom_nay": 1, "7": 7, "30": 30}
_THU = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Nút bật/tắt dùng chung — cùng màu đỏ của sidebar, không viết hoa
TOGGLE_PROPS = "dense no-caps unelevated toggle-color=red-9 color=grey-2 text-color=grey-9"


def tu_ngay_cua(khoang: str) -> str:
    n = _SO_NGAY.get(khoang)
    return (_dt.date.today() - _dt.timedelta(days=n - 1)).isoformat() if n else ""


def nhan_ngay(iso: str) -> str:
    """'2026-09-22' → 'Hôm nay · 22/09/2026' / 'Hôm qua · …' / 'Thứ Hai · …'."""
    try:
        d = _dt.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    lech = (_dt.date.today() - d).days
    ten = "Hôm nay" if lech == 0 else "Hôm qua" if lech == 1 else _THU[d.weekday()]
    return f"{ten} · {d.strftime('%d/%m/%Y')}"


def gio(ts) -> str:
    """'2026-09-22 10:32:05.123' → '10:32:05'."""
    return str(ts or "")[11:19]


class BoLocNgay:
    """Chọn nhanh khoảng ngày; "Tuỳ chọn…" mới hiện hai ô ngày. Đổi là gọi `on_change`."""

    def __init__(self, on_change, mac_dinh: str = "7"):
        self._cb = on_change
        self._mac_dinh = mac_dinh
        self.chon = ui.toggle(KHOANG, value=mac_dinh, on_change=self._doi).props(TOGGLE_PROPS)
        with ui.row().classes("items-center gap-2") as self.hang:
            self.tu = _o_chon_ngay_trong("Từ ngày")
            self.den = _o_chon_ngay_trong("Đến ngày")
        self.hang.set_visibility(mac_dinh == "tuy_chon")
        self.tu.on_value_change(self._doi_ngay)
        self.den.on_value_change(self._doi_ngay)

    async def _doi(self, _):
        self.hang.set_visibility(self.chon.value == "tuy_chon")
        await self._cb()

    async def _doi_ngay(self, e):
        # Đang gõ dở (vd "03/09/20") thì chưa lọc — chỉ phản ứng khi rỗng hoặc đủ ngày
        v = (e.value or "").strip()
        if not v or _ISO_RE.match(_iso_tu_dmy(v)):
            await self._cb()

    def api(self) -> tuple[str, str]:
        if self.chon.value == "tuy_chon":
            tu, den = _iso_tu_dmy(self.tu.value or ""), _iso_tu_dmy(self.den.value or "")
            return (tu if _ISO_RE.match(tu) else "", den if _ISO_RE.match(den) else "")
        return tu_ngay_cua(self.chon.value), ""

    def url(self) -> dict:
        if self.chon.value == "tuy_chon":
            tu, den = self.api()
            return {"tu_ngay": tu, "den_ngay": den}
        return {"khoang": self.chon.value}

    def dat(self, loc: dict):
        """Đặt từ địa chỉ trang hoặc từ một mục bấm ở tab khác. Không tự tải.
        `loc` không nói gì về ngày → về mặc định, không giữ khoảng của lần lọc trước."""
        if loc.get("khoang") in KHOANG and loc["khoang"] != "tuy_chon":
            self.chon.value = loc["khoang"]
        else:
            tu, den = loc.get("tu_ngay", ""), loc.get("den_ngay", "")
            khop = next((k for k in _SO_NGAY if tu and not den and tu_ngay_cua(k) == tu), None)
            if khop:
                self.chon.value = khop
            elif tu or den:
                self.tu.value, self.den.value = _dmy(tu) if tu else "", _dmy(den) if den else ""
                self.chon.value = "tuy_chon"
            else:
                self.chon.value = self._mac_dinh
        self.hang.set_visibility(self.chon.value == "tuy_chon")

    def mo_ta(self) -> str:
        if self.chon.value != "tuy_chon":
            return KHOANG[self.chon.value]
        tu, den = self.api()
        return f"{_dmy(tu) if tu else '…'} – {_dmy(den) if den else 'nay'}"


def the_loc(khung, the: list[tuple[str, object]], xoa_het=None):
    """Vẽ các điều kiện đang lọc thành thẻ có ✕. `the` = [(nhãn, hàm gỡ)]."""
    khung.clear()
    with khung:
        for nhan, go in the:
            ui.chip(nhan, removable=True, on_value_change=go,
                    color="red-1", text_color="red-10").props("dense").classes("text-xs")
        if xoa_het and len(the) > 1:
            ui.button("Xoá hết lọc", on_click=xoa_het).props("flat dense no-caps size=sm").classes(
                "text-gray-600")


def phan_trang(khung, page: int, pages: int, di_toi):
    khung.clear()
    if pages <= 1:
        return
    with khung:
        ui.button("◀ Trước", on_click=lambda: di_toi(page - 1)).props(
            "flat dense no-caps").set_enabled(page > 1)
        ui.label(f"Trang {page} / {pages}").classes("text-sm text-gray-600 px-2")
        ui.button("Sau ▶", on_click=lambda: di_toi(page + 1)).props(
            "flat dense no-caps").set_enabled(page < pages)


def tieu_de_ngay(iso: str):
    ui.label(nhan_ngay(iso)).classes(
        "w-full text-xs font-semibold text-gray-600 bg-gray-100 px-3 py-1.5 mt-2 "
        "border-y border-gray-200")


class TabNhatKy:
    """Khung chung của một tab: nhớ bộ lọc đã tải để không tải trùng.

    Handler `async` của NiceGUI chạy SAU khi mã gán giá trị cho ô lọc — gán năm ô
    từ địa chỉ trang là năm lượt on_change đến muộn. Không chặn được bằng cờ bật/tắt,
    nên `tai()` so bộ lọc với lần tải trước: trùng thì bỏ qua.
    """
    ten = ""

    def __init__(self, ctx):
        self.ctx = ctx
        self._da_tai = None
        self._luot = 0
        self.page = 1

    def tham_so(self) -> dict:          # tham số gửi API (không gồm trang)
        raise NotImplementedError

    def tham_so_url(self) -> dict:      # tham số ghi lên địa chỉ trang
        return self.tham_so()

    def dat_loc(self, loc: dict):
        raise NotImplementedError

    async def _ve(self, luot: int):
        raise NotImplementedError

    def con_hieu_luc(self, luot: int) -> bool:
        """Lượt tải cũ về muộn hơn lượt mới (bấm lọc liên tục) thì không được vẽ đè."""
        return luot == self._luot

    async def tai(self, page: int = 1, ep: bool = False):
        ts = self.tham_so()
        if not ep and ts == self._da_tai:
            return
        self._da_tai, self.page = ts, page
        self._luot += 1
        self.ctx.ghi_url(self.ten, dict(self.tham_so_url(), page=page if page > 1 else ""))
        await self._ve(self._luot)

    async def mo(self, loc: dict | None = None):
        if loc:
            self.dat_loc(loc)
            try:
                page = max(1, int(loc.get("page") or 1))
            except ValueError:
                page = 1
            await self.tai(page, ep=True)
        elif self._da_tai is None:
            await self.tai()
        else:
            self.ctx.ghi_url(self.ten, dict(self.tham_so_url(), page=self.page if self.page > 1 else ""))


class NhatKyCtx:
    """Nối các tab với nhau: bấm một mục ở tab này mở tab kia với bộ lọc điền sẵn."""

    def __init__(self):
        self.tabs = None
        self.bang: dict[str, TabNhatKy] = {}
        self._dang_chuyen = False

    def ghi_url(self, tab: str, ts: dict):
        # Ghi bộ lọc lên địa chỉ trang: gửi link là người nhận thấy đúng danh sách
        # này, bấm Quay lại / tải lại trang không mất bộ lọc.
        q = urlencode({"tab": tab, **{k: v for k, v in ts.items() if v not in ("", None, 0)}})
        ui.run_javascript(f"history.replaceState(null, '', {json.dumps(DUONG_DAN + '?' + q)})")

    async def mo_tab(self, ten: str, loc: dict | None = None):
        if ten not in self.bang:
            ten = "tong-quan"
        # Đổi tab.value cũng bắn on_change → _khi_doi_tab; cờ này để lượt đó không
        # mở tab lần hai với bộ lọc rỗng.
        # Tab đang mở sẵn thì gán lại không bắn sự kiện — đặt cờ lúc đó là cờ kẹt,
        # nuốt mất lần bấm tab kế tiếp của người dùng.
        if self.tabs.value != ten:
            self._dang_chuyen = True
            self.tabs.value = ten
        await self.bang[ten].mo(loc)

    async def khi_doi_tab(self, e):
        if self._dang_chuyen:
            self._dang_chuyen = False
            return
        await self.bang[e.value].mo()
