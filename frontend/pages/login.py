"""Trang đăng nhập."""
import asyncio
from datetime import datetime
from nicegui import ui, app
import frontend.api_client as api
import frontend.ui_kit as ui_kit
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

/* Chrome/Edge tô nền xanh #E8F0FE cho ô vừa được điền hộ từ mật khẩu đã lưu.
   background-color không đè được — trình duyệt khoá thuộc tính đó. Cách duy
   nhất là phủ một bóng đổ trắng dày vào bên trong ô. Chỉ áp trong card login. */
.pc-card input:-webkit-autofill,
.pc-card input:-webkit-autofill:hover,
.pc-card input:-webkit-autofill:focus,
.pc-card input:-webkit-autofill:active {
  -webkit-box-shadow: 0 0 0 1000px #FFFFFF inset !important;
          box-shadow: 0 0 0 1000px #FFFFFF inset !important;
  -webkit-text-fill-color: #1A1A2E !important;
  caret-color: #1A1A2E;
  transition: background-color 9999s ease-in-out 0s;  /* chặn nháy xanh lúc tải */
}

.pc-footer { color: rgba(255, 255, 255, 0.55); font-size: 12px; }

/* ── Cột đường dẫn nhanh hai bên card ───────────────────────────────── */
/* Ba số đo dưới đây khoá toàn bộ layout. Mọi hàng cao đúng --pc-row, tiêu đề
   nhóm cao đúng --pc-head → hàng trái và hàng phải luôn ngang nhau. */
.pc-links {
  --pc-row: 44px;      /* chiều cao một hàng link */
  --pc-head: 38px;     /* tiêu đề nhóm (30px) + khoảng cách dưới (8px) */
  --pc-pad: 14px;      /* padding trên/dưới của panel */
  --pc-bd: 1px;        /* viền panel */
  gap: 0 !important;
}
/* Khoảng cách giữa 2 panel cột phải KHÔNG viết ở đây — nó phụ thuộc số link
   mỗi nhóm nên được tính bằng Python, xem _split_gap_css() phía dưới. */

.pc-panel {
  padding: var(--pc-pad) 12px;
  border-radius: 14px;
  border: var(--pc-bd) solid rgba(255, 255, 255, 0.13);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.09), rgba(255, 255, 255, 0.03));
  box-shadow: 0 6px 22px rgba(0, 0, 0, 0.18);
  transition: border-color 0.25s, box-shadow 0.25s, background 0.25s;
  animation: pc-rise 0.5s ease-out both;
}
.pc-panel:hover {
  border-color: rgba(201, 162, 39, 0.55);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.30);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.13), rgba(255, 255, 255, 0.05));
}
@keyframes pc-rise {
  from { opacity: 0; transform: translateY(14px); }
  to   { opacity: 1; transform: none; }
}

/* Tiêu đề nhóm — box-sizing: border-box nên height đã gồm padding + viền */
.pc-phead {
  height: 30px; margin-bottom: 8px;
  display: flex; align-items: center; gap: 8px;
  padding: 0 4px 6px;
  color: #E8C75A; font-size: 14.5px; font-weight: 700;
  letter-spacing: 0.075em; text-transform: uppercase;
  border-bottom: 1px solid rgba(201, 162, 39, 0.35);
}
.pc-phead .q-icon { font-size: 20px; color: #E8C75A; }

.pc-link {
  height: var(--pc-row);
  display: flex; align-items: center; gap: 7px;
  color: rgba(255, 255, 255, 0.85) !important;
  font-size: 17.5px; text-decoration: none !important;
  padding: 0 12px 0 7px; border-radius: 8px;
  white-space: nowrap;
  transition: background 0.18s, color 0.18s, transform 0.18s;
}
.pc-link::before {                   /* mũi nhọn dẫn hướng, sáng lên khi rê chuột */
  content: "›"; font-size: 22px; font-weight: 700; line-height: 1;
  color: rgba(201, 162, 39, 0.5);
  transition: color 0.18s, transform 0.18s;
}
.pc-link:hover {
  color: #FFFFFF !important; background: rgba(255, 255, 255, 0.12);
  transform: translateX(4px);
}
.pc-link:hover::before { color: #E8C75A; transform: translateX(2px); }
</style>
"""

# Nhóm đường dẫn: (tiêu đề, icon, [mục...]). Mỗi mục là URL trần (hiện nguyên
# URL) hoặc cặp (tên hiển thị, URL) — có tên thì URL đầy đủ nằm ở tooltip.
# Số hàng của mỗi nhóm quyết định layout — xem công thức --pc-* ở CSS.
_GROUP_DOMESTIC = ("Thanh toán trong nước", "account_balance", [
    ("Hệ thống Thanh toán tập trung",   "https://payment.agribank.com.vn"),
    ("Trục thanh toán - Payment Hub",   "https://paymenthub.agribank.com.vn"),
    ("Hệ thống TT ĐTLNH - Cổng 1",      "http://10.0.85.100/CITAD001"),
    ("Hệ thống TT ĐTLNH - Cổng 9",      "http://10.0.85.100/CITAD"),
    ("Hệ thống TT ĐTLNH - Cổng 12",     "http://10.0.85.100/CITAD9212"),
    ("Hệ thống TT ĐTLNH - Cổng 17",     "http://10.0.85.100/CITAD7917"),
    ("Hệ thống TT ĐTLNH - Cổng 18",     "http://10.0.85.100/CITAD4818"),
    ("Hệ thống TTSP 247",               "http://10.0.0.16"),
    ("Hệ thống Song phương realtime",   "http://10.0.0.17"),
    ("Hệ thống Open SmartBank",         "https://osb.agribank.com.vn"),
])

_GROUP_INTL = ("Thanh toán quốc tế", "public", [
    ("Hệ thống Thanh toán quốc tế tập trung", "https://swifthub.agribank.com.vn"),
    ("Trục Thanh toán quốc tế - SWIFT",       "https://swiftadmin.agribank.com.vn"),
])

_GROUP_INTERNAL = ("Nội bộ", "apartment", [
    ("Mail Agribank",                       "https://mail.agribank.com.vn"),
    ("Hệ thống Văn phòng điện tử - Ioffice", "https://ioffice.agribank.com.vn"),
    ("Hệ thống Quản lý công việc",          "http://qlcv.agribank.com.vn"),
    ("Hệ thống E-learning",                 "https://elearning.agribank.com.vn"),
])


def _split_gap_css() -> str:
    """Khoảng cách giữa 2 panel cột phải, tính từ chính số link mỗi nhóm.

    Một giá trị duy nhất thoả cùng lúc 2 điều kiện, vì cả hai quy về cùng một
    phương trình:  G = (n_trái − n_phải_trên − n_phải_dưới)·row − head − 2·pad − 2·viền
      1. Hai cột cao bằng nhau → items-center không làm lệch
      2. Hàng đầu của panel dưới bên phải khớp đúng một hàng bên trái
    Tính bằng Python thay vì viết số cứng trong CSS: thêm/bớt link ở bất kỳ
    nhóm nào cũng tự khớp lại, không phải nhớ sửa hệ số.
    """
    n = len(_GROUP_DOMESTIC[2]) - len(_GROUP_INTL[2]) - len(_GROUP_INTERNAL[2])
    return (
        "<style>.pc-links--split { gap: calc("
        f"{n} * var(--pc-row) - var(--pc-head)"
        " - 2 * var(--pc-pad) - 2 * var(--pc-bd)) !important; }</style>"
    )


def _link_column(groups: list[tuple], order_cls: str, extra_cls: str = "") -> None:
    """Một cột nhóm đường dẫn, tự căn giữa khoảng trống bên cạnh card."""
    with ui.element("div").classes(
        f"flex-1 flex justify-center min-w-[380px] {order_cls}"
    ):
        with ui.column().classes(f"pc-links w-auto items-stretch {extra_cls}"):
            for i, (title, icon, urls) in enumerate(groups):
                with ui.element("div").classes("pc-panel w-full").style(
                    f"animation-delay: {0.08 * i:.2f}s"
                ):
                    with ui.element("div").classes("pc-phead"):
                        ui.icon(icon)
                        ui.label(title)
                    for item in urls:
                        label, url = item if isinstance(item, tuple) else (item, item)
                        link = ui.link(label, url, new_tab=True).classes("pc-link")
                        if label != url:
                            link.tooltip(url)


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

    ui_kit.install()          # trang này không có sidebar nên phải tự gọi
    ui.add_head_html(_LOGIN_CSS)
    ui.add_head_html(_split_gap_css())

    # Hoạ tiết nền (phương án A) — nằm dưới nội dung, không nhận sự kiện chuột
    ui.element("div").classes("pc-topbar")
    with ui.element("div").classes("pc-bg"):
        ui.element("div").classes("pc-ring")

    # bg-red-900 đặt trực tiếp trên container nội dung để đảm bảo hiển thị
    # ngay cả khi lớp bọc của NiceGUI/Quasar phủ nền riêng lên trên <body>.
    with ui.column().classes("w-full min-h-screen items-center justify-center bg-red-900").style(
        "position: relative; z-index: 1; background: #6E0F14;"
    ):
        # Card giữ nguyên bề rộng ở giữa; hai cột link chiếm phần còn lại và tự
        # căn giữa khoảng trống của mình. Màn hẹp: card lên trước (order-1).
        with ui.row().classes(
            "w-full items-center justify-center flex-wrap px-4"
        ).style("gap: 16px;"):
            _link_column([_GROUP_DOMESTIC], "order-2 lg:order-1")

            with ui.card().classes(
                "w-96 shrink-0 p-8 shadow-2xl rounded-2xl bg-white pc-card order-1 lg:order-2"
            ):
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
                        # Mọi vai trò đều đáp xuống Trang chủ — một điểm vào duy nhất.
                        if result.get("must_change_password"):
                            ui.navigate.to("/change-password")
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

            _link_column([_GROUP_INTL, _GROUP_INTERNAL], "order-3", "pc-links--split")

        ui.label(f"© {datetime.now().year} Agribank · Trung tâm Thanh toán").classes("pc-footer mt-5")
