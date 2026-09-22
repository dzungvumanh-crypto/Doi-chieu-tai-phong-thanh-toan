"""Tab Tổng quan — mở trang ra là thấy ngay "có gì bất thường không".

Mọi con số và mục "cần chú ý" do backend tính (GET /api/admin/logs/tong-quan), kèm
sẵn tab + bộ lọc để bấm vào là mở đúng danh sách. Sức khoẻ máy chủ nằm ở màn Giám sát
hệ thống, không vẽ lại ở đây.
"""
import asyncio
import logging
from datetime import date

from nicegui import ui

import frontend.api_client as api
from frontend.shared import _handle_api_error

from ._chung import TOGGLE_PROPS, TabNhatKy

_log = logging.getLogger(__name__)

_KHOANG = {1: "Hôm nay", 7: "7 ngày", 30: "30 ngày"}
_KHOANG_TAB = {1: "hom_nay", 7: "7", 30: "30"}      # khoảng tương ứng ở các tab danh sách


class TabTongQuan(TabNhatKy):
    ten = "tong-quan"

    def __init__(self, ctx):
        super().__init__(ctx)
        with ui.row().classes("w-full items-center gap-2"):
            self.khoang = ui.toggle(_KHOANG, value=1, on_change=self._doi_loc).props(TOGGLE_PROPS)
            ui.space()
            ui.button("Làm mới", icon="refresh", on_click=lambda: self.tai(ep=True)).props(
                "flat dense no-caps").classes("text-gray-700")
        self.hang_so = ui.row().classes("w-full gap-3 mt-3 flex-wrap")
        ui.label("Cần chú ý").classes("text-base font-bold text-gray-800 mt-5")
        self.khung = ui.column().classes("w-full gap-0 bg-white rounded border border-gray-200")
        self.he_thong = ui.row().classes(
            "w-full items-center gap-3 mt-5 px-3 py-2 bg-white rounded border border-gray-200 flex-wrap")

    async def _doi_loc(self):
        await self.tai()

    def tham_so(self) -> dict:
        return {"so_ngay": self.khoang.value}

    def dat_loc(self, loc: dict):
        try:
            n = int(loc.get("so_ngay") or 1)
        except ValueError:
            n = 1
        self.khoang.value = n if n in _KHOANG else 1

    def _loc_tab(self, loc: dict) -> dict:
        """Bộ lọc backend gửi kèm dùng `tu_ngay`; đổi sang khoảng chọn nhanh tương ứng
        để tab đích hiện nút "Hôm nay"/"7 ngày" thay vì hai ô ngày."""
        ra = dict(loc)
        ra.pop("tu_ngay", None)
        ra["khoang"] = _KHOANG_TAB[self.khoang.value]
        return ra

    async def _ve(self, luot: int):
        try:
            data = await asyncio.to_thread(api.get, "/api/admin/logs/tong-quan", self.tham_so())
        except Exception as ex:
            _handle_api_error(ex)
            return
        if not self.con_hieu_luc(luot):
            return
        so, khoang = data.get("so", {}), _KHOANG_TAB[self.khoang.value]

        self.hang_so.clear()
        with self.hang_so:
            self._the_so("Thao tác", so.get("thao_tac", 0), "edit_note", "gray",
                         "thao-tac", {"khoang": khoang})
            self._the_so("Thao tác thất bại", so.get("that_bai", 0), "report", "orange",
                         "thao-tac", {"khoang": khoang, "ket_qua": "loi"})
            self._the_so("Lượt đăng nhập", so.get("dang_nhap", 0), "login", "gray",
                         "dang-nhap", {"khoang": khoang, "success": "true"})
            # Gồm cả lượt bị chặn vì tài khoản đang mở ở máy khác — không chỉ sai mật khẩu
            self._the_so("Đăng nhập thất bại", so.get("dang_nhap_sai", 0), "no_accounts", "red",
                         "dang-nhap", {"khoang": khoang, "success": "false"})
            self._the_so("Lỗi hệ thống", so.get("loi_he_thong", 0), "error", "red",
                         "loi", {"khoang": khoang, "level": "ERROR"})

        self.khung.clear()
        with self.khung:
            ds = data.get("chu_y", [])
            if not ds:
                with ui.row().classes("w-full items-center gap-2 px-4 py-6 text-green-800"):
                    ui.icon("check_circle").classes("text-2xl")
                    ui.label(f"Không có gì bất thường trong {_KHOANG[self.khoang.value].lower()}.").classes("text-sm")
            for m in ds:
                self._dong_chu_y(m)

        await self._ve_he_thong()

    def _the_so(self, nhan: str, so: int, icon: str, mau: str, tab: str, loc: dict):
        # Số 0 ở ô cảnh báo thì để xám — tô đỏ số 0 là tập cho người xem quen bỏ qua màu đỏ
        canh_bao = so > 0 and mau != "gray"
        vien = {"orange": "border-orange-300 bg-orange-50", "red": "border-red-300 bg-red-50"}.get(
            mau, "") if canh_bao else "border-gray-200 bg-white"
        chu = {"orange": "text-orange-700", "red": "text-red-700"}.get(mau, "") if canh_bao else "text-gray-800"
        with ui.card().classes(f"w-44 p-3 gap-1 cursor-pointer hover:shadow-md border {vien}").on(
                "click", lambda: self.ctx.mo_tab(tab, loc)):
            with ui.row().classes("items-center gap-1 text-gray-500"):
                ui.icon(icon).classes("text-base")
                ui.label(nhan).classes("text-xs")
            ui.label(f"{so:,}".replace(",", ".")).classes(f"text-2xl font-bold {chu}")

    def _dong_chu_y(self, m: dict):
        loi = m.get("muc") == "loi"
        with ui.row().classes(
                "w-full items-center gap-3 px-3 py-2 border-b border-gray-100 cursor-pointer "
                "hover:bg-blue-50").on("click", lambda m=m: self.ctx.mo_tab(m["tab"], self._loc_tab(m["loc"]))):
            ui.icon("error" if loi else "warning").classes(
                "text-lg " + ("text-red-600" if loi else "text-orange-500"))
            ui.label(m.get("noi_dung") or "").classes("text-sm flex-1 text-gray-800")
            ui.label(_gio_ngan(m.get("thoi_gian"))).classes("text-xs text-gray-500 font-mono")
            ui.label("Xem →").classes("text-xs text-red-800 font-medium")

    async def _ve_he_thong(self):
        """Sao lưu + đồng hồ + nút tải bản sao — trước nằm trên màn Lịch sử lỗi."""
        bk, ts = await asyncio.gather(
            asyncio.to_thread(api.get, "/api/admin/logs/backup-info"),
            asyncio.to_thread(api.get, "/api/admin/logs/time-sync"),
            return_exceptions=True,
        )
        self.he_thong.clear()
        with self.he_thong:
            ui.icon("backup").classes("text-gray-500")
            if isinstance(bk, dict):
                # Đếm riêng bản đặt tay: chúng KHÔNG bị dọn tự động, gộp chung làm người xem
                # tưởng backup tự động chạy dày hơn thực tế
                tay = bk.get("count_thu_cong") or 0
                them = f" + {tay} bản đặt tay" if tay else ""
                ui.label(f"Sao lưu tự động gần nhất: {bk['time']} ({bk.get('count', 1)} bản{them})"
                         if bk.get("exists") else f"Chưa có sao lưu tự động{them}").classes("text-xs text-gray-600")
            else:
                _log.warning("Không lấy được thông tin backup gần nhất: %s", bk)
                ui.label("Không đọc được thông tin sao lưu").classes("text-xs text-gray-400")
            ui.label("·").classes("text-gray-300")
            txt, mau = _dong_ho(ts)
            ui.label(txt).classes(f"text-xs px-2 py-0.5 rounded {mau}")
            ui.space()
            ui.button("Tải bản sao CSDL", icon="download", on_click=self._backup).props(
                "outline dense no-caps size=sm color=orange-9").tooltip(
                "File chứa TOÀN BỘ dữ liệu, gồm cả mã băm mật khẩu — lượt tải được ghi vào nhật ký")

    async def _backup(self):
        try:
            content = await asyncio.to_thread(api.download, "/api/admin/logs/backup")
            ui.download(content, f"ksnb_backup_{date.today().isoformat()}.db")
            ui.notify("Đã tạo bản sao cơ sở dữ liệu.", type="positive")
        except Exception as ex:
            _handle_api_error(ex)


def _gio_ngan(ts) -> str:
    """'2026-09-22 10:32' → '10:32 22/09'."""
    s = str(ts or "")
    return f"{s[11:16]} {s[8:10]}/{s[5:7]}" if len(s) >= 16 else s


def _dong_ho(ts) -> tuple[str, str]:
    if not isinstance(ts, dict):
        _log.warning("Không lấy được trạng thái lệch giờ NTP: %s", ts)
        return "Đồng hồ: không kiểm tra được", "bg-gray-100 text-gray-500"
    if not ts.get("enabled"):
        return "Đồng bộ giờ: đã tắt", "bg-gray-100 text-gray-500"
    if ts.get("error"):
        return f"Giờ chuẩn: không kiểm tra được ({ts.get('server')})", "bg-gray-100 text-gray-500"
    if ts.get("ok"):
        return f"Giờ máy khớp NTP (lệch {ts['drift_seconds']}s)", "bg-green-100 text-green-800"
    return (f"⚠ Đồng hồ lệch {ts['drift_seconds']}s so với NTP — giờ trong nhật ký có thể sai",
            "bg-red-100 text-red-800")
