"""Tab Lỗi hệ thống — đọc logs/app.log. Dòng đầu là câu thông báo; vết kỹ thuật gập sẵn."""
import asyncio

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _handle_api_error

from ._chung import (TOGGLE_PROPS, BoLocNgay, TabNhatKy, gio, phan_trang, the_loc,
                     tieu_de_ngay)

_MUC = {"ERROR": "Lỗi", "WARNING": "Cảnh báo", "INFO": "Thông tin", "": "Mọi mức"}
_MAU = {
    "ERROR":    "bg-red-100 text-red-800",
    "CRITICAL": "bg-red-600 text-white",
    "WARNING":  "bg-orange-100 text-orange-800",
    "INFO":     "bg-blue-50 text-blue-800",
}
_API = "/api/admin/logs/"


class TabLoi(TabNhatKy):
    ten = "loi"

    def __init__(self, ctx):
        super().__init__(ctx)
        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
            self.ngay = BoLocNgay(self._doi_loc)
        with ui.row().classes("w-full items-center gap-2 flex-wrap mt-2"):
            # Mặc định chỉ Lỗi: "Thông tin" chiếm phần lớn file, để lẫn vào là lỗi thật chìm mất
            self.muc = ui.toggle(_MUC, value="ERROR", on_change=self._doi_loc).props(TOGGLE_PROPS)
            self.tim = ui.input(placeholder="Tìm trong nội dung lỗi…", on_change=self._doi_loc).props(
                "dense outlined clearable debounce=500").classes("w-72")
            with self.tim.add_slot("prepend"):
                ui.icon("search").classes("text-gray-400")
        with ui.row().classes("w-full items-center gap-2 mt-2 min-h-[2rem]"):
            self.dong_dem = ui.label("").classes("text-sm text-gray-600 font-medium")
            self.khung_the = ui.row().classes("items-center gap-1 flex-wrap flex-1")
            ui.button("Làm mới", icon="refresh", on_click=lambda: self.tai(self.page, ep=True)).props(
                "flat dense no-caps").classes("text-gray-700")
        ui.label("Chỉ đọc file nhật ký hiện hành (logs/app.log) — bản cũ hơn đã xoay vòng sang "
                 "app.log.1 không hiện ở đây.").classes("text-xs text-gray-400")
        self.khung = ui.column().classes("w-full gap-0 mt-1 bg-white rounded border border-gray-200")
        self.hang_trang = ui.row().classes("w-full justify-center items-center gap-2 mt-3")

    async def _doi_loc(self):
        await self.tai()

    def tham_so(self) -> dict:
        tu, den = self.ngay.api()
        return {"tu_ngay": tu, "den_ngay": den, "level": self.muc.value or "",
                "q": (self.tim.value or "").strip()}

    def tham_so_url(self) -> dict:
        return {**self.ngay.url(), "level": self.muc.value or "tat_ca",
                "q": (self.tim.value or "").strip()}

    def dat_loc(self, loc: dict):
        self.ngay.dat(loc)
        lv = loc.get("level", "ERROR")
        self.muc.value = "" if lv == "tat_ca" else (lv if lv in _MUC else "ERROR")
        self.tim.value = loc.get("q", "")

    async def _go(self, truong: str):
        if truong == "ngay":
            self.ngay.dat({"khoang": "tat_ca"})
        else:
            getattr(self, truong).value = ""
        await self.tai()

    async def _xoa_het(self):
        self.dat_loc({"khoang": "tat_ca", "level": "tat_ca"})
        await self.tai()

    def _ve_the(self):
        the = []
        if self.ngay.chon.value != "tat_ca":
            the.append((f"Thời gian: {self.ngay.mo_ta()}", lambda: self._go("ngay")))
        if self.muc.value:
            the.append((f"Mức: {_MUC[self.muc.value]}", lambda: self._go("muc")))
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
                self.dong_dem.set_text("Không tải được nhật ký lỗi.")
            _handle_api_error(ex)
            return
        if not self.con_hieu_luc(luot):
            return

        ds, tong = data.get("entries", []), data.get("total", 0)
        self.dong_dem.set_text(f"Tìm thấy {tong:,} dòng".replace(",", "."))
        self.khung.clear()
        with self.khung:
            if not ds:
                with ui.column().classes("w-full items-center py-10 text-gray-500"):
                    ui.icon("task_alt").classes("text-4xl text-green-600")
                    ui.label("Không có dòng nào khớp bộ lọc.").classes("text-sm")
            ngay_truoc = None
            for e in ds:
                ngay = str(e.get("ts") or "")[:10]
                if ngay != ngay_truoc:
                    tieu_de_ngay(ngay)
                    ngay_truoc = ngay
                self._ve_dong(e)
        phan_trang(self.hang_trang, self.page, data.get("pages", 1),
                   lambda p: self.tai(p, ep=True))

    @staticmethod
    def _ve_dong(e: dict):
        lv = e.get("level", "INFO")
        dau, _, con_lai = (e.get("msg") or "").partition("\n")
        with ui.row().classes("w-full items-start gap-3 px-3 py-2 border-b border-gray-100"):
            ui.label(gio(e.get("ts"))).classes("text-xs font-mono text-gray-500 w-16 shrink-0 pt-0.5")
            ui.label(_MUC.get(lv) or {"CRITICAL": "Nghiêm trọng", "DEBUG": "Gỡ lỗi"}.get(lv, lv)).classes(
                f"text-xs px-2 py-0.5 rounded font-medium w-24 text-center shrink-0 whitespace-nowrap {_MAU.get(lv, 'bg-gray-100')}")
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                ui.label(dau).classes("text-sm text-gray-900 break-words")
                ui.label(e.get("logger") or "").classes("text-xs font-mono text-gray-400")
                if con_lai:
                    so_dong = con_lai.count("\n") + 1
                    with ui.expansion(f"Chi tiết kỹ thuật ({so_dong} dòng)").props("dense").classes(
                            "w-full text-xs text-gray-600"):
                        ui.label(con_lai).classes(
                            "text-xs font-mono whitespace-pre-wrap break-all text-gray-700 "
                            "bg-gray-50 rounded p-2 leading-5")
