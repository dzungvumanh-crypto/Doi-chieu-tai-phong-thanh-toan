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
import frontend.pages.login           # noqa: F401
import frontend.pages.dashboard       # noqa: F401
import frontend.pages.staff           # noqa: F401
import frontend.pages.handovers       # noqa: F401
import frontend.pages.bundles         # noqa: F401
import frontend.pages.storage         # noqa: F401
import frontend.pages.user_management # noqa: F401
import frontend.pages.leaves          # noqa: F401
import frontend.pages.logs            # noqa: F401
import frontend.pages.change_password # noqa: F401
import frontend.pages.reports         # noqa: F401

# Re-export shared utilities để giữ backward compat với các import từ bên ngoài
from frontend.shared import (           # noqa: F401
    _sidebar, _content_area, _page_header, _card,
    _require_auth, _redirect_if_cv, _handle_api_error,
    MENU_ITEMS, MENU_ITEMS_CV, COLORS,
)

if __name__ in {"__main__", "__mp_main__"}:
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
