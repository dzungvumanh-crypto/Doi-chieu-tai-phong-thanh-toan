"""Nhắc lịch nhân sự — nâng lương, bổ nhiệm lại, cấp công cụ mới.

Mốc nhắc do backend tính (`hr_service.tinh_nhac_lich`): nâng lương và cấp công
cụ nhắc trước 1 quý, bổ nhiệm lại nhắc trước 1 năm. Việc **đã quá hạn** vẫn nằm
trong danh sách và được tô đỏ — cho biến mất thì đúng thứ cần xử lý gấp lại là
thứ không ai nhìn thấy.
"""
import asyncio

from nicegui import ui

import frontend.api_client as api
from frontend.shared import (_content_area, _dmy, _handle_api_error, _page_header,
                             _require_auth, _sidebar)

_KHOI = [
    ("nang_luong",   "Đến kỳ nâng lương",       "payments",   "trước 1 quý"),
    ("bo_nhiem_lai", "Đến hạn bổ nhiệm lại",    "how_to_reg", "trước 1 năm"),
    ("cap_moi",      "Đến hạn cấp công cụ mới", "smartphone", "trước 1 quý"),
]


def _mau(con_lai: int) -> tuple[str, str]:
    """(màu nền, chữ trạng thái) theo số ngày còn lại."""
    if con_lai < 0:
        return "bg-red-50 border-red-300", f"Quá hạn {abs(con_lai)} ngày"
    if con_lai <= 30:
        return "bg-amber-50 border-amber-300", f"Còn {con_lai} ngày"
    return "bg-white border-gray-200", f"Còn {con_lai} ngày"


@ui.page("/hr_reminders")
async def hr_reminders_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.hr_reminders"):
        ui.navigate.to("/home")
        return

    await _sidebar("hr_reminders")

    with _content_area():
        _page_header("Nhắc lịch nhân sự",
                     "Nâng lương, bổ nhiệm lại và cấp công cụ, dụng cụ mới")

        khung = ui.column().classes("w-full gap-4")

        async def tai():
            try:
                rows = await asyncio.to_thread(api.get, "/api/hr/reminders")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(str(e), type="negative")
                return
            theo_loai: dict[str, list] = {}
            for r in rows:
                theo_loai.setdefault(r["loai"], []).append(r)

            khung.clear()
            with khung:
                if not rows:
                    ui.label("Không có việc nào đến hạn trong kỳ nhắc."
                             ).classes("text-gray-500 py-8 text-center w-full")
                for loai, tieu_de, icon, ky in _KHOI:
                    muc = theo_loai.get(loai, [])
                    if not muc:
                        continue
                    with ui.card().classes("w-full p-0 overflow-hidden"):
                        with ui.row().classes(
                            "w-full bg-red-50 px-4 py-2 items-center gap-2 border-b border-red-100"
                        ):
                            ui.icon(icon).classes("text-red-700")
                            ui.label(f"{tieu_de} ({ky})").classes(
                                "font-semibold text-red-800 flex-1")
                            ui.label(str(len(muc))).classes(
                                "text-xs font-bold bg-red-700 text-white rounded-full px-2 py-0.5")
                        with ui.column().classes("w-full p-3 gap-2"):
                            for m in muc:
                                nen, trang_thai = _mau(m["con_lai"])
                                with ui.row().classes(
                                    f"w-full items-center gap-3 border rounded px-3 py-2 {nen}"
                                ):
                                    with ui.column().classes("gap-0 flex-1 min-w-0"):
                                        ui.label(f"{m['full_name']} "
                                                 f"({m['employee_code'] or '—'})"
                                                 ).classes("text-sm font-medium truncate")
                                        ui.label(f"{m['department'] or '—'} · {m['mo_ta'] or ''}"
                                                 ).classes("text-xs text-gray-600 truncate")
                                    ui.label(_dmy(m["ngay_moc"])).classes(
                                        "text-sm font-semibold w-28 text-right")
                                    ui.label(trang_thai).classes(
                                        "text-xs w-32 text-right "
                                        + ("text-red-700 font-semibold" if m["con_lai"] < 0
                                           else "text-gray-600"))
                                    if api.has_feature("menu.hr_profiles"):
                                        ui.button(
                                            icon="open_in_new",
                                            on_click=lambda: ui.navigate.to("/hr_profiles"),
                                        ).props("dense flat round size=sm").tooltip("Mở hồ sơ")

        await tai()
