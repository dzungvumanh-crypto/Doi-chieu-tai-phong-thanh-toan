"""
NiceGUI Frontend Application — Entry point
Truy cập: http://localhost:8080
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from nicegui import ui, app

# Serve static assets (logo, etc.)
app.add_static_files('/static', os.path.join(os.path.dirname(__file__), 'static'))

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
        port=8080,
        title="PAYMENT CENTER",
        favicon="🏦",
        dark=False,
        reload=False,
        show=False,
        storage_secret="ksnb-htvh-agribank-2025",
        reconnect_timeout=30,
    )
