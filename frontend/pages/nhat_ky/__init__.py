"""Trang Nhật ký hệ thống — một mục menu, bốn tab: Tổng quan · Thao tác · Đăng nhập · Lỗi hệ thống.

Trước đây là ba mục menu rời (/audit-logs, /logs, /login-logs) — tên na ná nhau, người
dùng không biết mở cái nào, và muốn lần từ một lượt đăng nhập sang thao tác của người
đó phải tự nhớ giờ rồi sang màn khác lọc lại. Bộ lọc ghi trên địa chỉ trang
(?tab=…&…) nên gửi link là người nhận thấy đúng danh sách đó.

Mỗi tab một file; nối nhau qua `NhatKyCtx.mo_tab()` — xem `_chung.py`.
"""
from fastapi import Request
from nicegui import ui

import frontend.api_client as api
from frontend.shared import _content_area, _page_header, _require_auth, _sidebar

from ._chung import NhatKyCtx
from ._dang_nhap import TabDangNhap
from ._loi import TabLoi
from ._thao_tac import TabThaoTac
from ._tong_quan import TabTongQuan

_TAB = [
    ("tong-quan", "Tổng quan",     "insights",      TabTongQuan),
    ("thao-tac",  "Thao tác",      "history",       TabThaoTac),
    ("dang-nhap", "Đăng nhập",     "login",         TabDangNhap),
    ("loi",       "Lỗi hệ thống",  "error_outline", TabLoi),
]


@ui.page("/audit-logs")
async def nhat_ky_page(request: Request):
    if not _require_auth():
        return
    if not api.has_feature("menu.logs"):
        ui.navigate.to("/home")
        return
    _ = await _sidebar("audit-logs")

    loc = dict(request.query_params)
    tab_dau = loc.pop("tab", "tong-quan")
    ctx = NhatKyCtx()

    with _content_area():
        _page_header("Nhật ký hệ thống",
                     "Ai đã làm gì, ai đăng nhập, hệ thống gặp lỗi gì — lưu 12 tháng gần nhất")
        with ui.tabs(on_change=ctx.khi_doi_tab).props(
                "dense no-caps align=left active-color=red-9 indicator-color=red-9").classes(
                "text-gray-600 border-b border-gray-200 w-full") as ctx.tabs:
            the = {ten: ui.tab(ten, label=nhan, icon=icon) for ten, nhan, icon, _ in _TAB}
        with ui.tab_panels(ctx.tabs, value="tong-quan").props("animated=false").classes(
                "w-full bg-transparent"):
            for ten, _, _, lop in _TAB:
                with ui.tab_panel(the[ten]).classes("px-0"):
                    ctx.bang[ten] = lop(ctx)

    await ctx.bang["thao-tac"].nap_danh_muc()
    await ctx.mo_tab(tab_dau, loc)


# ── Địa chỉ cũ: sổ đánh dấu, link trong màn Giám sát hệ thống ──
@ui.page("/logs")
def _lich_su_loi_cu():
    ui.navigate.to("/audit-logs?tab=loi")


@ui.page("/login-logs")
def _dang_nhap_cu():
    ui.navigate.to("/audit-logs?tab=dang-nhap")
