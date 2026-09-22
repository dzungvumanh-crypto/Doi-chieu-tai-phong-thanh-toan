"""Tab Đăng nhập — ai vào, từ máy nào, thành công hay không; tô sẵn chỗ nghi dò mật khẩu."""
import asyncio
from datetime import date

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _handle_api_error

from ._chung import (TOGGLE_PROPS, BoLocNgay, TabNhatKy, gio, phan_trang, the_loc,
                     tieu_de_ngay)

_KET_QUA = {"": "Mọi kết quả", "true": "Thành công", "false": "Thất bại"}
_API = "/api/admin/logs/logins"


class TabDangNhap(TabNhatKy):
    ten = "dang-nhap"

    def __init__(self, ctx):
        super().__init__(ctx)
        # Khớp ĐÚNG (không phải tìm chứa chuỗi) — đặt bằng cách bấm tên đăng nhập / IP
        # trên dòng hoặc từ mục "Cần chú ý"
        self.tai_khoan = ""
        self.ip = ""
        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
            self.ngay = BoLocNgay(self._doi_loc)
        with ui.row().classes("w-full items-center gap-2 flex-wrap mt-2"):
            self.ket_qua = ui.toggle(_KET_QUA, value="", on_change=self._doi_loc).props(TOGGLE_PROPS)
            self.tim = ui.input(placeholder="Tìm tài khoản, họ tên, IP…", on_change=self._doi_loc).props(
                "dense outlined clearable debounce=500").classes("w-64")
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

    async def _doi_loc(self):
        await self.tai()

    def tham_so(self) -> dict:
        tu, den = self.ngay.api()
        return {"tu_ngay": tu, "den_ngay": den, "success": self.ket_qua.value or "",
                "q": (self.tim.value or "").strip(), "tai_khoan": self.tai_khoan, "ip": self.ip}

    def tham_so_url(self) -> dict:
        return {**self.ngay.url(), "success": self.ket_qua.value or "",
                "q": (self.tim.value or "").strip(), "tai_khoan": self.tai_khoan, "ip": self.ip}

    def dat_loc(self, loc: dict):
        self.ngay.dat(loc)
        self.ket_qua.value = loc.get("success", "") if loc.get("success", "") in _KET_QUA else ""
        self.tim.value = loc.get("q", "")
        self.tai_khoan = loc.get("tai_khoan", "")
        self.ip = loc.get("ip", "")

    async def _loc_dung(self, truong: str, gia_tri: str):
        """Bấm tên đăng nhập / IP trên dòng — thêm vào bộ lọc đang có."""
        setattr(self, truong, gia_tri or "")
        await self.tai()

    async def _go(self, truong: str):
        if truong == "ngay":
            self.ngay.dat({"khoang": "tat_ca"})
        elif truong in ("tai_khoan", "ip"):
            setattr(self, truong, "")
        else:
            getattr(self, truong).value = ""
        await self.tai()

    async def _xoa_het(self):
        self.dat_loc({"khoang": "tat_ca"})
        await self.tai()

    def _ve_the(self):
        the = []
        if self.ngay.chon.value != "tat_ca":
            the.append((f"Thời gian: {self.ngay.mo_ta()}", lambda: self._go("ngay")))
        if self.ket_qua.value:
            the.append((f"Kết quả: {_KET_QUA[self.ket_qua.value]}", lambda: self._go("ket_qua")))
        if self.tai_khoan:
            the.append((f"Tài khoản: {self.tai_khoan}", lambda: self._go("tai_khoan")))
        if self.ip:
            the.append((f"Máy: {self.ip}", lambda: self._go("ip")))
        if (self.tim.value or "").strip():
            the.append((f"Tìm: “{self.tim.value.strip()}”", lambda: self._go("tim")))
        the_loc(self.khung_the, the, self._xoa_het)

    async def _ve(self, luot: int):
        self._ve_the()
        self.dong_dem.set_text("Đang tải…")
        try:
            data = await asyncio.to_thread(api.get, _API, dict(self.tham_so(), page=self.page))
        except Exception as ex:
            if self.con_hieu_luc(luot):
                self.dong_dem.set_text("Không tải được nhật ký đăng nhập.")
            _handle_api_error(ex)
            return
        if not self.con_hieu_luc(luot):
            return

        ds, tong = data.get("entries", []), data.get("total", 0)
        self.dong_dem.set_text(f"Tìm thấy {tong:,} lượt đăng nhập".replace(",", "."))
        self.khung.clear()
        with self.khung:
            if not ds:
                with ui.column().classes("w-full items-center py-10 text-gray-500"):
                    ui.icon("search_off").classes("text-4xl")
                    ui.label("Không có lượt đăng nhập nào khớp bộ lọc.").classes("text-sm")
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
        ok = e.get("success", False)
        nghi = e.get("nghi_van", False)
        nen = "bg-red-50" if nghi else ("" if ok else "bg-orange-50/60")
        dong = ui.row().classes(f"w-full items-center gap-3 px-3 py-2 border-b border-gray-100 {nen}")
        # Lượt thành công → bấm để xem người này đã làm gì trong ngày hôm đó
        if ok and e.get("staff_id"):
            dong.classes("cursor-pointer hover:bg-blue-50")
            dong.tooltip("Xem các thao tác của người này trong ngày")
            dong.on("click", lambda _, e=e: self._xem_thao_tac(e))
        with dong:
            ui.label(gio(e.get("created_at"))).classes("text-xs font-mono text-gray-500 w-16 shrink-0")
            ui.label("Thành công" if ok else "Thất bại").classes(
                "text-xs px-2 py-0.5 rounded font-medium w-24 text-center shrink-0 whitespace-nowrap "
                + ("bg-green-100 text-green-800" if ok else "bg-red-100 text-red-800"))
            # Lượt sai không lưu staff_id (chưa xác thực được là ai) → không có họ tên;
            # hiện tên đăng nhập đã gõ làm dòng chính
            with ui.column().classes("w-56 shrink-0 gap-0"):
                if e.get("full_name"):
                    ui.label(e["full_name"]).classes("text-sm truncate")
                tk = ui.label(e.get("username") or "").classes(
                    "text-xs font-mono text-blue-800 hover:underline truncate cursor-pointer")
                tk.tooltip("Chỉ xem tài khoản này")
                tk.on("click.stop", lambda _, e=e: self._loc_dung("tai_khoan", e.get("username")))
            may = ui.label(e.get("ip_address") or "—").classes("text-xs font-mono text-gray-600 w-32 shrink-0")
            if e.get("ip_address"):
                may.classes("text-blue-800 hover:underline cursor-pointer")
                may.tooltip("Chỉ xem máy này")
                may.on("click.stop", lambda _, e=e: self._loc_dung("ip", e.get("ip_address")))
            ui.label(e.get("detail") or "").classes("text-xs text-gray-600 flex-1 truncate")
            if nghi:
                ui.label(f"⚠ Nghi dò mật khẩu · sai {e.get('so_sai_ngay')} lần trong ngày").classes(
                    "text-xs px-2 py-0.5 rounded bg-red-600 text-white font-medium shrink-0")

    async def _xem_thao_tac(self, e: dict):
        ngay = str(e.get("created_at") or "")[:10]
        await self.ctx.mo_tab("thao-tac", {
            "tu_ngay": ngay, "den_ngay": ngay, "actor_id": e["staff_id"],
            "nguoi_nhan": e.get("full_name") or e.get("username"),
        })

    async def _xuat(self):
        try:
            content = await asyncio.to_thread(api.download, f"{_API}/export", self.tham_so())
            ui.download(content, f"nhat_ky_dang_nhap_{date.today().strftime('%Y%m%d')}.xlsx")
        except Exception as ex:
            _handle_api_error(ex)
