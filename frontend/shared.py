"""Shared utilities, helpers và constants dùng chung cho tất cả pages."""
import asyncio
import os
from nicegui import ui, app
import frontend.api_client as api

# ─── Constants ──────────────────────────────────────────────────────────────
MENU_ITEMS = [
    ("home",         "Trang chủ",                     "dashboard"),
    ("staff",        "Quản lý User",                  "manage_accounts"),
    ("source_users", "Danh sách giao dịch viên",       "manage_accounts"),
    ("handovers",    "Bàn giao chứng từ",             "receipt_long"),
    ("bundles",      "Đóng chứng từ",                "folder_zip"),
    ("storage",      "Lưu trữ",                       "inventory_2"),
    ("leaves",       "Nghỉ phép",                     "event_busy"),
    ("reports",      "Báo cáo",                       "assessment"),
]

COLORS = {
    "primary": "#8B0000",
    "accent": "#C00000",
    "bg": "#F5F7FA",
    "card": "#FFFFFF",
    "text": "#1A1A2E",
    "muted": "#6B7280",
    "border": "#E5E7EB",
    "success": "#16A34A",
    "warning": "#D97706",
    "danger": "#DC2626",
}

MENU_ITEMS_CV = [
    ("handovers", "Bàn giao chứng từ", "receipt_long"),
    ("leaves",    "Nghỉ phép",          "event_busy"),
]


# ─── Helpers ────────────────────────────────────────────────────────────────
async def _logout():
    await asyncio.to_thread(api.logout_session)
    api.clear_auth()
    ui.navigate.to("/login")


def _sidebar(current_page: str) -> dict:
    badge_refs: dict = {}
    with ui.column().classes("w-56 min-h-screen bg-red-900 text-white fixed left-0 top-0 shadow-xl"):
        # Logo
        with ui.row().classes("w-full items-center px-3 py-3 border-b border-red-700"):
            ui.image("/static/agribank_logo.png").classes("w-10 h-10 shrink-0")
            ui.label("KSNB & HTVH").classes("font-semibold text-sm text-white ml-2 leading-snug")

        # Thông tin user (click → Quản lý người dùng)
        user = api.get_current_user()
        user_role = user.get("role", "") if user else ""
        if user:
            role_map = {
                "giam_doc":      "Giám đốc",
                "pho_giam_doc":  "Phó Giám đốc",
                "admin":         "Quản trị viên",
                "hau_kiem_vien": "Hậu kiểm viên",
                "truong_phong":  "Trưởng phòng",
                "pho_phong":     "Phó phòng",
                "controller":    "Phó phòng",
                "chuyen_vien":   "Chuyên viên",
            }
            clickable = user_role != "chuyen_vien"
            col_cls = "px-4 py-3 border-b border-red-700 w-full"
            if clickable:
                col_cls += " cursor-pointer hover:bg-red-800"
            col = ui.column().classes(col_cls)
            if clickable:
                col.on("click", lambda: ui.navigate.to("/user-management"))
            with col:
                with ui.row().classes("items-center gap-1"):
                    ui.label(user.get("full_name", "")).classes("font-semibold text-sm")
                    if clickable:
                        ui.icon("manage_accounts").classes("text-yellow-300 text-sm")
                ui.label(role_map.get(user.get("role"), "")).classes("text-yellow-300 text-xs")

        # Menu — chuyên viên chỉ thấy bàn giao chứng từ
        menu = MENU_ITEMS_CV if user_role == "chuyen_vien" else MENU_ITEMS
        with ui.column().classes("w-full py-2 flex-1"):
            for key, label, icon in menu:
                is_active = current_page == key
                bg = "bg-red-700" if is_active else "hover:bg-red-800"
                with ui.row().classes(f"w-full items-center px-4 py-3 cursor-pointer {bg}").on(
                    "click", lambda k=key: ui.navigate.to(f"/{k}")
                ):
                    ui.icon(icon).classes("text-xl mr-3 text-red-100")
                    ui.label(label).classes("text-sm flex-1")
                    if key in ("leaves", "handovers"):
                        b = ui.label("").classes(
                            "text-xs font-bold bg-yellow-400 text-red-900 rounded-full "
                            "min-w-[1.1rem] h-[1.1rem] flex items-center justify-center px-1"
                        )
                        b.set_visibility(False)
                        badge_refs[key] = b

        # Admin / GĐ / PGĐ: Nhật ký hệ thống
        if user_role in ("admin", "giam_doc", "pho_giam_doc"):
            is_active = current_page == "logs"
            bg = "bg-red-700" if is_active else "hover:bg-red-800"
            with ui.row().classes(f"w-full items-center px-4 py-3 cursor-pointer {bg}").on(
                "click", lambda: ui.navigate.to("/logs")
            ):
                ui.icon("terminal").classes("text-xl mr-3 text-red-100")
                ui.label("Nhật ký hệ thống").classes("text-sm")

        # Đăng xuất
        with ui.row().classes("w-full items-center px-4 py-3 cursor-pointer hover:bg-red-800 border-t border-red-700").on(
            "click", _logout
        ):
            ui.icon("logout").classes("text-xl mr-3 text-red-300")
            ui.label("Đăng xuất").classes("text-sm")
    return badge_refs


def _content_area():
    return ui.column().classes("ml-56 min-h-screen bg-gray-50 p-6 overflow-x-hidden").style("width: calc(100vw - 14rem)")


def _page_header(title: str, subtitle: str = ""):
    with ui.column().classes("mb-6"):
        ui.label(title).classes("text-2xl font-bold text-red-900")
        if subtitle:
            ui.label(subtitle).classes("text-gray-500 text-sm mt-1")


def _card(title: str = ""):
    with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden") as card:
        if title:
            with ui.row().classes("w-full bg-red-50 px-4 py-3 border-b border-red-100"):
                ui.label(title).classes("font-semibold text-red-800")
    return card


def _require_auth():
    """Redirect về login nếu chưa đăng nhập."""
    if not api.get_current_user():
        ui.navigate.to("/login")
        return False

    client = ui.context.client

    async def _tab_check():
        try:
            await client.connected()
        except Exception:
            return
        tab_id = client.tab_id
        tab_data = app.storage._tabs.get(tab_id) if tab_id else None
        if not (tab_data and tab_data.get("session_alive")):
            api.clear_auth()
            client.open("/login")
    asyncio.ensure_future(_tab_check())
    return True


def _redirect_if_cv():
    """Redirect chuyên viên về /handovers nếu họ truy cập trang không được phép."""
    user = api.get_current_user()
    if user and user.get("role") == "chuyen_vien":
        ui.navigate.to("/handovers")
        return True
    return False


def _handle_api_error(e: Exception) -> bool:
    """Xử lý lỗi API. Trả True nếu session hết hạn và đã redirect (caller nên return)."""
    if isinstance(e, api.SessionExpiredError):
        ui.notify(str(e), type="warning")
        ui.navigate.to("/login")
        return True
    ui.notify(str(e), type="negative")
    return False
