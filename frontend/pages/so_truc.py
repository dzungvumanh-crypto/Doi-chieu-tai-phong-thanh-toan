"""Trang Sổ trực cuối ngày — Phòng Thanh toán.

Luồng nghiệp vụ đầy đủ xem docstring ở `backend/services/so_truc_service.py`.
Giao diện đổi hoàn toàn theo `status` trả về từ API, KHÔNG theo role cứng —
cùng 1 người có thể vừa nhập vai GDV vừa nằm trong nhóm KSV, nên phải xét
đúng trạng thái bản ghi (ai là `initiated_by`, có feature `so_truc.ksv_confirm`
hay không) để quyết định nút nào hiện ra, backend luôn là nơi chốt quyền thật.
"""
import asyncio
import datetime
from urllib.parse import quote

from nicegui import ui
from starlette.requests import Request as _StarletteRequest
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _require_auth, _handle_api_error

# Card/header kiểu "modern SaaS" giống hệt frontend/pages/doi_chieu_citad.py
# (copy nguyên — mỗi trang muốn kiểu này TỰ ĐỊNH NGHĨA local theo đúng
# convention đã ghi trong doi_chieu_citad.py, KHÔNG sửa frontend/shared.py
# dùng chung để tránh ảnh hưởng các trang khác).
_ACCENT = {
    "blue": ("bg-blue-50", "text-blue-600", "border-blue-100", "bg-blue-50/40"),
    "indigo": ("bg-indigo-50", "text-indigo-600", "border-indigo-100", "bg-indigo-50/40"),
    "emerald": ("bg-emerald-50", "text-emerald-600", "border-emerald-100", "bg-emerald-50/40"),
    "amber": ("bg-amber-50", "text-amber-600", "border-amber-100", "bg-amber-50/40"),
    "rose": ("bg-rose-50", "text-rose-600", "border-rose-100", "bg-rose-50/40"),
}


def _navy_header(title: str, subtitle: str = ""):
    with ui.column().classes("w-full bg-blue-950 rounded-2xl px-6 py-4 mb-4 gap-0.5"):
        ui.label(title).classes("text-xl font-bold text-white tracking-wide")
        if subtitle:
            ui.label(subtitle).classes("text-blue-200 text-sm")


def _section_card(title: str, icon: str = "table_chart", accent: str = "blue", outer_border: str = "border border-gray-200"):
    bg, text, border, wash = _ACCENT.get(accent, _ACCENT["blue"])
    card = ui.card().classes(
        f"w-full rounded-2xl {outer_border} shadow-sm hover:shadow-md "
        f"transition-shadow duration-200 {wash} p-0 overflow-hidden"
    )
    with card:
        with ui.row().classes(f"w-full items-center gap-3 px-5 py-4 border-b {border} bg-gray-50/60"):
            with ui.row().classes(f"items-center justify-center w-9 h-9 rounded-xl {bg} shrink-0"):
                ui.icon(icon).classes(f"{text} text-lg")
            ui.label(title).classes("font-semibold text-gray-800 text-[15px]")
    return card


_STATUS_LABEL = {
    "draft": ("Đang lập", "grey-6"),
    "pending_ksv": ("Chờ KSV duyệt", "blue-7"),
    "approved": ("Hoàn thành", "green-7"),
    "cancelled": ("Đã huỷ", "red-7"),
}


def _status_badge(status: str):
    label, color = _STATUS_LABEL.get(status, (status, "grey-6"))
    ui.badge(label, color=color).classes("text-sm px-3 py-1")


def _iso_to_ddmmyyyy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def _ddmmyyyy_to_iso(dmy: str) -> str:
    d, m, y = dmy.split("/")
    return f"{y}-{m}-{d}"


def _iso_dt_to_ddmmyyyy(dt_str: str) -> str:
    """'2026-08-17 10:35:45.031208' -> '17/08/2026 10:35:45' (bỏ micro-giây)."""
    if not dt_str:
        return dt_str
    date_part, _, time_part = dt_str.partition(" ")
    try:
        dmy = _iso_to_ddmmyyyy(date_part)
    except ValueError:
        return dt_str
    time_part = time_part.split(".")[0]
    return f"{dmy} {time_part}" if time_part else dmy


def _date_picker_input(label: str, initial: str = None):
    """Ô nhập ngày HIỂN THỊ dd/mm/yyyy — thống nhất với header "Sổ trực
    ngày DD/MM/YYYY" ngay bên dưới, các dòng Lịch sử, và với
    `doi_chieu_citad.py::_date_picker_input` (trước đây ô này hiển thị
    ISO YYYY-MM-DD, lệch với phần còn lại của trang). `initial` truyền
    vào/trả về từ nơi gọi vẫn ở ISO (khớp `truc_date` lưu DB, deep-link
    `?ngay=`) — convert 2 chiều bằng `_iso_to_ddmmyyyy()`/`_ddmmyyyy_to_iso()`
    ngay tại đây và tại nơi gọi, KHÔNG đổi định dạng lưu trữ nội bộ.

    Dùng `.bind_value(date_input)` giữa `ui.date` và ô nhập — đã test A/B
    trực tiếp bằng script cô lập (không dính gì tới phần còn lại của trang):
    bản `on_change` một chiều (tự set `date_input.value` trong callback,
    không bind) làm menu lịch TỰ MỞ và chặn pointer event trên toàn bộ
    trang (Quasar báo "q-portal--menu intercepts pointer events"), gõ tay
    bị kẹt cứng sau 1 ký tự. Bản `.bind_value()` KHÔNG bị lỗi đó, test
    xong không phát sinh vấn đề gì mới. Rủi ro lý thuyết của `.bind_value()`
    (đồng bộ ngược ghi đè giá trị gõ tay, xem lịch sử ở
    `_date_filter_input` bên doi_chieu_citad.py) không xảy ra ở đây vì
    không có nơi nào khác ghi trực tiếp vào `date_input.value` bằng Python."""
    initial_dmy = _iso_to_ddmmyyyy(initial or datetime.date.today().isoformat())
    with ui.input(label, value=initial_dmy).props("dense outlined").classes("w-44") as date_input:
        with date_input.add_slot("append"):
            ui.icon("edit_calendar").on("click", lambda: menu.open()).classes("cursor-pointer")
        with ui.menu() as menu:
            ui.date(value=initial_dmy, mask="DD/MM/YYYY", on_change=menu.close).bind_value(date_input)
    return date_input


def _date_filter_input(label: str):
    """Ô lọc theo ngày cho tab Lịch sử — HIỂN THỊ dd/mm/yyyy (trước đây ISO
    YYYY-MM-DD, lệch với `_date_picker_input` ở trên và các dòng Lịch sử).
    Nơi gọi phải tự convert bằng `_ddmmyyyy_to_iso()` trước khi dùng giá trị
    ô này để gọi API (`tu_ngay`/`den_ngay` lưu ISO). RỖNG mặc định như
    `doi_chieu_citad.py::_date_filter_input` — xem docstring ở đó về lý do
    không truyền `value=` ban đầu cho `ui.date` (tránh bug đồng bộ ngược của
    `.bind_value()` khi có giá trị khởi tạo)."""
    with ui.input(label, value="").props("dense outlined clearable").classes("w-44") as date_input:
        with date_input.add_slot("append"):
            ui.icon("edit_calendar").on("click", lambda: menu.open()).classes("cursor-pointer")
        with ui.menu() as menu:
            ui.date(mask="DD/MM/YYYY", on_change=menu.close).bind_value(date_input)
    return date_input


@ui.page("/so_truc")
async def so_truc_page(request: _StarletteRequest):
    if not _require_auth():
        return
    if not api.has_feature("menu.so_truc"):
        ui.navigate.to("/home")
        return

    current_user = api.get_current_user()
    my_id = current_user.get("id") if current_user else None
    is_ksv = api.has_feature("so_truc.ksv_confirm")

    # Deep-link từ khối "Công việc chờ xử lý" (/pending/so_truc) — mở thẳng
    # đúng ngày đang chờ mình xử lý, khỏi phải tự gõ lại ngày trên form.
    # truc_date đã là YYYY-MM-DD (ISO) nên không cần convert như doi_chieu_citad.
    deep_link_ngay = request.query_params.get("ngay")

    # Cùng cơ chế "gán qua dict" như history_refresh của doi_chieu_citad.py —
    # mọi hành động lưu/duyệt gọi lại refresh tab Lịch sử mà không chuyển tab.
    history_refresh = {"fn": None}
    state = {"ngay": deep_link_ngay or datetime.date.today().isoformat()}

    def _result_link_block(ngay: str):
        with ui.row().classes("items-center gap-2 mt-3"):
            ui.icon("link", color="indigo").classes("text-lg")
            ui.label("Kết quả trực:").classes("text-sm font-medium text-gray-600")
            ngay_hien_thi = _iso_to_ddmmyyyy(ngay)
            link = f"/doi_chieu_citad?ngay={quote(ngay_hien_thi)}"
            ui.button(
                f"Xem lịch sử chấm CITAD ngày {ngay_hien_thi}", icon="open_in_new",
                on_click=lambda: ui.navigate.to(link, new_tab=True),
            ).props("flat dense color=indigo")

    def _render_readonly_summary(rec: dict):
        # So khớp BẰNG ID (gdv1_id/gdv2_id với initiated_by/confirmed_by),
        # KHÔNG so tên — user_tttt.full_name không có ràng buộc UNIQUE, 2
        # người trùng tên so tên sẽ gắn nhầm dấu ✓ cho người không thao tác.
        # Không khớp (vd người thứ 3 có quyền thao tác hộ — hiếm, do bản đầu
        # chưa tích hợp Phân lịch trực) thì không chấm, 2 dòng chi tiết bên
        # dưới vẫn hiện tên thật của người thao tác nên không mất thông tin.
        # Mỗi trường (GDV1/GDV2/KSV/Ghi chú) 1 Ô RIÊNG (nền xám nhạt + viền) —
        # trước đây GDV1/GDV2/KSV chỉ là dòng chữ trần xếp chồng lên nhau,
        # khó phân biệt field nào với field nào khi liếc nhanh; GHI CHÚ đã có
        # khung riêng từ trước, nay áp dụng ĐỒNG BỘ kiểu khung đó cho cả 3
        # field còn lại — TẤT CẢ cùng viền đỏ đô (border-red-800) theo yêu
        # cầu, không còn tách riêng xám/đỏ như trước nữa.
        def _info_box(label: str, extra_cls: str = ""):
            box = ui.column().classes(
                f"gap-0.5 p-3 rounded-lg bg-gray-50 border-2 border-red-800 {extra_cls}"
            )
            with box:
                ui.label(label).classes("text-[11px] font-semibold text-gray-400 tracking-wide")
            return box

        def _gdv_box(label: str, name: str, gdv_id):
            with _info_box(label, "flex-1"):
                with ui.row().classes("items-center gap-1"):
                    ui.label(name or "—").classes("text-sm text-gray-700 font-medium")
                    if gdv_id and gdv_id == rec.get("initiated_by"):
                        ui.icon("check_circle", color="green").classes("text-base").tooltip(
                            f"Đã bấm \"Chuyển KSV xác nhận\" lúc {_iso_dt_to_ddmmyyyy(rec.get('initiated_at')) or ''}"
                        )
                        ui.label("đã xác nhận").classes("text-xs text-gray-400 italic")
                    elif gdv_id and gdv_id == rec.get("confirmed_by"):
                        ui.icon("check_circle", color="green").classes("text-base").tooltip(
                            f"Đã bấm \"Xác nhận phiên trực\" lúc {_iso_dt_to_ddmmyyyy(rec.get('confirmed_at')) or ''}"
                        )
                        ui.label("đã xác nhận").classes("text-xs text-gray-400 italic")

        with ui.column().classes(
            "w-full gap-2 p-4 rounded-xl bg-white border border-gray-200 shadow-sm"
        ):
            with ui.row().classes("w-full gap-2"):
                _gdv_box("GDV 1", rec.get("gdv1_name"), rec.get("gdv1_id"))
                _gdv_box("GDV 2", rec.get("gdv2_name"), rec.get("gdv2_id"))
            with _info_box("KSV ĐƯỢC CHỌN"):
                ui.label(rec.get("ksv_name") or "—").classes("text-sm text-gray-700 font-medium")
            with _info_box("TRỰC PHỤ"):
                names = rec.get("truc_phu_names") or []
                ui.label(", ".join(names) if names else "—").classes("text-sm text-gray-700 font-medium")
            with ui.column().classes(
                "w-full gap-0.5 p-3 rounded-lg bg-gray-50 border-2 border-red-800"
            ):
                ui.label("GHI CHÚ").classes(
                    "text-[11px] font-semibold text-gray-400 tracking-wide"
                )
                ui.label(rec.get("ghi_chu") or "—").classes(
                    "text-sm text-gray-700 whitespace-pre-wrap"
                )
            if rec.get("initiated_by_name"):
                ui.label(
                    f"Người chuyển KSV xác nhận: {rec['initiated_by_name']} lúc "
                    f"{_iso_dt_to_ddmmyyyy(rec.get('initiated_at')) or ''}"
                ).classes("text-xs text-gray-400")
            if rec.get("confirmed_by_name"):
                ui.label(
                    f"Người xác nhận phiên trực: {rec['confirmed_by_name']} lúc "
                    f"{_iso_dt_to_ddmmyyyy(rec.get('confirmed_at')) or ''}"
                ).classes("text-xs text-gray-400")

    async def _reload_main():
        await load_day(state["ngay"])

    async def load_day(ngay: str, notify_if_exists: bool = False):
        state["ngay"] = ngay
        main_area.clear()
        # `rec` là dữ liệu chính, thiếu thì không vẽ được gì — lỗi ở đây phải
        # dừng hẳn. `citad_status` chỉ là cảnh báo PHỤ TRỢ (nhắc "chưa đối
        # chiếu CITAD" trước khi xác nhận) — lỗi ở gọi này KHÔNG được phép
        # làm chết cả trang, nên tách khỏi try/except chính bằng
        # return_exceptions=True, lỗi thì coi như "chưa có bản đối chiếu"
        # (an toàn hơn — vẫn cảnh báo, không im lặng bỏ qua).
        try:
            rec = await asyncio.to_thread(api.get, f"/api/so-truc/{ngay}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi tải sổ trực: {e}", type="negative")
            return
        citad_results = await asyncio.gather(
            asyncio.to_thread(api.get, f"/api/so-truc/{ngay}/citad-status"),
            return_exceptions=True,
        )
        citad_result = citad_results[0]
        if isinstance(citad_result, Exception):
            if isinstance(citad_result, api.SessionExpiredError):
                _handle_api_error(citad_result)
                return
            citad_status = {"exists": False, "matched": False}
        else:
            citad_status = citad_result
        # `notify_if_exists` CHỈ bật khi gọi từ nút "Chọn ngày lập sổ trực"
        # (không bật ở lần tự nạp mặc định lúc mở trang, tránh toast thừa mỗi
        # lần vào trang) — nhắc NHẸ (toast tự tắt sau 5s, không cần bấm gì)
        # khi ngày vừa chọn ĐÃ có sổ trực (bất kỳ status, khác popup "Đã có
        # người lập trước" chỉ xét riêng status='draft').
        if notify_if_exists and rec.get("gdv1_id"):
            label = _STATUS_LABEL.get(rec.get("status"), (rec.get("status"), "grey-6"))[0]
            ui.notify(
                f"Ngày {_iso_to_ddmmyyyy(ngay)} đã có sổ trực (trạng thái: {label}) — "
                "kiểm tra kỹ trước khi thao tác.",
                type="info", timeout=3000, position="center",
                classes="text-lg px-6 py-4",
            )
        with main_area:
            _render_record(ngay, rec, citad_status)

    def _citad_ready(citad_status: dict) -> bool:
        return bool(citad_status.get("exists") and citad_status.get("matched"))

    def _citad_warning_msg(citad_status: dict, ngay: str) -> str:
        ngay_dmy = _iso_to_ddmmyyyy(ngay)
        return (
            f"Chưa có bản đối chiếu CITAD nào được lưu cho ngày {ngay_dmy}."
            if not citad_status.get("exists")
            else f"Đối chiếu CITAD ngày {ngay_dmy} đã có bản lưu nhưng vẫn còn chênh lệch, chưa khớp."
        )

    async def _confirm_with_citad_warning(citad_status: dict, ngay: str, do_confirm):
        """Dùng cho nút "Chuyển KSV xác nhận" (GDV1/GDV2, chỉ 1 người là đủ
        — không còn bước "GDV còn lại đồng ý" chặn giữa nữa) — khi Đối chiếu
        CITAD ngày này chưa có bản lưu khớp: hiện cảnh báo, "Để sau" chỉ
        ĐÓNG dialog (không gọi API, không đổi trạng thái gì — tự đi chấm
        CITAD rồi quay lại bấm sau), "Vẫn xác nhận" mới thực sự gọi hành
        động gốc."""
        if _citad_ready(citad_status):
            await do_confirm()
            return
        msg = _citad_warning_msg(citad_status, ngay)
        with ui.dialog() as dialog, ui.card().classes("p-5 w-[420px]"):
            with ui.row().classes("items-center gap-2 mb-1"):
                ui.icon("warning", color="amber-700").classes("text-xl")
                ui.label("Đối chiếu CITAD chưa hoàn tất").classes("text-base font-bold text-amber-800")
            ui.label(msg).classes("text-sm text-gray-700")
            ui.label(
                "Vẫn xác nhận tiếp phiên trực, hay dừng lại để chấm CITAD cho hoàn "
                "chỉnh rồi quay lại xác nhận sau?"
            ).classes("text-sm text-gray-500 mt-1 mb-2")
            with ui.row().classes("gap-2 justify-end w-full"):
                ui.button("Để sau", on_click=dialog.close).props("flat")

                async def _proceed_anyway():
                    dialog.close()
                    await do_confirm()

                ui.button("Vẫn xác nhận", on_click=_proceed_anyway).classes(
                    "bg-amber-600 hover:bg-amber-700 text-white"
                )
        dialog.open()

    def _open_reason_dialog(
        ngay: str, title: str, endpoint: str, notify_msg: str, confirm_label: str, confirm_cls: str,
        extra_warning: str | None = None, confirm_style: str | None = None,
    ):
        """Dialog nhập lý do dùng chung cho MỌI loại từ chối/huỷ cần lý do —
        GDV tự huỷ draft (draft-cancel), KSV "từ chối để sửa" (ksv-reject,
        quay lại draft) và "để huỷ" (ksv-cancel, ngõ cụt). Trước đây định
        nghĩa riêng bên trong `_render_pending_ksv()`, nay đưa lên dùng
        chung cấp trang vì `_render_draft_form()` cũng cần — tránh lặp lại
        y hệt logic. `extra_warning` (nếu có): chèn thêm 1 dòng cảnh báo (vd
        CITAD chưa khớp) — CHỈ hiển thị thêm thông tin, không đổi hành vi
        nút bên dưới. `confirm_style` (nếu có): inline CSS đè màu nền —
        Quasar tự gắn class `bg-primary` cho MỌI nút "standard" (không
        outline/flat) không truyền `color=`, VÀ rule đó viết sẵn
        `!important` trong `quasar.prod.css` (đã soi tận CSSOM để xác nhận)
        — thắng cả class Tailwind tự viết LẪN `.style()` inline thường,
        nút vẫn hiện XANH dù đã gắn đúng class/style đỏ. BẮT BUỘC
        `confirm_style` phải tự kèm `!important` (vd
        `"background:#991b1b !important"`) mới thắng nổi. KHÔNG cần sửa
        lại `confirm_cls` cũ (giữ nguyên các nơi gọi khác chưa gặp vấn đề
        này/chưa cần fix)."""
        with ui.dialog() as dialog, ui.card().classes("p-5 w-96"):
            ui.label(title).classes("text-base font-bold text-gray-800 mb-2")
            if extra_warning:
                with ui.row().classes(
                    "items-start gap-2 p-2 rounded-lg bg-amber-50 border border-amber-200 mb-2"
                ):
                    ui.icon("warning", color="amber-700").classes("text-base mt-0.5")
                    ui.label(extra_warning).classes("text-xs text-amber-800")
            reason_input = ui.textarea("Nhập lý do").props("dense outlined rows=3").classes("w-full")
            with ui.row().classes("gap-2 justify-end w-full mt-3"):
                ui.button("Huỷ bỏ", on_click=dialog.close).props("flat")

                async def _confirm():
                    if not reason_input.value or not reason_input.value.strip():
                        ui.notify("Phải nhập lý do", type="warning")
                        return
                    dialog.close()
                    try:
                        await asyncio.to_thread(
                            api.post, f"/api/so-truc/{ngay}/{endpoint}",
                            {"reason": reason_input.value.strip()},
                        )
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        ui.notify(f"Lỗi: {e}", type="negative")
                        return
                    ui.notify(notify_msg, type="info")
                    await _reload_main()
                    if history_refresh["fn"]:
                        await history_refresh["fn"]()

                _confirm_btn = ui.button(confirm_label, on_click=_confirm).classes(confirm_cls)
                if confirm_style:
                    _confirm_btn.style(confirm_style)
        dialog.open()

    def _render_record(ngay: str, rec: dict, citad_status: dict):
        status = rec.get("status", "draft")
        with ui.row().classes("items-center gap-3 mb-3"):
            ui.label(f"Sổ trực ngày {_iso_to_ddmmyyyy(ngay)}").classes("text-lg font-bold text-gray-800")
            _status_badge(status)

        if status == "draft" and rec.get("reject_reason"):
            # status='draft' kèm reject_reason có 4 nguồn khác nhau, PHẢI
            # phân biệt đúng ai/tại sao chứ không ghi cứng 1 câu — ưu tiên
            # xét `ksv_decision` trước (KSV luôn là người quyết trong 3/4
            # trường hợp này), CHỈ khi rỗng mới là nhánh GDV tự yêu cầu sửa
            # từ "Hoàn thành" (`request_edit()` nhánh GDV — gdv_decided_by
            # mới được set, ksv_decision luôn NULL ở nhánh đó). GDV tự huỷ
            # (draft_cancel) chuyển thẳng "cancelled" nên không rơi vào đây.
            _ksv_decision = rec.get("ksv_decision")
            if _ksv_decision == "reject_fix":
                _actor = rec.get("ksv_decided_by_name") or "KSV"
                _verb = "đã từ chối để sửa"
            elif _ksv_decision == "reject_cancel":
                _actor = rec.get("ksv_decided_by_name") or "KSV"
                _verb = "đã từ chối để huỷ"
            elif _ksv_decision == "self_edit":
                _actor = rec.get("ksv_decided_by_name") or "KSV"
                _verb = "đang tự chỉnh sửa lại phiên đã hoàn thành"
            elif rec.get("gdv_decided_by"):
                _actor = rec.get("gdv_decided_by_name") or "GDV"
                _verb = "đã yêu cầu chỉnh sửa phiên đã hoàn thành"
            else:
                _actor = rec.get("ksv_decided_by_name") or "KSV"
                _verb = "đã từ chối"
            with ui.row().classes(
                "w-full items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 mb-3"
            ):
                ui.icon("report", color="red").classes("text-lg mt-0.5")
                with ui.column().classes("gap-0"):
                    ui.label(f"{_actor} {_verb}, xem lý do bên dưới:").classes(
                        "text-sm font-semibold text-red-700"
                    )
                    ui.label(rec["reject_reason"]).classes("text-sm text-red-600")

        if status == "draft":
            _render_draft_form(ngay, rec, citad_status)
        elif status == "pending_ksv":
            _render_pending_ksv(ngay, rec, citad_status)
        elif status == "approved":
            _render_approved(ngay, rec)
        else:
            ui.label(f"Trạng thái không xác định: {status}").classes("text-red-500")

        # KHÔNG hiện lúc status='draft' — GDV đang lập/sửa sổ (dù bản đầy đủ
        # hay nhánh bị khoá reject_cancel/is_ksv_self_edit) đã CÓ SẴN hành
        # động riêng của họ ngay trên form (Chuyển KSV xác nhận/Huỷ phiên
        # trực/Lưu & Hoàn thành) — bấm 1 trong số đó đã đủ ghi nhận, thêm
        # nút "Xác nhận phiên trực" lúc này là thừa/gây rối. Chỉ có ý nghĩa
        # SAU khi đã chuyển KSV (pending_ksv) hoặc đã duyệt (approved) —
        # đúng lúc người GDV còn lại (không phải người vừa thao tác) mới
        # cần 1 cách để xác nhận đã xem/đồng ý.
        if status != "draft":
            _render_gdv_ack_button(ngay, rec, citad_status)
        _result_link_block(ngay)

    def _render_gdv_ack_button(ngay: str, rec: dict, citad_status: dict):
        """Nút "Xác nhận phiên trực" cho GDV CHƯA có dấu tick nào (không phải
        người đã chuyển KSV, cũng chưa tự bấm xác nhận trước đó) — backend
        (gdv_ack() service) cho gọi ở MỌI trạng thái, nhưng frontend CHỈ
        hiện nút này khi status khác 'draft' (xem điều kiện ở nơi gọi,
        `_render_record()`) — lúc còn draft, GDV đang lập/sửa đã có hành
        động riêng ngay trên form rồi (Chuyển KSV xác nhận/Huỷ phiên trực/
        Lưu & Hoàn thành), thêm nút này lúc đó là thừa.

        Cùng cảnh báo Đối chiếu CITAD chưa khớp như nút "Chuyển KSV xác
        nhận" của GDV đầu (`_confirm_with_citad_warning`) — GDV bấm sau
        cũng cần biết tình trạng đối chiếu, nhưng THUẦN THÔNG BÁO: có
        "Để sau" để bỏ qua, không chặn/không bắt buộc phải xử lý CITAD
        trước khi ghi nhận đã xác nhận (khớp đúng gdv_ack() không ràng
        buộc gì)."""
        if my_id not in (rec.get("gdv1_id"), rec.get("gdv2_id")):
            return
        if my_id == rec.get("initiated_by") or my_id == rec.get("confirmed_by"):
            return  # đã có dấu tick rồi (1 trong 2 cách), không cần bấm nữa

        async def _ack():
            try:
                await asyncio.to_thread(api.post, f"/api/so-truc/{ngay}/gdv-ack")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi: {e}", type="negative")
                return
            ui.notify("Đã xác nhận phiên trực", type="positive")
            await _reload_main()

        async def _on_ack_click():
            await _confirm_with_citad_warning(citad_status, ngay, _ack)

        ui.button("Xác nhận phiên trực", icon="visibility", on_click=_on_ack_click).props(
            "outline dense color=grey-8"
        ).classes("mt-2")

    def _render_draft_form(ngay: str, rec: dict, citad_status: dict):
        # Một khi gdv1_id/gdv2_id đã được CHỌN (khoá), CHỈ đúng 2 tài khoản đó
        # được sửa tiếp — trước khi ai chọn (sổ trống), ai có menu.so_truc
        # cũng tạo mới được. Backend enforce lại (NotAllowedError/403), đây
        # chỉ là UI để tránh cho người không liên quan thấy form nhập nhầm.
        locked = bool(rec.get("gdv1_id") or rec.get("gdv2_id"))
        # KSV tự mở lại sửa phiên đã "Hoàn thành" qua "Yêu cầu chỉnh sửa" ở
        # tab Lịch sử (request_edit(), nhánh KSV) — ĐÚNG KSV đó được sửa
        # form NGAY TẠI ĐÂY (khác mọi trường hợp khác, form chỉ 2 GDV sửa
        # được) rồi tự chốt thẳng, xem nhánh is_ksv_self_edit bên dưới.
        is_ksv_self_edit = rec.get("ksv_decision") == "self_edit" and my_id == rec.get("ksv_id")
        can_edit = (not locked) or (my_id in (rec.get("gdv1_id"), rec.get("gdv2_id"))) or is_ksv_self_edit
        if not can_edit:
            _render_readonly_summary(rec)
            ui.label(
                f"Chỉ 2 GDV được phân trực ngày {_iso_to_ddmmyyyy(ngay)} mới được sửa tiếp."
            ).classes("text-sm text-amber-600 italic mt-2")
            return

        if is_ksv_self_edit:
            ks_gdv1_select = ui.select({}, label="GDV 1").props("dense outlined").classes("w-64")
            ks_gdv2_select = ui.select({}, label="GDV 2").props("dense outlined").classes("w-64")
            ks_truc_phu_select = ui.select({}, label="Trực phụ", multiple=True).props(
                "dense outlined use-chips"
            ).classes("w-full mt-2")
            ks_ghichu_input = ui.textarea("Ghi chú ca trực", value=rec.get("ghi_chu", "")).props(
                "dense outlined rows=3"
            ).classes("w-full mt-2")

            async def _ks_load_options():
                try:
                    candidates = await asyncio.to_thread(api.get, "/api/so-truc/gdv-candidates")
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi tải danh sách GDV: {e}", type="negative")
                    return
                options = {c["id"]: c["full_name"] for c in candidates}
                ks_gdv1_select.options = options
                ks_gdv2_select.options = options
                ks_truc_phu_select.options = options
                if rec.get("gdv1_id") in options:
                    ks_gdv1_select.value = rec["gdv1_id"]
                if rec.get("gdv2_id") in options:
                    ks_gdv2_select.value = rec["gdv2_id"]
                ks_truc_phu_select.value = [uid for uid in rec.get("truc_phu_ids", []) if uid in options]
                ks_gdv1_select.update()
                ks_gdv2_select.update()
                ks_truc_phu_select.update()

            ui.timer(0.1, _ks_load_options, once=True)

            async def do_ksv_finalize_edit():
                if not ks_gdv1_select.value or not ks_gdv2_select.value:
                    ui.notify("Phải chọn đủ 2 GDV trực", type="warning")
                    return
                if ks_gdv1_select.value == ks_gdv2_select.value:
                    ui.notify("GDV 1 và GDV 2 không được trùng nhau", type="warning")
                    return
                try:
                    await asyncio.to_thread(
                        api.post, f"/api/so-truc/{ngay}/ksv-finalize-edit",
                        {
                            "gdv1_id": ks_gdv1_select.value, "gdv2_id": ks_gdv2_select.value,
                            "ghi_chu": ks_ghichu_input.value, "truc_phu_ids": ks_truc_phu_select.value or [],
                        },
                    )
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi lưu: {e}", type="negative")
                    return
                ui.notify("Đã lưu, phiên trực trở lại Hoàn thành", type="positive")
                await _reload_main()
                if history_refresh["fn"]:
                    await history_refresh["fn"]()

            ui.button(
                "Lưu & Hoàn thành", icon="task_alt", on_click=do_ksv_finalize_edit,
            ).classes("bg-emerald-600 hover:bg-emerald-700 text-white mt-3")
            return

        # KSV vừa "từ chối để huỷ" (ksv_decision='reject_cancel') — CHỈ còn
        # nút "Huỷ phiên trực" cho 2 GDV, KHÔNG được sửa nội dung rồi đẩy KSV
        # lại như trường hợp "để sửa" (backend cũng chặn lại ở save_draft()/
        # forward_to_ksv() — đây chỉ là UI khớp theo, tránh hiện form nhập
        # nhầm rồi bị 400 khi bấm Lưu/Chuyển KSV xác nhận).
        if rec.get("ksv_decision") == "reject_cancel":
            _render_readonly_summary(rec)

            def do_draft_cancel_only():
                _open_reason_dialog(
                    ngay,
                    f"Lý do huỷ — phiên trực ngày {_iso_to_ddmmyyyy(ngay)} sẽ đóng, phải lập phiên trực mới nếu cần làm lại",
                    "draft-cancel",
                    "Đã huỷ phiên trực này",
                    "Huỷ phiên trực",
                    "bg-red-600 hover:bg-red-700 text-white",
                )

            ui.button("Huỷ phiên trực", icon="delete_forever", on_click=do_draft_cancel_only).classes(
                "bg-red-600 hover:bg-red-700 text-white mt-3"
            )
            return

        # Cảnh báo ai đó ĐÃ động vào sổ ngày này trước rồi — CHỈ hiện cho
        # người THỰC SỰ sửa được tiếp (đã qua nhánh can_edit ở trên, vd
        # đúng GDV2 bị khoá cùng), không hiện cho KSV/người không liên quan
        # — họ không sửa/lưu đè được gì (đã bị chặn ở nhánh readonly phía
        # trên rồi) nên cảnh báo "kiểm tra kỹ trước khi sửa/lưu đè" vô nghĩa
        # với họ, gây hiểu nhầm là họ cũng đang thao tác vào phiên này.
        # Không hiện cho chính người đã tạo (gdv1_id == my_id) — báo cho
        # chính mình biết "bạn đã lập" là vô nghĩa.
        if rec.get("gdv1_id") and rec.get("gdv1_id") != my_id:
            with ui.dialog() as _who_dialog, ui.card().classes("p-5 w-[420px]"):
                with ui.row().classes("items-center gap-2 mb-1"):
                    ui.icon("info", color="blue-7").classes("text-xl")
                    ui.label("Đã có người lập trước").classes("text-base font-bold text-gray-800")
                names = rec.get("gdv1_name") or "—"
                if rec.get("gdv2_id") and rec.get("gdv2_name"):
                    names += f" và {rec['gdv2_name']}"
                ui.label(
                    f"{names} đã lập sổ trực cuối ngày {_iso_to_ddmmyyyy(ngay)}."
                ).classes("text-sm text-gray-700")
                ui.label(
                    "Nội dung hiện có đã được tải sẵn vào form bên dưới — kiểm tra kỹ "
                    "trước khi sửa/lưu tiếp, tránh ghi đè nhầm."
                ).classes("text-sm text-gray-500 mt-1 mb-2")
                ui.button("Đã hiểu", on_click=_who_dialog.close).classes(
                    "bg-blue-600 hover:bg-blue-700 text-white"
                )
            _who_dialog.open()

        # GDV1/GDV2 CHỌN từ danh sách nhân viên Phòng Thanh toán (không gõ tay
        # tự do) — tránh gõ sai tên/trùng tên, khớp yêu cầu người dùng.
        gdv1_select = ui.select({}, label="GDV 1").props("dense outlined").classes("w-64")
        gdv2_select = ui.select({}, label="GDV 2").props("dense outlined").classes("w-64")
        # Trực phụ — CHỈ liệt kê để biết, KHÔNG xác nhận/khoá quyền gì (khác
        # GDV1/GDV2/KSV) — chọn nhiều người, cùng danh sách ứng viên với GDV
        # (nhân sự Phòng Thanh toán), cùng vòng đời sửa với GDV1/GDV2/Ghi chú.
        truc_phu_select = ui.select({}, label="Trực phụ", multiple=True).props(
            "dense outlined use-chips"
        ).classes("w-full mt-2")
        ghichu_input = ui.textarea("Ghi chú ca trực", value=rec.get("ghi_chu", "")).props(
            "dense outlined rows=3"
        ).classes("w-full mt-2")

        # KSV: một khi đã chọn (kể cả sau khi bị "từ chối để sửa"), KHOÁ luôn
        # — không đổi sang người khác được (yêu cầu người dùng: đẩy lại phải
        # đúng người KSV cũ). Chỉ hiện dropdown khi thật sự chưa chọn lần nào.
        ksv_locked_id = rec.get("ksv_id")
        if ksv_locked_id:
            with ui.row().classes("items-center gap-2 mt-2"):
                ui.icon("lock", color="grey").classes("text-base")
                ui.label(f"KSV xác nhận: {rec.get('ksv_name') or '—'} (giữ nguyên)").classes(
                    "text-sm text-gray-700"
                )
            ksv_select = None
        else:
            ksv_select = ui.select({}, label="Chọn KSV xác nhận").props("dense outlined").classes("w-64 mt-2")

        async def _load_gdv_options():
            try:
                candidates = await asyncio.to_thread(api.get, "/api/so-truc/gdv-candidates")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi tải danh sách GDV: {e}", type="negative")
                return
            options = {c["id"]: c["full_name"] for c in candidates}
            gdv1_select.options = options
            gdv2_select.options = options
            truc_phu_select.options = options
            if rec.get("gdv1_id") in options:
                gdv1_select.value = rec["gdv1_id"]
            elif my_id in options:
                # Sổ trực CHƯA có ai lập (gdv1_id trống) — mặc định GDV 1 là
                # chính người đang mở form này (thường đúng thực tế: ai lập
                # sổ thì tự nhiên là 1 trong 2 GDV trực). Vẫn SỬA được nếu
                # sai — chỉ là gợi ý mặc định, không khoá.
                gdv1_select.value = my_id
            if rec.get("gdv2_id") in options:
                gdv2_select.value = rec["gdv2_id"]
            truc_phu_select.value = [uid for uid in rec.get("truc_phu_ids", []) if uid in options]
            gdv1_select.update()
            gdv2_select.update()
            truc_phu_select.update()

        async def _load_ksv_options():
            if ksv_select is None:
                return
            try:
                candidates = await asyncio.to_thread(api.get, "/api/so-truc/ksv-candidates")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi tải danh sách KSV: {e}", type="negative")
                return
            ksv_select.options = {c["id"]: c["full_name"] for c in candidates}
            ksv_select.update()

        ui.timer(0.1, _load_gdv_options, once=True)
        ui.timer(0.1, _load_ksv_options, once=True)

        async def do_save_draft():
            if gdv1_select.value and gdv2_select.value and gdv1_select.value == gdv2_select.value:
                ui.notify("GDV 1 và GDV 2 không được trùng nhau", type="warning")
                return
            try:
                await asyncio.to_thread(
                    api.post, f"/api/so-truc/{ngay}/save-draft",
                    {
                        "gdv1_id": gdv1_select.value, "gdv2_id": gdv2_select.value,
                        "ghi_chu": ghichu_input.value, "truc_phu_ids": truc_phu_select.value or [],
                    },
                )
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi lưu: {e}", type="negative")
                return
            ui.notify("Đã lưu", type="positive")
            await _reload_main()
            if history_refresh["fn"]:
                await history_refresh["fn"]()

        async def do_forward_ksv():
            if not gdv1_select.value or not gdv2_select.value:
                ui.notify("Phải chọn đủ 2 GDV trực", type="warning")
                return
            if gdv1_select.value == gdv2_select.value:
                ui.notify("GDV 1 và GDV 2 không được trùng nhau", type="warning")
                return
            ksv_id_to_send = ksv_locked_id if ksv_select is None else ksv_select.value
            if not ksv_id_to_send:
                ui.notify("Phải chọn KSV xác nhận", type="warning")
                return
            try:
                await asyncio.to_thread(
                    api.post, f"/api/so-truc/{ngay}/forward-ksv",
                    {
                        "gdv1_id": gdv1_select.value, "gdv2_id": gdv2_select.value,
                        "ghi_chu": ghichu_input.value, "ksv_id": ksv_id_to_send,
                        "truc_phu_ids": truc_phu_select.value or [],
                    },
                )
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi chuyển KSV xác nhận: {e}", type="negative")
                return
            ui.notify("Đã chuyển KSV xác nhận", type="positive")
            await _reload_main()
            if history_refresh["fn"]:
                await history_refresh["fn"]()

        async def _on_forward_ksv_click():
            await _confirm_with_citad_warning(citad_status, ngay, do_forward_ksv)

        def do_draft_cancel():
            _open_reason_dialog(
                ngay,
                f"Lý do huỷ — phiên trực ngày {_iso_to_ddmmyyyy(ngay)} sẽ đóng, phải lập phiên trực mới nếu cần làm lại",
                "draft-cancel",
                "Đã huỷ phiên trực này",
                "Huỷ phiên trực",
                "bg-red-600 hover:bg-red-700 text-white",
            )

        with ui.row().classes("gap-3 mt-3"):
            ui.button("Lưu", icon="save", on_click=do_save_draft).props("outline")
            ui.button("Chuyển KSV xác nhận", icon="send", on_click=_on_forward_ksv_click).classes(
                "bg-indigo-600 hover:bg-indigo-700 text-white"
            )
            # Chỉ có gì để huỷ khi đã KHOÁ (đã chọn ít nhất 1 GDV) — draft
            # trống thì không cần nút này (chưa có nội dung nào để huỷ).
            if locked:
                ui.button("Huỷ phiên trực", icon="delete_forever", on_click=do_draft_cancel).props(
                    "outline color=red"
                )

    def _render_pending_ksv(ngay: str, rec: dict, citad_status: dict):
        _render_readonly_summary(rec)
        if not (is_ksv and my_id == rec.get("ksv_id")):
            ui.label(
                f"Đang chờ KSV {rec.get('ksv_name') or ''} xác nhận phiên trực ngày {_iso_to_ddmmyyyy(ngay)}."
            ).classes("text-sm text-blue-600 italic mt-2")
            return

        # Đối chiếu CITAD ngày này CHƯA khớp — gộp cảnh báo vào ĐÚNG 1 popup
        # với hành động thật (không phải 1 popup cảnh báo riêng rồi mới tới
        # popup hành động thật như 2 bước GDV, vì KSV vốn ĐÃ CÓ SẴN dialog cho
        # "Xác nhận" (giờ mới thêm) lẫn 2 nút "Từ chối" (đã có dialog nhập lý
        # do từ trước) — chỉ cần chèn thêm 1 dòng cảnh báo vào các dialog đó,
        # không tạo thêm lớp popup nào nữa. Nếu CITAD đã khớp: mọi thứ y hệt
        # trước đây, không có gì thay đổi.
        citad_not_ready = not _citad_ready(citad_status)
        citad_warning_line = _citad_warning_msg(citad_status, ngay) if citad_not_ready else None

        async def do_ksv_confirm():
            try:
                await asyncio.to_thread(api.post, f"/api/so-truc/{ngay}/ksv-confirm")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi xác nhận: {e}", type="negative")
                return
            ui.notify("Đã xác nhận sổ trực", type="positive")
            await _reload_main()
            if history_refresh["fn"]:
                await history_refresh["fn"]()

        def _warning_row(msg: str):
            with ui.row().classes(
                "items-start gap-2 p-2 rounded-lg bg-amber-50 border border-amber-200 mb-2"
            ):
                ui.icon("warning", color="amber-700").classes("text-base mt-0.5")
                ui.label(msg).classes("text-xs text-amber-800")

        async def _on_ksv_confirm_click():
            if not citad_not_ready:
                await do_ksv_confirm()
                return
            # Gộp cảnh báo + hành động xác nhận vào ĐÚNG 1 dialog — bấm
            # "Xác nhận" trong dialog này gọi thẳng luôn, không có bước
            # trung gian nào khác.
            with ui.dialog() as dialog, ui.card().classes("p-5 w-96"):
                ui.label(f"Xác nhận hoàn thành phiên trực ngày {_iso_to_ddmmyyyy(ngay)}?").classes(
                    "text-base font-bold text-gray-800 mb-2"
                )
                _warning_row(citad_warning_line)
                with ui.row().classes("gap-2 justify-end w-full mt-1"):
                    ui.button("Đóng", on_click=dialog.close).props("flat")

                    async def _confirm():
                        dialog.close()
                        await do_ksv_confirm()

                    ui.button("Xác nhận", on_click=_confirm).classes(
                        "bg-emerald-600 hover:bg-emerald-700 text-white"
                    )
            dialog.open()

        def do_ksv_reject():
            _open_reason_dialog(
                ngay,
                f"Lý do từ chối phiên trực ngày {_iso_to_ddmmyyyy(ngay)} — yêu cầu 2 GDV sửa lại",
                "ksv-reject",
                "Đã từ chối, trả lại cho GDV sửa",
                "Từ chối, yêu cầu sửa",
                "bg-amber-600 hover:bg-amber-700 text-white",
                extra_warning=citad_warning_line,
            )

        def do_ksv_cancel():
            _open_reason_dialog(
                ngay,
                f"Lý do đề nghị huỷ phiên trực ngày {_iso_to_ddmmyyyy(ngay)} — trả lại cho 1 trong 2 GDV "
                "tự bấm \"Huỷ phiên trực\" để đóng hẳn",
                "ksv-cancel",
                "Đã gửi yêu cầu huỷ, chờ GDV xác nhận",
                "Từ chối, yêu cầu huỷ",
                "bg-red-600 hover:bg-red-700 text-white",
                extra_warning=citad_warning_line,
            )

        with ui.row().classes("gap-3 mt-2"):
            ui.button("Xác nhận", icon="check_circle", on_click=_on_ksv_confirm_click).classes(
                "bg-emerald-600 hover:bg-emerald-700 text-white"
            )
            ui.button("Từ chối — Yêu cầu sửa lại", icon="edit_note", on_click=do_ksv_reject).props(
                "outline color=amber-8"
            )
            ui.button("Từ chối — Yêu cầu huỷ", icon="delete_forever", on_click=do_ksv_cancel).props(
                "outline color=red"
            )

    def _render_approved(ngay: str, rec: dict):
        _render_readonly_summary(rec)
        with ui.row().classes("items-center gap-2 mt-2 text-emerald-700"):
            ui.icon("verified", color="green")
            ui.label(
                f"Đã duyệt bởi {rec.get('ksv_decided_by_name') or '—'} lúc "
                f"{_iso_dt_to_ddmmyyyy(rec.get('ksv_decided_at')) or '—'}"
            ).classes("text-sm font-medium")

    def _build_history_panel():
        """Tab "Lịch sử" — liệt kê mọi dòng trong so_truc_records (bảng tự
        thân đã là lịch sử, xem docstring so_truc_service.py); 1 ngày có thể
        có NHIỀU dòng nếu từng bị "huỷ" rồi mở phiên trực mới. KHÔNG lọc gì
        thì chỉ hiện ĐÚNG 1 dòng gần nhất (xem get_history() trong service)
        — bấm lọc theo khoảng ngày mới hiện đầy đủ lịch sử."""
        ui.label(
            "Mặc định chỉ hiện phiên trực gần nhất — chọn khoảng ngày rồi bấm \"Lọc\" để xem đầy đủ lịch sử."
        ).classes("text-xs text-gray-500 mb-2")
        with ui.row().classes("w-full items-end gap-3 flex-wrap mb-2"):
            tu_input = _date_filter_input("Từ ngày")
            den_input = _date_filter_input("Đến ngày")
            ui.button("Lọc", icon="filter_alt", on_click=lambda: load_history()).props("outline")

            async def clear_filter():
                tu_input.value = ""
                den_input.value = ""
                await load_history()

            ui.button("Xoá lọc", icon="clear", on_click=clear_filter).props("outline color=grey dense")

            async def do_export():
                if not tu_input.value or not den_input.value:
                    ui.notify("Phải chọn đủ Từ ngày / Đến ngày để xuất Excel", type="warning")
                    return
                tu_iso = _ddmmyyyy_to_iso(tu_input.value)
                den_iso = _ddmmyyyy_to_iso(den_input.value)
                try:
                    content = await asyncio.to_thread(
                        api.download, "/api/so-truc/export",
                        {"tu_ngay": tu_iso, "den_ngay": den_iso},
                    )
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi xuất Excel: {e}", type="negative")
                    return
                fname = f"so_truc_lich_su_{tu_iso}_{den_iso}.xlsx".replace("-", "")
                ui.download(content, fname)

            ui.button("Xuất Excel", icon="download", on_click=do_export).props(
                "outline color=green-8 dense"
            )

        rows_area = ui.column().classes("w-full gap-1")

        async def load_history():
            rows_area.clear()
            try:
                params = {}
                if tu_input.value:
                    params["tu_ngay"] = _ddmmyyyy_to_iso(tu_input.value)
                if den_input.value:
                    params["den_ngay"] = _ddmmyyyy_to_iso(den_input.value)
                rows = await asyncio.to_thread(api.get, "/api/so-truc/history", params)
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi tải lịch sử: {e}", type="negative")
                return
            with rows_area:
                if not rows:
                    msg = (
                        "Không có ngày nào khớp bộ lọc — thử bấm \"Xoá lọc\" để xem tất cả."
                        if (tu_input.value or den_input.value)
                        else "Chưa có sổ trực nào."
                    )
                    ui.label(msg).classes("text-gray-400 p-4")
                    return
                with ui.column().classes("w-full border-2 border-red-800 rounded-xl gap-0 overflow-hidden"):
                    with ui.row().classes(
                        "w-full items-center gap-0 px-3 py-2 bg-blue-600 border-b border-gray-200 "
                        "text-xs font-semibold text-white"
                    ):
                        ui.label("Ngày").classes("w-28 border-r border-white/30 pr-2 mr-2")
                        ui.label("GDV 1 / GDV 2").classes("w-56 border-r border-white/30 pr-2 mr-2")
                        ui.label("KSV").classes("w-40 border-r border-white/30 pr-2 mr-2")
                        ui.label("Trạng thái").classes("w-44 border-r border-white/30 pr-2 mr-2")
                        ui.label("Cập nhật lúc").classes("flex-1")
                    for i, r in enumerate(rows, start=1):
                        _history_row(r, is_last=(i == len(rows)))

        def _history_row(r: dict, is_last: bool):
            ngay = r["truc_date"]
            expanded = {"open": False}
            with ui.column().classes("w-full" + ("" if is_last else " border-b border-gray-200")):
                with ui.row().classes(
                    "w-full items-center gap-0 px-3 py-2 cursor-pointer hover:bg-gray-50"
                ) as row:
                    ui.label(_iso_to_ddmmyyyy(ngay)).classes(
                        "w-28 font-bold border-r border-gray-200 pr-2 mr-2"
                    )
                    with ui.column().classes("w-56 border-r border-gray-200 pr-2 mr-2 gap-0"):
                        ui.label(r.get("gdv1_name") or "—").classes("text-sm")
                        ui.label(r.get("gdv2_name") or "—").classes("text-sm")
                    ui.label(r.get("ksv_name") or "—").classes(
                        "w-40 border-r border-gray-200 pr-2 mr-2 text-sm"
                    )
                    with ui.row().classes("w-44 border-r border-gray-200 pr-2 mr-2"):
                        _status_badge(r.get("status", "draft"))
                    ui.label(_iso_dt_to_ddmmyyyy(r.get("updated_at")) or "").classes("flex-1 text-xs text-gray-400")
                    ui.icon("expand_more").classes("text-gray-500")
                detail_area = ui.column().classes("w-full pl-4 pb-2")

                def toggle_detail():
                    if expanded["open"]:
                        detail_area.clear()
                        expanded["open"] = False
                        return
                    expanded["open"] = True
                    with detail_area:
                        _render_readonly_summary(r)
                        if r.get("reject_reason"):
                            # Cùng logic phân biệt nguồn với banner đỏ chính trong
                            # _render_record() (dòng ~359-391) — reject_reason có
                            # thể đến từ 3 nhánh KSV hoặc từ GDV tự yêu cầu chỉnh
                            # sửa (request_edit(), nhánh GDV), không chỉ "từ chối".
                            if r.get("status") == "cancelled":
                                _label = "Lý do huỷ"
                            elif r.get("ksv_decision") == "reject_fix":
                                _label = "Lý do KSV từ chối (yêu cầu sửa)"
                            elif r.get("ksv_decision") == "reject_cancel":
                                _label = "Lý do KSV từ chối (yêu cầu huỷ)"
                            elif r.get("ksv_decision") == "self_edit":
                                _label = "Lý do KSV tự chỉnh sửa lại"
                            elif r.get("gdv_decided_by"):
                                _label = "Lý do GDV yêu cầu chỉnh sửa"
                            else:
                                _label = "Lý do từ chối gần nhất"
                            ui.label(f"{_label}: {r['reject_reason']}").classes(
                                "text-xs text-red-500 mt-1"
                            )
                        # Chỉ hiện ở tab Lịch sử (không hiện bên tab Sổ trực
                        # chính) — đúng 2 GDV hoặc đúng KSV của PHIÊN NÀY mới
                        # mở lại sửa được phiên đã "Hoàn thành" — xem
                        # request_edit() trong so_truc_service.py.
                        if r.get("status") == "approved" and my_id in (
                            r.get("gdv1_id"), r.get("gdv2_id"), r.get("ksv_id"),
                        ):
                            # `!important` trong `.style()` inline BẮT BUỘC
                            # phải có — đã soi tận CSS rule thật của Quasar
                            # (`quasar.prod.css`): `.bg-primary` tự gắn cho
                            # MỌI nút "standard" không truyền `color=` VIẾT
                            # SẴN `!important` (`background: var(--q-primary)
                            # !important`) — không chỉ thắng class Tailwind
                            # tự viết mà còn thắng CẢ `.style()` inline
                            # THƯỜNG (không !important). Chỉ inline
                            # `!important` mới thắng nổi. Xem docstring
                            # `_open_reason_dialog()` phần `confirm_style`.
                            def do_request_edit(ngay=ngay):
                                _open_reason_dialog(
                                    ngay,
                                    f"Lý do yêu cầu chỉnh sửa phiên trực ngày {_iso_to_ddmmyyyy(ngay)}",
                                    "request-edit",
                                    "Đã gửi yêu cầu chỉnh sửa",
                                    "Yêu cầu chỉnh sửa",
                                    "text-white",
                                    confirm_style="background:#991b1b !important",
                                )

                            ui.button(
                                "Yêu cầu chỉnh sửa", icon="edit_note", on_click=do_request_edit,
                            ).props("dense").classes("text-white mt-2").style(
                                "background:#991b1b !important"
                            )
                        _result_link_block(ngay)

                row.on("click", toggle_detail)

        history_refresh["fn"] = load_history
        ui.timer(0.1, load_history, once=True)

    with ui.row().classes("w-full"):
        await _sidebar("so_truc")
        with _content_area():
            _navy_header(
                "SỔ TRỰC CUỐI NGÀY",
                "Ghi nhận kết quả ca trực cuối ngày — 2 GDV nhập số liệu, KSV xác nhận",
            )

            with ui.tabs().props(
                "active-color=indigo-600 indicator-color=indigo-600 align=left"
            ).classes("w-full border-b border-gray-200 mb-1") as tabs:
                tab_so_truc = ui.tab("Sổ trực")
                tab_lich_su = ui.tab("Lịch sử")

            with ui.tab_panels(tabs, value=tab_so_truc).classes("w-full"):
                with ui.tab_panel(tab_so_truc):
                    with ui.column().classes("w-full gap-4"):
                        with _section_card(
                            "Chọn ngày trực", icon="calendar_month", accent="indigo",
                            outer_border="border-2 border-red-800",
                        ):
                            with ui.row().classes("w-full items-end gap-3 p-4"):
                                ngay_input = _date_picker_input("Ngày trực", state["ngay"])
                                ui.button(
                                    "Chọn ngày lập sổ trực", icon="cloud_download",
                                    on_click=lambda: load_day(
                                        _ddmmyyyy_to_iso(ngay_input.value), notify_if_exists=True
                                    ),
                                ).props("outline")

                        with _section_card(
                            "Sổ trực trong ngày", icon="assignment_turned_in", accent="blue",
                            outer_border="border-2 border-red-800",
                        ):
                            main_area = ui.column().classes("w-full gap-2 p-4")
                    ui.timer(0.1, lambda: load_day(state["ngay"]), once=True)

                with ui.tab_panel(tab_lich_su):
                    with _section_card(
                        "Lịch sử sổ trực", icon="history", accent="emerald",
                        outer_border="border-2 border-red-800",
                    ):
                        with ui.column().classes("w-full gap-2 p-4"):
                            _build_history_panel()
