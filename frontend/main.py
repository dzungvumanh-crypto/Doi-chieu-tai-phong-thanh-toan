"""
NiceGUI Frontend Application
Truy cập: http://localhost:8080
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
from nicegui import ui, app
import frontend.api_client as api

# Serve static assets (logo, etc.)
app.add_static_files('/static', os.path.join(os.path.dirname(__file__), 'static'))

# ─── Shared layout ──────────────────────────────────────────────────────────
MENU_ITEMS = [
    ("home",         "Trang chủ",                     "dashboard"),
    ("staff",        "Quản lý User",                  "manage_accounts"),
    ("source_users", "Danh sách giao dịch viên",       "manage_accounts"),
    ("handovers",    "Bàn giao chứng từ",             "receipt_long"),
    ("bundles",      "Đóng chứng từ",                "folder_zip"),
    ("storage",      "Lưu trữ",                       "inventory_2"),
    ("leaves",       "Nghỉ phép",                     "event_busy"),
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
                "controller":    "Phó phòng",  # backward compat JWT cũ
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


async def _logout():
    await asyncio.to_thread(api.logout_session)
    api.clear_auth()
    ui.navigate.to("/login")


def _content_area():
    """Container cho nội dung chính (offset sidebar)"""
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
    """Redirect về login nếu chưa đăng nhập"""
    if not api.get_current_user():
        ui.navigate.to("/login")
        return False

    # Capture client synchronously while slot context is still valid.
    # After the await the slot stack is empty — access tab storage and
    # navigate via the captured client reference, not via ui.context.
    client = ui.context.client

    async def _tab_check():
        try:
            await client.connected()
        except Exception:
            return  # Timeout hoặc lỗi kết nối — không logout
        # app.storage.tab internally calls context.client (fails post-await).
        # Access _tabs directly by tab_id — no context lookup needed.
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


# ─── LOGIN PAGE ──────────────────────────────────────────────────────────────
from starlette.requests import Request as _StarletteRequest

@ui.page("/login")
async def login_page(request: _StarletteRequest):
    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )

    ui.add_head_html('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">')
    with ui.column().classes("w-full min-h-screen items-center justify-center bg-gradient-to-br from-red-900 to-red-700"):
        with ui.card().classes("w-96 p-8 shadow-2xl rounded-2xl bg-white"):
            with ui.column().classes("w-full items-center mb-6"):
                ui.image("/static/agribank_logo.png").classes("w-24 h-24 mb-2")
                ui.label("KSNB&HTVH").classes("text-2xl font-bold text-red-900")
                ui.label("Agribank – Trung tâm Thanh toán").classes("text-gray-700 text-sm font-bold")

            username = ui.input("Tên đăng nhập", placeholder="admin").classes("w-full")
            password = ui.input("Mật khẩu", password=True, password_toggle_button=True).classes("w-full mt-3")
            err_label = ui.label("").classes("text-red-500 text-sm mt-1")

            # Conflict dialog (built before do_login so the closure captures the objects)
            conflict_label = None
            conflict_dialog = None

            async def do_login(force: bool = False):
                err_label.set_text("")
                try:
                    result = await asyncio.to_thread(
                        api.login, username.value, password.value, client_ip, force
                    )
                    api.set_token(result["access_token"], {
                        "id": result["staff_id"],
                        "full_name": result["full_name"],
                        "role": result["role"],
                        "department_id": result.get("department_id"),
                    })
                    app.storage.tab["session_alive"] = True
                    if result["role"] == "chuyen_vien":
                        ui.navigate.to("/handovers")
                    else:
                        ui.navigate.to("/home")
                except Exception as e:
                    msg = str(e)
                    if "đang được sử dụng" in msg:
                        conflict_label.set_text(msg)
                        conflict_dialog.open()
                    else:
                        err_label.set_text(msg)

            async def _force_login():
                conflict_dialog.close()
                await do_login(force=True)

            with ui.dialog() as conflict_dialog, ui.card().classes("p-6 w-80"):
                ui.label("Tài khoản đang được sử dụng").classes("text-lg font-bold text-orange-700 mb-2")
                conflict_label = ui.label("").classes("text-sm text-gray-700 mb-1")
                ui.label("Bạn có muốn đăng nhập tại đây và ngắt phiên cũ không?").classes("text-sm text-gray-500 mb-4")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Hủy", on_click=conflict_dialog.close).props("flat").classes("text-gray-500")
                    ui.button("Đăng nhập tại đây", on_click=_force_login).classes("bg-orange-600 text-white")

            ui.button("Đăng nhập", on_click=do_login).classes(
                "w-full mt-4 bg-red-700 text-white font-semibold py-3 rounded-lg hover:bg-red-800"
            )

            password.on("keydown.enter", do_login)


# ─── DASHBOARD ───────────────────────────────────────────────────────────────
@ui.page("/home")
@ui.page("/")
async def dashboard_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    badge_refs = _sidebar("home")
    with _content_area():
        _page_header("Trang chủ", "Hệ thống quản lý KSNB&HTVH – Agribank")

        loading_row = ui.row().classes("w-full justify-center items-center py-10")
        with loading_row:
            ui.spinner(size="3em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-3 text-sm")
        content = ui.column().classes("w-full gap-6")

        try:
            await ui.context.client.connected()
        except Exception:
            pass

        async def _empty_list():
            return []

        async def _empty_dict():
            return {}

        try:
            results = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/staff/"),
                asyncio.to_thread(api.get, "/api/departments/"),
                asyncio.to_thread(api.get, "/api/bundles/groups"),
                asyncio.to_thread(api.get, "/api/dashboard/summary"),
                asyncio.to_thread(api.get, "/api/dashboard/pending-counts"),
                return_exceptions=True,
            )
        except Exception as e:
            if isinstance(e, api.SessionExpiredError):
                ui.notify(str(e), type="warning")
                ui.navigate.to("/login")
                return
            results = [[], [], [], {}, {}]

        staff_list, depts, groups, summary, pending = results
        for r in results:
            if isinstance(r, api.SessionExpiredError):
                ui.notify(str(r), type="warning")
                ui.navigate.to("/login")
                return
        staff_list = staff_list if isinstance(staff_list, list) else []
        depts      = depts      if isinstance(depts, list)      else []
        groups     = groups     if isinstance(groups, list)     else []
        summary    = summary    if isinstance(summary, dict)    else {}
        pending    = pending    if isinstance(pending, dict)    else {}

        loading_row.set_visibility(False)

        # ── Cập nhật badge sidebar ────────────────────────────────────────────
        for _bkey in ("leaves", "handovers"):
            _cnt = pending.get(_bkey, 0)
            if _bkey in badge_refs and isinstance(_cnt, int) and _cnt > 0:
                badge_refs[_bkey].set_text(str(_cnt))
                badge_refs[_bkey].set_visibility(True)

        # ── Tỷ lệ đúng hạn ────────────────────────────────────────────────────
        overall   = summary.get("overall", {})
        rate_val  = overall.get("rate")     # None nếu chưa có dữ liệu
        period    = summary.get("period", "")
        on_time   = overall.get("on_time", 0)
        late_cnt  = overall.get("late", 0)
        total_doc = overall.get("total", 0)

        if rate_val is None:
            rate_str  = "—"
            rate_icon = "help_outline"
            rate_clr  = "bg-gray-50 border-gray-200"
            rate_txt_clr = "text-gray-500"
        elif rate_val >= 90:
            rate_str  = f"{rate_val:.1f}%"
            rate_icon = "check_circle"
            rate_clr  = "bg-green-50 border-green-200"
            rate_txt_clr = "text-green-700"
        elif rate_val >= 70:
            rate_str  = f"{rate_val:.1f}%"
            rate_icon = "warning"
            rate_clr  = "bg-yellow-50 border-yellow-200"
            rate_txt_clr = "text-yellow-700"
        else:
            rate_str  = f"{rate_val:.1f}%"
            rate_icon = "error"
            rate_clr  = "bg-red-50 border-red-200"
            rate_txt_clr = "text-red-700"

        stats = [
            ("Cán bộ KSNB",    len(staff_list),                                      "people",     "bg-red-50 border-red-200"),
            ("Phòng nghiệp vụ", len([d for d in depts if d.get("is_source")]),        "business",   "bg-blue-50 border-blue-200"),
            ("Nhóm tập",        len(groups),                                           "folder_zip", "bg-purple-50 border-purple-200"),
            ("Tập đã in",       sum(len(g.get("bundles", [])) for g in groups),        "print",      "bg-orange-50 border-orange-200"),
        ]

        with content:
            # ── Thẻ thống kê + đúng hạn ──────────────────────────────────────
            with ui.row().classes("w-full gap-4 mb-2 flex-wrap"):
                for lbl, val, icon, colors in stats:
                    with ui.card().classes(f"flex-1 min-w-[120px] p-4 rounded-xl border {colors} shadow-sm"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon(icon).classes("text-3xl text-gray-500")
                            with ui.column().classes("gap-0"):
                                ui.label(str(val)).classes("text-3xl font-bold text-gray-800")
                                ui.label(lbl).classes("text-sm text-gray-500")

                # Thẻ đúng hạn
                period_vn = ""
                if period:
                    try:
                        y, m = period.split("-")
                        period_vn = f"Tháng {int(m):02d}/{y}"
                    except Exception:
                        period_vn = period
                with ui.card().classes(f"flex-1 min-w-[160px] p-4 rounded-xl border {rate_clr} shadow-sm"):
                    with ui.row().classes("items-center gap-3"):
                        ui.icon(rate_icon).classes(f"text-3xl {rate_txt_clr}")
                        with ui.column().classes("gap-0"):
                            ui.label(rate_str).classes(f"text-3xl font-bold {rate_txt_clr}")
                            ui.label("Đúng hạn").classes("text-sm text-gray-500")
                            if period_vn:
                                ui.label(period_vn).classes("text-xs text-gray-400")

            # ── Việc đang chờ tôi ─────────────────────────────────────────────
            pend_leaves    = pending.get("leaves",    0)
            pend_handovers = pending.get("handovers", 0)
            if pend_leaves or pend_handovers:
                with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white border border-yellow-100"):
                    ui.label("Việc đang chờ tôi").classes("font-semibold text-red-900 mb-3")
                    if pend_handovers:
                        with ui.row().classes(
                            "w-full items-center gap-3 p-3 bg-orange-50 rounded-lg border border-orange-200 "
                            "cursor-pointer hover:bg-orange-100 mb-2"
                        ).on("click", lambda: ui.navigate.to("/handovers")):
                            ui.icon("receipt_long").classes("text-2xl text-orange-600")
                            with ui.column().classes("flex-1 gap-0"):
                                ui.label(f"{pend_handovers} chứng từ chờ xác nhận").classes("text-sm font-semibold text-orange-800")
                                ui.label("Nhấn để đến Bàn giao chứng từ").classes("text-xs text-orange-500")
                            ui.icon("chevron_right").classes("text-orange-400")
                    if pend_leaves:
                        with ui.row().classes(
                            "w-full items-center gap-3 p-3 bg-blue-50 rounded-lg border border-blue-200 "
                            "cursor-pointer hover:bg-blue-100"
                        ).on("click", lambda: ui.navigate.to("/leaves")):
                            ui.icon("event_busy").classes("text-2xl text-blue-600")
                            with ui.column().classes("flex-1 gap-0"):
                                ui.label(f"{pend_leaves} đơn nghỉ phép chờ duyệt").classes("text-sm font-semibold text-blue-800")
                                ui.label("Nhấn để đến Nghỉ phép").classes("text-xs text-blue-500")
                            ui.icon("chevron_right").classes("text-blue-400")

            # ── Tỷ lệ nộp đúng hạn theo phòng ───────────────────────────────
            by_dept = summary.get("by_dept", [])
            with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white"):
                with ui.row().classes("w-full justify-between items-center mb-1"):
                    title_txt = f"Tỷ lệ nộp chứng từ đúng hạn — {period_vn}" if period_vn else "Tỷ lệ nộp chứng từ đúng hạn"
                    ui.label(title_txt).classes("font-semibold text-red-900")
                    if total_doc:
                        ui.label(f"Tổng {total_doc} chứng từ · {on_time} đúng hạn · {late_cnt} muộn").classes("text-xs text-gray-500")
                ui.label("Đúng hạn = nộp trong 1 ngày làm việc sau ngày giao dịch (bỏ T7/CN, ngày lễ, ngày nghỉ phép của người nhận)").classes(
                    "text-xs text-gray-400 italic mb-3")

                if not by_dept:
                    ui.label("Chưa có dữ liệu bàn giao trong tháng này.").classes("text-gray-400 text-sm mt-1")
                else:
                    with ui.row().classes("w-full px-3 py-2 bg-red-50 text-xs font-semibold text-red-700 border-b border-red-100"):
                        ui.label("Phòng").classes("flex-1")
                        ui.label("Đúng hạn").classes("w-20 text-center")
                        ui.label("Muộn").classes("w-16 text-center")
                        ui.label("Tỷ lệ").classes("w-20 text-center")
                    for row in by_dept:
                        r = row.get("rate")
                        if r is None:
                            r_str, r_cls = "—", "bg-gray-100 text-gray-500"
                        elif r >= 90:
                            r_str, r_cls = f"{r:.1f}%", "bg-green-100 text-green-700"
                        elif r >= 70:
                            r_str, r_cls = f"{r:.1f}%", "bg-yellow-100 text-yellow-700"
                        else:
                            r_str, r_cls = f"{r:.1f}%", "bg-red-100 text-red-700"
                        with ui.row().classes("w-full px-3 py-2 border-b border-gray-100 items-center"):
                            ui.label(row.get("dept_name", "")).classes("flex-1 text-sm")
                            ui.label(str(row.get("on_time", 0))).classes("w-20 text-center text-sm text-green-700 font-medium")
                            ui.label(str(row.get("late", 0))).classes("w-16 text-center text-sm text-red-600")
                            ui.label(r_str).classes(f"w-20 text-center text-xs font-semibold px-2 py-0.5 rounded {r_cls}")

            # ── Các tập chứng từ gần đây ──────────────────────────────────────
            with ui.card().classes("w-full p-4 rounded-xl shadow-sm bg-white"):
                with ui.row().classes("w-full justify-between items-center mb-3"):
                    ui.label("Các tập chứng từ gần đây").classes("font-semibold text-red-900")
                    ui.button("Xem tất cả", icon="arrow_forward",
                              on_click=lambda: ui.navigate.to("/bundles")
                              ).props("flat dense").classes("text-red-700 text-sm")
                if groups:
                    with ui.row().classes(
                        "w-full px-3 py-2 bg-red-50 text-xs font-semibold text-red-700"
                        " border-b border-red-100 rounded-t"
                    ):
                        ui.label("Tên bìa chứng từ").classes("flex-1")
                        ui.label("Số tập").classes("w-20 text-center")
                        ui.label("Ngày tạo").classes("w-28 text-center")
                    for g in groups[:10]:
                        dept        = g.get("department") or {}
                        dept_name   = dept.get("name", "N/A")
                        notes       = g.get("notes") or ""
                        bundle_lbl  = f"{dept_name} – {notes}" if notes else dept_name
                        n_bundles   = g.get("total_bundles", 0)
                        date_str    = (g.get("created_at") or "")[:10]
                        with ui.row().classes(
                            "w-full px-3 py-2 border-b border-gray-100 items-center"
                            " cursor-pointer hover:bg-red-50"
                        ).on("click", lambda: ui.navigate.to("/bundles")):
                            ui.label(bundle_lbl).classes("flex-1 text-sm text-gray-800")
                            ui.label(str(n_bundles)).classes(
                                "w-20 text-center text-sm font-semibold text-red-700"
                            )
                            ui.label(date_str).classes("w-28 text-center text-sm text-gray-500")
                else:
                    ui.label("Chưa có tập chứng từ nào").classes("text-gray-400 text-sm")


# ─── STAFF PAGE ───────────────────────────────────────────────────────────────
@ui.page("/staff")
async def staff_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return

    try:
        all_depts = await asyncio.to_thread(api.get, "/api/departments/")
    except Exception:
        all_depts = []
    dept_id_to_name = {d["id"]: d["name"] for d in all_depts}
    all_dept_opts   = {d["id"]: d["name"] for d in all_depts}

    _ = _sidebar("staff")
    with _content_area():
        _page_header("Quản lý User", "Quản lý tài khoản đăng nhập hệ thống")

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") == "admin"

        ROLE_OPTS = {
            "chuyen_vien":   "Chuyên viên",
            "pho_phong":     "Phó phòng",
            "truong_phong":  "Trưởng phòng",
            "hau_kiem_vien": "Hậu kiểm viên",
            "giam_doc":      "Giám đốc",
            "pho_giam_doc":  "Phó Giám đốc",
            "admin":         "Quản trị viên",
        }
        # controller kept in display map cho JWT session cũ chưa expire
        role_map = {**ROLE_OPTS, "controller": "Phó phòng"}

        staff_cache = []
        edit_target = {"id": None}

        # ── Edit dialog ───────────────────────────────────────────────────────
        edit_dialog = ui.dialog()
        with edit_dialog, ui.card().classes("w-96 p-6"):
            ui.label("Sửa tài khoản").classes("text-lg font-bold mb-4")
            ef_name   = ui.input("Họ tên *").classes("w-full")
            ef_role   = ui.select(ROLE_OPTS, label="Quyền *").classes("w-full mt-2")
            ef_dept   = ui.select(all_dept_opts, label="Phòng *").classes("w-full mt-2")
            ef_phone  = ui.input("Điện thoại").classes("w-full mt-2")
            ef_active = ui.checkbox("Đang hoạt động").classes("mt-2")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=lambda: edit_dialog.close()).classes("text-gray-500")
                async def do_edit():
                    if not edit_target["id"]:
                        return
                    if not ef_dept.value:
                        ui.notify("Vui lòng chọn Phòng", type="warning")
                        return
                    try:
                        await asyncio.to_thread(api.put, f"/api/staff/{edit_target['id']}", {
                            "full_name": ef_name.value,
                            "role": ef_role.value,
                            "phone": ef_phone.value or None,
                            "is_active": ef_active.value,
                            "department_id": ef_dept.value,
                        })
                        edit_dialog.close()
                        ui.notify("Đã cập nhật tài khoản", type="positive")
                        await load_staff()
                    except Exception as e:
                        if _handle_api_error(e): return
                ui.button("Lưu", on_click=do_edit).classes("bg-red-700 text-white")

        # ── Add dialog ────────────────────────────────────────────────────────
        add_dialog = ui.dialog()
        with add_dialog, ui.card().classes("w-96 p-6"):
            ui.label("Thêm tài khoản").classes("text-lg font-bold mb-4")
            f_name     = ui.input("Họ tên *").classes("w-full")
            f_role     = ui.select(ROLE_OPTS, label="Quyền *", value="chuyen_vien").classes("w-full mt-2")
            f_dept     = ui.select(all_dept_opts, label="Phòng *").classes("w-full mt-2")
            f_username = ui.input("Username *").classes("w-full mt-2")
            f_password = ui.input("Mật khẩu *", password=True).classes("w-full mt-2")
            f_phone    = ui.input("Điện thoại").classes("w-full mt-2")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=lambda: add_dialog.close()).classes("text-gray-500")
                async def do_add():
                    if not f_name.value or not f_username.value or not f_password.value:
                        ui.notify("Vui lòng điền đầy đủ Họ tên, Username và Mật khẩu", type="warning")
                        return
                    if not f_dept.value:
                        ui.notify("Vui lòng chọn Phòng", type="warning")
                        return
                    try:
                        await asyncio.to_thread(api.post, "/api/staff/", {
                            "employee_code": f_username.value,
                            "full_name": f_name.value,
                            "role": f_role.value,
                            "username": f_username.value,
                            "password": f_password.value,
                            "phone": f_phone.value or None,
                            "department_id": f_dept.value,
                        })
                        add_dialog.close()
                        ui.notify("Đã thêm tài khoản", type="positive")
                        await load_staff()
                    except Exception as e:
                        if _handle_api_error(e): return
                ui.button("Lưu", on_click=do_add).classes("bg-red-700 text-white")

        # ── Controls ──────────────────────────────────────────────────────────
        with ui.row().classes("w-full justify-between items-center mb-4 gap-2 flex-wrap"):
            with ui.row().classes("items-center gap-2"):
                search = ui.input(placeholder="Tên hoặc username...").classes("w-52").props("dense")
                dept_filter_opts = {0: "Tất cả phòng", **{d["id"]: d["name"] for d in all_depts}}
                dept_filter = ui.select(dept_filter_opts, value=0, label="Phòng").classes("w-48").props("dense")
                ui.button("Tìm kiếm", icon="search", on_click=lambda: render_staff_rows()).classes("bg-gray-700 text-white").props("dense")
            if is_admin:
                ui.button("+ Thêm tài khoản", on_click=lambda: add_dialog.open()).classes("bg-red-700 text-white").props("dense")

        staff_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
        with staff_loading:
            ui.spinner(size="2em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
        rows_container = ui.column().classes("w-full")

        def open_edit(s: dict):
            edit_target["id"] = s["id"]
            ef_name.set_value(s["full_name"])
            ef_role.set_value(s["role"])
            ef_dept.set_value(s.get("department_id"))
            ef_phone.set_value(s.get("phone") or "")
            ef_active.set_value(s.get("is_active", True))
            edit_dialog.open()

        def render_staff_rows():
            rows_container.clear()
            q = search.value.lower()
            sel_dept = dept_filter.value  # 0 = all
            filtered = [
                s for s in staff_cache
                if (not q or q in s["full_name"].lower()
                    or q in s.get("username", "").lower()
                    or q in s.get("employee_code", "").lower())
                and (sel_dept == 0 or s.get("department_id") == sel_dept)
            ]
            # Phân loại: Ban GĐ / tất cả phòng còn lại
            _BGD_ROLES = {"giam_doc", "pho_giam_doc"}
            bgd_list  = [s for s in filtered if s.get("role") in _BGD_ROLES]
            dept_list = [s for s in filtered if s.get("role") not in _BGD_ROLES]

            with rows_container:
                # Header
                with ui.row().classes("w-full px-3 py-2 bg-red-50 font-semibold text-xs text-red-800 border border-red-100 rounded-t"):
                    ui.label("Họ tên").classes("flex-1")
                    ui.label("Quyền").classes("w-28 text-center")
                    ui.label("Phòng").classes("w-40")
                    ui.label("Username").classes("w-28")
                    ui.label("Trạng thái").classes("w-22 text-center")
                    if is_admin:
                        ui.label("Thao tác").classes("w-16 text-center")

                def _row(s: dict):
                    dname = dept_id_to_name.get(s.get("department_id"), "KSNB&HTVH")
                    with ui.row().classes("w-full px-3 py-2 border-b border-gray-100 items-center hover:bg-gray-50"):
                        ui.label(s["full_name"]).classes("flex-1 text-sm")
                        ui.label(role_map.get(s["role"], s["role"])).classes("w-28 text-center text-sm")
                        ui.label(dname).classes("w-40 text-sm text-gray-600")
                        ui.label(s.get("username", "")).classes("w-28 text-sm text-gray-500")
                        if s.get("is_active"):
                            ui.badge("Hoạt động").classes("w-22 text-center").props('color="positive"')
                        else:
                            ui.badge("Tạm khóa").classes("w-22 text-center").props('color="grey"')
                        if is_admin:
                            with ui.row().classes("w-16 gap-0 justify-center"):
                                ui.button(icon="edit", on_click=lambda s=s: open_edit(s)).props("flat dense").classes("text-red-600").tooltip("Sửa")
                                ui.button(icon="delete", on_click=lambda sid=s["id"]: do_deactivate_staff(sid)).props("flat dense").classes("text-red-500").tooltip("Xóa")

                # Nhóm Ban Giám đốc
                if bgd_list:
                    with ui.row().classes("w-full px-3 py-1 bg-red-50 text-xs text-red-700 font-semibold border-b border-red-100 items-center gap-1"):
                        ui.icon("star").classes("text-sm")
                        ui.label("Ban Giám đốc")
                    for s in bgd_list:
                        _row(s)

                # Nhóm theo phòng — Admin/HKV/TP/PP/CV gộp theo department_id
                if dept_list:
                    by_dept: dict = {}
                    for s in dept_list:
                        by_dept.setdefault(s.get("department_id"), []).append(s)
                    for dept_id, members in sorted(by_dept.items(),
                                                   key=lambda x: dept_id_to_name.get(x[0], "")):
                        dname = dept_id_to_name.get(dept_id, f"Phòng ID {dept_id}")
                        with ui.row().classes("w-full px-3 py-1 bg-blue-50 text-xs text-blue-700 font-semibold border-b border-blue-100 items-center gap-1"):
                            ui.icon("badge").classes("text-sm")
                            ui.label(dname)
                        for s in members:
                            _row(s)

                if not filtered:
                    ui.label("Không có kết quả").classes("text-gray-400 text-center py-6 w-full")

        async def load_staff():
            nonlocal staff_cache
            staff_loading.classes(remove="hidden")
            try:
                staff_cache = await asyncio.to_thread(api.get, "/api/staff/", {"active_only": False})
            except Exception as e:
                _handle_api_error(e)
            finally:
                staff_loading.classes(add="hidden")
            render_staff_rows()

        async def do_deactivate_staff(sid: int):
            try:
                await asyncio.to_thread(api.delete, f"/api/staff/{sid}")
                ui.notify("Đã xóa tài khoản", type="positive")
                await load_staff()
            except Exception as ex:
                ui.notify(str(ex) or "Lỗi không xác định", type="negative")

        await load_staff()


# ─── SOURCE USERS PAGE ────────────────────────────────────────────────────────
@ui.page("/source_users")
async def source_users_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _ = _sidebar("source_users")
    with _content_area():
        _page_header("Danh sách giao dịch viên", "User IPCAS, PaymentHub và Họ tên giao dịch viên các phòng")

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") in ("admin", "hau_kiem_vien")

        try:
            depts = [d for d in await asyncio.to_thread(api.get, "/api/departments/") if d.get("is_source")]
        except Exception:
            depts = []

        dept_options = {d["id"]: d["name"] for d in depts}
        edit_su_target = {"id": None}

        # ── Edit dialog ───────────────────────────────────────────────────────
        edit_su_dialog = ui.dialog()
        with edit_su_dialog, ui.card().classes("w-96 p-6"):
            ui.label("Sửa thông tin cán bộ").classes("text-lg font-bold mb-4")
            esu_ipcas  = ui.input("User IPCAS *").classes("w-full")
            esu_hub    = ui.input("User PaymentHub").classes("w-full mt-2")
            esu_vn     = ui.input("Họ và tên").classes("w-full mt-2")
            esu_dept   = ui.select(dept_options, label="Phòng *").classes("w-full mt-2")
            esu_active = ui.checkbox("Đang hoạt động").classes("mt-3")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=lambda: edit_su_dialog.close()).classes("text-gray-500")
                async def do_edit_su():
                    if not edit_su_target["id"]:
                        return
                    try:
                        await asyncio.to_thread(api.put, f"/api/source-users/{edit_su_target['id']}", {
                            "user_code": esu_ipcas.value,
                            "full_name": esu_hub.value or None,
                            "vn_name": esu_vn.value or None,
                            "department_id": esu_dept.value,
                            "is_active": esu_active.value,
                        })
                    except Exception as e:
                        if _handle_api_error(e): return
                        return
                    edit_su_dialog.close()
                    ui.notify("Đã cập nhật cán bộ", type="positive")
                    await load_users()
                ui.button("Lưu", on_click=do_edit_su).classes("bg-red-700 text-white")

        # ── Add dialog ────────────────────────────────────────────────────────
        user_dialog = ui.dialog()
        with user_dialog, ui.card().classes("w-96 p-6"):
            ui.label("Thêm cán bộ").classes("text-lg font-bold mb-4")
            uf_ipcas = ui.input("User IPCAS *").classes("w-full")
            uf_hub   = ui.input("User PaymentHub").classes("w-full mt-2")
            uf_vn    = ui.input("Họ và tên").classes("w-full mt-2")
            uf_dept  = ui.select(dept_options, label="Phòng *",
                                 value=depts[0]["id"] if depts else None).classes("w-full mt-2")
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=lambda: user_dialog.close()).classes("text-gray-500")
                async def do_add_user():
                    if not uf_ipcas.value or not uf_dept.value:
                        ui.notify("Vui lòng điền User IPCAS và chọn phòng", type="warning")
                        return
                    try:
                        await asyncio.to_thread(api.post, "/api/source-users/", {
                            "user_code": uf_ipcas.value,
                            "full_name": uf_hub.value or None,
                            "vn_name": uf_vn.value or None,
                            "department_id": uf_dept.value,
                        })
                    except Exception as e:
                        if _handle_api_error(e): return
                        return
                    user_dialog.close()
                    ui.notify("Đã thêm cán bộ", type="positive")
                    await load_users()
                ui.button("Lưu", on_click=do_add_user).classes("bg-red-700 text-white")

        # ── Controls ──────────────────────────────────────────────────────────
        with ui.row().classes("w-full justify-between items-center mb-4"):
            dept_filter = ui.select(
                {**{None: "-- Tất cả phòng --"}, **dept_options},
                label="Lọc theo phòng", value=None
            ).classes("w-72")
            if is_admin:
                ui.button("+ Thêm cán bộ", on_click=lambda: user_dialog.open()).classes("bg-red-700 text-white")

        su_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
        with su_loading:
            ui.spinner(size="2em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
        rows_container = ui.column().classes("w-full")

        def open_edit_su(u: dict):
            edit_su_target["id"] = u["id"]
            esu_ipcas.set_value(u["user_code"])
            esu_hub.set_value(u.get("full_name") or "")
            esu_vn.set_value(u.get("vn_name") or "")
            esu_dept.set_value(u["department_id"])
            esu_active.set_value(u.get("is_active", True))
            edit_su_dialog.open()

        async def load_users():
            su_loading.classes(remove="hidden")
            rows_container.clear()
            try:
                params: dict = {"active_only": False}
                if dept_filter.value:
                    params["department_id"] = dept_filter.value
                users = await asyncio.to_thread(api.get, "/api/source-users/", params)
            except Exception as e:
                _handle_api_error(e)
                su_loading.classes(add="hidden")
                return
            su_loading.classes(add="hidden")

            with rows_container:
                ui.label(f"{len(users)} cán bộ").classes("text-gray-500 text-sm mb-2")

                with ui.row().classes("w-full px-3 py-2 bg-red-50 font-semibold text-xs text-red-800 border border-red-100 rounded-t"):
                    ui.label("STT").classes("w-10 text-center")
                    ui.label("User IPCAS").classes("w-36")
                    ui.label("User PaymentHub").classes("w-44")
                    ui.label("Họ và tên").classes("flex-1")
                    ui.label("Phòng").classes("w-52")
                    ui.label("TT").classes("w-8 text-center")
                    if is_admin:
                        ui.label("").classes("w-20 text-center")

                for idx, u in enumerate(users):
                    is_active = u.get("is_active", True)

                    def _make_deactivate(uid):
                        async def _h():
                            try:
                                await asyncio.to_thread(api.delete, f"/api/source-users/{uid}")
                            except Exception as e:
                                if _handle_api_error(e): return
                                return
                            ui.notify("Đã ẩn cán bộ (dữ liệu lịch sử được giữ nguyên)", type="positive")
                            await load_users()
                        return _h

                    row_cls = "w-full px-3 py-2 border-b border-gray-100 items-center hover:bg-gray-50"
                    if not is_active:
                        row_cls += " opacity-50"
                    with ui.row().classes(row_cls):
                        ui.label(str(idx + 1)).classes("w-10 text-center text-gray-400 text-sm")
                        ui.label(u["user_code"]).classes("w-36 text-sm font-mono")
                        ui.label(u.get("full_name") or "—").classes("w-44 text-sm text-gray-600")
                        ui.label(u.get("vn_name") or "—").classes("flex-1 text-sm")
                        ui.label(dept_options.get(u["department_id"], "")).classes("w-52 text-sm text-gray-500")
                        if is_active:
                            ui.icon("check_circle").classes("w-8 text-center text-green-500")
                        else:
                            ui.icon("cancel").classes("w-8 text-center text-red-400")
                        if is_admin:
                            with ui.row().classes("w-20 gap-1 justify-center"):
                                ui.button(icon="edit", on_click=lambda u=u: open_edit_su(u)).props("flat dense").classes("text-red-600").tooltip("Sửa")
                                if is_active:
                                    ui.button(icon="visibility_off", on_click=_make_deactivate(u["id"])).props("flat dense").classes("text-gray-500").tooltip("Ẩn (giữ lịch sử)")

                if not users:
                    ui.label("Không có cán bộ nào").classes("text-gray-400 text-center py-6 w-full")

        dept_filter.on("update:model-value", lambda: load_users())
        await load_users()


# ─── HANDOVERS PAGE ───────────────────────────────────────────────────────────
# Màu ô theo entry_status
_CELL_STATUS_STYLE = {
    "pending_confirm": ("background:#FEF3C7", "2px solid #F59E0B"),  # vàng nhạt
    "borrowed":        ("background:#FFEDD5", "2px solid #EA580C"),  # cam nhạt
    "confirmed":       ("background:#DCFCE7", "2px solid #16A34A"),  # xanh lá nhạt
}
_STATUS_DOT_COLOR = {
    "pending_confirm": "#D97706",
    "confirmed":       "#16A34A",
    "borrowed":        "#EA580C",
}
_STATUS_LABEL_MAP = {
    "pending_confirm": "Chờ xác nhận",
    "confirmed":       "Đã xác nhận",
    "borrowed":        "Đang mượn",
}
_ACTION_COLOR_MAP = {
    "blue":   "#2563EB",
    "green":  "#16A34A",
    "orange": "#EA580C",
    "purple": "#7C3AED",
}

@ui.page("/handovers")
async def handovers_page():
    if not _require_auth():
        return

    user_data = api.get_current_user()
    user_role = user_data.get("role", "") if user_data else ""
    is_cv     = user_role == "chuyen_vien"

    badge_refs = _sidebar("handovers")

    # ── Right drawer panel ────────────────────────────────────────────────────
    with ui.right_drawer(value=False).props("width=360 overlay").classes(
        "bg-white shadow-2xl overflow-y-auto"
    ) as right_panel:
        panel_container = ui.column().classes("w-full gap-0")

    with _content_area():
        _page_header("Bàn giao chứng từ", "Nhập số chứng từ theo ngày và cán bộ")

        from datetime import date as _date
        today = _date.today()

        # ── Filter controls ───────────────────────────────────────────────────
        try:
            _all_depts_raw, _pending = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/departments/"),
                asyncio.to_thread(api.get, "/api/dashboard/pending-counts"),
                return_exceptions=True,
            )
        except Exception:
            _all_depts_raw, _pending = [], {}
        if not isinstance(_all_depts_raw, list):
            _all_depts_raw = []
        if isinstance(_pending, dict):
            _hcnt = _pending.get("handovers", 0)
            if "handovers" in badge_refs and _hcnt > 0:
                badge_refs["handovers"].set_text(str(_hcnt))
                badge_refs["handovers"].set_visibility(True)
        all_depts = [d for d in _all_depts_raw if d.get("is_source")]

        # Block Tổng hợp staff from accessing handovers entirely
        if user_role in ("chuyen_vien", "pho_phong", "truong_phong"):
            _user_dept_id = user_data.get("department_id") if user_data else None
            _user_dept = next((d for d in _all_depts_raw if d.get("id") == _user_dept_id), None)
            if _user_dept and _user_dept.get("code", "").upper() in ("TONGHOP", "TONG_HOP", "TH"):
                ui.notify("Phòng Tổng hợp không có quyền truy cập bàn giao chứng từ", type="negative", timeout=5000)
                ui.navigate.to("/")
                return

        dept_opts  = {d["id"]: d["name"] for d in all_depts}
        year_opts  = {y: str(y) for y in range(2023, today.year + 3)}
        month_opts = {m: f"Tháng {m:02d}" for m in range(1, 13)}

        # Chuyên viên: tự động xác định phòng của mình
        cv_dept_id = user_data.get("department_id") if is_cv else None
        default_dept  = cv_dept_id if (is_cv and cv_dept_id) else (all_depts[0]["id"] if all_depts else None)
        default_year  = today.year
        default_month = today.month


        with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 mb-4"):
            with ui.row().classes("items-end gap-4 flex-wrap"):
                sel_dept = ui.select(dept_opts, label="Phòng", value=default_dept).classes("w-72")
                if is_cv:
                    sel_dept.props("disable")
                    sel_dept.tooltip("Phòng của bạn (không thể thay đổi)")
                sel_year  = ui.select(year_opts,  label="Năm",   value=default_year).classes("w-28")
                sel_month = ui.select(month_opts, label="Tháng", value=default_month).classes("w-36")
                ui.button("Tải dữ liệu", icon="search",
                          on_click=lambda: load_grid()
                          ).classes("bg-red-700 text-white px-4").tooltip("Tải dữ liệu")

        # Chú thích màu trạng thái
        with ui.row().classes("items-center gap-4 mb-2 flex-wrap"):
            for status_key, label in [("confirmed", "Đã xác nhận"), ("pending_confirm", "Chờ xác nhận"), ("borrowed", "Đang mượn")]:
                bg, border = _CELL_STATUS_STYLE[status_key]
                with ui.row().classes("items-center gap-1"):
                    ui.element("div").style(
                        f"width:14px;height:14px;border-radius:3px;{bg};border:{border}"
                    )
                    ui.label(label).classes("text-xs text-gray-600")

        async def save_pending():
            save_btn.props("loading")
            year  = sel_year.value
            month = sel_month.value
            # Collect all modified cells from the DOM (works even without prior blur)
            changes = await ui.run_javascript("""
                var r = [];
                document.querySelectorAll('.hv-inp').forEach(function(inp) {
                    var orig = parseInt(inp.dataset.orig || '0');
                    var curr = inp.value === '' ? 0 : (parseInt(inp.value) || 0);
                    if (curr !== orig) r.push({uid: parseInt(inp.dataset.uid), day: parseInt(inp.dataset.day), count: curr});
                });
                return r;
            """)
            changes = changes or []
            errors = []
            for item in changes:
                date_str = f"{year}-{month:02d}-{item['day']:02d}"
                try:
                    await asyncio.to_thread(
                        api.put, "/api/handovers/entry-upsert",
                        {"source_user_id": item["uid"], "date": date_str, "sheet_count": item["count"]},
                    )
                except Exception as ex:
                    if _handle_api_error(ex):
                        save_btn.props(remove="loading")
                        return
                    errors.append(str(ex))
            save_btn.props(remove="loading")
            if errors:
                ui.notify(f"Lỗi khi lưu: {'; '.join(errors[:3])}", type="negative")
            elif changes:
                ui.notify(f"Đã lưu {len(changes)} ô", type="positive")
            else:
                ui.notify("Không có thay đổi nào", type="info")
            await load_grid()

        with ui.row().classes("gap-2 mb-2 items-center"):
            save_btn = ui.button("Lưu", icon="save",
                on_click=save_pending
            ).classes("bg-green-700 text-white px-4").tooltip("Lưu tất cả thay đổi")

            async def _export_handovers():
                try:
                    import calendar as _cal
                    y, m = sel_year.value, sel_month.value
                    last_day = _cal.monthrange(y, m)[1]
                    from_d = f"{y}-{m:02d}-01"
                    to_d   = f"{y}-{m:02d}-{last_day:02d}"
                    params = {"from_date": from_d, "to_date": to_d}
                    if sel_dept.value:
                        params["department_id"] = sel_dept.value
                    content = await asyncio.to_thread(
                        api.download, "/api/handovers/export",
                        params=params,
                    )
                    ui.download(content, f"chung_tu_{y}_{m:02d}.xlsx")
                except Exception as e:
                    _handle_api_error(e)

            ui.button("Xuất Excel", icon="download",
                      on_click=_export_handovers).classes("bg-blue-700 text-white px-4").tooltip("Tải file Excel")

        title_label    = ui.label("").classes("text-lg font-bold text-red-900 mb-3")
        loading_row    = ui.row().classes("w-full justify-center items-center py-10 hidden")
        with loading_row:
            ui.spinner(size="3em", color="red")
            ui.label("Đang tải dữ liệu...").classes("text-gray-500 ml-3 text-sm")
        grid_container = ui.column().classes("w-full")

        def _save_filter_state():
            app.storage.tab["hv_dept"]  = sel_dept.value
            app.storage.tab["hv_year"]  = sel_year.value
            app.storage.tab["hv_month"] = sel_month.value

        # ── Side panel renderer ───────────────────────────────────────────────
        async def open_entry_panel(entry_id: int, user_name: str):
            panel_container.clear()
            try:
                hist = await asyncio.to_thread(
                    api.get, f"/api/handovers/entries/{entry_id}/history"
                )
            except Exception as ex:
                with panel_container:
                    with ui.row().classes("w-full justify-between items-center px-4 py-3 bg-red-50 border-b border-red-100"):
                        ui.label("Lỗi").classes("font-bold text-red-900")
                        ui.button(icon="close", on_click=right_panel.hide).props("flat dense").classes("text-gray-400")
                    ui.label(str(ex)).classes("text-red-500 p-4 text-sm")
                right_panel.show()
                return

            current_status = hist.get("current_status", "confirmed")
            dot_color = _STATUS_DOT_COLOR.get(current_status, "#6B7280")
            status_label_text = _STATUS_LABEL_MAP.get(current_status, current_status)

            with panel_container:
                # Header
                with ui.column().classes("w-full bg-red-50 px-4 py-3 border-b border-red-100 gap-1"):
                    with ui.row().classes("w-full justify-between items-center"):
                        ui.label(hist.get("source_user_name", user_name)).classes("font-bold text-red-900 text-base")
                        ui.button(icon="close", on_click=right_panel.hide).props("flat dense").classes("text-gray-400")
                    ui.label(
                        f"Ngày {hist.get('transaction_date', '')}  •  {hist.get('sheet_count', 0)} tờ"
                    ).classes("text-sm text-gray-600")
                    with ui.row().classes("items-center gap-1 mt-1"):
                        ui.element("div").style(
                            f"width:8px;height:8px;border-radius:50%;background:{dot_color}"
                        )
                        ui.label(status_label_text).classes("text-xs font-semibold").style(f"color:{dot_color}")
                    if hist.get("borrow_reason"):
                        ui.label(f"Lý do mượn: {hist['borrow_reason']}").classes("text-xs text-orange-700 italic")

                # Thao tác
                with ui.column().classes("w-full px-4 py-3 border-b border-gray-100 gap-2"):
                    ui.label("THAO TÁC").classes("text-xs font-bold text-gray-400 tracking-widest")
                    has_action = False

                    borrow_reason_val = hist.get("borrow_reason")

                    if user_role in ("admin", "hau_kiem_vien", "pho_phong", "truong_phong"):
                        if current_status == "pending_confirm":
                            has_action = True
                            btn_label = "✓  Xác nhận cho mượn" if borrow_reason_val else "✓  Xác nhận đã nhận"
                            async def _do_confirm(eid=entry_id, uname=user_name):
                                try:
                                    await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/confirm-received", {})
                                    ui.notify("Đã xác nhận", type="positive")
                                    await open_entry_panel(eid, uname)
                                    await load_grid()
                                except Exception as ex2:
                                    ui.notify(str(ex2), type="negative")
                            with ui.row().classes("w-full gap-2"):
                                ui.button(btn_label, on_click=_do_confirm).classes(
                                    "flex-1 bg-green-600 text-white rounded-lg text-sm font-semibold"
                                )
                                with ui.dialog() as reject_dialog, ui.card().classes("w-96"):
                                    ui.label("Từ chối chứng từ").classes("font-bold text-lg mb-2 text-red-700")
                                    reject_reason_inp = ui.input("Lý do từ chối *").classes("w-full")
                                    with ui.row().classes("justify-end gap-2 mt-3"):
                                        ui.button("Huỷ", on_click=reject_dialog.close).props("flat")
                                        async def _do_reject_submit(eid=entry_id, uname=user_name):
                                            reason = reject_reason_inp.value.strip()
                                            if not reason:
                                                ui.notify("Vui lòng nhập lý do từ chối", type="warning")
                                                return
                                            try:
                                                await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/reject", {"reason": reason})
                                                reject_dialog.close()
                                                ui.notify("Đã từ chối chứng từ", type="warning")
                                                right_panel.hide()
                                                await load_grid()
                                            except Exception as ex2:
                                                ui.notify(str(ex2), type="negative")
                                        ui.button("Từ chối", on_click=_do_reject_submit).classes("bg-red-600 text-white")
                                ui.button("✗  Từ chối", on_click=reject_dialog.open).classes(
                                    "flex-1 bg-red-600 text-white rounded-lg text-sm font-semibold"
                                )

                    if is_cv and current_status == "confirmed":
                        has_action = True
                        with ui.dialog() as borrow_dialog, ui.card():
                            ui.label("Mượn lại chứng từ").classes("font-bold text-lg mb-2")
                            reason_inp = ui.input("Lý do mượn *").classes("w-full")
                            with ui.row().classes("justify-end gap-2 mt-2"):
                                ui.button("Huỷ", on_click=borrow_dialog.close).props("flat")
                                async def _do_borrow_submit(eid=entry_id, uname=user_name):
                                    reason = reason_inp.value.strip()
                                    if not reason:
                                        ui.notify("Vui lòng nhập lý do mượn", type="warning")
                                        return
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/borrow", {"reason": reason})
                                        borrow_dialog.close()
                                        ui.notify("Đã gửi yêu cầu mượn", type="warning")
                                        await open_entry_panel(eid, uname)
                                        await load_grid()
                                    except Exception as ex2:
                                        ui.notify(str(ex2), type="negative")
                                ui.button("Gửi yêu cầu", on_click=_do_borrow_submit).classes("bg-orange-600 text-white")
                        ui.button("↩  Mượn lại", on_click=borrow_dialog.open).classes(
                            "w-full bg-orange-500 text-white rounded-lg text-sm font-semibold"
                        )

                    if is_cv and current_status == "borrowed":
                        has_action = True
                        _current_count = hist.get("sheet_count", 1)
                        with ui.dialog() as handback_dialog, ui.card():
                            ui.label("Bàn giao lại chứng từ").classes("font-bold text-lg mb-1")
                            ui.label("Số tờ bàn giao lại sẽ cập nhật số tờ hiện tại.").classes("text-sm text-gray-500 mb-2")
                            count_inp = ui.number(label="Số tờ bàn giao *", value=_current_count, min=1, precision=0).classes("w-full")
                            with ui.row().classes("justify-end gap-2 mt-2"):
                                ui.button("Huỷ", on_click=handback_dialog.close).props("flat")
                                async def _do_handback_submit(eid=entry_id, uname=user_name):
                                    count = int(count_inp.value) if count_inp.value else 0
                                    if count <= 0:
                                        ui.notify("Vui lòng nhập số tờ hợp lệ", type="warning")
                                        return
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/handback", {"sheet_count": count})
                                        handback_dialog.close()
                                        ui.notify("Đã bàn giao lại chứng từ", type="positive")
                                        right_panel.hide()
                                        await load_grid()
                                    except Exception as ex2:
                                        ui.notify(str(ex2), type="negative")
                                ui.button("Xác nhận bàn giao", on_click=_do_handback_submit).classes("bg-blue-600 text-white")
                        ui.button("📋  Bàn giao lại", on_click=handback_dialog.open).classes(
                            "w-full bg-blue-600 text-white rounded-lg text-sm font-semibold"
                        )

                    if not has_action:
                        ui.label("Không có thao tác khả dụng").classes("text-sm text-gray-400 italic")

                # Lịch sử
                with ui.column().classes("w-full px-4 py-3 gap-4"):
                    ui.label("LỊCH SỬ THAY ĐỔI").classes("text-xs font-bold text-gray-400 tracking-widest")
                    logs = hist.get("logs", [])
                    if not logs:
                        ui.label("Chưa có lịch sử").classes("text-sm text-gray-400 italic")
                    else:
                        for log in logs:
                            dot_c = _ACTION_COLOR_MAP.get(log.get("action_color", "blue"), "#2563EB")
                            with ui.row().classes("w-full gap-3 items-start"):
                                ui.element("div").style(
                                    f"min-width:10px;height:10px;border-radius:50%;"
                                    f"background:{dot_c};margin-top:5px;flex-shrink:0"
                                )
                                with ui.column().classes("flex-1 gap-0"):
                                    ui.label(log.get("timestamp", "")).classes("text-xs text-gray-400 font-mono")
                                    ui.label(log.get("performed_by_role", "")).classes("text-xs text-gray-500")
                                    ui.label(log.get("action_label", "")).classes("text-sm font-medium text-gray-800")

            right_panel.show()

        # ── Grid loader ───────────────────────────────────────────────────────
        async def load_grid():
            dept_id = sel_dept.value
            year    = sel_year.value
            month   = sel_month.value
            if not dept_id or not year or not month:
                return

            _save_filter_state()
            title_label.set_text(f"{dept_opts.get(dept_id, '')} tháng {month:02d}/{year}")

            grid_container.clear()
            loading_row.classes(remove="hidden")

            try:
                data = await asyncio.to_thread(
                    api.get,
                    "/api/handovers/grid",
                    {"department_id": dept_id, "year": year, "month": month},
                )
            except Exception as e:
                _handle_api_error(e)
                loading_row.classes(add="hidden")
                return

            loading_row.classes(add="hidden")

            users         = data["users"]
            entries       = data["entries"]
            days_in_month = data["days_in_month"]

            # cell_data[uid][day] = {sheet_count, entry_id, entry_status}
            cell_data: dict = {}
            for e in entries:
                uid_key = e["source_user_id"]
                day_key = e["day"]
                cell_data.setdefault(uid_key, {})[day_key] = {
                    "sheet_count":   e["sheet_count"],
                    "entry_id":      e.get("entry_id"),
                    "entry_status":  e.get("entry_status", "confirmed"),
                }

            import calendar as _cal
            import html as _html

            # ── Build grid as single HTML string (much faster than NiceGUI widgets) ──
            NW = 200   # name column width px
            CW = 50    # cell width px
            _SB = {    # status → (bg, border)
                "confirmed":       ("#DCFCE7", "2px solid #16A34A"),
                "pending_confirm": ("#FEF3C7", "2px solid #F59E0B"),
                "borrowed":        ("#FFEDD5", "2px solid #EA580C"),
            }

            if not users:
                with grid_container:
                    ui.label("Không có cán bộ nào trong phòng này").classes(
                        "text-gray-400 text-center py-8 w-full"
                    )
            else:
                p = [
                    '<div style="overflow-x:auto;width:100%;border:1px solid #bfdbfe;'
                    'border-radius:10px;box-shadow:0 2px 10px rgba(30,64,175,.10);">'
                ]
                # Header row
                p.append(
                    '<div style="display:flex;flex-wrap:nowrap;background:#dbeafe;border-bottom:2px solid #93c5fd;">'
                    f'<div style="min-width:{NW}px;width:{NW}px;flex-shrink:0;font-size:14px;font-weight:700;'
                    f'color:#1e40af;padding:10px 14px;border-right:2px solid #93c5fd;'
                    f'position:sticky;left:0;z-index:3;background:#dbeafe;">Họ và tên</div>'
                )
                for d in range(1, days_in_month + 1):
                    dow = _cal.weekday(year, month, d)
                    hbg = "#fde68a" if dow >= 5 else "#dbeafe"
                    hcl = "#92400e" if dow >= 5 else "#1e40af"
                    p.append(
                        f'<div style="min-width:{CW}px;width:{CW}px;flex-shrink:0;text-align:center;'
                        f'font-size:13px;font-weight:700;color:{hcl};padding:10px 2px;'
                        f'border-right:1px solid #bfdbfe;background:{hbg};">{d:02d}</div>'
                    )
                p.append('</div>')

                # Data rows
                for row_idx, u in enumerate(users):
                    uid    = u["id"]
                    name   = u.get("vn_name") or u.get("user_code") or ""
                    rbg    = "#ffffff" if row_idx % 2 == 0 else "#f0f9ff"
                    p.append(
                        f'<div style="display:flex;flex-wrap:nowrap;border-bottom:1px solid #dbeafe;background:{rbg};">'
                        f'<div style="min-width:{NW}px;width:{NW}px;flex-shrink:0;font-size:15px;font-weight:500;'
                        f'padding:7px 14px;border-right:2px solid #dbeafe;white-space:nowrap;overflow:hidden;'
                        f'display:flex;align-items:center;position:sticky;left:0;z-index:2;background:{rbg};">'
                        f'{_html.escape(name)}</div>'
                    )
                    for d in range(1, days_in_month + 1):
                        info    = cell_data.get(uid, {}).get(d, {})
                        val     = info.get("sheet_count", 0)
                        eid     = info.get("entry_id")
                        status  = info.get("entry_status", "confirmed")
                        dow     = _cal.weekday(year, month, d)
                        if val:
                            cbg, bdr = _SB.get(status, ("#f3f4f6", "1px solid #d1d5db"))
                        elif dow >= 5:
                            cbg, bdr = "#fef9c3", "1px solid #dbeafe"
                        else:
                            cbg, bdr = rbg, "1px solid #dbeafe"
                        eid_attr = f' data-eid="{eid}"' if eid else ""
                        p.append(
                            f'<div style="min-width:{CW}px;width:{CW}px;flex-shrink:0;background:{cbg};border-right:{bdr};">'
                            f'<input class="hv-inp" id="hv_{row_idx}_{d}" data-uid="{uid}" data-day="{d}"'
                            f' data-orig="{val}" data-uname="{_html.escape(name, quote=True)}"{eid_attr}'
                            f' value="{val if val else ""}"'
                            f' style="width:100%;border:none;outline:none;background:transparent;'
                            f'font-size:15px;font-weight:600;color:#1e3a8a;text-align:center;'
                            f'padding:7px 0;box-sizing:border-box;" /></div>'
                        )
                    p.append('</div>')
                p.append('</div>')

                with grid_container:
                    ui.html("".join(p))

                ui.run_javascript(f"""
                    window._hv_max_row = {len(users) - 1};
                    window._hv_max_col = {days_in_month};
                    document.querySelectorAll('.hv-inp').forEach(function(inp) {{
                        inp.addEventListener('focus', function() {{
                            var eid = inp.dataset.eid;
                            if (eid) emitEvent('hv_open_panel', {{entry_id: parseInt(eid), user_name: inp.dataset.uname||''}});
                        }});
                    }});
                    if (!window._hv_arrow_registered) {{
                        window._hv_arrow_registered = true;
                        document.addEventListener('keydown', function(e) {{
                            if (!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) return;
                            var a = document.activeElement;
                            if (!a || !a.classList.contains('hv-inp')) return;
                            var pts = a.id.split('_');
                            if (pts.length < 3) return;
                            var row = parseInt(pts[1]), col = parseInt(pts[2]);
                            var mr = window._hv_max_row, mc = window._hv_max_col;
                            e.preventDefault();
                            var tr = row, tc = col;
                            if (e.key==='ArrowUp') tr=Math.max(0,row-1);
                            else if (e.key==='ArrowDown') tr=Math.min(mr,row+1);
                            else if (e.key==='ArrowLeft') {{ if(col>1)tc=col-1; else if(row>0){{tr=row-1;tc=mc;}} }}
                            else if (e.key==='ArrowRight') {{ if(col<mc)tc=col+1; else if(row<mr){{tr=row+1;tc=1;}} }}
                            if (tr!==row||tc!==col) {{
                                var el=document.getElementById('hv_'+tr+'_'+tc);
                                if(el) {{ el.focus(); el.select(); }}
                            }}
                        }});
                    }}
                """)

        # app.storage.tab chỉ khả dụng sau khi WebSocket kết nối
        try:
            await ui.context.client.connected()
        except Exception:
            pass

        saved = app.storage.tab
        init_dept  = saved.get("hv_dept",  default_dept)
        init_year  = saved.get("hv_year",  default_year)
        init_month = saved.get("hv_month", default_month)
        if init_dept not in dept_opts:
            init_dept = default_dept

        if not is_cv:
            sel_dept.value  = init_dept
        sel_year.value  = init_year
        sel_month.value = init_month

        ui.on('hv_open_panel', lambda e: asyncio.ensure_future(
            open_entry_panel(e.args['entry_id'], e.args.get('user_name', ''))
        ))

        await load_grid()


@ui.page("/handovers/new")
async def new_handover_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _ = _sidebar("handovers")
    with _content_area():
        _page_header("Tạo phiếu bàn giao", "Nhập thông tin tiếp nhận chứng từ từ phòng nguồn")

        try:
            depts = [d for d in await asyncio.to_thread(api.get, "/api/departments/") if d.get("is_source")]
        except:
            depts = []

        dept_options = {d["id"]: d["name"] for d in depts}
        entries = []  # List of entry dicts

        with ui.card().classes("w-full p-6 mb-4 bg-white rounded-xl shadow-sm"):
            ui.label("Thông tin chung").classes("font-semibold text-red-800 mb-3")
            with ui.row().classes("w-full gap-4"):
                f_dept = ui.select(dept_options, label="Phòng nguồn *").classes("flex-1")
                f_date = ui.input("Ngày bàn giao *", value=str(__import__('datetime').date.today())).classes("flex-1")
                f_deliver = ui.input("Người giao").classes("flex-1")

        # Entries section
        entries_container = ui.column().classes("w-full")
        source_users_cache = {}

        async def refresh_users():
            if f_dept.value and f_dept.value not in source_users_cache:
                try:
                    users = await asyncio.to_thread(api.get, "/api/source-users/", {"department_id": f_dept.value})
                    source_users_cache[f_dept.value] = {
                        u["id"]: f"{u['user_code']}{' – ' + u['full_name'] if u.get('full_name') else ''}"
                        for u in users
                    }
                except:
                    source_users_cache[f_dept.value] = {}

        async def render_entries():
            entries_container.clear()
            await refresh_users()
            with entries_container:
                with ui.card().classes("w-full p-4 bg-white rounded-xl shadow-sm"):
                    with ui.row().classes("w-full justify-between items-center mb-3"):
                        ui.label(f"Chứng từ ({len(entries)} dòng)").classes("font-semibold text-red-800")
                        ui.button("+ Thêm dòng", on_click=add_entry_row).classes("bg-green-600 text-white text-sm")

                    for idx, entry in enumerate(entries):
                        with ui.row().classes("w-full items-center gap-2 mb-2"):
                            users_for_dept = source_users_cache.get(f_dept.value or 0, {})
                            user_sel = ui.select(users_for_dept, value=entry.get("source_user_id"), label="User").classes("flex-1")
                            date_inp = ui.input("Ngày GD", value=entry.get("transaction_date", "")).classes("w-36")
                            count_inp = ui.number("Số tờ", value=entry.get("sheet_count", 0), min=1).classes("w-24")
                            ui.button(icon="delete", on_click=lambda i=idx: remove_entry(i)).classes("text-red-400")

                            def update_entry(i=idx, us=user_sel, d=date_inp, c=count_inp):
                                if i < len(entries):
                                    entries[i]["source_user_id"] = us.value
                                    entries[i]["transaction_date"] = d.value
                                    entries[i]["sheet_count"] = int(c.value or 0)

                            user_sel.on("update:model-value", update_entry)
                            date_inp.on("blur", update_entry)
                            count_inp.on("update:model-value", update_entry)

        def add_entry_row():
            entries.append({"source_user_id": None, "transaction_date": str(__import__('datetime').date.today()), "sheet_count": 0})
            ui.run_coroutine(render_entries())

        def remove_entry(idx):
            if idx < len(entries):
                entries.pop(idx)
                ui.run_coroutine(render_entries())

        f_dept.on("update:model-value", lambda: ui.run_coroutine(render_entries()))
        add_entry_row()

        with ui.row().classes("w-full justify-end gap-3 mt-4"):
            ui.button("Hủy", on_click=lambda: ui.navigate.to("/handovers")).classes("text-gray-500 border px-4 py-2 rounded")
            async def save_handover():
                try:
                    await asyncio.to_thread(api.post, "/api/handovers/", {
                        "department_id": f_dept.value,
                        "handover_date": f_date.value,
                        "delivered_by": f_deliver.value or None,
                        "entries": [e for e in entries if e.get("source_user_id") and e.get("sheet_count", 0) > 0],
                    })
                    ui.notify("Đã tạo phiếu bàn giao", type="positive")
                    ui.navigate.to("/handovers")
                except Exception as e:
                    if _handle_api_error(e): return
            ui.button("Lưu phiếu", on_click=save_handover).classes("bg-red-700 text-white px-6 py-2 rounded")


# ─── HANDOVER DETAIL PAGE ────────────────────────────────────────────────────
@ui.page("/handovers/{handover_id}")
async def handover_detail_page(handover_id: int):
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _ = _sidebar("handovers")
    with _content_area():
        with ui.row().classes("w-full items-center gap-3 mb-4"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/handovers")).props("flat").classes("text-red-700")
            ui.label("Chi tiết phiếu bàn giao").classes("text-2xl font-bold text-red-900")

        try:
            h = await asyncio.to_thread(api.get, f"/api/handovers/{handover_id}")
        except Exception as e:
            if _handle_api_error(e): return
            ui.label("Không tìm thấy phiếu bàn giao").classes("text-red-500")
            return

        is_draft = h.get("status") == "draft"
        dept = h.get("department") or {}
        dept_id = dept.get("id") or h.get("department_id")

        # Info card
        with ui.card().classes("w-full p-4 mb-4 bg-white rounded-xl shadow-sm"):
            with ui.row().classes("w-full gap-8 flex-wrap"):
                with ui.column().classes("gap-1"):
                    ui.label("Phòng nguồn").classes("text-xs text-gray-500")
                    ui.label(dept.get("name", "")).classes("font-semibold")
                with ui.column().classes("gap-1"):
                    ui.label("Ngày bàn giao").classes("text-xs text-gray-500")
                    ui.label(str(h.get("handover_date", ""))).classes("font-semibold")
                with ui.column().classes("gap-1"):
                    ui.label("Người giao").classes("text-xs text-gray-500")
                    ui.label(h.get("delivered_by") or "—").classes("font-semibold")
                with ui.column().classes("gap-1"):
                    ui.label("Trạng thái").classes("text-xs text-gray-500")
                    if is_draft:
                        ui.badge("Nháp").props('color="orange"')
                    else:
                        ui.badge("Đã xác nhận").props('color="positive"')

        # Entries section
        entries_container = ui.column().classes("w-full")
        detail_loading = ui.row().classes("w-full justify-center items-center py-4 hidden")
        with detail_loading:
            ui.spinner(size="lg", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")

        source_users_detail_cache = {}

        async def load_detail_users():
            if dept_id and dept_id not in source_users_detail_cache:
                try:
                    users = await asyncio.to_thread(api.get, "/api/source-users/", {"department_id": dept_id})
                    source_users_detail_cache[dept_id] = users
                except Exception:
                    source_users_detail_cache[dept_id] = []

        async def render_detail_entries():
            detail_loading.classes(remove="hidden")
            entries_container.clear()
            try:
                current_h = await asyncio.to_thread(api.get, f"/api/handovers/{handover_id}")
            except Exception as ex:
                ui.notify(str(ex), type="negative")
                detail_loading.classes(add="hidden")
                return
            finally:
                detail_loading.classes(add="hidden")

            entries = current_h.get("entries", [])
            total_sheets = sum(e.get("sheet_count", 0) for e in entries)

            with entries_container:
                with ui.card().classes("w-full p-4 bg-white rounded-xl shadow-sm"):
                    with ui.row().classes("w-full justify-between items-center mb-3"):
                        ui.label(f"Danh sách chứng từ ({len(entries)} dòng – tổng {total_sheets} tờ)").classes("font-semibold text-red-800")
                        if is_draft:
                            ui.button("+ Thêm dòng", on_click=lambda: add_entry_dialog.open()).classes("bg-green-600 text-white text-sm")

                    if entries:
                        with ui.row().classes("w-full px-3 py-2 bg-red-50 font-semibold text-xs text-red-700 rounded"):
                            ui.label("User").classes("flex-1")
                            ui.label("Họ tên").classes("flex-1")
                            ui.label("Ngày GD").classes("w-28 text-center")
                            ui.label("Số tờ").classes("w-20 text-center")
                            if is_draft:
                                ui.label("").classes("w-10")

                        for e in entries:
                            su = e.get("source_user") or {}
                            eid = e["id"]
                            with ui.row().classes("w-full px-3 py-2 border-b border-gray-100 items-center"):
                                ui.label(su.get("user_code", "")).classes("flex-1 text-sm")
                                ui.label(su.get("full_name") or "—").classes("flex-1 text-sm text-gray-600")
                                ui.label(str(e.get("transaction_date", ""))).classes("w-28 text-center text-sm")
                                ui.label(str(e.get("sheet_count", 0))).classes("w-20 text-center text-sm font-semibold")
                                if is_draft:
                                    ui.button(icon="delete", on_click=lambda eid=eid: do_delete_entry(eid)).props("flat dense").classes("w-10 text-red-400").tooltip("Xóa dòng")
                    else:
                        ui.label("Chưa có chứng từ nào").classes("text-gray-400 text-sm text-center py-4")

        async def do_delete_entry(entry_id: int):
            try:
                await asyncio.to_thread(api.delete, f"/api/handovers/{handover_id}/entries/{entry_id}")
                ui.notify("Đã xóa dòng chứng từ", type="positive")
                await render_detail_entries()
            except Exception as ex:
                ui.notify(str(ex), type="negative")

        # Dialog thêm dòng
        await load_detail_users()
        users_for_dept = source_users_detail_cache.get(dept_id, [])
        user_opts = {u["id"]: f"{u['user_code']}{' – ' + u['full_name'] if u.get('full_name') else ''}" for u in users_for_dept}

        with ui.dialog() as add_entry_dialog, ui.card().classes("w-96 p-6"):
            ui.label("Thêm dòng chứng từ").classes("text-lg font-bold mb-4")
            ae_user = ui.select(user_opts, label="User *").classes("w-full")
            ae_date = ui.input("Ngày GD (YYYY-MM-DD) *", value=str(__import__('datetime').date.today())).classes("w-full mt-2")
            ae_count = ui.number("Số tờ *", value=1, min=1).classes("w-full mt-2")

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=add_entry_dialog.close).classes("text-gray-500")
                async def do_add_entry():
                    if not ae_user.value or not ae_date.value or not ae_count.value:
                        ui.notify("Vui lòng điền đầy đủ thông tin", type="warning")
                        return
                    try:
                        await asyncio.to_thread(api.post, f"/api/handovers/{handover_id}/entries", {
                            "source_user_id": ae_user.value,
                            "transaction_date": ae_date.value,
                            "sheet_count": int(ae_count.value),
                        })
                        ui.notify("Đã thêm dòng chứng từ", type="positive")
                        add_entry_dialog.close()
                        await render_detail_entries()
                    except Exception as ex:
                        ui.notify(str(ex), type="negative")
                ui.button("Thêm", on_click=do_add_entry).classes("bg-red-700 text-white")

        await render_detail_entries()

        # Action buttons (draft only)
        if is_draft:
            with ui.row().classes("w-full justify-end gap-3 mt-4"):
                async def do_confirm_detail():
                    try:
                        await asyncio.to_thread(api.post, f"/api/handovers/{handover_id}/confirm")
                        ui.notify("Đã xác nhận phiếu bàn giao", type="positive")
                        ui.navigate.to(f"/handovers/{handover_id}")
                    except Exception as ex:
                        ui.notify(str(ex), type="negative")

                async def do_delete_handover():
                    try:
                        await asyncio.to_thread(api.delete, f"/api/handovers/{handover_id}")
                        ui.notify("Đã xóa phiếu bàn giao", type="positive")
                        ui.navigate.to("/handovers")
                    except Exception as ex:
                        ui.notify(str(ex), type="negative")

                ui.button("Xóa phiếu", icon="delete", on_click=do_delete_handover).classes("border border-red-500 text-red-500 px-4 py-2 rounded")
                ui.button("Xác nhận phiếu", icon="check_circle", on_click=do_confirm_detail).classes("bg-green-600 text-white px-6 py-2 rounded")


# ─── BUNDLES PAGE ─────────────────────────────────────────────────────────────
@ui.page("/bundles")
async def bundles_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _ = _sidebar("bundles")
    with _content_area():
        _page_header("Đóng chứng từ", "Tạo bìa chứng từ và quản lý")

        from datetime import date as _bd
        _today_b = _bd.today()

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") in ("admin", "hau_kiem_vien")

        try:
            await ui.context.client.connected()
        except Exception:
            pass
        with ui.tabs().classes("mb-4") as tabs:
            t_list = ui.tab("Danh sách bìa chứng từ")
            t_new  = ui.tab("Tạo bìa chứng từ")

        with ui.tab_panels(tabs, value=t_list).classes("w-full"):

            # ── Tab 1: Danh sách bìa ─────────────────────────────────────────
            with ui.tab_panel(t_list):
                try:
                    _list_depts = await asyncio.to_thread(
                        api.get, "/api/departments/"
                    )
                    _list_depts = [d for d in _list_depts if d.get("is_source")]
                except Exception:
                    _list_depts = []
                _list_dept_opts = {None: "-- Tất cả phòng --",
                                   **{d["id"]: d["name"] for d in _list_depts}}

                _year_opts  = {None: "-- Tất cả năm --", **{y: str(y) for y in range(2023, _today_b.year + 2)}}
                _month_opts = {None: "-- Tất cả tháng --", **{m: f"Tháng {m:02d}" for m in range(1, 13)}}
                with ui.row().classes("items-end gap-3 mb-4"):
                    list_dept_sel  = ui.select(_list_dept_opts, label="Lọc theo phòng", value=None).classes("w-64")
                    list_year_sel  = ui.select(_year_opts,      label="Năm",            value=None).classes("w-36")
                    list_month_sel = ui.select(_month_opts,     label="Tháng",          value=None).classes("w-36")
                    ui.button("Lọc", icon="filter_list",
                              on_click=lambda: asyncio.ensure_future(load_groups())
                              ).classes("bg-red-700 text-white")

                bundles_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
                with bundles_loading:
                    ui.spinner(size="2em", color="red")
                    ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
                groups_container = ui.column().classes("w-full")

                async def _download_all_covers(group_id: int, label: str = ""):
                    try:
                        content = await asyncio.to_thread(api.download, f"/api/bundles/groups/{group_id}/cover-all")
                        fname = f"{label}.docx" if label else f"bia_chung_tu_{group_id}.docx"
                        ui.download(content, fname)
                        ui.notify("Đang tải bìa...", type="positive")
                    except Exception as e:
                        if _handle_api_error(e): return

                async def _mark_group_printed(group_id: int):
                    try:
                        await asyncio.to_thread(api.post, f"/api/bundles/groups/{group_id}/mark-printed")
                        ui.notify("Đã đánh dấu đã in", type="positive")
                        await load_groups()
                    except Exception as e:
                        if _handle_api_error(e): return

                confirm_del_dialog = ui.dialog()
                _del_target = {"id": None, "name": ""}
                with confirm_del_dialog, ui.card().classes("p-6 w-80"):
                    ui.label("Xác nhận xóa").classes("text-lg font-bold mb-2 text-red-700")
                    del_msg = ui.label("").classes("text-sm text-gray-600 mb-4")
                    with ui.row().classes("justify-end gap-2"):
                        ui.button("Hủy", on_click=lambda: confirm_del_dialog.close()).classes("text-gray-500")
                        async def _do_delete():
                            gid = _del_target["id"]
                            confirm_del_dialog.close()
                            if not gid:
                                return
                            try:
                                await asyncio.to_thread(api.delete, f"/api/bundles/groups/{gid}")
                                ui.notify("Đã xóa nhóm bìa", type="positive")
                                await load_groups()
                            except Exception as e:
                                if _handle_api_error(e): return
                        ui.button("Xóa", on_click=_do_delete).classes("bg-red-600 text-white")

                def _delete_group(group_id: int, dept_name: str):
                    _del_target["id"] = group_id
                    _del_target["name"] = dept_name
                    del_msg.set_text(f'Xóa toàn bộ bìa chứng từ của "{dept_name}"?')
                    confirm_del_dialog.open()

                async def load_groups():
                    bundles_loading.classes(remove="hidden")
                    groups_container.clear()
                    try:
                        params = {}
                        if list_dept_sel.value:
                            params["department_id"] = list_dept_sel.value
                        if list_year_sel.value:
                            params["year"] = list_year_sel.value
                        if list_month_sel.value:
                            params["month"] = list_month_sel.value
                        groups = await asyncio.to_thread(api.get, "/api/bundles/groups", params)
                    except Exception as e:
                        _handle_api_error(e)
                        bundles_loading.classes(add="hidden")
                        return
                    bundles_loading.classes(add="hidden")

                    with groups_container:
                        if not groups:
                            ui.label("Chưa có bìa chứng từ nào").classes(
                                "text-gray-400 text-center py-8"
                            )
                            return

                        # Header
                        with ui.row().classes(
                            "w-full px-4 py-2 bg-red-50 rounded-lg mb-1 text-xs font-semibold text-red-700"
                        ):
                            ui.label("Tên bìa chứng từ").classes("flex-1")
                            ui.label("Ngày tạo").classes("w-40 text-center")
                            ui.label("Người tạo").classes("w-40 text-center")
                            ui.label("Số bìa").classes("w-20 text-center")
                            ui.label("").classes("w-64")

                        for g in groups:
                            dept         = g.get("department") or {}
                            dept_name    = dept.get("name", "—")
                            notes        = g.get("notes") or ""
                            bundle_lbl   = f"{dept_name} – {notes}" if notes else dept_name
                            creator      = g.get("created_by_staff") or {}
                            creator_name = creator.get("full_name", "—")
                            created_at   = (g.get("created_at") or "")[:16].replace("T", " ")
                            n_bundles    = g.get("total_bundles", 0)
                            gid          = g["id"]

                            # Build download filename: "Phòng X tháng 04 năm 2025"
                            try:
                                month_year = notes.replace("Tháng ", "").strip()  # "04/2025"
                                m_str, y_str = month_year.split("/")
                                file_label = f"{dept_name} tháng {m_str} năm {y_str}"
                            except Exception:
                                file_label = bundle_lbl

                            with ui.row().classes(
                                "w-full px-4 py-3 bg-white border border-gray-100"
                                " rounded-lg mb-2 items-center shadow-sm"
                            ):
                                ui.label(bundle_lbl).classes(
                                    "flex-1 font-semibold text-gray-800 text-sm"
                                )
                                ui.label(created_at).classes("w-40 text-center text-sm text-gray-500")
                                ui.label(creator_name).classes("w-40 text-center text-sm text-gray-600")
                                ui.label(str(n_bundles)).classes(
                                    "w-20 text-center text-sm font-semibold text-red-700"
                                )
                                with ui.row().classes("w-64 justify-end gap-2"):
                                    ui.button("Tải xuống", icon="download",
                                              on_click=lambda g_id=gid, lbl=file_label: _download_all_covers(g_id, lbl)
                                              ).classes("bg-red-700 text-white text-xs px-3 py-1")
                                    ui.button("In", icon="print",
                                              on_click=lambda g_id=gid: _mark_group_printed(g_id)
                                              ).classes("bg-green-700 text-white text-xs px-3 py-1")
                                    if is_admin:
                                        ui.button("Xóa", icon="delete",
                                                  on_click=lambda g_id=gid, d=bundle_lbl: _delete_group(g_id, d)
                                                  ).classes("bg-red-600 text-white text-xs px-3 py-1")

                list_dept_sel.on("update:model-value",  load_groups)
                list_year_sel.on("update:model-value",  load_groups)
                list_month_sel.on("update:model-value", load_groups)
                await load_groups()

            # ── Tab 2: Tạo bìa ───────────────────────────────────────────────
            with ui.tab_panel(t_new):
                try:
                    depts, staff_list = await asyncio.gather(
                        asyncio.to_thread(api.get, "/api/departments/"),
                        asyncio.to_thread(api.get, "/api/staff/"),
                    )
                    depts = [d for d in depts if d.get("is_source")]
                except Exception as e:
                    if isinstance(e, api.SessionExpiredError):
                        ui.notify(str(e), type="warning")
                        ui.navigate.to("/login")
                        return
                    depts, staff_list = [], []

                dept_opts2  = {d["id"]: d["name"] for d in depts}
                staff_opts2 = {s["id"]: s["full_name"] for s in staff_list}
                year_opts2  = {y: str(y) for y in range(2023, _today_b.year + 3)}
                month_opts2 = {m: f"Tháng {m:02d}" for m in range(1, 13)}

                selected_entry_ids = []

                # ── Dialog thông báo thành công ───────────────────────────────
                success_dialog = ui.dialog().props("persistent")
                with success_dialog, ui.card().classes("p-8 items-center text-center gap-3"):
                    ui.icon("check_circle", color="green").classes("text-6xl")
                    ui.label("Tạo bìa thành công!").classes("text-xl font-bold text-green-700")
                    success_detail = ui.label("").classes("text-gray-600 text-sm")
                    async def _ok_and_go():
                        success_dialog.close()
                        tabs.set_value(t_list)
                        await load_groups()
                    ui.button("OK", on_click=_ok_and_go).classes("bg-red-700 text-white px-10 mt-2")

                with ui.row().classes("w-full gap-4 items-start"):
                    # ── Trái: Cấu hình ────────────────────────────────────────
                    with ui.card().classes("w-72 p-4 bg-white rounded-xl shadow-sm shrink-0"):
                        ui.label("Cấu hình").classes("font-semibold text-red-800 mb-3")
                        nb_dept  = ui.select(dept_opts2,  label="Phòng nghiệp vụ *").classes("w-full")
                        nb_year  = ui.select(year_opts2,  label="Năm *",
                                             value=_today_b.year).classes("w-full mt-2")
                        nb_month = ui.select(month_opts2, label="Tháng *",
                                             value=_today_b.month).classes("w-full mt-2")
                        nb_cust  = ui.select(staff_opts2, label="Cán bộ đóng chứng từ").classes("w-full mt-3")

                        async def do_generate():
                            if not nb_dept.value:
                                ui.notify("Vui lòng chọn phòng", type="warning")
                                return
                            dept_label  = dept_opts2.get(nb_dept.value, "")
                            month_label = f"Tháng {nb_month.value:02d}/{nb_year.value}"
                            bundle_name = f"{dept_label} – {month_label}"
                            try:
                                grid_data = await asyncio.to_thread(api.get, "/api/handovers/grid", {
                                    "department_id": nb_dept.value,
                                    "year": nb_year.value,
                                    "month": nb_month.value,
                                })
                            except Exception as e:
                                if _handle_api_error(e): return
                                return
                            entry_ids = [
                                e["entry_id"]
                                for e in grid_data.get("entries", [])
                                if e.get("entry_id")
                            ]
                            if not entry_ids:
                                ui.notify("Không có chứng từ để tạo bìa", type="warning")
                                return
                            try:
                                result = await asyncio.to_thread(api.post, "/api/bundles/generate", {
                                    "department_id": nb_dept.value,
                                    "entry_ids": entry_ids,
                                    "custodian_id": nb_cust.value,
                                    "notes": month_label,
                                })
                                n = result.get("total_bundles", 0)
                                success_detail.set_text(
                                    f"{bundle_name} — {n} bìa chứng từ"
                                )
                                success_dialog.open()
                                # Cập nhật preview bằng grid_data đã có, không gọi API lại
                                await _refresh_preview(grid_data)
                            except Exception as e:
                                if _handle_api_error(e): return

                        ui.button("Tạo bìa chứng từ", icon="folder_zip",
                                  on_click=do_generate).classes(
                            "w-full bg-red-700 text-white mt-4 py-2 rounded"
                        )

                    # ── Phải: Preview chứng từ ────────────────────────────────
                    with ui.column().classes("flex-1 min-w-0"):
                        preview_container = ui.column().classes("w-full")

                async def _refresh_preview(grid_data: dict):
                    preview_container.clear()
                    year  = nb_year.value
                    month = nb_month.value
                    grid_entries = [e for e in grid_data.get("entries", []) if e.get("entry_id")]
                    selected_entry_ids.clear()
                    selected_entry_ids.extend([e["entry_id"] for e in grid_entries])
                    users_map = {u["id"]: u for u in grid_data.get("users", [])}
                    with preview_container:
                        total_sheets = sum(e.get("sheet_count", 0) for e in grid_entries)
                        ui.label(
                            f"{len(grid_entries)} chứng từ tháng {month:02d}/{year}"
                            f" – tổng {total_sheets} tờ"
                        ).classes("text-gray-600 text-sm mb-2")
                        if grid_entries:
                            with ui.element("div").classes("max-h-96 overflow-y-auto w-full"):
                                with ui.table(
                                    columns=[
                                        {"name": "name",   "label": "Họ và tên",  "field": "name",   "align": "left"},
                                        {"name": "date",   "label": "Ngày",        "field": "date",   "align": "center"},
                                        {"name": "sheets", "label": "Số tờ",       "field": "sheets", "align": "center"},
                                    ],
                                    rows=[{
                                        "id": e["entry_id"],
                                        "name": (users_map.get(e["source_user_id"]) or {}).get("vn_name")
                                                or (users_map.get(e["source_user_id"]) or {}).get("user_code") or "",
                                        "date": f"{year}-{month:02d}-{e['day']:02d}",
                                        "sheets": e["sheet_count"],
                                    } for e in grid_entries],
                                    row_key="id"
                                ).classes("w-full"):
                                    pass
                        else:
                            ui.label("Không có chứng từ nào trong tháng này").classes(
                                "text-gray-400 text-sm text-center py-4"
                            )

                async def load_entries_preview():
                    dept_id = nb_dept.value
                    year    = nb_year.value
                    month   = nb_month.value
                    if not dept_id or not year or not month:
                        return
                    try:
                        grid_data = await asyncio.to_thread(api.get, "/api/handovers/grid", {
                            "department_id": dept_id,
                            "year": year,
                            "month": month,
                        })
                    except Exception as e:
                        if _handle_api_error(e): return
                        return
                    await _refresh_preview(grid_data)

                nb_dept.on("update:model-value",  load_entries_preview)
                nb_year.on("update:model-value",  load_entries_preview)
                nb_month.on("update:model-value", load_entries_preview)
                if nb_dept.value:
                    await load_entries_preview()


# ─── STORAGE PAGE ─────────────────────────────────────────────────────────────
@ui.page("/storage")
async def storage_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _ = _sidebar("storage")
    with _content_area():
        _page_header("Lưu trữ", "Tra cứu và bàn giao tập chứng từ")

        from datetime import date as _sd
        import json as _json

        _today_s = _sd.today()

        try:
            _s_depts_raw = await asyncio.to_thread(api.get, "/api/departments/")
            _s_depts = [d for d in _s_depts_raw if d.get("is_source")]
        except Exception:
            _s_depts = []
        _s_dept_opts  = {d["id"]: d["name"] for d in _s_depts}
        _s_year_opts  = {y: str(y) for y in range(2023, _today_s.year + 3)}
        _s_month_opts = {m: f"Tháng {m:02d}" for m in range(1, 13)}

        with ui.tabs().classes("mb-2") as storage_tabs:
            t_lookup   = ui.tab("Tra cứu lưu trữ")
            t_handover = ui.tab("Bàn giao cho lưu trữ")

        with ui.tab_panels(storage_tabs, value=t_lookup).classes("w-full"):

            # ── Tab 1: Tra cứu ────────────────────────────────────────────────
            with ui.tab_panel(t_lookup):

                with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 mb-4"):
                    with ui.row().classes("items-end gap-4 flex-wrap"):
                        s_dept  = ui.select(_s_dept_opts, label="Phòng nghiệp vụ",
                                            value=_s_depts[0]["id"] if _s_depts else None).classes("w-72")
                        s_year  = ui.select(_s_year_opts, label="Năm",
                                            value=_today_s.year).classes("w-28")
                        s_month = ui.select(_s_month_opts, label="Tháng",
                                            value=_today_s.month).classes("w-36")
                        ui.button("Tải dữ liệu", icon="search",
                                  on_click=lambda: load_storage()).classes("bg-red-700 text-white px-4")

                storage_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
                with storage_loading:
                    ui.spinner(size="2em", color="red")
                    ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
                result_area = ui.column().classes("w-full")

                def _build_html(data: dict) -> str:
                    rows       = data.get("rows", [])
                    dept_name  = data.get("department_name", "")
                    period     = data.get("period", "")
                    tot_sheets = data.get("total_sheets", 0)
                    tot_bndls  = data.get("total_bundles", 0)

                    if not rows:
                        return ""

                    n_day = max((len(r["days"]) for r in rows), default=1)
                    n_day = max(n_day, 2)
                    n_sh  = max((len(r["bundle_sheets"]) for r in rows), default=1)
                    n_sh  = max(n_sh, 3)

                    C  = "border:1px solid #000;text-align:center;padding:5px 8px;font-size:13px"
                    CE = "border:1px solid #000;text-align:center;padding:5px 8px;font-size:13px;color:#bbb"
                    CH = f"{C};background:#dbeafe;font-weight:700"
                    CF = f"{C};background:#dbeafe;font-weight:700"
                    ED = "outline:none"

                    n_total = n_day + n_sh + 1
                    html = f"""<table id="sv-table" style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif">
<tr><td colspan="{n_total}" style="{C};font-size:17px;font-weight:700;padding:10px">
  Phòng {dept_name} {period}
</td></tr>
<tr>
  <td colspan="{n_day}" style="{CH}">Ngày</td>
  <td colspan="{n_sh}"  style="{CH}">Số chứng từ</td>
  <td style="{CH}">Số tập</td>
</tr>
"""
                    for r in rows:
                        bids = r.get("bundle_ids", [])
                        # data-bids: JSON array, data-ncols: số cột sheet thực tế
                        html += f'<tr data-bids=\'{_json.dumps(bids)}\' data-ncols="{len(r["bundle_sheets"])}">'
                        for i in range(n_day):
                            v = str(r["days"][i]) if i < len(r["days"]) else ""
                            s = C if v else CE
                            html += f'<td contenteditable="true" style="{s};{ED}">{v}</td>'
                        for i in range(n_sh):
                            bid = bids[i] if i < len(bids) else ""
                            v   = str(r["bundle_sheets"][i]) if i < len(r["bundle_sheets"]) else ""
                            s   = C if v else CE
                            da  = f' data-bid="{bid}"' if bid else ""
                            html += f'<td contenteditable="true"{da} style="{s};{ED}">{v}</td>'
                        html += f'<td style="{C};font-weight:700">{r["n_bundles"]}</td>'
                        html += "</tr>\n"

                    html += f"""<tr>
  <td colspan="{n_day}" style="{CF};text-align:right">Cộng tổng:</td>
  <td colspan="{n_sh}"  style="{CF};font-size:15px">{tot_sheets:,}</td>
  <td style="{CF};font-size:15px">{tot_bndls}</td>
</tr>
</table>"""
                    return html

                async def load_storage():
                    result_area.clear()
                    if not s_dept.value or not s_year.value or not s_month.value:
                        return
                    storage_loading.classes(remove="hidden")
                    try:
                        data = await asyncio.to_thread(api.get, "/api/bundles/storage-view", {
                            "department_id": s_dept.value,
                            "year": s_year.value,
                            "month": s_month.value,
                        })
                    except Exception as e:
                        _handle_api_error(e)
                        storage_loading.classes(add="hidden")
                        return
                    storage_loading.classes(add="hidden")

                    html_table = _build_html(data)

                    with result_area:
                        if not html_table:
                            ui.label(
                                f"Không có dữ liệu cho {_s_dept_opts.get(s_dept.value,'')} "
                                f"tháng {s_month.value:02d}/{s_year.value}"
                            ).classes("text-gray-400 text-center py-8 w-full")
                            return

                        async def do_save():
                            # Đọc giá trị ô "Số chứng từ" từ DOM qua data-bid
                            result = await ui.run_javascript("""
                                var rows = [];
                                document.querySelectorAll('#sv-table tr[data-bids]').forEach(function(tr) {
                                    var bids = JSON.parse(tr.getAttribute('data-bids'));
                                    if (!bids.length) return;
                                    var sheets = [];
                                    tr.querySelectorAll('td[data-bid]').forEach(function(td) {
                                        var v = parseInt(td.innerText.trim().replace(/[^0-9]/g,''), 10);
                                        sheets.push(isNaN(v) ? 0 : v);
                                    });
                                    if (sheets.length) rows.push({bundle_ids: bids, bundle_sheets: sheets});
                                });
                                return rows;
                            """)
                            if not result:
                                ui.notify("Không có dữ liệu để lưu", type="warning")
                                return
                            try:
                                await asyncio.to_thread(api.patch, "/api/bundles/storage-view",
                                                        {"rows": result})
                                ui.notify("Đã lưu thay đổi", type="positive")
                            except Exception as e:
                                if _handle_api_error(e): return

                        with ui.row().classes("w-full justify-end gap-2 mb-3"):
                            ui.button("Lưu thay đổi", icon="save",
                                      on_click=do_save).classes("bg-red-700 text-white px-4")
                            def do_print():
                                print_html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>
  body{{font-family:Arial,sans-serif;margin:10mm}}
  table{{border-collapse:collapse;width:100%}}
  @page{{size:A4 landscape;margin:10mm}}
  @media print{{button{{display:none}}}}
</style>
</head><body>
<div style="text-align:right;margin-bottom:6px">
  <button onclick="window.print()" style="padding:6px 16px;background:#1d4ed8;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px">🖨 In</button>
</div>
{html_table}
</body></html>"""
                                escaped = _json.dumps(print_html)
                                ui.run_javascript(
                                    f"var w=window.open('','_blank');"
                                    f"w.document.write({escaped});"
                                    f"w.document.close();"
                                )
                            ui.button("In danh sách (A4 ngang)", icon="print",
                                      on_click=do_print).classes("bg-green-700 text-white px-4")

                        with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 overflow-x-auto"):
                            ui.html(html_table)

                await load_storage()

            # ── Tab 2: Bàn giao cho lưu trữ ──────────────────────────────────
            with ui.tab_panel(t_handover):

                with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 mb-4"):
                    ui.label("Tạo dữ liệu bàn giao cho lưu trữ").classes("font-semibold text-red-800 mb-3")
                    with ui.row().classes("items-end gap-4 flex-wrap"):
                        ha_dept = ui.select(_s_dept_opts, label="Phòng nghiệp vụ *",
                                            value=_s_depts[0]["id"] if _s_depts else None).classes("w-72")
                        ha_year = ui.select(_s_year_opts, label="Năm *",
                                            value=_today_s.year).classes("w-28")
                        ui.button("Xem trước", icon="preview",
                                  on_click=lambda: load_archive_preview()
                                  ).classes("bg-red-700 text-white px-4")
                        ui.button("Tải về Excel", icon="download",
                                  on_click=lambda: download_archive()
                                  ).classes("bg-green-700 text-white px-4")

                ha_result = ui.column().classes("w-full")

                ha_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
                with ha_loading:
                    ui.spinner(size="2em", color="red")
                    ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")

                async def load_archive_preview():
                    ha_result.clear()
                    if not ha_dept.value or not ha_year.value:
                        ui.notify("Vui lòng chọn phòng và năm", type="warning")
                        return
                    ha_loading.classes(remove="hidden")
                    try:
                        data = await asyncio.to_thread(api.get, "/api/bundles/handover-archive", {
                            "department_id": ha_dept.value,
                            "year": ha_year.value,
                        })
                    except Exception as e:
                        _handle_api_error(e)
                        ha_loading.classes(add="hidden")
                        return
                    ha_loading.classes(add="hidden")

                    records = data.get("records", [])
                    total   = data.get("total", 0)

                    with ha_result:
                        dept_lbl = _s_dept_opts.get(ha_dept.value, "")
                        ui.label(
                            f"Phòng {dept_lbl} – Năm {ha_year.value}: {total} hồ sơ"
                        ).classes("font-semibold text-red-900 mb-3")

                        if not records:
                            ui.label(
                                f"Không có dữ liệu cho {dept_lbl} năm {ha_year.value}"
                            ).classes("text-gray-400 text-sm text-center py-6 w-full")
                            return

                        preview = records[:30]
                        with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden"):
                            with ui.row().classes(
                                "w-full px-3 py-2 bg-red-50 font-semibold text-xs text-red-700"
                                " border-b border-red-100"
                            ):
                                ui.label("NGAY_MO_HS").classes("w-28")
                                ui.label("NGAY_KT_HS").classes("w-28")
                                ui.label("TIEUDE_HS").classes("flex-1")
                            for rec in preview:
                                with ui.row().classes(
                                    "w-full px-3 py-2 border-b border-gray-100 items-start"
                                ):
                                    ui.label(rec["ngay_mo"]).classes(
                                        "w-28 text-sm font-mono text-gray-600 shrink-0"
                                    )
                                    ui.label(rec["ngay_kt"]).classes(
                                        "w-28 text-sm font-mono text-gray-600 shrink-0"
                                    )
                                    ui.label(rec["tieu_de"]).classes("flex-1 text-sm")
                        if total > 30:
                            ui.label(f"... và {total - 30} hồ sơ khác (xem đầy đủ trong file Excel)").classes(
                                "text-gray-400 text-sm text-center py-2"
                            )

                async def download_archive():
                    if not ha_dept.value or not ha_year.value:
                        ui.notify("Vui lòng chọn phòng và năm", type="warning")
                        return
                    ha_loading.classes(remove="hidden")
                    try:
                        content = await asyncio.to_thread(
                            api.download, "/api/bundles/handover-archive-excel", {
                                "department_id": ha_dept.value,
                                "year": ha_year.value,
                            }
                        )
                        dept_lbl = _s_dept_opts.get(ha_dept.value, str(ha_dept.value))
                        filename = f"ban_giao_luu_tru_{dept_lbl}_{ha_year.value}.xlsx"
                        ui.download(content, filename)
                        ui.notify("Đang tải file Excel...", type="positive")
                    except Exception as e:
                        _handle_api_error(e)
                    finally:
                        ha_loading.classes(add="hidden")


# ─── USER MANAGEMENT PAGE ────────────────────────────────────────────────────
@ui.page("/user-management")
async def user_management_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _ = _sidebar("")
    with _content_area():
        _page_header("Quản lý người dùng", "Đổi mật khẩu tài khoản")

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") == "admin"

        # ── Yêu cầu mật khẩu ──────────────────────────────────────────────────
        with ui.card().classes("w-full max-w-xl shadow-sm rounded-xl bg-red-50 border border-red-200 p-4 mb-6"):
            ui.label("Yêu cầu đối với mật khẩu mới:").classes("font-semibold text-red-800 mb-2")
            reqs = [
                "Ít nhất 8 ký tự",
                "Có ít nhất 1 chữ hoa (A–Z)",
                "Có ít nhất 1 chữ thường (a–z)",
                "Có ít nhất 1 chữ số (0–9)",
                "Có ít nhất 1 ký tự đặc biệt (ví dụ: @, #, !, $, %...)",
            ]
            for r in reqs:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("check_circle").classes("text-red-600 text-base")
                    ui.label(r).classes("text-sm text-red-700")

        # ── Đổi mật khẩu của chính mình ───────────────────────────────────────
        with ui.card().classes("w-full max-w-xl shadow-sm rounded-xl bg-white p-6 mb-6"):
            ui.label("Đổi mật khẩu của tôi").classes("text-lg font-bold text-red-900 mb-4")

            cp_old  = ui.input("Mật khẩu cũ", password=True, password_toggle_button=True).classes("w-full")
            cp_new  = ui.input("Mật khẩu mới", password=True, password_toggle_button=True).classes("w-full mt-3")
            cp_conf = ui.input("Nhập lại mật khẩu mới", password=True, password_toggle_button=True).classes("w-full mt-3")
            cp_msg  = ui.label("").classes("text-sm mt-2")

            def _validate_new_pw(pw: str):
                import re
                if len(pw) < 8:
                    return "Mật khẩu phải có ít nhất 8 ký tự"
                if not re.search(r'[A-Z]', pw):
                    return "Thiếu chữ hoa (A–Z)"
                if not re.search(r'[a-z]', pw):
                    return "Thiếu chữ thường (a–z)"
                if not re.search(r'\d', pw):
                    return "Thiếu chữ số (0–9)"
                if not re.search(r'[^a-zA-Z\d]', pw):
                    return "Thiếu ký tự đặc biệt (@, #, !, $...)"
                return ""

            async def do_change_pw():
                cp_msg.set_text("")
                cp_msg.classes(remove="text-green-600 text-red-600")
                old_v = cp_old.value.strip()
                new_v = cp_new.value
                conf_v = cp_conf.value
                if not old_v:
                    cp_msg.set_text("Vui lòng nhập mật khẩu cũ")
                    cp_msg.classes("text-red-600")
                    return
                err = _validate_new_pw(new_v)
                if err:
                    cp_msg.set_text(f"Mật khẩu mới không hợp lệ: {err}")
                    cp_msg.classes("text-red-600")
                    return
                if new_v != conf_v:
                    cp_msg.set_text("Mật khẩu mới và nhập lại không khớp")
                    cp_msg.classes("text-red-600")
                    return
                try:
                    await asyncio.to_thread(api.post, "/api/auth/change-password", {
                        "old_password": old_v,
                        "new_password": new_v,
                    })
                    cp_old.set_value("")
                    cp_new.set_value("")
                    cp_conf.set_value("")
                    cp_msg.set_text("Đổi mật khẩu thành công!")
                    cp_msg.classes("text-green-600")
                except Exception as e:
                    if isinstance(e, api.SessionExpiredError):
                        ui.notify(str(e), type="warning")
                        ui.navigate.to("/login")
                        return
                    cp_msg.set_text(str(e))
                    cp_msg.classes("text-red-600")

            with ui.row().classes("w-full justify-end mt-4"):
                ui.button("Lưu mật khẩu", on_click=do_change_pw).classes("bg-red-700 text-white")

        # ── Admin: Đặt lại mật khẩu cho user khác ─────────────────────────────
        if is_admin:
            with ui.card().classes("w-full max-w-xl shadow-sm rounded-xl bg-white p-6"):
                ui.label("Đặt lại mật khẩu cho người dùng khác").classes("text-lg font-bold text-orange-700 mb-1")
                ui.label("Chỉ Quản trị viên mới thấy mục này").classes("text-xs text-gray-400 mb-4")

                try:
                    staff_list = await asyncio.to_thread(api.get, "/api/staff/", {"active_only": True})
                except Exception:
                    staff_list = []

                # loại bỏ chính mình
                self_id = current_user.get("id") if current_user else None
                staff_options = {
                    s["id"]: f"{s['full_name']} ({s['username']})"
                    for s in staff_list if s["id"] != self_id
                }

                ar_user = ui.select(staff_options, label="Chọn người dùng").classes("w-full")
                ar_new  = ui.input("Mật khẩu mới", password=True, password_toggle_button=True).classes("w-full mt-3")
                ar_conf = ui.input("Nhập lại mật khẩu mới", password=True, password_toggle_button=True).classes("w-full mt-3")
                ar_msg  = ui.label("").classes("text-sm mt-2")

                async def do_admin_reset():
                    ar_msg.set_text("")
                    ar_msg.classes(remove="text-green-600 text-red-600")
                    if not ar_user.value:
                        ar_msg.set_text("Vui lòng chọn người dùng")
                        ar_msg.classes("text-red-600")
                        return
                    new_v  = ar_new.value
                    conf_v = ar_conf.value
                    err = _validate_new_pw(new_v)
                    if err:
                        ar_msg.set_text(f"Mật khẩu không hợp lệ: {err}")
                        ar_msg.classes("text-red-600")
                        return
                    if new_v != conf_v:
                        ar_msg.set_text("Mật khẩu mới và nhập lại không khớp")
                        ar_msg.classes("text-red-600")
                        return
                    try:
                        await asyncio.to_thread(api.post, "/api/auth/admin-reset-password", {
                            "staff_id": ar_user.value,
                            "new_password": new_v,
                        })
                        selected_name = staff_options.get(ar_user.value, "")
                        ar_new.set_value("")
                        ar_conf.set_value("")
                        ar_msg.set_text(f"Đã đặt lại mật khẩu cho {selected_name}")
                        ar_msg.classes("text-green-600")
                    except Exception as e:
                        if isinstance(e, api.SessionExpiredError):
                            ui.notify(str(e), type="warning")
                            ui.navigate.to("/login")
                            return
                        ar_msg.set_text(str(e))
                        ar_msg.classes("text-red-600")

                with ui.row().classes("w-full justify-end mt-4"):
                    ui.button("Đặt lại mật khẩu", on_click=do_admin_reset).classes("bg-orange-600 text-white")


# ─── LEAVES PAGE ─────────────────────────────────────────────────────────────
_LEAVE_STATUS = {
    "pending_ksv":      ("Chờ KSV duyệt",  "bg-orange-100 text-orange-700 border-orange-300"),
    "pending_tong_hop": ("Chờ Tổng hợp",   "bg-yellow-100 text-yellow-700 border-yellow-300"),
    "pending_gd":       ("Chờ GĐ duyệt",   "bg-blue-100 text-blue-700 border-blue-300"),
    "approved":         ("Đã duyệt",        "bg-green-100 text-green-700 border-green-300"),
    "rejected":         ("Từ chối",         "bg-red-100 text-red-700 border-red-300"),
    "cancelled":        ("Đã hủy",          "bg-gray-100 text-gray-500 border-gray-300"),
}
_LEAVE_TYPE = {
    "annual":   "Nghỉ phép năm",
    "sick":     "Nghỉ ốm",
    "personal": "Nghỉ việc riêng",
    "other":    "Khác",
}
# Nhóm hiển thị 3 trạng thái đơn giản trong cột Trạng thái của bảng
_STATUS_GROUP = {
    "pending_ksv":      ("Chờ phê duyệt", "bg-orange-100 text-orange-700"),
    "pending_tong_hop": ("Chờ phê duyệt", "bg-orange-100 text-orange-700"),
    "pending_gd":       ("Chờ phê duyệt", "bg-orange-100 text-orange-700"),
    "approved":         ("Hoàn thành",    "bg-green-100 text-green-700"),
    "rejected":         ("Từ chối",       "bg-red-100 text-red-700"),
    "cancelled":        ("Đã hủy",        "bg-gray-100 text-gray-500"),
}


def _leave_status_badge(status: str):
    label, cls = _LEAVE_STATUS.get(status, (status, "bg-gray-100 text-gray-500"))
    ui.label(label).classes(f"text-xs font-medium px-2 py-0.5 rounded border {cls}")


def _fmt_leave_dates(start_str: str, end_str: str) -> str:
    """1 ngày → DD/MM/YYYY; nhiều ngày → DD/MM – DD/MM/YYYY"""
    if not start_str or not end_str:
        return "—"
    try:
        from datetime import date as _date
        s = _date.fromisoformat(start_str[:10])
        e = _date.fromisoformat(end_str[:10])
        if s == e:
            return s.strftime("%d/%m/%Y")
        return f"{s.strftime('%d/%m')} – {e.strftime('%d/%m/%Y')}"
    except Exception:
        return start_str[:10]


def _gd_display(leave: dict) -> str:
    """Thêm (TUQ) nếu PGĐ ký thay GĐ."""
    name = leave.get("gd_approver_name") or ""
    if name and leave.get("gd_is_pgd"):
        return f"{name} (TUQ)"
    return name


@ui.page("/leaves")
async def leaves_page():
    if not _require_auth():
        return
    badge_refs = _sidebar("leaves")

    current_user = api.get_current_user()
    user_role    = current_user.get("role", "") if current_user else ""
    user_id      = current_user.get("staff_id") if current_user else None

    can_all        = user_role in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")
    can_delegation = user_role == "admin"
    show_approver  = user_role not in ("giam_doc", "pho_giam_doc", "admin")

    # ── Drawer và dialog phải là con trực tiếp của page ──────────────────────
    with ui.right_drawer(value=False).props("width=440 overlay").classes(
        "bg-white shadow-2xl overflow-y-auto"
    ) as detail_drawer:
        drawer_container = ui.column().classes("w-full gap-0")

    with ui.dialog() as history_dialog, ui.card().classes("p-0 w-[560px] max-h-[80vh] overflow-y-auto"):
        history_container = ui.column().classes("w-full gap-0")

    # ── Dialog từ chối (yêu cầu lý do) ──────────────────────────────────────
    _reject_cb: list = [None]
    with ui.dialog() as reject_dialog, ui.card().classes("p-6 w-80"):
        ui.label("Nhập lý do từ chối").classes("text-lg font-bold text-red-900 mb-4")
        reject_reason = ui.textarea("Lý do từ chối").classes("w-full").props("rows=3")

        async def _confirm_reject():
            if not reject_reason.value.strip():
                ui.notify("Vui lòng nhập lý do từ chối", type="warning")
                return
            cb = _reject_cb[0]
            reason = reject_reason.value.strip()
            reject_reason.value = ""
            reject_dialog.close()
            if cb:
                await cb(reason)

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Hủy", on_click=reject_dialog.close).classes("text-gray-500")
            ui.button("Xác nhận từ chối", on_click=_confirm_reject).classes("bg-red-700 text-white")

    # ── Dialog TH chọn GĐ/PGĐ ────────────────────────────────────────────────
    _th_cb: list = [None]
    with ui.dialog() as th_dialog, ui.card().classes("p-6 w-96"):
        ui.label("Chuyển lên GĐ/PGĐ phê duyệt").classes("text-lg font-bold text-red-900 mb-4")
        th_gd_select = ui.select({}, label="Chọn GĐ / Phó GĐ").classes("w-full")
        th_note      = ui.textarea("Ghi chú (tuỳ chọn)").classes("w-full mt-2").props("rows=2")

        async def _load_gd_opts():
            try:
                lst = await asyncio.to_thread(api.get, "/api/leaves/gd-list")
                th_gd_select.options = {s["id"]: f"{s['full_name']} — {s['role_label']}" for s in (lst or [])}
                th_gd_select.update()
            except Exception:
                pass

        async def _confirm_th_forward():
            if not th_gd_select.value:
                ui.notify("Vui lòng chọn GĐ/PGĐ", type="warning")
                return
            gd_id = th_gd_select.value
            note  = th_note.value or None
            th_note.value = ""
            th_dialog.close()
            cb = _th_cb[0]
            if cb:
                await cb(gd_id, note)

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Hủy", on_click=th_dialog.close).classes("text-gray-500")
            ui.button("Xác nhận", on_click=_confirm_th_forward).classes("bg-blue-700 text-white")

    with _content_area():
        _page_header("Quản lý Nghỉ phép", "Đăng ký và phê duyệt nghỉ phép")

        # ── Load dữ liệu song song ────────────────────────────────────────────
        my_leaves, pending_leaves, all_leaves, delegations, balance_info, approver_list = \
            [], [], [], [], {}, []

        async def _empty():
            return []

        try:
            results = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "mine"}),
                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "pending"}),
                asyncio.to_thread(api.get, "/api/leaves/", {"scope": "all"}) if can_all else _empty(),
                asyncio.to_thread(api.get, "/api/delegations/") if can_delegation else _empty(),
                asyncio.to_thread(api.get, "/api/auth/me"),
                asyncio.to_thread(api.get, "/api/leaves/approvers") if show_approver else _empty(),
                return_exceptions=True,
            )
            my_leaves, pending_leaves, all_leaves, delegations, balance_info, approver_list = results
            for r in results:
                if isinstance(r, api.SessionExpiredError):
                    ui.notify(str(r), type="warning")
                    ui.navigate.to("/login")
                    return
            my_leaves      = my_leaves      if isinstance(my_leaves, list)     else []
            pending_leaves = pending_leaves if isinstance(pending_leaves, list) else []
            all_leaves     = all_leaves     if isinstance(all_leaves, list)    else []
            delegations    = delegations    if isinstance(delegations, list)   else []
            balance_info   = balance_info   if isinstance(balance_info, dict)  else {}
            approver_list  = approver_list  if isinstance(approver_list, list) else []
        except Exception as e:
            if _handle_api_error(e):
                return

        pending_ids = {lv["id"] for lv in pending_leaves}

        # ── Cập nhật badge sidebar ────────────────────────────────────────────
        _lcnt = len(pending_leaves)
        if "leaves" in badge_refs and _lcnt > 0:
            badge_refs["leaves"].set_text(str(_lcnt))
            badge_refs["leaves"].set_visibility(True)

        if any(lv.get("status") == "rejected" for lv in my_leaves):
            ui.notify("Có đơn nghỉ phép bị từ chối. Xem tab 'Của tôi'.", type="negative", timeout=8000)

        # ── Balance card ──────────────────────────────────────────────────────
        annual    = balance_info.get("annual_leave_days", 12)
        used      = balance_info.get("used_leave_days", 0)
        remaining = max(0, annual - used)
        with ui.row().classes("gap-4 mb-4"):
            with ui.card().classes("bg-blue-50 border border-blue-200 p-4 rounded-xl min-w-40"):
                ui.label("Phép còn lại").classes("text-xs text-blue-600")
                ui.label(f"{remaining} / {annual} ngày").classes("text-xl font-bold text-blue-800")

        # ── Dialogs tạo đơn / nộp lại ────────────────────────────────────────
        approver_opts = {s["id"]: f"{s['full_name']} — {s['role_label']}" for s in approver_list}

        with ui.dialog() as create_dialog, ui.card().classes("p-6 w-[420px]"):
            ui.label("Tạo đơn nghỉ phép").classes("text-lg font-bold text-red-900 mb-4")
            c_start    = ui.date(value="").props("label='Từ ngày' mask='YYYY-MM-DD'").classes("w-full")
            c_end      = ui.date(value="").props("label='Đến ngày' mask='YYYY-MM-DD'").classes("w-full mt-2")
            c_type     = ui.select({k: v for k, v in _LEAVE_TYPE.items()}, label="Loại nghỉ phép", value="annual").classes("w-full mt-2")
            c_reason   = ui.textarea("Lý do (tuỳ chọn)").classes("w-full mt-2")
            c_approver = ui.select(approver_opts, label="Người phê duyệt (KSV)").classes("w-full mt-2") if show_approver else None

            async def do_create():
                if not c_start.value or not c_end.value:
                    ui.notify("Vui lòng chọn ngày", type="warning")
                    return
                if show_approver and not c_approver.value:
                    ui.notify("Vui lòng chọn người phê duyệt", type="warning")
                    return
                body = {"start_date": c_start.value, "end_date": c_end.value,
                        "leave_type": c_type.value, "reason": c_reason.value or None}
                if show_approver:
                    body["ksv_approver_id"] = c_approver.value
                try:
                    await asyncio.to_thread(api.post, "/api/leaves/", body)
                    create_dialog.close()
                    ui.notify("Đã tạo đơn nghỉ phép thành công!", type="positive")
                    ui.navigate.to("/leaves")
                except Exception as e:
                    _handle_api_error(e)

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=create_dialog.close).classes("text-gray-500")
                ui.button("Gửi đơn", on_click=do_create).classes("bg-red-700 text-white")

        # ── Dialog nộp lại ────────────────────────────────────────────────────
        _rsub_id: list = [None]
        with ui.dialog() as resubmit_dialog, ui.card().classes("p-6 w-[420px]"):
            ui.label("Chỉnh sửa & Nộp lại").classes("text-lg font-bold text-red-900 mb-4")
            r_start    = ui.date(value="").props("label='Từ ngày' mask='YYYY-MM-DD'").classes("w-full")
            r_end      = ui.date(value="").props("label='Đến ngày' mask='YYYY-MM-DD'").classes("w-full mt-2")
            r_type     = ui.select({k: v for k, v in _LEAVE_TYPE.items()}, label="Loại nghỉ phép", value="annual").classes("w-full mt-2")
            r_reason   = ui.textarea("Lý do (tuỳ chọn)").classes("w-full mt-2")
            r_approver = ui.select(approver_opts, label="Người phê duyệt (KSV)").classes("w-full mt-2") if show_approver else None

            async def do_resubmit():
                lid = _rsub_id[0]
                if not lid or not r_start.value or not r_end.value:
                    ui.notify("Vui lòng chọn ngày", type="warning")
                    return
                if show_approver and not r_approver.value:
                    ui.notify("Vui lòng chọn người phê duyệt", type="warning")
                    return
                body = {"start_date": r_start.value, "end_date": r_end.value,
                        "leave_type": r_type.value, "reason": r_reason.value or None}
                if show_approver:
                    body["ksv_approver_id"] = r_approver.value
                try:
                    await asyncio.to_thread(api.put, f"/api/leaves/{lid}/resubmit", body)
                    resubmit_dialog.close()
                    detail_drawer.hide()
                    ui.notify("Đã nộp lại đơn!", type="positive")
                    ui.navigate.to("/leaves")
                except Exception as e:
                    _handle_api_error(e)

            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("Hủy", on_click=resubmit_dialog.close).classes("text-gray-500")
                ui.button("Nộp lại", on_click=do_resubmit).classes("bg-orange-600 text-white")

        # ── Hàm mở drawer chi tiết ────────────────────────────────────────────
        async def open_detail(leave: dict):
            drawer_container.clear()
            with drawer_container:
                lid      = leave["id"]
                status   = leave["status"]
                is_owner = user_id is not None and leave.get("staff_id") == user_id
                in_pend  = lid in pending_ids
                ksv_act  = status == "pending_ksv" and in_pend and user_role in ("truong_phong", "pho_phong", "hau_kiem_vien")
                th_act   = status == "pending_tong_hop" and in_pend
                gd_act   = status == "pending_gd" and in_pend and user_role in ("giam_doc", "pho_giam_doc")

                with ui.row().classes("w-full bg-red-800 text-white px-5 py-4 items-center gap-2"):
                    ui.icon("event_busy").classes("text-2xl")
                    with ui.column().classes("gap-0"):
                        ui.label("Chi tiết đơn nghỉ phép").classes("font-bold text-base")
                        ui.label(leave.get("staff_name", "")).classes("text-red-200 text-sm")

                with ui.column().classes("px-5 py-4 gap-3 w-full"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label("Trạng thái:").classes("text-sm text-gray-600 font-medium")
                        _leave_status_badge(status)

                    def _info(lbl, val):
                        with ui.row().classes("w-full items-start gap-2"):
                            ui.label(lbl).classes("text-sm text-gray-500 w-28 shrink-0")
                            ui.label(str(val) if val else "—").classes("text-sm font-medium flex-1")

                    _info("Phòng:", leave.get("department_name") or "—")
                    _info("Từ ngày:", (leave.get("start_date") or "")[:10])
                    _info("Đến ngày:", (leave.get("end_date") or "")[:10])
                    _info("Số ngày nghỉ:", f"{leave.get('leave_days', '')} ngày")
                    _info("Loại:", _LEAVE_TYPE.get(leave.get("leave_type", ""), leave.get("leave_type", "")))
                    _info("Lý do:", leave.get("reason") or "—")

                    # Bước 1: KSV (ẩn nếu GĐ/PGĐ/admin tạo thẳng lên TH)
                    if leave.get("ksv_approver_id") or status == "pending_ksv":
                        with ui.column().classes("w-full bg-orange-50 rounded-lg p-3 gap-1 border border-orange-100"):
                            ui.label("Bước 1 — KSV phê duyệt").classes("text-xs font-bold text-orange-700 uppercase")
                            _info("Người duyệt:", leave.get("ksv_approver_name") or "Chưa xác định")
                            if leave.get("ksv_approved_at"):
                                _info("Ngày duyệt:", leave["ksv_approved_at"][:10])
                                _info("Ý kiến:", leave.get("ksv_comment") or "—")

                    # Bước 2: Tổng hợp
                    with ui.column().classes("w-full bg-yellow-50 rounded-lg p-3 gap-1 border border-yellow-100"):
                        ui.label("Bước 2 — Phòng Tổng hợp").classes("text-xs font-bold text-yellow-700 uppercase")
                        _info("Người xử lý:", leave.get("tong_hop_approver_name") or "Chưa xử lý")
                        if leave.get("tong_hop_approved_at"):
                            _info("Ngày:", leave["tong_hop_approved_at"][:10])
                            _info("Ghi chú:", leave.get("tong_hop_comment") or "—")

                    # Bước 3: GĐ
                    with ui.column().classes("w-full bg-blue-50 rounded-lg p-3 gap-1 border border-blue-100"):
                        ui.label("Bước 3 — Giám đốc phê duyệt").classes("text-xs font-bold text-blue-700 uppercase")
                        _info("Người duyệt:", _gd_display(leave) or "Chưa xác định")
                        if leave.get("gd_approved_at"):
                            _info("Ngày duyệt:", leave["gd_approved_at"][:10])
                            _info("Ý kiến:", leave.get("gd_comment") or "—")

                    ui.separator()

                    async def _download(l=lid):
                        try:
                            content = await asyncio.to_thread(api.download, f"/api/leaves/{l}/download")
                            ui.download(content, f"phieu_nghi_phep_{l}.docx")
                        except Exception as e:
                            _handle_api_error(e)

                    with ui.row().classes("gap-2 flex-wrap"):
                        ui.button("Tải phiếu", icon="download", on_click=_download).classes("bg-gray-100 text-gray-700 text-sm")

                        # KSV
                        if ksv_act:
                            async def _ksv_approve(l=lid):
                                try:
                                    await asyncio.to_thread(api.put, f"/api/leaves/{l}/ksv-review", {"action": "approve"})
                                    detail_drawer.hide()
                                    ui.notify("Đã phê duyệt KSV", type="positive")
                                    ui.navigate.to("/leaves")
                                except Exception as e:
                                    _handle_api_error(e)

                            def _ksv_reject_open(l=lid):
                                async def _cb(reason, _l=l):
                                    try:
                                        await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review",
                                            {"action": "reject", "comment": reason})
                                        detail_drawer.hide()
                                        ui.notify("Đã từ chối", type="warning")
                                        ui.navigate.to("/leaves")
                                    except Exception as e:
                                        _handle_api_error(e)
                                _reject_cb[0] = _cb
                                reject_dialog.open()

                            ui.button("Phê duyệt", on_click=_ksv_approve).classes("bg-green-600 text-white text-sm")
                            ui.button("Từ chối",   on_click=_ksv_reject_open).classes("bg-red-600 text-white text-sm")

                        # TH
                        if th_act:
                            async def _th_forward_open(l=lid):
                                await _load_gd_opts()

                                async def _cb(gd_id, note, _l=l):
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",
                                            {"action": "forward", "gd_approver_id": gd_id, "comment": note})
                                        detail_drawer.hide()
                                        ui.notify("Đã chuyển lên GĐ/PGĐ", type="positive")
                                        ui.navigate.to("/leaves")
                                    except Exception as e:
                                        _handle_api_error(e)
                                _th_cb[0] = _cb
                                th_dialog.open()

                            def _th_reject_open(l=lid):
                                async def _cb(reason, _l=l):
                                    try:
                                        await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",
                                            {"action": "reject", "comment": reason})
                                        detail_drawer.hide()
                                        ui.notify("Đã từ chối", type="warning")
                                        ui.navigate.to("/leaves")
                                    except Exception as e:
                                        _handle_api_error(e)
                                _reject_cb[0] = _cb
                                reject_dialog.open()

                            ui.button("Chuyển GĐ/PGĐ", icon="forward",
                                      on_click=lambda l=lid: asyncio.ensure_future(_th_forward_open(l))).classes("bg-blue-600 text-white text-sm")
                            ui.button("Từ chối", on_click=_th_reject_open).classes("bg-red-600 text-white text-sm")

                        # GĐ
                        if gd_act:
                            async def _gd_approve(l=lid):
                                try:
                                    await asyncio.to_thread(api.put, f"/api/leaves/{l}/gd-review", {"action": "approve"})
                                    detail_drawer.hide()
                                    ui.notify("Đã phê duyệt", type="positive")
                                    ui.navigate.to("/leaves")
                                except Exception as e:
                                    _handle_api_error(e)

                            def _gd_reject_open(l=lid):
                                async def _cb(reason, _l=l):
                                    try:
                                        await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review",
                                            {"action": "reject", "comment": reason})
                                        detail_drawer.hide()
                                        ui.notify("Đã từ chối", type="warning")
                                        ui.navigate.to("/leaves")
                                    except Exception as e:
                                        _handle_api_error(e)
                                _reject_cb[0] = _cb
                                reject_dialog.open()

                            ui.button("Phê duyệt", on_click=_gd_approve).classes("bg-green-600 text-white text-sm")
                            ui.button("Từ chối",   on_click=_gd_reject_open).classes("bg-red-600 text-white text-sm")

                        # Resubmit
                        if is_owner and status == "rejected":
                            def _open_resubmit(lv=leave):
                                r_start.value  = (lv.get("start_date") or "")[:10]
                                r_end.value    = (lv.get("end_date") or "")[:10]
                                r_type.value   = lv.get("leave_type", "annual")
                                r_reason.value = lv.get("reason") or ""
                                _rsub_id[0]    = lv["id"]
                                if r_approver:
                                    r_approver.value = lv.get("ksv_approver_id")
                                resubmit_dialog.open()

                            ui.button("Sửa & Nộp lại", icon="refresh", on_click=_open_resubmit).classes("bg-orange-500 text-white text-sm")

                        # Hủy
                        if is_owner and status in ("pending_ksv", "pending_tong_hop", "pending_gd"):
                            async def _cancel(l=lid):
                                try:
                                    await asyncio.to_thread(api.patch, f"/api/leaves/{l}/cancel", {})
                                    detail_drawer.hide()
                                    ui.notify("Đã hủy đơn", type="warning")
                                    ui.navigate.to("/leaves")
                                except Exception as e:
                                    _handle_api_error(e)

                            ui.button("Hủy đơn", icon="cancel", on_click=_cancel).classes("bg-gray-200 text-gray-700 text-sm")

            detail_drawer.show()

        # ── Hàm mở dialog lịch sử ────────────────────────────────────────────
        async def open_history(leave: dict):
            history_container.clear()
            with history_container:
                with ui.row().classes("w-full bg-gray-800 text-white px-5 py-3 items-center gap-2"):
                    ui.icon("history").classes("text-xl")
                    with ui.column().classes("gap-0"):
                        ui.label("Lịch sử thao tác").classes("font-bold text-base")
                        ui.label(leave.get("staff_name", "")).classes("text-gray-300 text-sm")
                try:
                    logs = await asyncio.to_thread(api.get, f"/api/leaves/{leave['id']}/history")
                except Exception:
                    logs = []
                if not logs:
                    with ui.column().classes("p-6"):
                        ui.label("Chưa có lịch sử thao tác.").classes("text-gray-400 text-sm")
                else:
                    _COLOR = {"green": "bg-green-100 text-green-700", "red": "bg-red-100 text-red-700",
                              "blue": "bg-blue-100 text-blue-700", "orange": "bg-orange-100 text-orange-700",
                              "grey": "bg-gray-100 text-gray-500"}
                    with ui.column().classes("px-5 py-4 gap-3 w-full"):
                        for log in logs:
                            cls = _COLOR.get(log.get("action_color", "grey"), "bg-gray-100 text-gray-500")
                            with ui.row().classes("w-full items-start gap-3 border-b border-gray-100 pb-3"):
                                with ui.column().classes("flex-1 gap-1"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.label(log.get("action_label", log.get("action", ""))).classes(
                                            f"text-xs font-medium px-2 py-0.5 rounded {cls}")
                                        ui.label(log.get("actor_name", "")).classes("text-sm font-medium")
                                    if log.get("comment"):
                                        ui.label(f"Lý do: {log['comment']}").classes("text-xs text-gray-500")
                                    ts = log.get("created_at", "")
                                    if ts:
                                        ui.label(ts[:16].replace("T", " ")).classes("text-xs text-gray-400")
            history_dialog.open()

        # ── Tracking selection ────────────────────────────────────────────────
        _sel: set = set()
        _approve_btn: list = []
        _reject_btn:  list = []

        def _upd_btns():
            en = bool(_sel)
            for b in _approve_btn:
                b.set_enabled(en)
            for b in _reject_btn:
                b.set_enabled(en)

        # ── Bulk actions ──────────────────────────────────────────────────────
        async def _bulk_approve():
            ids = list(_sel)
            lv_map = {lv["id"]: lv for lv in pending_leaves}
            th_ids     = [i for i in ids if lv_map.get(i, {}).get("status") == "pending_tong_hop"]
            other_ids  = [i for i in ids if i not in th_ids]

            for i in other_ids:
                st = lv_map.get(i, {}).get("status", "")
                try:
                    if st == "pending_ksv":
                        await asyncio.to_thread(api.put, f"/api/leaves/{i}/ksv-review", {"action": "approve"})
                    elif st == "pending_gd":
                        await asyncio.to_thread(api.put, f"/api/leaves/{i}/gd-review", {"action": "approve"})
                except Exception:
                    pass

            if th_ids:
                await _load_gd_opts()
                async def _th_bulk(gd_id, note):
                    for i in th_ids:
                        try:
                            await asyncio.to_thread(api.post, f"/api/leaves/{i}/tong-hop-review",
                                {"action": "forward", "gd_approver_id": gd_id, "comment": note})
                        except Exception:
                            pass
                    _sel.clear()
                    ui.notify("Hoàn thành", type="positive")
                    ui.navigate.to("/leaves")
                _th_cb[0] = _th_bulk
                th_dialog.open()
            else:
                _sel.clear()
                ui.notify("Đã phê duyệt các đơn đã chọn", type="positive")
                ui.navigate.to("/leaves")

        async def _bulk_reject_open():
            ids = list(_sel)
            lv_map = {lv["id"]: lv for lv in pending_leaves}
            async def _cb(reason):
                for i in ids:
                    st = lv_map.get(i, {}).get("status", "")
                    try:
                        if st == "pending_ksv":
                            await asyncio.to_thread(api.put, f"/api/leaves/{i}/ksv-review",
                                {"action": "reject", "comment": reason})
                        elif st == "pending_tong_hop":
                            await asyncio.to_thread(api.post, f"/api/leaves/{i}/tong-hop-review",
                                {"action": "reject", "comment": reason})
                        elif st == "pending_gd":
                            await asyncio.to_thread(api.put, f"/api/leaves/{i}/gd-review",
                                {"action": "reject", "comment": reason})
                    except Exception:
                        pass
                _sel.clear()
                ui.notify("Đã từ chối các đơn đã chọn", type="warning")
                ui.navigate.to("/leaves")
            _reject_cb[0] = _cb
            reject_dialog.open()

        # ── Toolbar ───────────────────────────────────────────────────────────
        with ui.row().classes("gap-2 mb-4 items-center flex-wrap"):
            ui.button("+ Tạo đơn", icon="add", on_click=create_dialog.open).classes("bg-red-700 text-white")
            ab = ui.button("Phê duyệt", icon="check_circle",
                           on_click=lambda: asyncio.ensure_future(_bulk_approve())).classes(
                "bg-green-600 text-white").props("disabled")
            rb = ui.button("Từ chối", icon="cancel",
                           on_click=lambda: asyncio.ensure_future(_bulk_reject_open())).classes(
                "bg-red-600 text-white").props("disabled")
            _approve_btn.append(ab)
            _reject_btn.append(rb)

            async def _export_leaves():
                try:
                    _scp = "all" if can_all else "mine"
                    content = await asyncio.to_thread(
                        api.download, "/api/leaves/export",
                        params={"scope": _scp},
                    )
                    ui.download(content, "danh_sach_nghi_phep.xlsx")
                except Exception as e:
                    _handle_api_error(e)

            ui.button("Xuất Excel", icon="download",
                      on_click=_export_leaves).classes("bg-blue-700 text-white").tooltip("Tải file Excel")

        # ── Hàm vẽ bảng ──────────────────────────────────────────────────────
        def _draw_table(leaves: list, show_name: bool = False):
            if not leaves:
                ui.label("Không có đơn nghỉ phép nào.").classes("text-gray-400 text-sm mt-4")
                return
            with ui.column().classes("w-full gap-0"):
                # Header
                with ui.row().classes("w-full bg-red-50 border-b border-red-100 px-3 py-2 items-center gap-2"):
                    ui.label("").classes("w-6 shrink-0")
                    ui.label("Ngày tạo").classes("font-semibold text-red-800 text-xs w-20 shrink-0")
                    ui.label("Trạng thái").classes("font-semibold text-red-800 text-xs w-28 shrink-0")
                    if show_name:
                        ui.label("Họ và tên").classes("font-semibold text-red-800 text-xs w-28 shrink-0")
                    ui.label("Ngày nghỉ").classes("font-semibold text-red-800 text-xs w-32 shrink-0")
                    ui.label("Kiểm soát").classes("font-semibold text-red-800 text-xs w-24 shrink-0")
                    ui.label("Phòng TH").classes("font-semibold text-red-800 text-xs w-24 shrink-0")
                    ui.label("Giám đốc").classes("font-semibold text-red-800 text-xs flex-1")
                    ui.label("").classes("w-16 shrink-0")

                for lv in leaves:
                    sg_lbl, sg_cls = _STATUS_GROUP.get(lv["status"], (lv["status"], "bg-gray-100 text-gray-500"))
                    with ui.row().classes("w-full bg-white border-b border-gray-100 px-3 py-1.5 items-center gap-2 hover:bg-red-50"):
                        ck = ui.checkbox(value=False).classes("w-6 shrink-0")
                        ck.on("update:model-value", lambda v, l=lv["id"]: (_sel.add(l) if v else _sel.discard(l)) or _upd_btns())

                        ui.label((lv.get("created_at") or "")[:10]).classes("text-xs w-20 shrink-0")
                        ui.label(sg_lbl).classes(f"text-xs px-1.5 py-0.5 rounded {sg_cls} w-28 shrink-0 text-center")
                        if show_name:
                            ui.label(lv.get("staff_name", "")).classes("text-xs w-28 shrink-0 truncate")
                        ui.label(_fmt_leave_dates(lv.get("start_date",""), lv.get("end_date",""))).classes("text-xs w-32 shrink-0")
                        ui.label(lv.get("ksv_approver_name") or "—").classes("text-xs w-24 shrink-0 truncate")
                        ui.label(lv.get("tong_hop_approver_name") or "—").classes("text-xs w-24 shrink-0 truncate")
                        ui.label(_gd_display(lv) or "—").classes("text-xs flex-1 truncate")
                        with ui.row().classes("w-16 gap-0.5 justify-end shrink-0"):
                            ui.button(icon="info", on_click=lambda l=lv: asyncio.ensure_future(open_detail(l))).props(
                                "flat round dense size=sm").classes("text-blue-600").tooltip("Chi tiết")
                            ui.button(icon="history", on_click=lambda l=lv: asyncio.ensure_future(open_history(l))).props(
                                "flat round dense size=sm").classes("text-gray-500").tooltip("Lịch sử")

        # ── Tabs ──────────────────────────────────────────────────────────────
        with ui.tabs().classes("mb-4") as leave_tabs:
            t_mine    = ui.tab("Của tôi")
            t_pending = ui.tab(f"Chờ duyệt ({len(pending_leaves)})")
            t_all     = ui.tab("Tất cả") if can_all else None
            t_cal     = ui.tab("Lịch nghỉ phép")
            t_deleg   = ui.tab("Ủy quyền GĐ") if can_delegation else None
            t_holiday = ui.tab("Ngày lễ") if can_delegation else None

        with ui.tab_panels(leave_tabs, value=t_mine).classes("w-full"):
            with ui.tab_panel(t_mine):
                _draw_table(my_leaves)

            with ui.tab_panel(t_pending):
                _draw_table(pending_leaves, show_name=True)

            if can_all and t_all:
                with ui.tab_panel(t_all):
                    _draw_table(all_leaves, show_name=True)

            with ui.tab_panel(t_cal):
                import datetime as _dt_mod
                _today = _dt_mod.date.today()
                with ui.row().classes("gap-3 mb-4 items-center"):
                    cal_year  = ui.select({y: str(y) for y in range(2024, _today.year + 2)},
                                          label="Năm", value=_today.year).classes("w-28")
                    cal_month = ui.select({m: f"Tháng {m:02d}" for m in range(1, 13)},
                                          label="Tháng", value=_today.month).classes("w-36")

                _CAL_TYPE_COLOR = {
                    "annual":   "bg-blue-100 text-blue-800",
                    "sick":     "bg-orange-100 text-orange-800",
                    "personal": "bg-purple-100 text-purple-800",
                    "other":    "bg-gray-100 text-gray-600",
                }
                _CAL_TYPE_DOT = {
                    "annual":   "#1565C0",
                    "sick":     "#E65100",
                    "personal": "#6A1B9A",
                    "other":    "#546E7A",
                }
                _DOW_VN = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

                cal_container = ui.column().classes("w-full gap-0")

                async def _reload_cal():
                    cal_container.clear()
                    try:
                        data = await asyncio.to_thread(
                            api.get, "/api/leaves/calendar",
                            {"year": cal_year.value, "month": cal_month.value},
                        )
                    except Exception:
                        data = {}
                    days_map = data.get("days", {}) if isinstance(data, dict) else {}
                    y, m = cal_year.value, cal_month.value

                    import calendar as _cal_mod
                    first_wd = _dt_mod.date(y, m, 1).weekday()  # 0=Thứ 2
                    last_day = _cal_mod.monthrange(y, m)[1]

                    with cal_container:
                        # Chú thích
                        with ui.row().classes("gap-4 mb-3 flex-wrap items-center"):
                            for _lt, _cls in _CAL_TYPE_COLOR.items():
                                with ui.row().classes("items-center gap-1"):
                                    ui.element("span").classes(f"text-xs px-2 py-0.5 rounded {_cls}").set_text(
                                        _LEAVE_TYPE.get(_lt, _lt))
                        # Header ngày trong tuần
                        with ui.row().classes("w-full grid gap-1").style(
                                "display:grid;grid-template-columns:repeat(7,1fr)"):
                            for d in _DOW_VN:
                                ui.label(d).classes(
                                    "text-center text-xs font-bold text-gray-500 py-1"
                                    + (" text-red-600" if d == "CN" else "")
                                )
                        # Lưới ngày
                        with ui.element("div").style(
                                "display:grid;grid-template-columns:repeat(7,1fr);gap:4px"):
                            # Ô trống trước ngày 1
                            for _ in range(first_wd):
                                ui.element("div").classes("rounded bg-gray-50 min-h-[72px] p-1")
                            for day in range(1, last_day + 1):
                                d_str = f"{y}-{m:02d}-{day:02d}"
                                d_obj = _dt_mod.date(y, m, day)
                                people = days_map.get(d_str, [])
                                is_weekend = d_obj.weekday() >= 5
                                is_today   = d_obj == _today
                                bg = "bg-blue-50 border-blue-300" if is_today else (
                                     "bg-red-50" if is_weekend else "bg-white border-gray-100")
                                with ui.element("div").classes(
                                        f"rounded border {bg} min-h-[72px] p-1 overflow-hidden"
                                ):
                                    ui.label(str(day)).classes(
                                        "text-xs font-bold mb-1 " + (
                                            "text-blue-700" if is_today else
                                            "text-red-500" if is_weekend else "text-gray-700"
                                        )
                                    )
                                    for p in people[:3]:
                                        lt   = p.get("leave_type", "other")
                                        cls  = _CAL_TYPE_COLOR.get(lt, "bg-gray-100 text-gray-600")
                                        name = p.get("staff_name", "")
                                        # Rút gọn họ tên → lấy tên cuối
                                        short = name.split()[-1] if name else ""
                                        ui.label(short).classes(
                                            f"text-[10px] leading-tight px-1 rounded truncate {cls} mb-0.5 w-full")
                                    if len(people) > 3:
                                        ui.label(f"+{len(people)-3}").classes(
                                            "text-[9px] text-gray-400 leading-tight")

                cal_year.on("update:model-value",  lambda: asyncio.ensure_future(_reload_cal()))
                cal_month.on("update:model-value", lambda: asyncio.ensure_future(_reload_cal()))
                await _reload_cal()

            if can_delegation and t_deleg:
                with ui.tab_panel(t_deleg):
                    # ── Dialog tạo ủy quyền ───────────────────────────────────
                    gd_staff_list, pgd_staff_list = [], []
                    try:
                        gd_staff_list, pgd_staff_list = await asyncio.gather(
                            asyncio.to_thread(api.get, "/api/delegations/staff/giam-doc"),
                            asyncio.to_thread(api.get, "/api/delegations/staff/pho-giam-doc"),
                        )
                    except Exception:
                        pass

                    gd_opts  = {s["id"]: s["full_name"] for s in (gd_staff_list  or [])}
                    pgd_opts = {s["id"]: s["full_name"] for s in (pgd_staff_list or [])}

                    with ui.dialog() as deleg_dialog, ui.card().classes("p-6 w-96"):
                        ui.label("Tạo ủy quyền Giám đốc").classes("text-lg font-bold text-red-900 mb-4")
                        d_gd   = ui.select(gd_opts,  label="Giám đốc ủy quyền").classes("w-full")
                        d_pgd  = ui.select(pgd_opts, label="Phó GĐ được ủy quyền").classes("w-full mt-2")
                        d_from = ui.date(value="").props("label='Từ ngày' mask='YYYY-MM-DD'").classes("w-full mt-2")
                        d_to   = ui.date(value="").props("label='Đến ngày' mask='YYYY-MM-DD'").classes("w-full mt-2")
                        d_note = ui.input("Ghi chú (tuỳ chọn)").classes("w-full mt-2")

                        async def do_create_deleg():
                            if not d_gd.value or not d_pgd.value or not d_from.value or not d_to.value:
                                ui.notify("Vui lòng điền đầy đủ thông tin", type="warning")
                                return
                            try:
                                await asyncio.to_thread(api.post, "/api/delegations/", {
                                    "giam_doc_id": d_gd.value, "pho_giam_doc_id": d_pgd.value,
                                    "start_date": d_from.value, "end_date": d_to.value,
                                    "note": d_note.value or None,
                                })
                                deleg_dialog.close()
                                ui.notify("Đã tạo ủy quyền thành công!", type="positive")
                                ui.navigate.to("/leaves")
                            except Exception as e:
                                _handle_api_error(e)

                        with ui.row().classes("w-full justify-end gap-2 mt-4"):
                            ui.button("Hủy", on_click=deleg_dialog.close).classes("text-gray-500")
                            ui.button("Tạo ủy quyền", on_click=do_create_deleg).classes("bg-red-700 text-white")

                    ui.button("+ Tạo ủy quyền", on_click=deleg_dialog.open).classes("bg-red-700 text-white mb-4")

                    if not delegations:
                        ui.label("Chưa có bản ghi ủy quyền nào.").classes("text-gray-400 text-sm")
                    else:
                        with ui.column().classes("w-full gap-0"):
                            with ui.row().classes("w-full bg-red-50 border-b border-red-100 px-4 py-2 gap-3"):
                                for hdr in ["Giám đốc", "Phó GĐ được ủy quyền", "Từ ngày", "Đến ngày", "Ghi chú", "Trạng thái", ""]:
                                    ui.label(hdr).classes("font-semibold text-red-800 text-sm flex-1")
                            for d in delegations:
                                today_str = __import__("datetime").date.today().isoformat()
                                is_eff = d["is_active"] and d["start_date"] <= today_str <= d["end_date"]
                                badge_cls = "bg-green-100 text-green-700" if is_eff else "bg-gray-100 text-gray-500"
                                badge_txt = "Đang hiệu lực" if is_eff else "Không hiệu lực"
                                with ui.row().classes("w-full bg-white border-b border-gray-100 px-4 py-2 gap-3 items-center"):
                                    ui.label(d.get("giam_doc_name", "")).classes("text-sm flex-1")
                                    ui.label(d.get("pho_giam_doc_name", "")).classes("text-sm flex-1")
                                    ui.label(d.get("start_date", "")[:10]).classes("text-sm flex-1")
                                    ui.label(d.get("end_date", "")[:10]).classes("text-sm flex-1")
                                    ui.label(d.get("note") or "—").classes("text-xs text-gray-500 flex-1")
                                    ui.label(badge_txt).classes(f"text-xs px-2 py-0.5 rounded {badge_cls} flex-1")
                                    if d["is_active"]:
                                        async def do_deactivate(did=d["id"]):
                                            try:
                                                await asyncio.to_thread(api.patch, f"/api/delegations/{did}/deactivate", {})
                                                ui.notify("Đã hủy ủy quyền", type="warning")
                                                ui.navigate.to("/leaves")
                                            except Exception as e:
                                                _handle_api_error(e)
                                        ui.button("Hủy", on_click=do_deactivate).classes("text-xs bg-gray-100 text-gray-600")
                                    else:
                                        ui.label("").classes("flex-1")

            if can_delegation and t_holiday:
                with ui.tab_panel(t_holiday):
                    _cur_year = __import__("datetime").date.today().year
                    with ui.row().classes("gap-3 mb-4 items-center"):
                        h_year_sel = ui.select(
                            {y: str(y) for y in range(2024, _cur_year + 3)},
                            label="Năm", value=_cur_year,
                        ).classes("w-28")
                        ui.button("+ Thêm ngày lễ", icon="add",
                                  on_click=lambda: add_holiday_dialog.open()).classes("bg-red-700 text-white")

                    holiday_table_area = ui.column().classes("w-full gap-0")

                    with ui.dialog() as add_holiday_dialog, ui.card().classes("p-6 w-80"):
                        ui.label("Thêm ngày lễ").classes("text-lg font-bold text-red-900 mb-4")
                        h_date_in = ui.date(value="").props("label='Ngày lễ' mask='YYYY-MM-DD'").classes("w-full")
                        h_name_in = ui.input("Tên ngày lễ").classes("w-full mt-2")

                        async def do_add_holiday():
                            if not h_date_in.value or not h_name_in.value.strip():
                                ui.notify("Vui lòng nhập đầy đủ thông tin", type="warning")
                                return
                            try:
                                await asyncio.to_thread(api.post, "/api/admin/holidays/", {
                                    "date": h_date_in.value,
                                    "name": h_name_in.value.strip(),
                                })
                                h_date_in.value = ""
                                h_name_in.value = ""
                                add_holiday_dialog.close()
                                ui.notify("Đã thêm ngày lễ!", type="positive")
                                await _reload_holidays()
                            except Exception as e:
                                _handle_api_error(e)

                        with ui.row().classes("w-full justify-end gap-2 mt-4"):
                            ui.button("Hủy", on_click=add_holiday_dialog.close).classes("text-gray-500")
                            ui.button("Thêm", on_click=do_add_holiday).classes("bg-red-700 text-white")

                    async def _reload_holidays():
                        holiday_table_area.clear()
                        try:
                            holidays_data = await asyncio.to_thread(
                                api.get, "/api/admin/holidays/", {"year": h_year_sel.value}
                            )
                        except Exception:
                            holidays_data = []
                        holidays_data = holidays_data if isinstance(holidays_data, list) else []
                        with holiday_table_area:
                            if not holidays_data:
                                ui.label("Chưa có ngày lễ nào trong năm này.").classes("text-gray-400 text-sm mt-4")
                                return
                            with ui.column().classes("w-full gap-0"):
                                with ui.row().classes("w-full bg-red-50 border-b border-red-100 px-4 py-2 gap-3"):
                                    ui.label("Ngày").classes("font-semibold text-red-800 text-sm w-32 shrink-0")
                                    ui.label("Tên ngày lễ").classes("font-semibold text-red-800 text-sm flex-1")
                                    ui.label("").classes("w-12 shrink-0")
                                for h in holidays_data:
                                    with ui.row().classes("w-full bg-white border-b border-gray-100 px-4 py-2 gap-3 items-center"):
                                        ui.label(h.get("date", "")[:10]).classes("text-sm w-32 shrink-0 font-mono")
                                        ui.label(h.get("name", "")).classes("text-sm flex-1")
                                        async def do_del_holiday(hid=h["id"]):
                                            try:
                                                await asyncio.to_thread(api.delete, f"/api/admin/holidays/{hid}")
                                                ui.notify("Đã xóa ngày lễ", type="warning")
                                                await _reload_holidays()
                                            except Exception as ex:
                                                _handle_api_error(ex)
                                        ui.button(icon="delete", on_click=do_del_holiday).props(
                                            "flat round dense size=sm").classes("text-red-500 w-12 shrink-0")

                    h_year_sel.on("update:model-value", lambda: asyncio.ensure_future(_reload_holidays()))
                    await _reload_holidays()


# ─── LOGS PAGE ───────────────────────────────────────────────────────────────
_LOG_LEVEL_CFG = {
    "ERROR":   ("Lỗi",       "bg-red-100 text-red-700 border-red-300"),
    "WARNING": ("Cảnh báo",  "bg-orange-100 text-orange-700 border-orange-300"),
    "INFO":    ("Thông tin", "bg-blue-100 text-blue-700 border-blue-300"),
    "DEBUG":   ("Debug",     "bg-gray-100 text-gray-500 border-gray-300"),
}


@ui.page("/logs")
async def logs_page():
    if not _require_auth():
        return
    user = api.get_current_user()
    if not user or user.get("role") not in ("admin", "giam_doc", "pho_giam_doc"):
        ui.navigate.to("/home")
        return
    _ = _sidebar("logs")

    with _content_area():
        _page_header("Nhật ký hệ thống", "Xem lịch sử lỗi và cảnh báo của ứng dụng")

        _level: list = [""]

        # ── Toolbar ────────────────────────────────────────────────────────────
        # (nút load được gắn sau khi _load được định nghĩa bên dưới)
        toolbar_row = ui.row().classes("gap-2 mb-2 items-center flex-wrap")
        status_label = ui.label("Đang tải...").classes("text-sm text-gray-500 mb-2")
        log_container = ui.column().classes("w-full gap-0")

        # ── Hàm load log ───────────────────────────────────────────────────────
        async def _load(level: str = ""):
            _level[0] = level
            status_label.set_text("Đang tải...")
            log_container.clear()
            try:
                data = await asyncio.to_thread(
                    api.get, "/api/admin/logs/", {"level": level, "limit": 500}
                )
            except Exception as e:
                status_label.set_text("Không thể tải log.")
                if _handle_api_error(e):
                    return
                return
            entries = data.get("entries", []) if isinstance(data, dict) else []
            total   = data.get("total", len(entries)) if isinstance(data, dict) else len(entries)
            status_label.set_text(f"Hiển thị {len(entries)} / {total} bản ghi (mới nhất trước)")

            with log_container:
                if not entries:
                    ui.label("Không có bản ghi nào.").classes("text-gray-400 text-sm mt-4")
                    return

                with ui.row().classes("w-full bg-gray-100 border-b border-gray-200 px-3 py-2 items-center gap-2"):
                    ui.label("Thời gian").classes("font-semibold text-gray-700 text-xs w-36 shrink-0")
                    ui.label("Mức độ").classes("font-semibold text-gray-700 text-xs w-24 shrink-0")
                    ui.label("Nguồn").classes("font-semibold text-gray-700 text-xs w-48 shrink-0")
                    ui.label("Nội dung").classes("font-semibold text-gray-700 text-xs flex-1")

                for e in entries:
                    lv  = e.get("level", "INFO")
                    lbl, badge_cls = _LOG_LEVEL_CFG.get(lv, (lv, "bg-gray-100 text-gray-500 border-gray-300"))
                    row_bg = "bg-red-50" if lv == "ERROR" else ("bg-orange-50" if lv == "WARNING" else "bg-white")
                    msg = e.get("msg", "")

                    with ui.row().classes(f"w-full {row_bg} border-b border-gray-100 px-3 py-1.5 items-start gap-2"):
                        ui.label(e.get("ts", "")).classes("text-xs font-mono w-36 shrink-0 text-gray-600 mt-0.5")
                        ui.label(lbl).classes(
                            f"text-xs font-medium px-2 py-0.5 rounded border {badge_cls} w-24 shrink-0 text-center mt-0.5"
                        )
                        ui.label(e.get("logger", "")).classes("text-xs font-mono w-48 shrink-0 text-gray-500 truncate mt-0.5")
                        if "\n" in msg:
                            ui.element("pre").classes(
                                "text-xs font-mono flex-1 whitespace-pre-wrap break-all text-gray-800 leading-5"
                            ).style("margin:0;background:transparent").set_text(msg)
                        else:
                            ui.label(msg).classes("text-xs flex-1 break-all text-gray-800")

        # ── Gắn nút vào toolbar ────────────────────────────────────────────────
        with toolbar_row:
            ui.button("↻ Làm mới", icon="refresh",
                      on_click=lambda: asyncio.ensure_future(_load(_level[0]))).classes(
                "bg-gray-700 text-white text-sm")
            ui.separator().props("vertical")
            for _code, _vn in [("", "Tất cả"), ("ERROR", "Lỗi"), ("WARNING", "Cảnh báo"), ("INFO", "Thông tin")]:
                ui.button(_vn,
                          on_click=lambda c=_code: asyncio.ensure_future(_load(c))).classes(
                    "text-sm bg-gray-100 text-gray-700 hover:bg-gray-200")
            ui.separator().props("vertical")

            async def _backup_db():
                try:
                    content = await asyncio.to_thread(api.download, "/api/admin/logs/backup")
                    from datetime import date as _dt
                    ui.download(content, f"ksnb_backup_{_dt.today().isoformat()}.db")
                    ui.notify("Đã tạo bản sao DB thành công!", type="positive")
                except Exception as e:
                    _handle_api_error(e)

            ui.button("Backup DB", icon="backup",
                      on_click=_backup_db).classes("bg-orange-600 text-white text-sm").tooltip(
                "Tải về bản sao cơ sở dữ liệu")

        await _load("")

        # ── Nhật ký đăng nhập ─────────────────────────────────────────────────
        ui.separator().classes("my-4")
        with ui.row().classes("items-center gap-3 mb-2"):
            ui.label("Nhật ký đăng nhập").classes("text-base font-bold text-gray-800")
            login_status_label = ui.label("").classes("text-sm text-gray-500")

        login_filter_ref: list = [""]
        login_container = ui.column().classes("w-full gap-0")

        async def _load_logins(success_filter: str = ""):
            login_filter_ref[0] = success_filter
            login_status_label.set_text("Đang tải...")
            login_container.clear()
            try:
                data = await asyncio.to_thread(
                    api.get, "/api/admin/logs/logins",
                    {"success": success_filter, "limit": 200},
                )
            except Exception:
                login_status_label.set_text("Không thể tải nhật ký đăng nhập.")
                return
            entries = data.get("entries", []) if isinstance(data, dict) else []
            total   = data.get("total", len(entries)) if isinstance(data, dict) else len(entries)
            login_status_label.set_text(f"{len(entries)} / {total} bản ghi")

            with login_container:
                if not entries:
                    ui.label("Không có bản ghi.").classes("text-gray-400 text-sm mt-2")
                    return
                with ui.row().classes("w-full bg-gray-100 border-b border-gray-200 px-3 py-2 items-center gap-2"):
                    ui.label("Thời gian").classes("font-semibold text-gray-700 text-xs w-36 shrink-0")
                    ui.label("Kết quả").classes("font-semibold text-gray-700 text-xs w-20 shrink-0")
                    ui.label("Username").classes("font-semibold text-gray-700 text-xs w-28 shrink-0")
                    ui.label("Họ và tên").classes("font-semibold text-gray-700 text-xs w-40 shrink-0")
                    ui.label("IP").classes("font-semibold text-gray-700 text-xs w-28 shrink-0")
                    ui.label("Chi tiết").classes("font-semibold text-gray-700 text-xs flex-1")
                for e in entries:
                    ok = e.get("success", False)
                    badge_cls = "bg-green-100 text-green-700" if ok else "bg-red-100 text-red-700"
                    badge_txt = "Thành công" if ok else "Thất bại"
                    with ui.row().classes("w-full bg-white border-b border-gray-100 px-3 py-1.5 items-center gap-2"):
                        ts = (e.get("created_at") or "")[:16].replace("T", " ")
                        ui.label(ts).classes("text-xs font-mono w-36 shrink-0 text-gray-600")
                        ui.label(badge_txt).classes(f"text-xs px-1.5 py-0.5 rounded {badge_cls} w-20 shrink-0 text-center")
                        ui.label(e.get("username", "")).classes("text-xs w-28 shrink-0 font-mono truncate")
                        ui.label(e.get("full_name") or "—").classes("text-xs w-40 shrink-0 truncate")
                        ui.label(e.get("ip_address") or "—").classes("text-xs font-mono w-28 shrink-0 text-gray-500")
                        ui.label(e.get("detail") or "").classes("text-xs flex-1 text-gray-500 truncate")

        with ui.row().classes("gap-2 mb-2 items-center"):
            for _sf, _lbl in [("", "Tất cả"), ("true", "Thành công"), ("false", "Thất bại")]:
                ui.button(_lbl,
                          on_click=lambda f=_sf: asyncio.ensure_future(_load_logins(f))).classes(
                    "text-sm bg-gray-100 text-gray-700 hover:bg-gray-200")
            ui.button("↻", icon="refresh",
                      on_click=lambda: asyncio.ensure_future(_load_logins(login_filter_ref[0]))).classes(
                "text-sm bg-gray-700 text-white")

        await _load_logins("")


# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0",
        port=8080,
        title="KSNB&HTVH – Agribank",
        favicon="🏦",
        dark=False,
        reload=False,
        show=False,
        storage_secret="ksnb-htvh-agribank-2025",
        reconnect_timeout=30,
    )
