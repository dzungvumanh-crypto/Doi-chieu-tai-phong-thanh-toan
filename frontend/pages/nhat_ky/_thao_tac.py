"""Tab Thao tác — ai đã thêm/sửa/xoá gì, kết quả ra sao.

Mỗi dòng đọc như một câu: giờ · người · việc · hồ sơ · kết quả. Bấm tên người hay
nhãn hồ sơ là lọc theo đó; bấm dòng mở ngăn chi tiết bên phải.
"""
import asyncio
import logging
from datetime import date

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _dmy, _handle_api_error

from ._chung import (TOGGLE_PROPS, BoLocNgay, TabNhatKy, gio, phan_trang, the_loc,
                     tieu_de_ngay)

_LOAI = {"": "Mọi loại", "POST": "Thêm mới", "PUT": "Sửa", "DELETE": "Xoá"}
_KET_QUA = {"": "Mọi kết quả", "ok": "Thành công", "loi": "Thất bại"}
_API = "/api/admin/logs/audit"
_log = logging.getLogger(__name__)


def _mau_ket_qua(ok: bool) -> str:
    return "bg-green-100 text-green-800" if ok else "bg-orange-100 text-orange-800"


class TabThaoTac(TabNhatKy):
    ten = "thao-tac"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.doi_tuong = ("", "")          # (khoá, nhãn) — chỉ đặt bằng cách bấm nhãn hồ sơ

        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
            self.ngay = BoLocNgay(self._doi_loc)
        with ui.row().classes("w-full items-center gap-2 flex-wrap mt-2"):
            self.nguoi = ui.select({}, label="Người thao tác", with_input=True, clearable=True,
                                   on_change=self._doi_loc).props("dense outlined").classes("w-60")
            self.module = ui.select({}, label="Chức năng", clearable=True,
                                    on_change=self._doi_loc).props("dense outlined").classes("w-56")
            self.loai = ui.toggle(_LOAI, value="", on_change=self._doi_loc).props(TOGGLE_PROPS)
            self.ket_qua = ui.toggle(_KET_QUA, value="", on_change=self._doi_loc).props(TOGGLE_PROPS)
            self.tim = ui.input(placeholder="Tìm tên, nội dung…", on_change=self._doi_loc).props(
                "dense outlined clearable debounce=500").classes("w-60")
            with self.tim.add_slot("prepend"):
                ui.icon("search").classes("text-gray-400")
        with ui.row().classes("w-full items-center gap-2 mt-2 min-h-[2rem]"):
            self.dong_dem = ui.label("").classes("text-sm text-gray-600 font-medium")
            self.khung_the = ui.row().classes("items-center gap-1 flex-wrap flex-1")
            ui.button("Làm mới", icon="refresh", on_click=lambda: self.tai(self.page, ep=True)).props(
                "flat dense no-caps").classes("text-gray-700")
            ui.button("Xuất Excel", icon="download", on_click=self._xuat).props(
                "flat dense no-caps").classes("text-green-800").tooltip(
                "Tải toàn bộ danh sách đang lọc (không chỉ trang này)")
        self.khung = ui.column().classes("w-full gap-0 mt-1 bg-white rounded border border-gray-200")
        self.hang_trang = ui.row().classes("w-full justify-center items-center gap-2 mt-3")
        self._dung_ngan_chi_tiet()

    # ── Bộ lọc ──
    async def _doi_loc(self):
        # Không truyền thẳng self.tai: NiceGUI thấy tham số là nhét sự kiện vào `page`
        await self.tai()

    def tham_so(self) -> dict:
        tu, den = self.ngay.api()
        return {"tu_ngay": tu, "den_ngay": den, "actor_id": self.nguoi.value or 0,
                "module": self.module.value or "", "method": self.loai.value or "",
                "ket_qua": self.ket_qua.value or "", "q": (self.tim.value or "").strip(),
                "doi_tuong": self.doi_tuong[0]}

    def tham_so_url(self) -> dict:
        ts = self.tham_so()
        ts.pop("tu_ngay"), ts.pop("den_ngay")
        return {**self.ngay.url(), **ts, "doi_tuong_nhan": self.doi_tuong[1]}

    def dat_loc(self, loc: dict):
        self.ngay.dat(loc)
        try:
            actor = int(loc.get("actor_id") or 0)
        except ValueError:
            actor = 0
        if actor:
            self._chon_nguoi(actor, loc.get("nguoi_nhan"))
        else:
            self.nguoi.value = None
        m = loc.get("module") or None
        if m and m not in self.module.options:
            self.module.options[m] = m
            self.module.update()
        self.module.value = m
        self.loai.value = loc.get("method", "") if loc.get("method", "") in _LOAI else ""
        self.ket_qua.value = loc.get("ket_qua", "") if loc.get("ket_qua", "") in _KET_QUA else ""
        self.tim.value = loc.get("q", "")
        self.doi_tuong = (loc.get("doi_tuong", ""), loc.get("doi_tuong_nhan", "") or loc.get("doi_tuong", ""))

    async def nap_danh_muc(self):
        """Danh sách người + chức năng cho hai ô chọn. Hỏng thì bảng chính vẫn dùng được."""
        try:
            data = await asyncio.to_thread(api.get, f"{_API}/filters")
        except Exception:
            _log.warning("Không nạp được danh sách người / chức năng cho bộ lọc", exc_info=True)
            return
        chon_nguoi, chon_module = self.nguoi.value, self.module.value
        self.nguoi.options = {a["id"]: a["label"] for a in data.get("actors", [])}
        self.module.options = {m["prefix"]: m["label"][:1].upper() + m["label"][1:]
                               for m in data.get("modules", [])}
        # Giữ giá trị đang chọn (có thể đặt từ địa chỉ trang trước khi danh sách về)
        if chon_nguoi and chon_nguoi not in self.nguoi.options:
            self.nguoi.options[chon_nguoi] = f"Mã người dùng {chon_nguoi}"
        if chon_module and chon_module not in self.module.options:
            self.module.options[chon_module] = chon_module
        self.nguoi.update()
        self.module.update()

    async def _go(self, truong: str):
        if truong == "ngay":
            self.ngay.dat({"khoang": "tat_ca"})
        elif truong == "doi_tuong":
            self.doi_tuong = ("", "")
        else:
            getattr(self, truong).value = None if truong in ("nguoi", "module") else ""
        await self.tai()

    async def _xoa_het(self):
        self.dat_loc({"khoang": "tat_ca"})
        await self.tai()

    def _ve_the(self):
        the = []
        if self.ngay.chon.value != "tat_ca":
            the.append((f"Thời gian: {self.ngay.mo_ta()}", lambda: self._go("ngay")))
        if self.nguoi.value:
            nhan = str(self.nguoi.options.get(self.nguoi.value, "")).rsplit(" (", 1)[0]
            the.append((f"Người: {nhan}", lambda: self._go("nguoi")))
        if self.module.value:
            the.append((f"Chức năng: {self.module.options.get(self.module.value, '')}",
                        lambda: self._go("module")))
        if self.loai.value:
            the.append((f"Loại: {_LOAI[self.loai.value]}", lambda: self._go("loai")))
        if self.ket_qua.value:
            the.append((f"Kết quả: {_KET_QUA[self.ket_qua.value]}", lambda: self._go("ket_qua")))
        if (self.tim.value or "").strip():
            the.append((f"Tìm: “{self.tim.value.strip()}”", lambda: self._go("tim")))
        if self.doi_tuong[0]:
            the.append((f"Hồ sơ: {self.doi_tuong[1]}", lambda: self._go("doi_tuong")))
        the_loc(self.khung_the, the, self._xoa_het)

    # ── Lối tắt từ một dòng ──
    def _chon_nguoi(self, actor_id: int, nhan: str):
        # Người chưa có trong danh sách (chưa nạp xong) — thêm tạm để ô chọn giữ được giá trị;
        # gán giá trị không có trong options thì ui.select ném ValueError
        if actor_id not in self.nguoi.options:
            self.nguoi.options[actor_id] = nhan or f"Mã người dùng {actor_id}"
            self.nguoi.update()
        self.nguoi.value = actor_id

    async def loc_nguoi(self, e: dict):
        """Thêm điều kiện "người này" vào bộ lọc đang có — không xoá các điều kiện khác."""
        if e.get("actor_id"):
            self._chon_nguoi(e["actor_id"], e.get("full_name") or e.get("username"))
            await self.tai()

    async def loc_ho_so(self, dt: dict):
        self.dat_loc({"khoang": "tat_ca", "doi_tuong": dt["khoa"], "doi_tuong_nhan": dt["nhan"]})
        await self.tai()

    # ── Vẽ danh sách ──
    async def _ve(self, luot: int):
        self._ve_the()
        self.dong_dem.set_text("Đang tải…")
        try:
            data = await asyncio.to_thread(api.get, _API, dict(self.tham_so(), page=self.page))
        except Exception as ex:
            if self.con_hieu_luc(luot):
                self.dong_dem.set_text("Không tải được nhật ký.")
            _handle_api_error(ex)
            return
        if not self.con_hieu_luc(luot):
            return

        ds, tong = data.get("entries", []), data.get("total", 0)
        self.dong_dem.set_text(f"Tìm thấy {tong:,} thao tác".replace(",", "."))
        self.khung.clear()
        with self.khung:
            if not ds:
                with ui.column().classes("w-full items-center py-10 text-gray-500"):
                    ui.icon("search_off").classes("text-4xl")
                    ui.label("Không có thao tác nào khớp bộ lọc.").classes("text-sm")
            ngay_truoc = None
            for e in ds:
                ngay = str(e.get("created_at") or "")[:10]
                if ngay != ngay_truoc:
                    tieu_de_ngay(ngay)
                    ngay_truoc = ngay
                self._ve_dong(e)
        phan_trang(self.hang_trang, self.page, data.get("pages", 1),
                   lambda p: self.tai(p, ep=True))

    def _ve_dong(self, e: dict):
        ok = e.get("result_ok", True)
        dong = ui.row().classes(
            "w-full items-center gap-3 px-3 py-2 border-b border-gray-100 cursor-pointer "
            + ("hover:bg-blue-50" if ok else "bg-orange-50/60 hover:bg-orange-100"))
        dong.on("click", lambda _, e=e: self._mo_chi_tiet(e))
        with dong:
            ui.label(gio(e.get("created_at"))).classes("text-xs font-mono text-gray-500 w-16 shrink-0")
            ten = e.get("full_name") or e.get("username") or "Không rõ người"
            nguoi = ui.label(ten).classes("text-sm w-44 shrink-0 truncate")
            if e.get("actor_id"):
                nguoi.classes("text-blue-800 hover:underline")
                nguoi.tooltip("Chỉ xem thao tác của người này")
                nguoi.on("click.stop", lambda _, e=e: self.loc_nguoi(e))
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.label(e.get("work") or "—").classes("text-sm font-medium text-gray-900 truncate")
                    dt = e.get("doi_tuong")
                    if dt:
                        ho_so = ui.label(dt["nhan"]).classes(
                            "text-xs px-1.5 rounded bg-gray-100 text-gray-700 hover:bg-blue-100 shrink-0")
                        ho_so.tooltip("Xem toàn bộ lịch sử của hồ sơ này")
                        ho_so.on("click.stop", lambda _, dt=dt: self.loc_ho_so(dt))
                if e.get("detail"):
                    ui.label(e["detail"]).classes("text-xs text-gray-500 truncate")
            ui.label(e.get("result") or "—").classes(
                f"text-xs px-2 py-0.5 rounded font-medium shrink-0 {_mau_ket_qua(ok)}")

    # ── Ngăn chi tiết bên phải ──
    def _dung_ngan_chi_tiet(self):
        # Dựng MỘT lần, mỗi lần bấm chỉ vẽ lại ruột — tạo mới trong handler là mỗi cú
        # bấm để lại một dialog chết trong cây phần tử.
        self.ngan = ui.dialog().props("position=right full-height")
        with self.ngan, ui.card().classes("w-[34rem] max-w-[95vw] h-full rounded-none gap-0 p-0"):
            with ui.row().classes("w-full items-center px-4 py-3 border-b bg-gray-50"):
                ui.label("Chi tiết thao tác").classes("text-base font-bold text-red-900 flex-1")
                ui.button(icon="close", on_click=self.ngan.close).props("flat round dense")
            self.ruot = ui.column().classes("w-full gap-3 p-4 overflow-y-auto flex-1")

    @staticmethod
    def _dong_tt(nhan: str, gia_tri: str, mono: bool = False):
        with ui.row().classes("w-full gap-2 items-start no-wrap"):
            ui.label(nhan).classes("text-xs text-gray-500 w-32 shrink-0 pt-0.5")
            ui.label(gia_tri or "—").classes(
                "text-sm flex-1 whitespace-pre-wrap break-all" + (" font-mono text-xs" if mono else ""))

    async def _mo_chi_tiet(self, e: dict):
        ok = e.get("result_ok", True)
        ts = str(e.get("created_at") or "")
        ten = e.get("full_name") or e.get("username") or "Không rõ người"
        self.ruot.clear()
        with self.ruot:
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(e.get("work") or "—").classes("text-lg font-bold text-gray-900")
                ui.label(e.get("result") or "—").classes(
                    f"text-xs px-2 py-0.5 rounded font-medium {_mau_ket_qua(ok)}")
            ui.label(f"{ten} — lúc {ts[11:19]} ngày {_dmy(ts[:10])}").classes("text-sm text-gray-700")
            if not ok:
                ui.label(_goi_y_loi(e.get("result") or "")).classes(
                    "text-xs text-orange-900 bg-orange-50 border border-orange-200 rounded px-2 py-1.5")

            with ui.column().classes("w-full gap-1"):
                ui.label("Nội dung đã gửi").classes("text-xs font-semibold text-gray-600 uppercase")
                ui.label(e.get("detail") or "(không có nội dung kèm theo)").classes(
                    "text-sm whitespace-pre-wrap break-words bg-gray-50 rounded px-2 py-1.5 w-full")

            with ui.row().classes("w-full gap-2 flex-wrap"):
                dt = e.get("doi_tuong")
                if dt:
                    ui.button(f"Lịch sử {dt['nhan']}", icon="history",
                              on_click=lambda dt=dt: self._tu_ngan(self.loc_ho_so(dt))).props(
                        "outline dense no-caps size=sm color=red-9")
                if e.get("actor_id"):
                    ui.button("Mọi thao tác của người này trong ngày", icon="person_search",
                              on_click=lambda: self._tu_ngan(self._loc_nguoi_trong_ngay(e))).props(
                        "outline dense no-caps size=sm color=red-9")

            ui.label("Ngay trước và sau đó (±10 phút)").classes(
                "text-xs font-semibold text-gray-600 uppercase mt-1")
            lan_can = ui.column().classes("w-full gap-0 border rounded")
            with lan_can:
                ui.label("Đang tải…").classes("text-xs text-gray-400 p-2")

            with ui.expansion("Thông tin kỹ thuật", icon="code").classes(
                    "w-full text-sm text-gray-600 border rounded"):
                self._dong_tt("Đường dẫn", f"{e.get('action') or ''} {e.get('target_type') or ''}".strip(), mono=True)
                self._dong_tt("Nguyên văn", e.get("raw_detail") or "", mono=True)
                self._dong_tt("Địa chỉ IP", e.get("ip_address") or "", mono=True)
                self._dong_tt("Tài khoản", e.get("username") or "", mono=True)
                self._dong_tt("Mã bản ghi", str(e.get("id") or ""), mono=True)
        self.ngan.open()

        try:
            data = await asyncio.to_thread(api.get, f"{_API}/{e['id']}/lan-can")
        except Exception as ex:
            lan_can.clear()
            with lan_can:
                ui.label("Không tải được.").classes("text-xs text-gray-400 p-2")
            _handle_api_error(ex)
            return
        lan_can.clear()
        with lan_can:
            ds = data.get("entries", [])
            if not ds:
                ui.label("Không có thao tác nào khác.").classes("text-xs text-gray-400 p-2")
            for x in ds:
                with ui.row().classes("w-full items-center gap-2 px-2 py-1 border-b border-gray-100 no-wrap"):
                    ui.label(gio(x.get("created_at"))).classes("text-xs font-mono text-gray-500 w-16 shrink-0")
                    ui.label(x.get("work") or "—").classes("text-xs flex-1 truncate")
                    ui.label(x.get("result") or "—").classes(
                        f"text-xs px-1.5 rounded shrink-0 {_mau_ket_qua(x.get('result_ok', True))}")

    async def _tu_ngan(self, viec):
        self.ngan.close()
        await viec

    async def _loc_nguoi_trong_ngay(self, e: dict):
        ngay = str(e.get("created_at") or "")[:10]
        self.dat_loc({"tu_ngay": ngay, "den_ngay": ngay, "actor_id": e["actor_id"],
                      "nguoi_nhan": e.get("full_name") or e.get("username")})
        await self.tai()

    async def _xuat(self):
        try:
            content = await asyncio.to_thread(api.download, f"{_API}/export", self.tham_so())
            ui.download(content, f"nhat_ky_thao_tac_{date.today().strftime('%Y%m%d')}.xlsx")
        except Exception as ex:
            _handle_api_error(ex)


def _goi_y_loi(ket_qua: str) -> str:
    """Một câu cho người giám sát biết nên hiểu kết quả này thế nào."""
    return {
        "Chưa đăng nhập": "Phiên đăng nhập đã hết hạn lúc thao tác — thường là người dùng để màn hình lâu rồi bấm tiếp.",
        "Không đủ quyền": "Người này bấm vào chức năng mà nhóm của họ chưa được cấp quyền (xem Phân quyền theo nhóm).",
        "Trùng / xung đột dữ liệu": "Dữ liệu đã có sẵn hoặc vừa bị người khác sửa — hệ thống từ chối để không ghi đè.",
        "Dữ liệu không hợp lệ": "Dữ liệu gửi lên thiếu hoặc sai khuôn — hệ thống từ chối thao tác.",
        "Lỗi hệ thống": "Lỗi phía máy chủ. Xem tab Lỗi hệ thống quanh cùng thời điểm để biết nguyên nhân.",
    }.get(ket_qua, "Thao tác không thành công.")
