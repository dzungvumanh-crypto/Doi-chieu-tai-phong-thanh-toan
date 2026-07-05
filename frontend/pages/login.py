"""Trang đăng nhập."""
import asyncio
from datetime import datetime
from nicegui import ui, app
import frontend.api_client as api
from starlette.requests import Request as _StarletteRequest

_LOGIN_CSS = """
<style>
/* ── Nền đỏ sẫm + hoạ tiết trang trí (phương án A) ──────────────────── */
html, body { background: #6E0F14 !important; }

.pc-bg { position: fixed; inset: 0; overflow: hidden; z-index: 0; pointer-events: none; }
.pc-bg::before {                     /* hình tròn sáng — góc trên phải */
  content: ""; position: absolute; top: -120px; right: -120px;
  width: 340px; height: 340px; border-radius: 50%;
  background: rgba(255, 255, 255, 0.05);
}
.pc-bg::after {                      /* hình tròn tối — góc dưới trái */
  content: ""; position: absolute; bottom: -160px; left: -100px;
  width: 400px; height: 400px; border-radius: 50%;
  background: rgba(0, 0, 0, 0.12);
}
.pc-ring {                           /* vòng tròn viền mảnh — mép trái */
  position: absolute; top: 38%; left: -60px;
  width: 180px; height: 180px; border-radius: 50%;
  border: 1.5px solid rgba(255, 255, 255, 0.08);
}

/* Thanh vàng đồng Agribank trên đỉnh trang */
.pc-topbar {
  position: fixed; top: 0; left: 0; right: 0; height: 4px;
  background: #C9A227; z-index: 2; pointer-events: none;
}

/* Viền card đăng nhập — nội dung bên trong giữ nguyên */
.pc-card { border: 1px solid #C9A227 !important; }

.pc-footer { color: rgba(255, 255, 255, 0.55); font-size: 12px; }
</style>
"""


@ui.page("/login")
async def login_page(request: _StarletteRequest):
    # Ưu tiên request.client.host (TCP connection trực tiếp từ browser đến NiceGUI server).
    # X-Forwarded-For chỉ dùng khi client là loopback — tức đang đứng sau một reverse proxy.
    _direct_ip = request.client.host if request.client else ""
    if _direct_ip and _direct_ip not in ("127.0.0.1", "::1", "localhost"):
        client_ip = _direct_ip
    else:
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.headers.get("X-Real-IP", "").strip()
            or _direct_ip
            or "unknown"
        )
    reason = request.query_params.get("reason", "")

    ui.add_head_html('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">')
    ui.add_head_html(_LOGIN_CSS)

    # Hoạ tiết nền (phương án A) — nằm dưới nội dung, không nhận sự kiện chuột
    ui.element("div").classes("pc-topbar")
    with ui.element("div").classes("pc-bg"):
        ui.element("div").classes("pc-ring")

    # bg-red-900 đặt trực tiếp trên container nội dung để đảm bảo hiển thị
    # ngay cả khi lớp bọc của NiceGUI/Quasar phủ nền riêng lên trên <body>.
    with ui.column().classes("w-full min-h-screen items-center justify-center bg-red-900").style(
        "position: relative; z-index: 1; background: #6E0F14;"
    ):
        with ui.card().classes("w-96 p-8 shadow-2xl rounded-2xl bg-white pc-card"):
            with ui.column().classes("w-full items-center mb-6"):
                ui.image("/static/agribank_logo.png").classes("w-24 h-24 mb-2")
                ui.label("PAYMENT CENTER").classes("text-2xl font-bold text-red-900")

            if reason == "displaced":
                with ui.row().classes(
                    "w-full items-center gap-2 mb-3 px-3 py-2 "
                    "bg-orange-50 border border-orange-300 rounded-lg"
                ):
                    ui.icon("warning").classes("text-orange-500 text-lg shrink-0")
                    ui.label("Tài khoản này đang được đăng nhập từ thiết bị khác").classes(
                        "text-sm text-orange-700 font-medium leading-snug"
                    )

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
                    await asyncio.to_thread(api.load_my_features)
                    app.storage.tab["session_alive"] = True
                    if result.get("must_change_password"):
                        ui.navigate.to("/change-password")
                    elif result["role"] == "chuyen_vien" and api.has_feature("menu.handovers"):
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

        ui.label(f"© {datetime.now().year} Agribank · Trung tâm Thanh toán").classes("pc-footer mt-5")
