"""Trang đổi mật khẩu bắt buộc lần đầu đăng nhập."""
import asyncio
from nicegui import ui
import frontend.api_client as api
import frontend.ui_kit as ui_kit
from frontend.shared import _require_auth, _handle_api_error

# ─── CHANGE PASSWORD (bắt buộc lần đầu) ─────────────────────────────────────
@ui.page("/change-password")
async def change_password_page():
    if not _require_auth():
        return

    ui_kit.install()          # trang này không có sidebar nên phải tự gọi
    with ui.column().classes("w-full min-h-screen items-center justify-center bg-gradient-to-br from-red-900 to-red-700"):
        with ui.card().classes("w-96 p-8 shadow-2xl rounded-2xl bg-white"):
            with ui.column().classes("w-full items-center mb-6"):
                ui.image("/static/agribank_logo.png").classes("w-16 h-16 mb-2")
                ui.label("Đổi mật khẩu").classes("text-xl font-bold text-red-900")
                ui.label("Vui lòng đổi mật khẩu trước khi tiếp tục").classes("text-orange-600 text-sm font-semibold text-center")

            f_old = ui.input("Mật khẩu hiện tại", password=True, password_toggle_button=True).classes("w-full")
            f_new = ui.input("Mật khẩu mới", password=True, password_toggle_button=True).classes("w-full mt-3")
            f_confirm = ui.input("Xác nhận mật khẩu mới", password=True, password_toggle_button=True).classes("w-full mt-3")
            err_label = ui.label("").classes("text-red-500 text-sm mt-1")

            async def do_change():
                err_label.set_text("")
                if not f_old.value or not f_new.value or not f_confirm.value:
                    err_label.set_text("Vui lòng điền đầy đủ các trường")
                    return
                if f_new.value != f_confirm.value:
                    err_label.set_text("Mật khẩu xác nhận không khớp")
                    return
                try:
                    await asyncio.to_thread(api.post, "/api/auth/change-password", {
                        "old_password": f_old.value,
                        "new_password": f_new.value,
                    })
                    ui.notify("Đổi mật khẩu thành công!", type="positive")
                    user = api.get_current_user()
                    if user and user.get("role") == "chuyen_vien":
                        ui.navigate.to("/handovers")
                    else:
                        ui.navigate.to("/home")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    err_label.set_text(str(e))

            ui.button("Đổi mật khẩu", on_click=do_change).classes(
                "w-full mt-4 bg-red-700 text-white font-semibold py-3 rounded-lg hover:bg-red-800"
            )
            f_confirm.on("keydown.enter", do_change)
