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


def _section_card(title: str, icon: str = "table_chart", accent: str = "blue"):
    bg, text, border, wash = _ACCENT.get(accent, _ACCENT["blue"])
    card = ui.card().classes(
        "w-full rounded-2xl border border-gray-200 shadow-sm hover:shadow-md "
        f"transition-shadow duration-200 {wash} p-0 overflow-hidden"
    )
    with card:
        with ui.row().classes(f"w-full items-center gap-3 px-5 py-4 border-b {border} bg-gray-50/60"):
            with ui.row().classes(f"items-center justify-center w-9 h-9 rounded-xl {bg} shrink-0"):
                ui.icon(icon).classes(f"{text} text-lg")
            ui.label(title).classes("font-semibold text-gray-800 text-[15px]")
    return card


_STATUS_LABEL = {
    "draft": ("Nháp", "grey-6"),
    "pending_gdv_confirm": ("Chờ GDV xác nhận", "amber-8"),
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


def _date_picker_input(label: str, initial: str = None):
    """Ô nhập ngày YYYY-MM-DD (khớp định dạng lưu `truc_date`) — khác
    `doi_chieu_citad.py::_date_picker_input` dùng dd/mm/yyyy vì đó là định
    dạng lưu của `doi_chieu_citad_sessions.ngay`, không dùng chung được."""
    initial = initial or datetime.date.today().isoformat()
    with ui.input(label, value=initial).props("dense outlined").classes("w-44") as date_input:
        with date_input.add_slot("append"):
            ui.icon("edit_calendar").on("click", lambda: menu.open()).classes("cursor-pointer")
        with ui.menu() as menu:
            ui.date(value=initial, on_change=menu.close).bind_value(date_input)
    return date_input


def _date_filter_input(label: str):
    with ui.input(label, value="").props("dense outlined clearable").classes("w-44") as date_input:
        with date_input.add_slot("append"):
            ui.icon("edit_calendar").on("click", lambda: menu.open()).classes("cursor-pointer")
        with ui.menu() as menu:
            ui.date(on_change=menu.close).bind_value(date_input)
    return date_input


@ui.page("/so_truc")
def so_truc_page(request: _StarletteRequest):
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
        def _gdv_row(label: str, name: str, gdv_id):
            with ui.row().classes("items-center gap-1"):
                ui.label(f"{label}: {name or '—'}").classes("text-sm text-gray-700")
                if gdv_id and gdv_id == rec.get("initiated_by"):
                    ui.icon("check_circle", color="green").classes("text-base").tooltip(
                        f"Đã bấm \"Chuyển KSV xác nhận\" lúc {rec.get('initiated_at') or ''}"
                    )
                elif gdv_id and gdv_id == rec.get("confirmed_by"):
                    ui.icon("check_circle", color="green").classes("text-base").tooltip(
                        f"Đã bấm \"Đồng ý xác nhận\" lúc {rec.get('confirmed_at') or ''}"
                    )

        with ui.column().classes(
            "w-full gap-1 p-4 rounded-xl bg-white border border-gray-200 shadow-sm"
        ):
            with ui.row().classes("gap-6"):
                _gdv_row("GDV 1", rec.get("gdv1_name"), rec.get("gdv1_id"))
                _gdv_row("GDV 2", rec.get("gdv2_name"), rec.get("gdv2_id"))
            with ui.column().classes(
                "w-full gap-0.5 mt-1 p-3 rounded-lg bg-gray-50 border-2 border-red-500"
            ):
                ui.label("GHI CHÚ").classes(
                    "text-[11px] font-semibold text-gray-400 tracking-wide"
                )
                ui.label(rec.get("ghi_chu") or "—").classes(
                    "text-sm text-gray-700 whitespace-pre-wrap"
                )
            ui.label(f"KSV được chọn: {rec.get('ksv_name') or '—'}").classes("text-sm text-gray-700")
            if rec.get("initiated_by_name"):
                ui.label(
                    f"Người chuyển KSV xác nhận: {rec['initiated_by_name']} lúc {rec.get('initiated_at') or ''}"
                ).classes("text-xs text-gray-400")
            if rec.get("confirmed_by_name"):
                ui.label(
                    f"Người đồng ý xác nhận: {rec['confirmed_by_name']} lúc {rec.get('confirmed_at') or ''}"
                ).classes("text-xs text-gray-400")

    async def _reload_main():
        await load_day(state["ngay"])

    async def load_day(ngay: str):
        state["ngay"] = ngay
        main_area.clear()
        try:
            rec = await asyncio.to_thread(api.get, f"/api/so-truc/{ngay}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi tải sổ trực: {e}", type="negative")
            return
        with main_area:
            _render_record(ngay, rec)

    def _render_record(ngay: str, rec: dict):
        status = rec.get("status", "draft")
        with ui.row().classes("items-center gap-3 mb-3"):
            ui.label(f"Sổ trực ngày {_iso_to_ddmmyyyy(ngay)}").classes("text-lg font-bold text-gray-800")
            _status_badge(status)

        if status == "draft" and rec.get("reject_reason"):
            with ui.row().classes(
                "w-full items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 mb-3"
            ):
                ui.icon("report", color="red").classes("text-lg mt-0.5")
                with ui.column().classes("gap-0"):
                    ui.label("KSV đã từ chối, cần sửa lại:").classes("text-sm font-semibold text-red-700")
                    ui.label(rec["reject_reason"]).classes("text-sm text-red-600")

        if status == "draft":
            _render_draft_form(ngay, rec)
        elif status == "pending_gdv_confirm":
            _render_pending_gdv(ngay, rec)
        elif status == "pending_ksv":
            _render_pending_ksv(ngay, rec)
        elif status == "approved":
            _render_approved(ngay, rec)
        else:
            ui.label(f"Trạng thái không xác định: {status}").classes("text-red-500")

        _result_link_block(ngay)

    def _render_draft_form(ngay: str, rec: dict):
        # Một khi gdv1_id/gdv2_id đã được CHỌN (khoá), CHỈ đúng 2 tài khoản đó
        # được sửa tiếp — trước khi ai chọn (sổ trống), ai có menu.so_truc
        # cũng tạo mới được. Backend enforce lại (NotAllowedError/403), đây
        # chỉ là UI để tránh cho người không liên quan thấy form nhập nhầm.
        locked = bool(rec.get("gdv1_id") or rec.get("gdv2_id"))
        can_edit = (not locked) or (my_id in (rec.get("gdv1_id"), rec.get("gdv2_id")))
        if not can_edit:
            _render_readonly_summary(rec)
            ui.label(
                "Chỉ 2 GDV được phân trực ngày này mới được sửa tiếp."
            ).classes("text-sm text-amber-600 italic mt-2")
            return

        # GDV1/GDV2 CHỌN từ danh sách nhân viên Phòng Thanh toán (không gõ tay
        # tự do) — tránh gõ sai tên/trùng tên, khớp yêu cầu người dùng.
        gdv1_select = ui.select({}, label="GDV 1").props("dense outlined").classes("w-64")
        gdv2_select = ui.select({}, label="GDV 2").props("dense outlined").classes("w-64")
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
            if rec.get("gdv1_id") in options:
                gdv1_select.value = rec["gdv1_id"]
            if rec.get("gdv2_id") in options:
                gdv2_select.value = rec["gdv2_id"]
            gdv1_select.update()
            gdv2_select.update()

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
                    {"gdv1_id": gdv1_select.value, "gdv2_id": gdv2_select.value, "ghi_chu": ghichu_input.value},
                )
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi lưu nháp: {e}", type="negative")
                return
            ui.notify("Đã lưu nháp", type="positive")
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

        with ui.row().classes("gap-3 mt-3"):
            ui.button("Lưu nháp", icon="save", on_click=do_save_draft).props("outline")
            ui.button("Chuyển KSV xác nhận", icon="send", on_click=do_forward_ksv).classes(
                "bg-indigo-600 hover:bg-indigo-700 text-white"
            )

    def _render_pending_gdv(ngay: str, rec: dict):
        _render_readonly_summary(rec)
        if my_id not in (rec.get("gdv1_id"), rec.get("gdv2_id")):
            ui.label(
                "Đang chờ người trực còn lại đồng ý xác nhận trước khi chuyển cho KSV."
            ).classes("text-sm text-blue-600 italic mt-2")
            return
        if rec.get("initiated_by") == my_id:
            ui.label(
                "Đang chờ người trực còn lại đồng ý xác nhận trước khi chuyển cho KSV."
            ).classes("text-sm text-amber-600 italic mt-2")
            return

        async def do_gdv_confirm():
            try:
                await asyncio.to_thread(api.post, f"/api/so-truc/{ngay}/gdv-confirm")
            except Exception as e:
                if _handle_api_error(e):
                    return
                ui.notify(f"Lỗi xác nhận: {e}", type="negative")
                return
            ui.notify("Đã đồng ý xác nhận, chuyển cho KSV duyệt", type="positive")
            await _reload_main()
            if history_refresh["fn"]:
                await history_refresh["fn"]()

        ui.button("Đồng ý xác nhận", icon="check_circle", on_click=do_gdv_confirm).classes(
            "bg-emerald-600 hover:bg-emerald-700 text-white mt-2"
        )

    def _render_pending_ksv(ngay: str, rec: dict):
        _render_readonly_summary(rec)
        if not (is_ksv and my_id == rec.get("ksv_id")):
            ui.label(
                f"Đang chờ KSV {rec.get('ksv_name') or ''} xác nhận."
            ).classes("text-sm text-blue-600 italic mt-2")
            return

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

        def _open_reason_dialog(title: str, endpoint: str, notify_msg: str, confirm_label: str, confirm_cls: str):
            """Dialog nhập lý do dùng chung cho cả 2 loại từ chối — "để sửa"
            (ksv-reject, quay lại draft) và "để huỷ" (ksv-cancel, ngõ cụt)."""
            with ui.dialog() as dialog, ui.card().classes("p-5 w-96"):
                ui.label(title).classes("text-base font-bold text-gray-800 mb-2")
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

                    ui.button(confirm_label, on_click=_confirm).classes(confirm_cls)
            dialog.open()

        def do_ksv_reject():
            _open_reason_dialog(
                "Lý do từ chối — yêu cầu 2 GDV sửa lại",
                "ksv-reject",
                "Đã từ chối, trả lại cho GDV sửa",
                "Từ chối, yêu cầu sửa",
                "bg-amber-600 hover:bg-amber-700 text-white",
            )

        def do_ksv_cancel():
            _open_reason_dialog(
                "Lý do huỷ — phiên trực này sẽ đóng, phải làm phiên khác cho ngày này",
                "ksv-cancel",
                "Đã huỷ phiên trực này",
                "Huỷ phiên trực",
                "bg-red-600 hover:bg-red-700 text-white",
            )

        with ui.row().classes("gap-3 mt-2"):
            ui.button("Xác nhận", icon="check_circle", on_click=do_ksv_confirm).classes(
                "bg-emerald-600 hover:bg-emerald-700 text-white"
            )
            ui.button("Từ chối — Yêu cầu sửa lại", icon="edit_note", on_click=do_ksv_reject).props(
                "outline color=amber-8"
            )
            ui.button("Từ chối — Huỷ phiên trực", icon="delete_forever", on_click=do_ksv_cancel).props(
                "outline color=red"
            )

    def _render_approved(ngay: str, rec: dict):
        _render_readonly_summary(rec)
        with ui.row().classes("items-center gap-2 mt-2 text-emerald-700"):
            ui.icon("verified", color="green")
            ui.label(
                f"Đã duyệt bởi {rec.get('ksv_decided_by_name') or '—'} lúc {rec.get('ksv_decided_at') or '—'}"
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
                try:
                    content = await asyncio.to_thread(
                        api.download, "/api/so-truc/export",
                        {"tu_ngay": tu_input.value, "den_ngay": den_input.value},
                    )
                except Exception as e:
                    if _handle_api_error(e):
                        return
                    ui.notify(f"Lỗi xuất Excel: {e}", type="negative")
                    return
                fname = f"so_truc_lich_su_{tu_input.value}_{den_input.value}.xlsx".replace("-", "")
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
                    params["tu_ngay"] = tu_input.value
                if den_input.value:
                    params["den_ngay"] = den_input.value
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
                with ui.column().classes("w-full border border-gray-200 rounded-xl gap-0 overflow-hidden"):
                    with ui.row().classes(
                        "w-full items-center gap-0 px-3 py-2 bg-blue-600 border-b border-gray-200 "
                        "text-xs font-semibold text-white"
                    ):
                        ui.label("Ngày").classes("w-28 border-r border-white/30 pr-2 mr-2")
                        ui.label("GDV 1 / GDV 2").classes("w-56 border-r border-white/30 pr-2 mr-2")
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
                    ui.label(f"{r.get('gdv1_name') or '—'} / {r.get('gdv2_name') or '—'}").classes(
                        "w-56 border-r border-gray-200 pr-2 mr-2 text-sm"
                    )
                    with ui.row().classes("w-44 border-r border-gray-200 pr-2 mr-2"):
                        _status_badge(r.get("status", "draft"))
                    ui.label(r.get("updated_at") or "").classes("flex-1 text-xs text-gray-400")
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
                            _label = "Lý do huỷ" if r.get("status") == "cancelled" else "Lý do từ chối gần nhất"
                            ui.label(f"{_label}: {r['reject_reason']}").classes(
                                "text-xs text-red-500 mt-1"
                            )
                        _result_link_block(ngay)

                row.on("click", toggle_detail)

        history_refresh["fn"] = load_history
        ui.timer(0.1, load_history, once=True)

    with ui.row().classes("w-full"):
        _sidebar("so_truc")
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
                        with _section_card("Chọn ngày trực", icon="calendar_month", accent="indigo"):
                            with ui.row().classes("w-full items-end gap-3 p-4"):
                                ngay_input = _date_picker_input("Ngày trực", state["ngay"])
                                ui.button(
                                    "Tải", icon="cloud_download",
                                    on_click=lambda: load_day(ngay_input.value),
                                ).props("outline")

                        with _section_card("Sổ trực trong ngày", icon="assignment_turned_in", accent="blue"):
                            main_area = ui.column().classes("w-full gap-2 p-4")
                    ui.timer(0.1, lambda: load_day(state["ngay"]), once=True)

                with ui.tab_panel(tab_lich_su):
                    with _section_card("Lịch sử sổ trực", icon="history", accent="emerald"):
                        with ui.column().classes("w-full gap-2 p-4"):
                            _build_history_panel()
