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
]

def _sidebar(current_page: str):
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
                "admin": "Quản trị viên",
                "hau_kiem_vien": "Hậu kiểm viên",
                "controller": "Kiểm soát viên",
                "viewer": "Xem",
                "chuyen_vien": "Giao dịch viên",
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
                    ui.label(label).classes("text-sm")

        # Đăng xuất
        with ui.row().classes("w-full items-center px-4 py-3 cursor-pointer hover:bg-red-800 border-t border-red-700").on(
            "click", _logout
        ):
            ui.icon("logout").classes("text-xl mr-3 text-red-300")
            ui.label("Đăng xuất").classes("text-sm")


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
        await client.connected()
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
    _sidebar("home")
    with _content_area():
        _page_header("Trang chủ", "Hệ thống quản lý KSNB&HTVH – Agribank")

        loading_row = ui.row().classes("w-full justify-center items-center py-10")
        with loading_row:
            ui.spinner(size="3em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-3 text-sm")
        content = ui.column().classes("w-full gap-6")

        await ui.context.client.connected()
        try:
            staff_list, depts, groups = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/staff/"),
                asyncio.to_thread(api.get, "/api/departments/"),
                asyncio.to_thread(api.get, "/api/bundles/groups"),
            )
        except Exception:
            staff_list, depts, groups = [], [], []

        loading_row.set_visibility(False)

        stats = [
            ("Cán bộ KSNB", len(staff_list), "people", "bg-red-50 border-red-200"),
            ("Phòng nghiệp vụ", len([d for d in depts if d.get("is_source")]), "business", "bg-green-50 border-green-200"),
            ("Nhóm tập",    len(groups), "folder_zip", "bg-purple-50 border-purple-200"),
            ("Tập đã in",   sum(len(g.get("bundles", [])) for g in groups), "print", "bg-orange-50 border-orange-200"),
        ]

        with content:
            with ui.row().classes("w-full gap-4 mb-6"):
                for label, value, icon, colors in stats:
                    with ui.card().classes(f"flex-1 p-4 rounded-xl border {colors} shadow-sm"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon(icon).classes("text-3xl text-gray-500")
                            with ui.column().classes("gap-0"):
                                ui.label(str(value)).classes("text-3xl font-bold text-gray-800")
                                ui.label(label).classes("text-sm text-gray-500")

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

    _sidebar("staff")
    with _content_area():
        _page_header("Quản lý User", "Quản lý tài khoản đăng nhập hệ thống")

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") == "admin"

        ROLE_OPTS = {
            "admin":         "Quản trị viên",
            "hau_kiem_vien": "Hậu kiểm viên",
            "controller":    "Kiểm soát viên",
            "chuyen_vien":   "Giao dịch viên",
        }
        # viewer kept in display map for existing accounts, but removed from creation
        role_map = {**ROLE_OPTS, "viewer": "Người xem"}

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
            f_role     = ui.select(ROLE_OPTS, label="Quyền *", value="controller").classes("w-full mt-2")
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
            ksnb_list = [s for s in filtered if s.get("role") != "chuyen_vien"]
            gdv_list  = [s for s in filtered if s.get("role") == "chuyen_vien"]

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
                    if s.get("department_id"):
                        dname = dept_id_to_name.get(s["department_id"], "—")
                    elif s.get("role") != "chuyen_vien":
                        dname = "KSNB&HTVH"
                    else:
                        dname = "—"
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

                # KSNB group
                if ksnb_list:
                    with ui.row().classes("w-full px-3 py-1 bg-red-50 text-xs text-red-700 font-semibold border-b border-red-100 items-center gap-1"):
                        ui.icon("people").classes("text-sm")
                        ui.label("Phòng KSNB&HTVH")
                    for s in ksnb_list:
                        _row(s)

                # GDV groups — one section per department
                if gdv_list:
                    by_dept: dict = {}
                    for s in gdv_list:
                        by_dept.setdefault(s.get("department_id"), []).append(s)
                    for dept_id, members in sorted(by_dept.items(),
                                                   key=lambda x: dept_id_to_name.get(x[0], "")):
                        dname = dept_id_to_name.get(dept_id, f"Phòng ID {dept_id}")
                        with ui.row().classes("w-full px-3 py-1 bg-blue-50 text-xs text-blue-700 font-semibold border-b border-blue-100 items-center gap-1"):
                            ui.icon("badge").classes("text-sm")
                            ui.label(f"Giao dịch viên — {dname}")
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
    _sidebar("source_users")
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

    _sidebar("handovers")

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
            all_depts = [d for d in await asyncio.to_thread(api.get, "/api/departments/") if d.get("is_source")]
        except Exception:
            all_depts = []

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

                # Thao tác
                with ui.column().classes("w-full px-4 py-3 border-b border-gray-100 gap-2"):
                    ui.label("THAO TÁC").classes("text-xs font-bold text-gray-400 tracking-widest")
                    has_action = False

                    if user_role in ("admin", "hau_kiem_vien", "controller"):
                        if current_status == "pending_confirm":
                            has_action = True
                            async def _do_confirm(eid=entry_id, uname=user_name):
                                try:
                                    await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/confirm-received", {})
                                    ui.notify("Đã xác nhận nhận chứng từ", type="positive")
                                    await open_entry_panel(eid, uname)
                                    await load_grid()
                                except Exception as ex2:
                                    ui.notify(str(ex2), type="negative")
                            ui.button("✓  Xác nhận đã nhận", on_click=_do_confirm).classes(
                                "w-full bg-green-600 text-white rounded-lg text-sm font-semibold"
                            )

                        if current_status == "borrowed":
                            has_action = True
                            async def _do_confirm_return(eid=entry_id, uname=user_name):
                                try:
                                    await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/confirm-returned", {})
                                    ui.notify("Đã xác nhận trả chứng từ", type="positive")
                                    await open_entry_panel(eid, uname)
                                    await load_grid()
                                except Exception as ex2:
                                    ui.notify(str(ex2), type="negative")
                            ui.button("✓  Xác nhận đã trả", on_click=_do_confirm_return).classes(
                                "w-full bg-green-600 text-white rounded-lg text-sm font-semibold"
                            )

                    if is_cv and current_status == "confirmed":
                        has_action = True
                        async def _do_borrow(eid=entry_id, uname=user_name):
                            try:
                                await asyncio.to_thread(api.post, f"/api/handovers/entries/{eid}/borrow", {})
                                ui.notify("Đã đánh dấu mượn chứng từ", type="warning")
                                await open_entry_panel(eid, uname)
                                await load_grid()
                            except Exception as ex2:
                                ui.notify(str(ex2), type="negative")
                        ui.button("↩  Mượn lại", on_click=_do_borrow).classes(
                            "w-full bg-orange-500 text-white rounded-lg text-sm font-semibold"
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

            NAME_W = "200px"
            CELL_W = "50px"

            with grid_container:
                if not users:
                    ui.label("Không có cán bộ nào trong phòng này").classes(
                        "text-gray-400 text-center py-8 w-full"
                    )
                else:
                    with ui.element("div").style(
                        "overflow-x:auto; width:100%;"
                        "border:1px solid #bfdbfe; border-radius:10px;"
                        "box-shadow:0 2px 10px rgba(30,64,175,.10)"
                    ):
                        # ── Header row ────────────────────────────────────────
                        with ui.row().style(
                            "gap:0; flex-wrap:nowrap; background:#dbeafe;"
                            "border-bottom:2px solid #93c5fd"
                        ):
                            ui.label("Họ và tên").style(
                                f"min-width:{NAME_W}; width:{NAME_W}; flex-shrink:0;"
                                "font-size:14px; font-weight:700; color:#1e40af;"
                                "padding:10px 14px; border-right:2px solid #93c5fd;"
                                "position:sticky; left:0; z-index:3; background:#dbeafe;"
                            )
                            for d in range(1, days_in_month + 1):
                                dow     = _cal.weekday(year, month, d)
                                is_wknd = dow >= 5
                                hdr_bg  = "#fde68a" if is_wknd else "#dbeafe"
                                hdr_col = "#92400e"  if is_wknd else "#1e40af"
                                ui.label(f"{d:02d}").style(
                                    f"min-width:{CELL_W}; width:{CELL_W}; flex-shrink:0;"
                                    f"text-align:center; font-size:13px; font-weight:700;"
                                    f"color:{hdr_col}; padding:10px 2px;"
                                    f"border-right:1px solid #bfdbfe; background:{hdr_bg}"
                                )

                        # ── Data rows ─────────────────────────────────────────
                        for row_idx, u in enumerate(users):
                            uid    = u["id"]
                            name   = u.get("vn_name") or u.get("user_code") or ""
                            row_bg = "#ffffff" if row_idx % 2 == 0 else "#f0f9ff"

                            with ui.row().style(
                                f"gap:0; flex-wrap:nowrap;"
                                f"border-bottom:1px solid #dbeafe; background:{row_bg}"
                            ):
                                ui.label(name).style(
                                    f"min-width:{NAME_W}; width:{NAME_W}; flex-shrink:0;"
                                    "font-size:15px; font-weight:500; padding:7px 14px;"
                                    "border-right:2px solid #dbeafe; white-space:nowrap;"
                                    "overflow:hidden; display:flex; align-items:center;"
                                    f"position:sticky; left:0; z-index:2; background:{row_bg};"
                                )

                                for d in range(1, days_in_month + 1):
                                    info       = cell_data.get(uid, {}).get(d, {})
                                    val        = info.get("sheet_count", 0)
                                    entry_id   = info.get("entry_id")
                                    status     = info.get("entry_status", "confirmed")
                                    dow        = _cal.weekday(year, month, d)
                                    is_wknd    = dow >= 5

                                    # Màu nền: status > weekend > row_bg
                                    status_bg, status_border = _CELL_STATUS_STYLE.get(
                                        status if val else "confirmed", (None, None)
                                    )
                                    if val and status_bg:
                                        cell_bg     = status_bg.replace("background:", "")
                                        border_r    = status_border
                                    elif is_wknd:
                                        cell_bg  = "#fef9c3"
                                        border_r = "1px solid #dbeafe"
                                    else:
                                        cell_bg  = row_bg
                                        border_r = "1px solid #dbeafe"

                                    def _make_save(u_id, day):
                                        date_str = f"{year}-{month:02d}-{day:02d}"
                                        async def _save(e):
                                            try:
                                                raw = e.sender.value
                                                cnt = int(raw) if raw and str(raw).strip().isdigit() else 0
                                                await asyncio.to_thread(
                                                    api.put,
                                                    "/api/handovers/entry-upsert",
                                                    {"source_user_id": u_id, "date": date_str, "sheet_count": cnt},
                                                )
                                                await load_grid()
                                            except Exception as ex:
                                                ui.notify(str(ex), type="negative")
                                        return _save

                                    inp = ui.input(value=str(val) if val else "").style(
                                        f"min-width:{CELL_W}; width:{CELL_W}; flex-shrink:0;"
                                        f"border-right:{border_r}; background:{cell_bg}"
                                    ).props(
                                        f"dense borderless id='hv_{row_idx}_{d}' "
                                        "input-style='font-size:15px; font-weight:600;"
                                        " color:#1e3a8a; text-align:center; padding:7px 0'"
                                    ).on("blur", _make_save(uid, d))

                                    # Focus: mở panel khi ô có dữ liệu
                                    if entry_id:
                                        inp.on("focus", lambda eid=entry_id, uname=name: asyncio.ensure_future(
                                            open_entry_panel(eid, uname)
                                        ))

            # Điều hướng bằng phím mũi tên
            if users:
                _n_rows = len(users) - 1
                _n_cols = days_in_month
                ui.run_javascript(f"""
                    window._hv_max_row = {_n_rows};
                    window._hv_max_col = {_n_cols};
                    if (!window._hv_arrow_registered) {{
                        window._hv_arrow_registered = true;
                        document.addEventListener('keydown', function(e) {{
                            if (!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) return;
                            var a = document.activeElement;
                            if (!a || a.tagName !== 'INPUT') return;
                            var w = a.closest('[id^="hv_"]');
                            if (!w) return;
                            var p = w.id.split('_');
                            if (p.length < 3) return;
                            var row = parseInt(p[1]), col = parseInt(p[2]);
                            var mr = window._hv_max_row, mc = window._hv_max_col;
                            e.preventDefault();
                            var tr = row, tc = col;
                            if (e.key==='ArrowUp') tr=Math.max(0,row-1);
                            else if (e.key==='ArrowDown') tr=Math.min(mr,row+1);
                            else if (e.key==='ArrowLeft') {{
                                if (col>1) tc=col-1;
                                else if (row>0) {{ tr=row-1; tc=mc; }}
                            }} else if (e.key==='ArrowRight') {{
                                if (col<mc) tc=col+1;
                                else if (row<mr) {{ tr=row+1; tc=1; }}
                            }}
                            if (tr!==row||tc!==col) {{
                                var el=document.getElementById('hv_'+tr+'_'+tc);
                                var inp=el?el.querySelector('input'):null;
                                if (inp) {{ inp.focus(); inp.select(); }}
                            }}
                        }});
                    }}
                """)

        # app.storage.tab chỉ khả dụng sau khi WebSocket kết nối
        await ui.context.client.connected()

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

        await load_grid()


@ui.page("/handovers/new")
async def new_handover_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _sidebar("handovers")
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
    _sidebar("handovers")
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
    _sidebar("bundles")
    with _content_area():
        _page_header("Đóng chứng từ", "Tạo bìa chứng từ và quản lý")

        from datetime import date as _bd
        _today_b = _bd.today()

        current_user = api.get_current_user()
        is_admin = current_user and current_user.get("role") in ("admin", "hau_kiem_vien")

        await ui.context.client.connected()
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
                              on_click=lambda: load_groups()
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

                list_dept_sel.on("update:model-value",  lambda: load_groups())
                list_year_sel.on("update:model-value",  lambda: load_groups())
                list_month_sel.on("update:model-value", lambda: load_groups())
                await load_groups()

            # ── Tab 2: Tạo bìa ───────────────────────────────────────────────
            with ui.tab_panel(t_new):
                try:
                    depts, staff_list = await asyncio.gather(
                        asyncio.to_thread(api.get, "/api/departments/"),
                        asyncio.to_thread(api.get, "/api/staff/"),
                    )
                    depts = [d for d in depts if d.get("is_source")]
                except Exception:
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
                    def _ok_and_go():
                        success_dialog.close()
                        load_groups()
                        tabs.set_value(t_list)
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
                        _handle_api_error(e)
                        return
                    await _refresh_preview(grid_data)


# ─── STORAGE PAGE ─────────────────────────────────────────────────────────────
@ui.page("/storage")
async def storage_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return
    _sidebar("storage")
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
                    ED = "outline:none"  # contenteditable style

                    n_total = n_day + n_sh + 1
                    html = f"""<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif">
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
                        html += "<tr>"
                        for i in range(n_day):
                            v = str(r["days"][i]) if i < len(r["days"]) else ""
                            s = C if v else CE
                            html += f'<td contenteditable="true" style="{s};{ED}">{v}</td>'
                        for i in range(n_sh):
                            v = str(r["bundle_sheets"][i]) if i < len(r["bundle_sheets"]) else ""
                            s = C if v else CE
                            html += f'<td contenteditable="true" style="{s};{ED}">{v}</td>'
                        html += f'<td contenteditable="true" style="{C};font-weight:700;{ED}">{r["n_bundles"]}</td>'
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

                        with ui.row().classes("w-full justify-end mb-3"):
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
    _sidebar("")
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
