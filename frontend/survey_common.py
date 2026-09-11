"""Thành phần dùng chung cho các trang Khảo sát (frontend/pages/survey*.py).

Nằm ngoài `pages/` vì main.py tự quét mọi module trong `pages/` để đăng ký trang
— file tiện ích đặt trong đó sẽ bị import như một trang.
"""
from nicegui import ui

from frontend.shared import _dmy, _iso_tu_dmy

# Loại câu hỏi — thứ tự này là thứ tự trong ô chọn của màn soạn thảo.
QTYPE_LABELS = {
    "short_text": "Trả lời ngắn",
    "paragraph":  "Đoạn văn",
    "single":     "Trắc nghiệm (chọn một)",
    "multi":      "Hộp kiểm (chọn nhiều)",
    "dropdown":   "Danh sách thả xuống",
    "scale":      "Thang đo tuyến tính",
    "date":       "Ngày",
}
QTYPE_ICONS = {
    "short_text": "short_text", "paragraph": "notes", "single": "radio_button_checked",
    "multi": "check_box", "dropdown": "arrow_drop_down_circle", "scale": "linear_scale",
    "date": "event",
}
CHOICE_TYPES = ("single", "multi", "dropdown")

# state (survey_service.trang_thai) → (nhãn, class chip). Luôn có chữ đi kèm màu.
STATE = {
    "draft":     ("Bản nháp",       "bg-gray-100 text-gray-600 border-gray-300"),
    "scheduled": ("Chưa tới giờ mở", "bg-blue-100 text-blue-700 border-blue-300"),
    "open":      ("Đang mở",        "bg-green-100 text-green-700 border-green-300"),
    "expired":   ("Đã quá hạn",     "bg-orange-100 text-orange-700 border-orange-300"),
    "closed":    ("Đã đóng",        "bg-gray-200 text-gray-600 border-gray-400"),
}


def state_chip(state: str):
    lbl, cls = STATE.get(state, (state, "bg-gray-100 text-gray-500 border-gray-300"))
    return ui.label(lbl).classes(
        f"text-xs font-medium px-2 py-0.5 rounded border whitespace-nowrap {cls}")


def fmt_dt(s: str | None) -> str:
    """'2026-09-20 17:00:00' → '20/09/2026 17:00'."""
    if not s:
        return "—"
    s = str(s)
    return f"{_dmy(s[:10])} {s[11:16]}".strip()


class NgayGio:
    """Ô ngày (dd/mm/yyyy) + ô giờ (HH:mm) → chuỗi 'YYYY-MM-DD HH:MM' cho API.

    Hai ô tách rời thay vì một ô gõ tự do: người dùng quen chọn lịch, và ô giờ có
    sẵn đồng hồ chọn. Ô ngày rỗng = không đặt (None).
    """

    def __init__(self, label: str, value: str | None = None, default_time: str = "17:00"):
        v = str(value or "")
        d0 = _dmy(v[:10]) if v else ""
        t0 = v[11:16] if len(v) >= 16 else default_time
        with ui.row().classes("items-center gap-2 no-wrap"):
            with ui.input(label, value=d0).props("dense outlined clearable").classes("w-44") as self.d:
                with self.d.add_slot("append"):
                    ui.icon("edit_calendar").on("click", lambda: m1.open()).classes("cursor-pointer")
                with ui.menu() as m1:
                    # KHÔNG truyền value= khi rỗng — xem _o_chon_ngay_trong() trong shared.py
                    kw = {"value": d0} if d0 else {}
                    ui.date(mask="DD/MM/YYYY", on_change=m1.close, **kw).bind_value(self.d)
            with ui.input("Giờ", value=t0).props("dense outlined mask='##:##'").classes("w-28") as self.t:
                with self.t.add_slot("append"):
                    ui.icon("schedule").on("click", lambda: m2.open()).classes("cursor-pointer")
                with ui.menu() as m2:
                    ui.time(value=t0, mask="HH:mm", on_change=m2.close).props("format24h").bind_value(self.t)

    def get(self) -> str | None:
        d = (self.d.value or "").strip()
        if not d:
            return None
        t = (self.t.value or "").strip() or "00:00"
        return f"{_iso_tu_dmy(d)} {t}"
