"""Trang chủ — Dashboard KPI."""
import asyncio
from datetime import date as _date, datetime as _datetime
from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _require_auth, _handle_api_error

# Sau giờ này trong ngày mà Sổ trực cuối ngày (Phòng Thanh toán) vẫn chưa có
# ai mở/chọn GDV thì nhắc trên trang chủ — ước lượng, chỉnh nếu không hợp
# thực tế giờ làm việc. Không chặn/bắt buộc gì, chỉ nhắc nhẹ.
_SO_TRUC_REMINDER_HOUR = 16


# CSS chỉ áp cho trang chủ (add_head_html mặc định shared=False → per-client).
# Lớp bọc .nicegui-content của NiceGUI có padding: 1rem cứng trong nicegui.css.
# Vùng nội dung cao đúng 100vh nằm trong lớp bọc đó → tổng 100vh + 32px, và 32px
# thừa đúng là thanh cuộn còn sót. Đặt padding về 0 mới thật sự hết cuộn.
# Tên phòng NOSTRO trong DB dài gần gấp đôi các phòng khác nên nhãn xuống 2 dòng,
# làm ô đó lệch hẳn so với các ô cùng hàng. Rút gọn chỉ ở chỗ hiển thị này — không
# đổi tên trong DB, vì tên đầy đủ còn dùng ở phiếu nghỉ phép, bìa tập và báo cáo.
# Tra theo code chứ không theo tên: đổi tên phòng không làm mất mapping.
_DEPT_SHORT = {"NOSTRO": "Phòng QLTK Nostro, Vostro"}

# Tài khoản quản trị — không phải người dùng nghiệp vụ, không đếm vào ô "Người dùng".
_ADMIN_ROLES = ("admin", "admin_l2")

_HOME_FIT_CSS = """
<style>
.nicegui-content { padding: 0 !important; gap: 0 !important; }
.q-page { min-height: 100vh !important; }
/* Chặn cuộn ở cấp trang: tránh thanh cuộn 1px do làm tròn pixel khi zoom.
   Nội dung vẫn cuộn được bên trong #app-content nếu màn hình quá thấp. */
html, body { overflow: hidden !important; }
</style>
"""


@ui.page("/home")
@ui.page("/")
async def dashboard_page():
    if not _require_auth():
        return
    # Không redirect chuyên viên sang /handovers nữa: mục "Trang chủ" luôn có trên
    # sidebar nên redirect làm nó thành mục bấm không bao giờ vào được. Việc đưa CV
    # đáp thẳng xuống Bàn giao chứng từ vẫn giữ, nhưng nằm ở trang login.
    await _sidebar("home")
    ui.add_head_html(_HOME_FIT_CSS)
    # Trang chủ khoá chiều cao đúng 1 viewport: 3 khối trên cùng cao cố định, biểu đồ
    # ăn hết phần còn lại. overflow-y-auto chỉ là lối thoát cho màn hình quá thấp.
    with _content_area() as _ca:
        _ca.classes(remove="min-h-screen p-6 overflow-x-auto",
                    add="h-screen p-4 gap-3 overflow-y-auto overflow-x-hidden")

        header_row = ui.row().classes("w-full items-center justify-between gap-3 flex-none")

        loading_row = ui.row().classes("w-full justify-center items-center py-10")
        with loading_row:
            ui.spinner(size="3em", color="red")
            ui.label("Đang tải...").classes("text-gray-500 ml-3 text-sm")
        content = ui.column().classes("w-full flex-1 min-h-0 gap-3")

        try:
            await ui.context.client.connected()
        except Exception:
            pass

        _today = _date.today()
        _has_so_truc = api.has_feature("menu.so_truc")
        try:
            # Bỏ /pending-counts: sidebar tự nạp số, Trang chủ không còn khối nào dùng
            results = await asyncio.gather(
                asyncio.to_thread(api.get, "/api/staff/"),
                asyncio.to_thread(api.get, "/api/departments/"),
                asyncio.to_thread(api.get, "/api/dashboard/summary"),
                asyncio.to_thread(api.get, "/api/leaves/today"),
                asyncio.to_thread(api.get, f"/api/so-truc/{_today.isoformat()}")
                if _has_so_truc else asyncio.sleep(0, result=None),
                return_exceptions=True,
            )
        except Exception as e:
            if isinstance(e, api.SessionExpiredError):
                ui.notify(str(e), type="warning")
                ui.navigate.to("/login")
                return
            results = [[], [], {}, {}, None]

        staff_list, depts, summary, today_leaves, so_truc_today = results
        for r in results:
            if isinstance(r, api.SessionExpiredError):
                ui.notify(str(r), type="warning")
                ui.navigate.to("/login")
                return
        staff_list = staff_list if isinstance(staff_list, list) else []
        depts      = depts      if isinstance(depts, list)      else []
        summary    = summary    if isinstance(summary, dict)    else {}
        today_leaves   = today_leaves if isinstance(today_leaves, dict) else {}
        leave_total    = today_leaves.get("total", 0)
        leave_by_dept  = today_leaves.get("by_dept", [])
        so_truc_today  = so_truc_today if isinstance(so_truc_today, dict) else None
        # Chưa có ai chọn GDV nào cho hôm nay → coi như "chưa mở sổ trực"
        _so_truc_chua_mo = bool(
            so_truc_today and so_truc_today.get("status") == "draft"
            and not so_truc_today.get("gdv1_id") and not so_truc_today.get("gdv2_id")
        )
        # Giờ máy chủ chạy app có thể lệch múi giờ VN — lấy "server_now" (đã
        # convert UTC+7 bởi _vn_now() phía backend) thay vì đồng hồ máy client.
        try:
            _server_hour = _datetime.fromisoformat(summary.get("server_now", "")).hour
        except ValueError:
            _server_hour = _datetime.now().hour

        loading_row.set_visibility(False)

        # Badge sidebar do khối "Công việc chờ xử lý" trong shared.py tự nạp.

        # Số người dùng không tính quản trị viên — CẢ hai cấp (admin, admin_l2).
        # Cấp 2 cũng là tài khoản quản trị, đếm vào đây thì con số nhảy lên mỗi
        # lần thêm một quản trị viên, trong khi ô này để nói "có bao nhiêu người
        # dùng nghiệp vụ".
        # /api/staff/ chỉ trả nhân sự phòng mình cho CV/TP/PP — nhãn phải nói đúng
        # phạm vi của con số, nếu không CV sẽ đọc "Người dùng: 8" là toàn trung tâm.
        _role = (api.get_current_user() or {}).get("role", "")
        _users_label = "Người dùng" if _role not in ("chuyen_vien", "truong_phong", "pho_phong") \
                       else "Nhân sự phòng"
        n_users = len([s for s in staff_list if s.get("role") not in _ADMIN_ROLES])
        stats = [
            (_users_label,      n_users,                                           "people",   "bg-red-50 border-red-200"),
            ("Phòng nghiệp vụ", len([d for d in depts if d.get("code") != "BGD"]), "business", "bg-blue-50 border-blue-200"),
        ]

        # Tiêu đề và 2 ô thống kê nằm chung một hàng — hai khối này trước đây chiếm
        # 2 hàng riêng nhưng cùng gần như trống, gộp lại tiết kiệm ~90px chiều cao.
        with header_row:
            with ui.column().classes("gap-0"):
                ui.label("Trang chủ").classes("text-xl font-bold text-red-900 leading-tight")
                ui.label("Hệ thống Trung tâm Thanh toán").classes("text-gray-500 text-xs")
            with ui.row().classes("items-center gap-2 flex-wrap justify-end"):
                for lbl, val, icon, colors in stats:
                    with ui.row().classes(
                        f"items-center gap-2 px-3 py-1.5 rounded-xl border {colors} shadow-sm"
                    ):
                        ui.icon(icon).classes("text-xl text-gray-500")
                        ui.label(str(val)).classes("text-xl font-bold text-gray-800 leading-none")
                        ui.label(lbl).classes("text-xs text-gray-500")

        with content:
            # Khối "Công việc đang chờ" đã chuyển hẳn về sidebar + trang /pending/<loại>.
            # Để lại đây sẽ là nơi thứ hai hiển thị cùng một thông tin, và là nơi duy nhất
            # người dùng phải quay về Trang chủ mới thấy được.

            # ── Nghỉ phép hôm nay ─────────────────────────────────────────────
            with ui.card().classes("w-full flex-none p-4 gap-3 rounded-xl shadow-sm bg-white border-2 border-red-400"):
                ui.label(f"Nghỉ phép hôm nay ({_today.strftime('%d/%m/%Y')})").classes("text-base font-semibold text-red-900")
                _by_dept_map = {d.get("dept_name", ""): d.get("count", 0) for d in leave_by_dept}
                # Thứ tự: BGD → Phòng Thanh toán → Phòng Tổng hợp → còn lại alpha
                _DEPT_PRI = {"Phòng Thanh toán": 1, "Phòng Tổng hợp": 2}
                _sorted_depts = sorted(depts, key=lambda d: (
                    0 if d.get("code") == "BGD" else 1,
                    _DEPT_PRI.get(d.get("name", ""), 99),
                    d.get("name", ""),
                ))
                _CELL_COLORS = [
                    "bg-red-50 border-red-200",
                    "bg-blue-50 border-blue-200",
                    "bg-green-50 border-green-200",
                    "bg-purple-50 border-purple-200",
                    "bg-yellow-50 border-yellow-200",
                    "bg-orange-50 border-orange-200",
                    "bg-teal-50 border-teal-200",
                    "bg-pink-50 border-pink-200",
                ]
                with ui.row().classes("w-full gap-2 flex-nowrap"):
                    # Ô tổng toàn trung tâm
                    _color0 = _CELL_COLORS[0]
                    _tc_num = "text-red-700 font-bold" if leave_total else "text-gray-500"
                    with ui.element("div").classes(f"flex-1 min-w-0 px-2 py-2 rounded-xl border {_color0} flex flex-col items-center justify-center").style("height:104px"):
                        ui.label(str(leave_total)).classes(f"text-4xl leading-none {_tc_num}")
                        ui.label("Toàn trung tâm").classes("text-xs font-semibold text-gray-600 mt-2 leading-tight text-center")
                    # Ô từng phòng ban
                    for _di, _dept in enumerate(_sorted_depts):
                        _dname   = _dept.get("name", "")
                        _cnt     = _by_dept_map.get(_dname, 0)   # tra count theo tên đầy đủ
                        _label   = _DEPT_SHORT.get(_dept.get("code", ""), _dname)
                        _color   = _CELL_COLORS[(_di + 1) % len(_CELL_COLORS)]
                        _num_cls = "text-red-700 font-bold" if _cnt else "text-gray-500"
                        with ui.element("div").classes(f"flex-1 min-w-0 px-2 py-2 rounded-xl border {_color} flex flex-col items-center justify-center").style("height:104px"):
                            ui.label(str(_cnt)).classes(f"text-4xl leading-none {_num_cls}")
                            ui.label(_label).classes("text-xs text-gray-600 mt-2 leading-tight text-center")

            # ── Nhắc "chưa mở Sổ trực cuối ngày" — chỉ Phòng Thanh toán thấy,
            # chỉ hiện sau 1 khung giờ nhất định, tự ẩn khi đã có người mở ──
            if _has_so_truc and _so_truc_chua_mo and _server_hour >= _SO_TRUC_REMINDER_HOUR:
                with ui.row().classes(
                    "w-full flex-none items-center gap-2 px-4 py-2.5 rounded-xl "
                    "border border-amber-300 bg-amber-50"
                ):
                    ui.icon("warning", color="amber-700").classes("text-lg")
                    ui.label(
                        f"Chưa có ai mở Sổ trực cuối ngày hôm nay ({_today.strftime('%d/%m/%Y')})."
                    ).classes("text-sm text-amber-800 flex-1")
                    ui.button(
                        "Mở ngay", icon="arrow_forward",
                        on_click=lambda: ui.navigate.to("/so_truc"),
                    ).props("dense flat color=amber-8")

            # ── Biểu đồ nộp chứng từ đúng hạn — chọn Tháng/Năm để xem ──
            # Nhãn NOSTRO lấy từ _DEPT_SHORT để trục X và ô nghỉ phép không lệch chữ nhau
            dept_slots = [
                ("PAYMENT", "Phòng Thanh toán"),
                ("ACCT",    "Phòng Kế toán"),
                ("SWIFT",   "Phòng Swift"),
                ("NOSTRO",  _DEPT_SHORT["NOSTRO"]),
            ]
            _today = _date.today()
            _year_opts  = list(range(_today.year, 2023, -1))
            _month_opts = {m: f"Tháng {m:02d}" for m in range(1, 13)}

            with ui.card().classes("w-full flex-1 min-h-0 p-3 gap-1 rounded-xl shadow-sm bg-white"):
                with ui.row().classes("w-full flex-none justify-between items-center flex-wrap gap-2"):
                    ui.label("Tỷ lệ nộp chứng từ đúng hạn").classes("text-sm font-semibold text-red-900")
                    with ui.row().classes("items-center gap-2"):
                        month_sel = ui.select(_month_opts, value=_today.month
                                              ).props("dense outlined").classes("w-32")
                        year_sel  = ui.select(_year_opts, value=_today.year
                                              ).props("dense outlined").classes("w-28")

                ui.label("Đúng hạn = nộp trong 1 ngày làm việc sau ngày giao dịch "
                         "(bỏ T7/CN, ngày lễ, ngày nghỉ phép của người nhận)"
                         ).classes("flex-none text-[11px] text-gray-500 italic leading-tight")

                chart_box = ui.column().classes("w-full flex-1 min-h-0 gap-0")

                def _render_chart(sm: dict):
                    # Vẽ lại toàn bộ vùng biểu đồ theo dữ liệu kỳ đã chọn
                    chart_box.clear()
                    ov  = sm.get("overall", {})
                    ot  = ov.get("on_time", 0)
                    lt  = ov.get("late", 0)
                    tot = ov.get("total", 0)
                    bd  = sm.get("by_dept", [])
                    by_code = {(r.get("dept_code") or "").upper(): r for r in bd}
                    labels  = [lbl for _, lbl in dept_slots]
                    ot_vals = [(by_code.get(c) or {}).get("on_time", 0) for c, _ in dept_slots]
                    lt_vals = [(by_code.get(c) or {}).get("late", 0)    for c, _ in dept_slots]
                    with chart_box:
                        if tot:
                            ui.label(f"Tổng {tot} chứng từ · {ot} đúng hạn · {lt} muộn"
                                     ).classes("flex-none text-[11px] text-gray-500")
                        _skipped = sm.get("no_submit_date", 0)
                        if _skipped:
                            ui.label(
                                f"Không tính {_skipped} chứng từ cũ chưa có dữ liệu ngày nộp. "
                                f"Xem chi tiết tại Báo cáo bàn giao chứng từ."
                            ).classes("flex-none text-[11px] text-gray-500 italic leading-tight")
                        if not bd:
                            ui.label("Chưa có dữ liệu bàn giao trong kỳ này."
                                     ).classes("text-gray-500 text-sm mt-1")
                        else:
                            # Grid tính bằng px (không phải %) để biểu đồ còn đọc được khi
                            # vùng vẽ bị nén trên màn hình thấp; ResizeObserver của echart
                            # tự vẽ lại khi cửa sổ đổi kích thước.
                            # barMaxWidth: chỉ 4 phòng trên toàn chiều ngang nên nếu không
                            # chặn, echart kéo cột rộng ~150px — đó là chỗ trông thô nhất.
                            ui.echart({
                                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                                "legend": {"data": ["Đúng hạn", "Nộp muộn"], "bottom": 0,
                                           "itemHeight": 10, "textStyle": {"fontSize": 11}},
                                "grid": {"left": 8, "right": 12, "top": 24, "bottom": 26, "containLabel": True},
                                "xAxis": {"type": "category", "data": labels,
                                          "axisLabel": {"interval": 0, "fontSize": 11}},
                                "yAxis": {"type": "value", "minInterval": 1},
                                "series": [
                                    {"name": "Đúng hạn", "type": "bar", "barGap": "10%", "barMaxWidth": 44,
                                     "data": ot_vals, "itemStyle": {"color": "#16a34a", "borderRadius": [3, 3, 0, 0]},
                                     "label": {"show": True, "position": "top", "fontSize": 11}},
                                    {"name": "Nộp muộn", "type": "bar", "barMaxWidth": 44,
                                     "data": lt_vals, "itemStyle": {"color": "#dc2626", "borderRadius": [3, 3, 0, 0]},
                                     "label": {"show": True, "position": "top", "fontSize": 11}},
                                ],
                            }).classes("w-full flex-1 min-h-0").style("min-height:180px; max-height:380px")

                _render_chart(summary)  # kỳ mặc định (tháng hiện tại) — dùng lại data đã tải

                async def _reload_chart():
                    chart_box.clear()
                    with chart_box:
                        ui.spinner(size="1.5em", color="red").classes("my-6")
                    try:
                        sm = await asyncio.to_thread(
                            api.get, "/api/dashboard/summary",
                            {"year": year_sel.value, "month": month_sel.value},
                        )
                    except Exception as e:
                        if _handle_api_error(e):
                            return
                        sm = {}
                    _render_chart(sm if isinstance(sm, dict) else {})

                month_sel.on_value_change(_reload_chart)
                year_sel.on_value_change(_reload_chart)
