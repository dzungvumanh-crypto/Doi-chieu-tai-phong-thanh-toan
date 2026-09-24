"""Ngăn kéo chi tiết một đơn nghỉ phép — tách khỏi `leaves/__init__.py` (728 dòng).

Thân hàm giữ NGUYÊN VĂN, chỉ đổi 17 tên trước đây mượn của hàm trang thành `ctx.<tên>`.

Vì sao là `ctx` chứ không phải 17 tham số: ba thứ trong đó (`leave_tabs`, `_nav_pending`,
`_nav_pending_th`) được tạo SAU chỗ định nghĩa hàm này. Closure cũ chạy được vì Python chỉ
tra tên lúc GỌI. Truyền theo giá trị lúc định nghĩa là ba thứ đó bằng None — hỏng đúng lúc
người dùng bấm nút, không test nào bắt. `ctx` đọc thuộc tính lúc gọi nên giữ nguyên hành vi ấy.
"""
import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Optional

from nicegui import app, ui

import frontend.api_client as api
from frontend.shared import _handle_api_error
from frontend.pages.leaves._chung import (
    _LEAVE_TYPE, _fmt_leave_dates, _gd_display, _leave_status_badge, _ten_tab,
)


@dataclass
class ChiTietCtx:
    """Hộp đựng những thứ ngăn kéo chi tiết mượn của trang.

    Điền dần trong lúc dựng trang — thứ nào chưa có thì để None và gán sau; hàm chỉ
    đọc lúc người dùng bấm mở một đơn, khi đó trang đã dựng xong.
    """
    # Dữ liệu người đang đăng nhập
    user_id: Optional[int] = None
    user_role: str = ""
    can_forward_th: bool = False
    pending_ids: Any = None

    # Thành phần giao diện
    detail_drawer: Any = None
    drawer_container: Any = None
    reject_dialog: Any = None
    leave_tabs: Any = None            # tạo sau — xem docstring module

    # Hàm của trang
    _ask_confirm: Optional[Callable] = None
    _borrow_confirm_or_run: Optional[Callable] = None
    _borrow_year_label: Optional[Callable] = None
    _load_resubmit_fields: Optional[Callable] = None
    _open_pdf_preview: Optional[Callable] = None
    _reject_cb: Optional[Callable] = None
    _sign_then_approve: Optional[Callable] = None
    _nav_pending: Optional[Callable] = None       # tạo sau
    _nav_pending_th: Optional[Callable] = None    # tạo sau
    open_detail: Optional[Callable] = None        # chính nó, để mở đơn khác từ trong ngăn kéo


async def mo_chi_tiet(leave: dict, ctx: "ChiTietCtx"):

    ctx.drawer_container.clear()

    with ctx.drawer_container:

        lid      = leave["id"]

        status   = leave["status"]

        is_owner = ctx.user_id is not None and leave.get("staff_id") == ctx.user_id

        in_pend  = lid in ctx.pending_ids

        _approver_roles = ("truong_phong", "pho_phong",
                           "giam_doc", "pho_giam_doc", "admin")
        _can_act = ctx.user_role in _approver_roles

        ksv_act  = status == "pending_ksv" and in_pend and ctx.user_role in ("truong_phong", "pho_phong")

        th_act   = status == "pending_tong_hop" and in_pend and (_can_act or ctx.can_forward_th)

        # gd_can_review (tính sẵn ở _LEAVE_JOIN_SQL): 0 khi người được chỉ định
        # duyệt là PGĐ nhưng giấy uỷ quyền hiện không còn hiệu lực hôm nay — ẩn
        # hẳn nút Phê duyệt/Từ chối trong trường hợp đó thay vì hiện nút rồi bấm
        # vào mới nhận 403 từ backend (gd_review/_can_gd_review) — banner cảnh
        # báo ở dưới vẫn còn, đây chỉ thêm việc ẨN nút cho khớp banner.
        gd_act   = (status == "pending_gd" and in_pend and ctx.user_role in ("giam_doc", "pho_giam_doc")
                    and leave.get("gd_can_review", True))

        # Đơn của GĐ đã tự động approved — TH chỉ cần "xác nhận đã biết" (thông báo),
        # không phải điều kiện duyệt.
        th_ack_act = (status == "approved" and leave.get("staff_role") == "giam_doc"
                      and not leave.get("tong_hop_approver_id"))



        with ui.row().classes("w-full bg-red-800 text-white px-5 py-4 items-center gap-2"):

            ui.icon("event_busy").classes("text-2xl")

            with ui.column().classes("gap-0"):

                ui.label("Chi tiết đơn nghỉ phép").classes("font-bold text-base")

                ui.label(leave.get("staff_name", "")).classes("text-red-200 text-sm")



        with ui.column().classes("px-5 py-4 gap-3 w-full"):

            with ui.row().classes("items-center gap-2"):

                ui.label("Trạng thái:").classes("text-sm text-gray-600 font-medium")

                _leave_status_badge(status, leave.get("status_label"))



            def _info(lbl, val):

                with ui.row().classes("w-full items-start gap-2"):

                    ui.label(lbl).classes("text-sm text-gray-500 w-28 shrink-0")

                    ui.label(str(val) if val else "→").classes("text-sm font-medium flex-1")

            def _goto_leave_new_tab(target_id: int):
                # Mở chi tiết đơn KHÁC (đơn gốc ↔ đơn điều chỉnh NPBB) ở TAB
                # TRÌNH DUYỆT MỚI (?open_id= được leaves_page() đọc và tự mở
                # đúng drawer chi tiết ngay khi tải trang xong) — không đổi nội
                # dung drawer đang mở ở tab hiện tại.
                ui.navigate.to(f"/leaves?open_id={target_id}", new_tab=True)



            _info("Phòng:", leave.get("department_name") or "→")

            _sd = leave.get("spread_dates")

            _s  = (leave.get("start_date") or "")[:10]

            _e  = (leave.get("end_date") or "")[:10]

            if _sd and len(_sd) >= 2:

                from datetime import date as _d

                with ui.row().classes("w-full items-start gap-2"):

                    ui.label("Ngày nghỉ:").classes("text-sm text-gray-500 w-28 shrink-0")

                    with ui.column().classes("flex-1 gap-0.5"):

                        for _dstr in sorted(_sd):

                            try:

                                ui.label(_d.fromisoformat(_dstr[:10]).strftime("%d/%m/%Y")).classes("text-sm font-medium")

                            except Exception:

                                ui.label(_dstr[:10]).classes("text-sm font-medium")

            else:

                _info("Từ ngày:", _s)

                _info("Đến ngày:", _e)

            _info("Số ngày nghỉ:", f"{leave.get('leave_days', '')} ngày")

            _info("Loại:", _LEAVE_TYPE.get(leave.get("leave_type", ""), leave.get("leave_type", "")))

            _info("Lý do:", leave.get("reason") or "→")

            # NPBB — đơn NÀY là đơn điều chỉnh: hiện lại ngày ĐÃ ĐĂNG KÝ của đơn
            # gốc để đối chiếu (đơn gốc trỏ qua adjusts_leave, xem npbb_adjust_leave()
            # ở backend).
            _adjusts = leave.get("adjusts_leave")
            if _adjusts:
                with ui.column().classes("w-full gap-1 p-3 bg-orange-50 border border-orange-200 rounded"):
                    ui.label("Điều chỉnh từ đơn nghỉ phép bắt buộc đã đăng ký").classes(
                        "text-xs font-medium text-orange-700")
                    ui.label(
                        f"Ngày đã đăng ký: {_fmt_leave_dates(_adjusts.get('start_date') or '', _adjusts.get('end_date') or '', _adjusts.get('spread_dates'))}"
                    ).classes("text-sm text-gray-700")
                    if _adjusts.get("id"):
                        ui.button(f"Xem đơn gốc #{_adjusts['id']}", icon="open_in_new",
                                  on_click=lambda _id=_adjusts["id"]: _goto_leave_new_tab(_id)
                                  ).props("flat dense no-caps").classes("text-orange-700 underline self-start px-0 min-h-0")

            # NPBB — đơn NÀY là đơn gốc: nếu đã có ai điều chỉnh, hiện trạng thái
            # đơn điều chỉnh liên kết (approved thì đơn gốc đã tự "Đã hủy - Đã điều
            # chỉnh", xem status_label ở backend).
            _npbb_adj = leave.get("npbb_adjustment")
            if _npbb_adj:
                _adj_status_vn = {
                    "pending_ksv": "Chờ KSV duyệt", "pending_tong_hop": "Chờ Tổng hợp",
                    "pending_gd": "Chờ Ban lãnh đạo duyệt", "approved": "Đã duyệt",
                    "rejected": "Bị từ chối", "cancelled": "Đã hủy",
                }.get(_npbb_adj.get("status"), _npbb_adj.get("status"))
                with ui.column().classes("w-full gap-1 p-3 bg-orange-50 border border-orange-200 rounded"):
                    ui.label(f"Có đơn điều chỉnh ngày NPBB ({_adj_status_vn})").classes(
                        "text-xs font-medium text-orange-700")
                    ui.label(
                        f"Ngày đề nghị điều chỉnh: {_fmt_leave_dates(_npbb_adj.get('start_date') or '', _npbb_adj.get('end_date') or '', _npbb_adj.get('spread_dates'))}"
                    ).classes("text-sm text-gray-700")
                    if _npbb_adj.get("id"):
                        ui.button(f"Xem đơn điều chỉnh #{_npbb_adj['id']}", icon="open_in_new",
                                  on_click=lambda _id=_npbb_adj["id"]: _goto_leave_new_tab(_id)
                                  ).props("flat dense no-caps").classes("text-orange-700 underline self-start px-0 min-h-0")



            if leave.get("is_direct"):

                # Khai báo hộ → không qua quy trình duyệt

                with ui.column().classes("w-full bg-purple-50 rounded-lg p-3 gap-1 border border-purple-100"):

                    ui.label("Khai báo hộ → Duyệt trực tiếp").classes("text-xs font-bold text-purple-700 uppercase")

                    _info("Người khai báo:", leave.get("declarer_name") or "→")

                    _info("Ghi chú:", "Đơn được khai báo và duyệt trực tiếp, không qua quy trình phê duyệt.")

            else:

                _is_admin = ctx.user_role == "admin"

                # Bước 1: KSV
                if leave.get("ksv_approver_id") or status == "pending_ksv":

                    with ui.column().classes("w-full bg-orange-50 rounded-lg p-3 gap-1 border border-orange-100"):

                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("Bước 1 → KSV phê duyệt").classes("text-xs font-bold text-orange-700 uppercase")
                            if _is_admin and status == "pending_ksv":
                                with ui.row().classes("gap-1"):
                                    async def _admin_ksv_approve(lv=leave, l=lid):
                                        async def _do(payload, _l=l):
                                            try:
                                                await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review", payload)
                                                ui.notify("Đã duyệt bước KSV! Tiếp tục duyệt bước TH.", type="positive")
                                                updated = await asyncio.to_thread(api.get, f"/api/leaves/{_l}")
                                                if updated: await ctx.open_detail(updated)
                                            except Exception as e:
                                                _handle_api_error(e)
                                        async def _run(_l=l):
                                            await ctx._sign_then_approve(_l, "ksv", f"/api/leaves/{_l}/preview",
                                                                     "Duyệt bước KSV", _do)
                                        await ctx._borrow_confirm_or_run(lv, _run)
                                    ui.button(icon="check", on_click=_admin_ksv_approve).props("round dense flat").classes("text-green-600 bg-green-50").tooltip("Phê duyệt KSV")
                                    async def _admin_ksv_reject(l=lid):
                                        async def _cb(reason, _l=l):
                                            try:
                                                await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review", {"action": "reject", "comment": reason})
                                                ctx.detail_drawer.hide(); ui.notify("Đã từ chối!", type="warning"); ctx._nav_pending()
                                            except Exception as e:
                                                _handle_api_error(e)
                                        ctx._reject_cb[0] = _cb; ctx.reject_dialog.open()
                                    ui.button(icon="close", on_click=_admin_ksv_reject).props("round dense flat").classes("text-red-600 bg-red-50").tooltip("Từ chối KSV")

                        _info("Người duyệt:", leave.get("ksv_approver_name") or "Chưa xác định")

                        if leave.get("ksv_approved_at"):
                            _info("Ngày duyệt:", leave["ksv_approved_at"][:10])
                            _info("Ý kiến:", leave.get("ksv_comment") or "→")
                            ui.label("✓ Đã phê duyệt").classes("text-xs text-green-600 font-semibold mt-1")
                        elif status != "pending_ksv" and leave.get("ksv_approver_id"):
                            ui.label("(Dữ liệu không ghi ngày duyệt)").classes("text-xs text-gray-500 italic")



                # Bước 2: Tổng hợp

                with ui.column().classes("w-full bg-yellow-50 rounded-lg p-3 gap-1 border border-yellow-100"):

                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Bước 2 → Phòng Tổng hợp").classes("text-xs font-bold text-yellow-700 uppercase")
                        if _is_admin and status == "pending_tong_hop":
                            with ui.row().classes("gap-1"):
                                async def _admin_th_approve(lv=leave, l=lid):
                                    async def _do(_l=l, _lv=lv):
                                        try:
                                            await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",
                                                {"action": "forward", "gd_approver_id": _lv.get("gd_approver_id"), "comment": None})
                                            ui.notify("Đã xác nhận TH! Tiếp tục duyệt bước GĐ.", type="positive")
                                            updated = await asyncio.to_thread(api.get, f"/api/leaves/{_l}")
                                            if updated: await ctx.open_detail(updated)
                                        except Exception as e:
                                            _handle_api_error(e)
                                    _th_borrow = lv.get("borrow_next_year_days") or 0
                                    _th_msg = "Xác nhận & chuyển lên Ban lãnh đạo?"
                                    if _th_borrow:
                                        _th_msg += (f" ⚠ Đơn này có sử dụng {_th_borrow:.0f} ngày phép "
                                                    f"của {ctx._borrow_year_label(lv)}.")
                                    ctx._ask_confirm("Xác nhận TH", _th_msg, _do, "Xác nhận", "bg-green-600")
                                ui.button(icon="check", on_click=_admin_th_approve).props("round dense flat").classes("text-green-600 bg-green-50").tooltip("Xác nhận TH")
                                async def _admin_th_reject(l=lid):
                                    async def _cb(reason, _l=l):
                                        try:
                                            await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review", {"action": "reject", "comment": reason})
                                            ctx.detail_drawer.hide(); ui.notify("Đã từ chối!", type="warning"); ctx._nav_pending()
                                        except Exception as e:
                                            _handle_api_error(e)
                                    ctx._reject_cb[0] = _cb; ctx.reject_dialog.open()
                                ui.button(icon="close", on_click=_admin_th_reject).props("round dense flat").classes("text-red-600 bg-red-50").tooltip("Từ chối TH")

                    _th_name = leave.get("tong_hop_approver_name")
                    _info("Người xử lý:", _th_name or "Chưa xử lý")

                    if leave.get("tong_hop_approved_at"):
                        _info("Ngày:", leave["tong_hop_approved_at"][:10])
                        _info("Ghi chú:", leave.get("tong_hop_comment") or "→")
                        ui.label("✓ Đã xác nhận").classes("text-xs text-green-600 font-semibold mt-1")
                    elif status not in ("pending_ksv", "pending_tong_hop") and _th_name:
                        ui.label("(Dữ liệu không ghi ngày xác nhận)").classes("text-xs text-gray-500 italic")

                    if th_ack_act and api.has_feature("leaves.forward_th"):
                        ui.label("Đơn của Giám đốc đã tự động duyệt — chỉ cần Tổng hợp xác nhận đã biết.").classes("text-xs text-gray-500 italic mt-1")
                        async def _th_ack(l=lid):
                            try:
                                await asyncio.to_thread(api.put, f"/api/leaves/{l}/tong-hop-ack", {})
                                ctx.detail_drawer.hide()
                                ui.notify("Đã xác nhận đã biết đơn của Giám đốc", type="positive")
                                ctx._nav_pending()
                            except Exception as e:
                                _handle_api_error(e)
                        ui.button("Xác nhận đã biết", icon="visibility", on_click=_th_ack).classes("bg-yellow-600 text-white text-xs mt-1")



                # Bước 3: GĐ

                with ui.column().classes("w-full bg-blue-50 rounded-lg p-3 gap-1 border border-blue-100"):

                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Bước 3 → Giám đốc phê duyệt").classes("text-xs font-bold text-blue-700 uppercase")
                        if _is_admin and status == "pending_gd":
                            with ui.row().classes("gap-1"):
                                async def _admin_gd_approve(lv=leave, l=lid):
                                    async def _do(payload, _l=l):
                                        try:
                                            await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review", payload)
                                            ctx.detail_drawer.hide(); ui.notify("Đã duyệt GĐ!", type="positive"); ctx._nav_pending()
                                        except Exception as e:
                                            _handle_api_error(e)
                                    async def _run(_l=l):
                                        await ctx._sign_then_approve(_l, "gd", f"/api/leaves/{_l}/preview",
                                                                 "Duyệt bước Giám đốc", _do)
                                    await ctx._borrow_confirm_or_run(lv, _run)
                                ui.button(icon="check", on_click=_admin_gd_approve).props("round dense flat").classes("text-green-600 bg-green-50").tooltip("Phê duyệt GĐ")
                                async def _admin_gd_reject(l=lid):
                                    async def _cb(reason, _l=l):
                                        try:
                                            await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review", {"action": "reject", "comment": reason})
                                            ctx.detail_drawer.hide(); ui.notify("Đã từ chối!", type="warning"); ctx._nav_pending()
                                        except Exception as e:
                                            _handle_api_error(e)
                                    ctx._reject_cb[0] = _cb; ctx.reject_dialog.open()
                                ui.button(icon="close", on_click=_admin_gd_reject).props("round dense flat").classes("text-red-600 bg-red-50").tooltip("Từ chối GĐ")

                    _info("Người duyệt:", _gd_display(leave) or "Chưa xác định")

                    # Đơn đứng ở bước GĐ mà người được chỉ định là PGĐ hết ủy quyền:
                    # backend trả danh sách "chờ duyệt" RỖNG cho họ nên drawer không
                    # dựng nút nào — không nói ra thì màn hình trông y như bị lỗi.
                    if status == "pending_gd" and not leave.get("gd_can_review", True):
                        with ui.column().classes("w-full bg-amber-50 border-l-4 border-amber-500 rounded p-2 gap-0 mt-1"):
                            ui.label("⚠ Ủy quyền của Phó Giám đốc đã hết hiệu lực").classes("text-xs font-bold text-amber-800")
                            ui.label("Đơn đang đứng lại: người được chỉ định duyệt là Phó Giám đốc, "
                                     "nhưng giấy ủy quyền không còn hiệu lực cho ngày hôm nay nên hệ thống "
                                     "không cho bấm duyệt. Cần gia hạn ủy quyền ở tab \"Ủy quyền GĐ\", "
                                     "hoặc nhờ Quản trị viên duyệt thay.").classes("text-xs text-amber-900 leading-snug")

                    if leave.get("gd_approved_at"):
                        _info("Ngày duyệt:", leave["gd_approved_at"][:10])
                        _info("Ý kiến:", leave.get("gd_comment") or "→")
                        ui.label("✓ Đã phê duyệt").classes("text-xs text-green-600 font-semibold mt-1")
                    elif status == "approved":
                        ui.label("(Dữ liệu không ghi ngày duyệt)").classes("text-xs text-gray-500 italic")



            ui.separator()



            async def _download_pdf(l=lid):

                try:

                    # timeout=160: backend cho Word cold-start tới 150s trước khi coi
                    # là treo thật (leave_pdf._CONVERT_TIMEOUT) — mặc định 60s của
                    # api.download() sẽ rớt về docx chưa ký oan dù server không lỗi.
                    content = await asyncio.to_thread(
                        api.download, f"/api/leaves/{l}/download", None, 160)

                    ctx._open_pdf_preview(content, f"phieu_nghi_phep_{l}.pdf")

                except Exception as e:

                    if _handle_api_error(e):
                        return

                    # Máy chủ không chuyển được PDF (chưa cài Word / Word treo)
                    # → vẫn phải lấy được phiếu, tải bản Word không chữ ký. Không
                    # xem trước được (browser không tự render docx) nên tải thẳng.
                    ui.notify(f"Không tạo được PDF — đang tải bản Word (không có chữ ký). ({e})",
                              type="warning", timeout=6000)
                    try:
                        content = await asyncio.to_thread(
                            api.download, f"/api/leaves/{l}/download", {"fmt": "docx"})
                        ui.download(content, f"phieu_nghi_phep_{l}.docx")
                    except Exception as e2:
                        _handle_api_error(e2)



            async def _download_docx(l=lid):

                # Bản Word render thẳng từ mẫu, KHÔNG qua leave_pdf.stamp() như PDF
                # nên không có ảnh chữ ký đã ký — chỉ dùng khi cần bản sửa được/không
                # cần chữ ký, không phải bản tương đương PDF.
                try:

                    content = await asyncio.to_thread(
                        api.download, f"/api/leaves/{l}/download", {"fmt": "docx"})

                    ui.download(content, f"phieu_nghi_phep_{l}.docx")

                except Exception as e:

                    _handle_api_error(e)



            with ui.row().classes("gap-2 flex-nowrap mt-4 border-t border-gray-100 pt-4 w-full items-center").style("display:grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));"):

                with ui.button("Tải phiếu", icon="download").props("outline").classes("text-gray-700 font-bold w-full"):
                    with ui.menu():
                        ui.menu_item("PDF (có chữ ký)", on_click=_download_pdf)
                        ui.menu_item("Word (không có chữ ký)", on_click=_download_docx)




                # KSV

                if ksv_act and api.has_feature("leaves.approve_ksv"):

                    async def _ksv_approve(lv=leave, l=lid):

                        async def _do(payload, _l=l):

                            try:

                                await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review", payload)

                                ctx.detail_drawer.hide()

                                ui.notify("Phê duyệt KSV thành công!", type="positive", timeout=3000)

                                ctx._nav_pending()

                            except Exception as e:

                                _handle_api_error(e)

                        async def _run(_l=l):
                            await ctx._sign_then_approve(_l, "ksv", f"/api/leaves/{_l}/preview",
                                                     "Xác nhận phê duyệt", _do)
                        await ctx._borrow_confirm_or_run(lv, _run)



                    def _ksv_reject_open(l=lid):

                        async def _cb(reason, _l=l):

                            try:

                                await asyncio.to_thread(api.put, f"/api/leaves/{_l}/ksv-review",

                                    {"action": "reject", "comment": reason})

                                ctx.detail_drawer.hide()

                                ui.notify("Đã từ chối đơn.", type="warning", timeout=3000)

                                ctx._nav_pending()

                            except Exception as e:

                                _handle_api_error(e)

                        ctx._reject_cb[0] = _cb

                        ctx.reject_dialog.open()



                    ui.button("Phê duyệt", icon="check_circle", on_click=_ksv_approve).classes("bg-green-600 text-white font-bold w-full")

                    ui.button("Từ chối", icon="cancel", on_click=_ksv_reject_open).classes("bg-red-600 text-white font-bold w-full")



                # TH → ẩn khi đơn lý recall request (backend cũng block, nhưng ẩn cho UX)

                if th_act and not leave.get("recall_reason") and api.has_feature("leaves.forward_th"):

                    def _th_forward_open(lv=leave, l=lid):
                        async def _do_forward(_l=l, _lv=lv):
                            try:
                                await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",
                                    {"action": "forward",
                                     "gd_approver_id": _lv.get("gd_approver_id"),
                                     "comment": None})
                                ctx.detail_drawer.hide()
                                ui.notify("Đã xác nhận & chuyển lên Ban lãnh đạo!", type="positive", timeout=3000)
                                ctx._nav_pending_th()
                            except Exception as e:
                                _handle_api_error(e)

                        # Chuyển cho PGĐ hết ủy quyền = đơn kẹt, chỉ Quản trị viên gỡ được.
                        # Không chặn (ủy quyền có thể được cấp sau) nhưng phải báo trước.
                        _warn = ("" if lv.get("gd_can_review", True) else
                                 " ⚠ Người duyệt là Phó Giám đốc nhưng giấy ủy quyền chưa/không còn "
                                 "hiệu lực hôm nay — chuyển lên bây giờ thì đơn sẽ đứng lại cho tới khi "
                                 "ủy quyền được gia hạn.")
                        _th_borrow = lv.get("borrow_next_year_days") or 0
                        if _th_borrow:
                            _warn += (f" ⚠ Đơn này có sử dụng {_th_borrow:.0f} ngày phép "
                                      f"của {ctx._borrow_year_label(lv)}.")
                        ctx._ask_confirm(
                            "Xác nhận phê duyệt",
                            f"Xác nhận đơn của {lv.get('staff_name','')} và chuyển lên Ban lãnh đạo?{_warn}",
                            _do_forward,
                            ok_label="Xác nhận",
                            ok_cls="bg-green-600"
                        )



                    def _th_reject_open(l=lid):

                        async def _cb(reason, _l=l):

                            try:

                                await asyncio.to_thread(api.post, f"/api/leaves/{_l}/tong-hop-review",

                                    {"action": "reject", "comment": reason})

                                ctx.detail_drawer.hide()

                                ui.notify("Đã từ chối đơn.", type="warning", timeout=3000)

                                ctx._nav_pending_th()

                            except Exception as e:

                                _handle_api_error(e)

                        ctx._reject_cb[0] = _cb

                        ctx.reject_dialog.open()



                    ui.button("Phê duyệt", icon="check_circle",
                              on_click=lambda lv=leave, l=lid: _th_forward_open(lv, l)).classes("bg-green-600 text-white font-bold w-full")

                    ui.button("Từ chối", icon="cancel", on_click=_th_reject_open).classes("bg-red-600 text-white font-bold w-full")



                # GĐ

                if gd_act and api.has_feature("leaves.approve_gd"):

                    async def _gd_approve(lv=leave, l=lid):

                        async def _do(payload, _l=l):

                            try:

                                await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review", payload)

                                ctx.detail_drawer.hide()

                                ui.notify("Phê duyệt Ban lãnh đạo thành công!", type="positive", timeout=3000)

                                ctx._nav_pending()

                            except Exception as e:

                                _handle_api_error(e)

                        async def _run(_l=l):
                            await ctx._sign_then_approve(_l, "gd", f"/api/leaves/{_l}/preview",
                                                     "Xác nhận phê duyệt", _do)
                        await ctx._borrow_confirm_or_run(lv, _run)



                    def _gd_reject_open(l=lid):

                        async def _cb(reason, _l=l):

                            try:

                                await asyncio.to_thread(api.put, f"/api/leaves/{_l}/gd-review",

                                    {"action": "reject", "comment": reason})

                                ctx.detail_drawer.hide()

                                ui.notify("Đã từ chối đơn.", type="warning", timeout=3000)

                                ctx._nav_pending()

                            except Exception as e:

                                _handle_api_error(e)

                        ctx._reject_cb[0] = _cb

                        ctx.reject_dialog.open()



                    ui.button("Phê duyệt", icon="check_circle", on_click=_gd_approve).classes("bg-green-600 text-white font-bold w-full")

                    ui.button("Từ chối", icon="cancel", on_click=_gd_reject_open).classes("bg-red-600 text-white font-bold w-full")



                if is_owner and status == "rejected" and api.has_feature("leaves.resubmit"):

                    async def _open_resubmit(lv=leave):
                        await ctx._load_resubmit_fields(lv, "Chỉnh sửa & Nộp lại")

                    ui.button("Sửa & Nộp lại", icon="refresh", on_click=_open_resubmit).classes("bg-orange-500 text-white text-sm")

                # Điều chỉnh ngày NPBB — chỉ đơn bat_buoc đã "Hoàn thành", tạo
                # đơn MỚI liên kết qua adjusts_leave_id (POST /npbb-adjust), KHÔNG
                # ghi đè đơn gốc — xem npbb_adjust_leave() ở backend. Ẩn nếu đã có
                # đơn điều chỉnh đang xử lý (chưa bị từ chối/hủy), VÀ ẩn nếu chính
                # đơn đang xem ĐÃ LÀ 1 đơn điều chỉnh (adjusts_leave_id có giá trị)
                # — backend chặn điều chỉnh chồng lên điều chỉnh (chỉ 1 cấp cha-con,
                # báo cáo NPBB chỉ dò đúng 1 cấp). Muốn điều chỉnh tiếp phải rút đơn
                # điều chỉnh này trước (nút "Hủy đơn"/rút đơn), đơn gốc tự khôi phục
                # "Hoàn thành" rồi mới bấm "Điều chỉnh ngày NPBB" lại từ đơn gốc đó.
                _pending_adj = leave.get("npbb_adjustment")
                _has_active_adj = bool(_pending_adj) and _pending_adj.get("status") not in ("rejected", "cancelled")
                if (is_owner and status == "approved" and leave.get("leave_type") == "bat_buoc"
                        and not _has_active_adj and not leave.get("adjusts_leave_id")
                        and api.has_feature("leaves.create")):

                    async def _open_npbb_adjust(lv=leave):
                        await ctx._load_resubmit_fields(lv, "Điều chỉnh ngày nghỉ phép bắt buộc",
                                                    lock_type=True, mode="npbb_adjust")

                    ui.button("Điều chỉnh ngày NPBB", icon="edit_calendar", on_click=_open_npbb_adjust).classes("bg-orange-500 text-white text-sm")

                # Hủy đơn bị từ chối (không resubmit nữa)
                if is_owner and status == "rejected":
                    async def _cancel_rejected(l=lid):
                        async def _do_cancel(_l=l):
                            try:
                                await asyncio.to_thread(api.patch, f"/api/leaves/{_l}/cancel", {})
                                ctx.detail_drawer.hide()
                                ui.notify("Đã hủy đơn thành công", type="positive")
                                # Quay lại đúng tab đang đứng (không ép về "Chờ duyệt")
                                app.storage.user["_leaves_goto_raw"] = _ten_tab(ctx.leave_tabs.value)
                                ui.navigate.to("/leaves")
                            except Exception as e:
                                _handle_api_error(e)
                        ctx._ask_confirm("Xác nhận hủy đơn",
                                     "Bạn có chắc muốn hủy đơn nghỉ này không?",
                                     _do_cancel,
                                     ok_label="Hủy đơn",
                                     ok_cls="bg-gray-600")
                    ui.button("Hủy đơn", icon="delete_forever", on_click=_cancel_rejected).classes("bg-gray-500 text-white text-sm")

                # Hủy
                # GĐ có toàn quyền huỷ đơn của chính mình bất cứ lúc nào — luôn hiện nút
                # dù feature "leaves.cancel" chưa được cấp qua cấu hình phân quyền.
                # Backend (cancel_leave) chỉ đòi hỏi quyền "leaves.cancel" riêng khi đơn
                # đã APPROVED — đơn còn đang chờ duyệt (pending_ksv/pending_tong_hop/
                # pending_gd) thì chủ đơn (hoặc admin) huỷ được ngay, không cần quyền
                # riêng đó. Trước đây nút này đòi "leaves.cancel" cho MỌI trạng thái,
                # nên đơn đang chờ duyệt của người chưa được cấp quyền lại không có nút
                # huỷ dù backend cho phép — khớp lại đúng với backend ở đây.
                _is_pending_status = status in ("pending_ksv", "pending_tong_hop", "pending_gd")
                _can_cancel_now = (is_owner or ctx.user_role == "admin") and status not in ("cancelled", "rejected") \
                        and (_is_pending_status or api.has_feature("leaves.cancel") or (is_owner and ctx.user_role == "giam_doc"))
                if _can_cancel_now:

                    def _cancel_open(l=lid, cur_status=status):
                        async def _do_cancel(_l=l, _st=cur_status):
                            try:
                                await asyncio.to_thread(api.patch, f"/api/leaves/{_l}/cancel", {})
                                ctx.detail_drawer.hide()
                                ui.notify("Đã hủy đơn thành công", type="warning")
                                # Quay lại đúng tab đang đứng — không ép theo trạng thái đơn
                                # (trước đây pending_tong_hop luôn nhảy sang "Chờ xác nhận TT"
                                # dù đang xem từ Dashboard hay tab khác).
                                app.storage.user["_leaves_goto_raw"] = _ten_tab(ctx.leave_tabs.value)
                                ui.navigate.to("/leaves")
                            except Exception as e:
                                _handle_api_error(e)
                        ctx._ask_confirm("Xác nhận hủy đơn",
                                     "Bạn có chắc muốn hủy đơn nghỉ này không?",
                                     _do_cancel, ok_label="Hủy đơn", ok_cls="bg-gray-600")

                    ui.button("Hủy đơn", icon="cancel", on_click=_cancel_open).classes("bg-gray-200 text-gray-700 text-sm")



                # Rút đơn (recall) → chủ nhân yêu cầu rút đơn đã duyệt.
                # Nếu đã có nút "Hủy đơn" (tự xử lý ngay) thì không cần thêm bước này nữa
                # vì kết quả giống nhau (đơn chuyển sang cancelled).

                has_recall = api.has_feature("leaves.recall")

                if is_owner and status == "approved" and not leave.get("recall_reason") \
                        and has_recall and not _can_cancel_now:

                    def _open_recall(l=lid):

                        async def _cb(reason, _l=l):

                            try:

                                await asyncio.to_thread(api.post, f"/api/leaves/{_l}/recall", {"reason": reason})

                                ctx.detail_drawer.hide()

                                ui.notify("Đã gửi yêu cầu rút → chờ Phòng Tổng hợp xác nhận", type="info")

                                ui.navigate.to("/leaves")

                            except Exception as e:

                                _handle_api_error(e)

                        ctx._reject_cb[0] = _cb

                        ctx.reject_dialog.open()



                    ui.button("Rút đơn", icon="undo", on_click=_open_recall).classes("bg-orange-100 text-orange-800 text-sm")



                # Xác nhận rút đơn → TH xác nhận khi đơn ở pending_tong_hop và recall

                if th_act and leave.get("recall_reason") and has_recall:

                    async def _confirm_recall(l=lid):

                        try:

                            await asyncio.to_thread(api.put, f"/api/leaves/{l}/recall-approve")

                            ctx.detail_drawer.hide()

                            ui.notify("Đã xác nhận rút đơn", type="positive")

                            ui.navigate.to("/leaves")

                        except Exception as e:

                            _handle_api_error(e)



                    ui.button("Xác nhận rút đơn", icon="undo", on_click=_confirm_recall).classes("bg-orange-700 text-white text-sm")



    ctx.detail_drawer.show()
