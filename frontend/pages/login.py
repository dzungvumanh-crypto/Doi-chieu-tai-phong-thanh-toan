"""Trang đăng nhập."""
import asyncio
from nicegui import ui, app
import frontend.api_client as api
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
                ui.label("PAYMENT CENTER").classes("text-2xl font-bold text-red-900")

            username = ui.input("Tên đăng nhập", placeholder="admin").classes("w-full")
            password = ui.input("Mật khẩu", password=True, password_toggle_button=True).classes("w-full mt-3")
            err_label = ui.label("").classes("text-red-500 text-sm mt-1")

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
                    if result.get("must_change_password"):
                        ui.navigate.to("/change-password")
                    elif result["role"] == "chuyen_vien":
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
