"""Trang Chấm ILO1000 — placeholder, sẽ bổ sung tính năng sau."""

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth,
)


@ui.page("/cham_ilo1000")
async def cham_ilo1000_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.cham_ilo1000"):
        ui.navigate.to("/home")
        return

    with ui.row().classes("w-full"):
        _sidebar("cham_ilo1000")
        with _content_area():
            _page_header("Chấm ILO1000", "Phòng Thanh toán")

            with ui.card().classes("w-full p-8 text-center"):
                ui.icon("construction").classes("text-5xl text-gray-300 mb-3")
                ui.label("Tính năng đang được phát triển").classes(
                    "text-base text-gray-400"
                )
