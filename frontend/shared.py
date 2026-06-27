"""Shared utilities, helpers và constants dùng chung cho tất cả pages."""
import asyncio
import os
from nicegui import ui, app
import frontend.api_client as api

# ─── Colors ──────────────────────────────────────────────────────────────────
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

# ─── Navigation structure ─────────────────────────────────────────────────────
# Mỗi department có thể có items con. Thêm item mới: chèn vào "items" của phòng tương ứng.
DEPARTMENTS = [
    {
        "id": "ksnb",
        "label": "Phòng KSNB & HTVH",
        "icon": "manage_search",
        "items": [
            ("handovers", "Bàn giao chứng từ", "receipt_long"),
            ("bundles",   "Đóng chứng từ",     "folder_zip"),
            ("storage",   "Lưu trữ",            "inventory_2"),
            ("reports",   "Báo cáo",            "assessment"),
        ],
    },
    {"id": "swift",   "label": "Phòng Swift",               "icon": "swap_horiz",     "items": []},
    {
        "id": "payment", "label": "Phòng Thanh toán", "icon": "payments",
        "items": [
            ("duty_schedule", "Phân lịch trực", "edit_calendar"),
            ("cham_459901",   "Chấm 459901",    "task_alt"),
        ],
    },
    {"id": "ktoan",   "label": "Phòng Kế toán",             "icon": "calculate",       "items": []},
    {"id": "nostro",  "label": "Phòng QLTK Nostro, Vostro", "icon": "account_balance", "items": []},
    {
        "id": "tonghop",
        "label": "Phòng Tổng hợp",
        "icon": "summarize",
        "items": [
            ("leaves", "Nghỉ phép", "event_busy"),
            {
                "label": "Báo cáo",
                "icon": "assessment",
                "items": [
                    ("th_reports", "Báo cáo dữ liệu thanh toán", "payments"),
                ],
            },
        ],
    },
    {"id": "bgd", "label": "Ban Giám đốc", "icon": "business_center", "items": []},
]

# Chuyên viên chỉ thấy 2 mục này (flat, không theo phòng ban)
MENU_ITEMS_CV = [
    ("handovers", "Bàn giao chứng từ", "receipt_long"),
    ("leaves",    "Nghỉ phép",          "event_busy"),
]

# CSS flyout menu — submenu hiện bên phải khi hover, không đẩy item phía dưới
_SIDEBAR_CSS = """<style>
.dept-item { position: relative; z-index: 0; }
.dept-item:hover { z-index: 1000; }
.dept-flyout {
  display: none;
  position: absolute;
  left: 100%;
  top: 0;
  background-color: #7f1d1d;
  z-index: 9999;
  min-width: 13rem;
  flex-direction: column;
  box-shadow: 6px 4px 20px rgba(0,0,0,0.5);
  border-radius: 0 8px 8px 0;
  border-left: 3px solid #991b1b;
  overflow: visible;
}
.dept-item:hover .dept-flyout { display: flex; }
.flyout-group { position: relative; z-index: 0; }
.flyout-group:hover { z-index: 10001; }
.sub-flyout {
  display: none;
  position: absolute;
  left: 100%;
  top: 0;
  background-color: #7f1d1d;
  z-index: 10000;
  min-width: 13rem;
  flex-direction: column;
  box-shadow: 6px 4px 20px rgba(0,0,0,0.5);
  border-radius: 0 8px 8px 0;
  border-left: 3px solid #991b1b;
  overflow: hidden;
}
.flyout-group:hover .sub-flyout { display: flex; }
</style>"""


# ─── Helpers ─────────────────────────────────────────────────────────────────
async def _logout():
    await asyncio.to_thread(api.logout_session)
    api.clear_auth()
    ui.navigate.to("/login")


def _nav_item(key: str, label: str, icon: str, current_page: str, badge_refs: dict):
    """Mục menu phẳng (không thuộc phòng ban)."""
    is_active = current_page == key
    bg = "bg-red-700" if is_active else "hover:bg-red-800"
    with ui.row().classes(
        f"w-full items-center px-4 py-2.5 cursor-pointer {bg}"
    ).on("click", lambda k=key: ui.navigate.to(f"/{k}")):
        ui.icon(icon).classes("text-lg mr-3 text-red-100 shrink-0")
        ui.label(label).classes("text-sm flex-1")
        if key in ("leaves", "handovers"):
            b = ui.label("").classes(
                "text-xs font-bold bg-yellow-400 text-red-900 rounded-full "
                "min-w-[1.1rem] h-[1.1rem] flex items-center justify-center px-1"
            )
            b.set_visibility(False)
            badge_refs[key] = b


def _item_visible(item, check_features: bool) -> bool:
    """Kiểm tra một item (tuple hoặc sub-group dict) có visible không."""
    if isinstance(item, tuple):
        k, _, _ = item
        return not check_features or api.has_feature(f"menu.{k}")
    # dict = sub-group: visible nếu ít nhất 1 child visible
    return any(
        not check_features or api.has_feature(f"menu.{k}")
        for k, _, _ in item["items"]
    )


def _dept_group(dept: dict, current_page: str, badge_refs: dict, check_features: bool = True):
    """Nhóm phòng ban — hover để xem flyout menu bên phải (không đẩy các mục dưới xuống).
    check_features=True: lọc items theo api.has_feature(); False: hiện tất cả (dùng cho admin menu cứng).
    Item có thể là tuple (key, label, icon) hoặc dict sub-group {"label", "icon", "items"}.
    """
    visible_items = [i for i in dept["items"] if _item_visible(i, check_features)]
    if dept["items"] and not visible_items:
        return

    # Tổng hợp tất cả route keys (kể cả trong sub-group) để detect active state
    dept_keys: set[str] = set()
    for item in visible_items:
        if isinstance(item, tuple):
            dept_keys.add(item[0])
        else:
            dept_keys.update(k for k, _, _ in item["items"])
    is_active_dept = current_page in dept_keys

    with ui.element("div").classes("dept-item w-full"):
        # ── Header phòng (luôn hiển thị, không click) ──
        active_cls = " bg-red-800" if is_active_dept else ""
        with ui.element("div").classes(
            f"flex items-center px-3 py-2.5 cursor-default select-none hover:bg-red-800 w-full{active_cls}"
        ):
            ui.icon(dept["icon"]).classes("text-base mr-2 text-red-200 shrink-0")
            ui.label(dept["label"]).classes("text-xs font-semibold text-red-100 flex-1 leading-tight")
            if visible_items:
                ui.icon("chevron_right").classes("text-sm text-red-400 shrink-0")

        # ── Flyout submenu (xuất hiện bên phải khi hover) ──
        if visible_items:
            with ui.element("div").classes("dept-flyout"):
                with ui.element("div").classes("px-3 py-1.5 border-b border-red-700").style("background:#4c0519"):
                    ui.label(dept["label"]).classes("text-xs font-semibold text-red-300")
                for item in visible_items:
                    if isinstance(item, tuple):
                        # ── Item thông thường ──
                        key, label, icon = item
                        is_active = current_page == key
                        bg = "bg-red-700" if is_active else "hover:bg-red-800"
                        with ui.row().classes(
                            f"w-full items-center px-4 py-2.5 cursor-pointer {bg}"
                        ).on("click", lambda k=key: ui.navigate.to(f"/{k}")):
                            ui.icon(icon).classes("text-base mr-2 text-red-100 shrink-0")
                            ui.label(label).classes("text-sm flex-1")
                            if key in ("leaves", "handovers"):
                                b = ui.label("").classes(
                                    "text-xs font-bold bg-yellow-400 text-red-900 rounded-full "
                                    "min-w-[1.1rem] h-[1.1rem] flex items-center justify-center px-1"
                                )
                                b.set_visibility(False)
                                badge_refs[key] = b
                    else:
                        # ── Sub-group (nested flyout) ──
                        sub_children = [
                            (k, lbl, ico) for k, lbl, ico in item["items"]
                            if not check_features or api.has_feature(f"menu.{k}")
                        ]
                        if not sub_children:
                            continue
                        is_active_sub = any(current_page == k for k, _, _ in sub_children)
                        sub_bg = "bg-red-700" if is_active_sub else "hover:bg-red-800"
                        with ui.element("div").classes("flyout-group w-full"):
                            with ui.row().classes(
                                f"w-full items-center px-4 py-2.5 cursor-default select-none {sub_bg}"
                            ):
                                ui.icon(item["icon"]).classes("text-base mr-2 text-red-100 shrink-0")
                                ui.label(item["label"]).classes("text-sm flex-1")
                                ui.icon("chevron_right").classes("text-sm text-red-400 shrink-0")
                            with ui.element("div").classes("sub-flyout"):
                                with ui.element("div").classes(
                                    "px-3 py-1.5 border-b border-red-700"
                                ).style("background:#4c0519"):
                                    ui.label(item["label"]).classes("text-xs font-semibold text-red-300")
                                for k, lbl, ico in sub_children:
                                    is_active = current_page == k
                                    bg = "bg-red-700" if is_active else "hover:bg-red-800"
                                    with ui.row().classes(
                                        f"w-full items-center px-4 py-2.5 cursor-pointer {bg}"
                                    ).on("click", lambda kk=k: ui.navigate.to(f"/{kk}")):
                                        ui.icon(ico).classes("text-base mr-2 text-red-100 shrink-0")
                                        ui.label(lbl).classes("text-sm flex-1")


def _sidebar(current_page: str) -> dict:
    badge_refs: dict = {}
    ui.add_head_html(_SIDEBAR_CSS)

    with ui.column().classes(
        "w-64 min-h-screen bg-red-900 text-white fixed left-0 top-0 shadow-xl z-[200]"
    ):
        # ── Logo ──
        with ui.row().classes(
            "w-full items-center px-3 py-3 border-b border-red-700 shrink-0"
        ):
            ui.image("/static/agribank_logo.png").classes("w-10 h-10 shrink-0")
            ui.label("PAYMENT CENTER").classes(
                "font-semibold text-sm text-white ml-2 leading-snug"
            )

        # ── User info (click → /user-management nếu không phải chuyen_vien) ──
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
            col_cls = "px-4 py-3 border-b border-red-700 w-full shrink-0"
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

        # ── Vùng menu ──
        with ui.column().classes("w-full flex-1 py-1"):
            # Trang chủ — luôn hiển thị
            _nav_item("home", "Trang chủ", "home", current_page, badge_refs)

            # Phân cấp theo phòng ban (flyout) — hiện theo feature
            for dept in DEPARTMENTS:
                _dept_group(dept, current_page, badge_refs, check_features=True)

            ui.separator().classes("border-red-700 my-1")

            # Quản lý User — admin luôn thấy, user khác cần feature
            if user_role == "admin" or api.has_feature("menu.staff"):
                _nav_item("staff", "Quản lý User", "manage_accounts", current_page, badge_refs)

            # Nhật ký hệ thống — admin luôn thấy, user khác cần feature
            if user_role == "admin" or api.has_feature("menu.logs"):
                _dept_group({
                    "id": "nhatky",
                    "label": "Nhật ký hệ thống",
                    "icon": "terminal",
                    "items": [
                        ("logs",       "Lịch sử lỗi & cảnh báo", "error_outline"),
                        ("login-logs", "Nhật ký đăng nhập",       "login"),
                    ],
                }, current_page, badge_refs, check_features=False)

            # Phân quyền chức năng — chỉ admin (hard-coded, không phải feature)
            if user_role == "admin":
                _dept_group({
                    "id": "phanquyen",
                    "label": "Phân quyền chức năng",
                    "icon": "admin_panel_settings",
                    "items": [
                        ("groups", "Nhóm user", "groups"),
                        ("group-features", "Phân quyền theo nhóm", "tune"),
                    ],
                }, current_page, badge_refs, check_features=False)

        # ── Đăng xuất ──
        with ui.row().classes(
            "w-full items-center px-4 py-3 cursor-pointer hover:bg-red-800 "
            "border-t border-red-700 shrink-0"
        ).on("click", _logout):
            ui.icon("logout").classes("text-xl mr-3 text-red-300")
            ui.label("Đăng xuất").classes("text-sm")

    return badge_refs


def _content_area():
    return (
        ui.column()
        .classes("ml-64 min-h-screen bg-gray-50 p-6 overflow-x-hidden")
        .style("width: calc(100vw - 16rem)")
    )


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

    # ── Kiểm tra session bị thay thế mỗi 60 giây ──
    async def _session_heartbeat():
        try:
            await asyncio.to_thread(api.get, "/api/auth/me")
        except api.DisplacedSessionError:
            api.clear_auth()
            ui.notify("Tài khoản này đang được đăng nhập từ thiết bị khác", type="warning", timeout=4000)
            client.open("/login?reason=displaced")
        except Exception:
            pass  # network hiccup — bỏ qua
    ui.timer(60, _session_heartbeat)

    return True


def _redirect_if_cv():
    """Redirect chuyên viên về /handovers nếu họ truy cập trang không được phép."""
    user = api.get_current_user()
    if user and user.get("role") == "chuyen_vien":
        ui.navigate.to("/handovers")
        return True
    return False


def _handle_api_error(e: Exception) -> bool:
    """Xử lý lỗi API. Trả True nếu cần redirect (caller nên return)."""
    if isinstance(e, api.DisplacedSessionError):
        ui.notify(str(e), type="warning", timeout=4000)
        ui.navigate.to("/login?reason=displaced")
        return True
    if isinstance(e, api.SessionExpiredError):
        ui.notify(str(e), type="warning")
        ui.navigate.to("/login")
        return True
    ui.notify(str(e), type="negative")
    return False
