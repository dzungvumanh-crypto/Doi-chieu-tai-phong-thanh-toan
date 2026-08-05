"""Trang quản lý người dùng — đổi mật khẩu."""
import asyncio
from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _redirect_if_cv


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
                ui.label("Chỉ Quản trị viên mới thấy mục này").classes("text-xs text-gray-500 mb-4")

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

                ar_user = ui.select(
                    staff_options,
                    label="Chọn người dùng",
                    with_input=True,
                ).classes("w-full")
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
