"""
NiceGUI Frontend Application — Entry point
Truy cập: http://localhost:<FRONTEND_PORT> (mặc định 8080, xem .env)
"""
import sys, os
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT_DIR, ".env"), override=True)

# Fail fast — khoá ký cookie app.storage.user. Không fallback: giá trị đoán được
# cho phép forge cookie phiên đăng nhập. Cùng lý do với SECRET_KEY ở backend/core/config.py
STORAGE_SECRET = os.getenv("STORAGE_SECRET", "").strip()
if not STORAGE_SECRET:
    raise RuntimeError(
        "Biến môi trường STORAGE_SECRET chưa được đặt.\n"
        "Tạo key mạnh: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "Sau đó thêm vào file .env:  STORAGE_SECRET=<giá_trị_vừa_tạo>\n"
        "Lưu ý: đổi giá trị này sẽ đăng xuất toàn bộ người dùng đang đăng nhập."
    )

from nicegui import ui, app

# Serve static assets (logo, etc.)
app.add_static_files('/static', os.path.join(os.path.dirname(__file__), 'static'))

# Proxy /api/* sang backend nội bộ — máy trạm chỉ cần gọi đúng 1 cổng
# frontend, không cần cổng backend được mở ra ngoài (xem api_proxy.py)
import frontend.api_proxy  # noqa: E402,F401

# Import page modules — @ui.page decorators tự đăng ký route khi import
# Thêm page mới: chỉ cần tạo file frontend/pages/<tên>.py, không cần sửa file này
import importlib
import pkgutil
import frontend.pages as _pages_pkg

for _importer, _modname, _ispkg in pkgutil.iter_modules(_pages_pkg.__path__):
    importlib.import_module(f"frontend.pages.{_modname}")

# Re-export shared utilities để giữ backward compat với các import từ bên ngoài
from frontend.shared import (           # noqa: F401
    _sidebar, _content_area, _page_header, _card,
    _require_auth, _redirect_if_cv, _handle_api_error,
    DEPARTMENTS, MENU_ITEMS_CV, COLORS,
)

def _on_exception(e: Exception):
    import logging, traceback
    logging.getLogger("nicegui.crash").error("Unhandled UI exception:\n%s", traceback.format_exc())


if __name__ in {"__main__", "__mp_main__"}:
    if hasattr(ui, "on_exception"):
        ui.on_exception(_on_exception)
    ui.run(
        host="0.0.0.0",
        port=int(os.getenv("FRONTEND_PORT", "8080")),
        title="PAYMENT CENTER",
        favicon="🏦",
        dark=False,
        reload=False,
        show=False,
        storage_secret=STORAGE_SECRET,
        reconnect_timeout=30,
    )
