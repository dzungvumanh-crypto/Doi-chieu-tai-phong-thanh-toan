"""Màn hình theo dõi việc đang chờ xử lý — mở từ khối "Công việc chờ xử lý" trên sidebar.

Một file, hai loại việc (/pending/handovers, /pending/leaves): cùng bố cục bảng +
cùng cách nạp dữ liệu, chỉ khác định nghĩa cột và cách dẫn tới màn hình thao tác.
"""
import asyncio
from nicegui import ui
import frontend.api_client as api
import frontend.ui_kit as ui_kit
from frontend.shared import (_sidebar, _content_area, _page_header, _require_auth,
                             _handle_api_error, _dmy)

_ACT_W = "w-36"     # cột nút cuối — header và ô dữ liệu phải cùng bề rộng mới thẳng cột

# kind → (nhãn trang, mô tả, khoá feature, key trong /pending-items)
_KINDS = {
    "handovers": ("Chứng từ chờ xác nhận",
                  "Danh sách chứng từ chờ xác nhận",
                  "menu.handovers"),
    "leaves":    ("Đơn nghỉ phép chờ duyệt",
                  "Danh sách đơn đang chờ đến lượt bạn xử lý",
                  "menu.leaves"),
}

# Viền ngang đặt trên HÀNG, không trên từng ô: ui.row() mặc định có gap 1rem
# (--nicegui-default-gap) nên viền theo ô sẽ đứt quãng đúng chỗ khoảng hở. Hai hàng
# đều phải gap-0 thì cột mới thẳng và đường kẻ mới liền.
_ROW  = "w-full flex-nowrap gap-0"
_TH   = "px-3 py-2 text-left text-xs font-semibold text-red-800 whitespace-nowrap"
_TD   = "px-3 py-2 text-sm text-gray-700 align-middle"


def _cols(kind: str) -> list[str]:
    if kind == "handovers":
        return ["Ngày chứng từ", "Phòng nghiệp vụ", "Chứng từ của", "Số lượng",
                "Người nộp", "Ngày bàn giao", "Ghi chú", ""]
    return ["Người xin nghỉ", "Phòng", "Loại phép", "Từ ngày", "Đến ngày",
            "Lý do", "Trạng thái", ""]


def _render_row(kind: str, it: dict):
    """Một hàng dữ liệu + nút chuyển tới nơi thao tác ở cuối hàng."""
    if kind == "handovers":
        cells = [
            (_dmy(it["transaction_date"]), "font-medium text-gray-900 whitespace-nowrap"),
            (it["dept_name"], ""),
            (f'{it["staff_name"]}' + (f' · {it["staff_code"]}' if it["staff_code"] else ""), ""),
            (f'{it["sheet_count"]:,}', "font-semibold text-blue-800"),
            (it["entered_by_name"] or "—", ""),
            (_dmy(it.get("submit_date")) or "—", "whitespace-nowrap"),
            (it["notes"] or "—", "text-xs text-gray-500 max-w-[16rem] truncate"),
        ]
    else:
        cells = [
            (f'{it["staff_name"]}' + (f' · {it["staff_code"]}' if it["staff_code"] else ""),
             "font-medium text-gray-900"),
            (it["dept_name"] or "—", ""),
            (ui_kit.LEAVE_TYPE.get(it["leave_type"], it["leave_type"]), "whitespace-nowrap"),
            (_dmy(it["start_date"]), "whitespace-nowrap"),
            (_dmy(it["end_date"]), "whitespace-nowrap"),
            (it["reason"] or "—", "text-xs text-gray-500 max-w-[16rem] truncate"),
        ]

    with ui.row().classes(f"{_ROW} items-stretch border-b border-gray-100 hover:bg-red-50"):
        for text, extra in cells:
            ui.label(str(text)).classes(f"{_TD} flex-1 min-w-0 {extra}")
        # Cột trạng thái riêng cho nghỉ phép (dùng chip màu thay vì chữ trơn)
        if kind == "leaves":
            with ui.element("div").classes(f"{_TD} flex-1 min-w-0 flex items-center"):
                ui_kit.status_chip(it["status"])
        with ui.element("div").classes(f"{_TD} shrink-0 {_ACT_W} flex items-center"):
            ui.button("Tới nơi xử lý", icon="open_in_new",
                      on_click=lambda i=it: _goto(kind, i)
                      ).props("dense no-caps").classes("bg-red-700 text-white text-xs px-3")


def _goto(kind: str, it: dict):
    """Chuyển sang màn hình thao tác, mang theo đủ tham số để dừng đúng chỗ."""
    if kind == "handovers":
        # entry là chìa để lưới tự cuộn tới và tô sáng đúng ô (input mang data-eid)
        ui.navigate.to(f'/handovers?dept={it["dept_id"]}&year={it["year"]}'
                       f'&month={it["month"]}&entry={it["entry_id"]}')
    else:
        from nicegui import app
        app.storage.user["_leaves_goto"] = (
            "pending_th" if it["status"] == "pending_tong_hop" else "pending"
        )
        app.storage.user["_leaves_focus"] = it["id"]
        ui.navigate.to("/leaves")


@ui.page("/pending/{kind}")
async def pending_work_page(kind: str):
    if not _require_auth():
        return
    if kind not in _KINDS:
        ui.navigate.to("/home")
        return

    title, subtitle, feature = _KINDS[kind]
    if not api.has_feature(feature):
        ui.navigate.to("/home")
        return

    _sidebar(kind)      # giữ mục nghiệp vụ tương ứng ở trạng thái đang chọn
    with _content_area():
        _page_header(title, subtitle)

        body = ui.column().classes("w-full gap-0")
        with body:
            ui_kit.skeleton_rows(6)

        try:
            await ui.context.client.connected()
        except Exception:
            pass

        try:
            data = await asyncio.to_thread(api.get, "/api/dashboard/pending-items")
        except Exception as e:
            body.clear()
            with body:
                if not _handle_api_error(e):
                    ui.label("Không tải được danh sách.").classes("text-red-600 text-sm py-4")
            return

        items = (data or {}).get(kind) or []
        body.clear()
        with body:
            if not items:
                ui_kit.empty_state("Không còn việc nào chờ xử lý", "task_alt",
                                   "Danh sách sẽ tự có khi phát sinh việc mới")
                return

            ui.label(f"{len(items)} việc đang chờ").classes("text-sm text-gray-500 mb-3")
            with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden "
                                   "border border-gray-200"):
                with ui.column().classes("w-full gap-0 overflow-x-auto"):
                    # Header — cùng cấu trúc flex với hàng dữ liệu để các cột thẳng nhau
                    with ui.row().classes(f"{_ROW} bg-red-50 border-b-2 border-red-200"):
                        for c in _cols(kind):
                            cls = f"{_TH} shrink-0 {_ACT_W}" if c == "" else f"{_TH} flex-1 min-w-0"
                            ui.label(c).classes(cls)
                    for it in items:
                        _render_row(kind, it)
