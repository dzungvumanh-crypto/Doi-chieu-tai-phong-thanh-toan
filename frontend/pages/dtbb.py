"""Trang Đối chiếu số liệu DTBB (Dự trữ bắt buộc) — Phòng Kế toán.

Upload ~18 file cân đối tài khoản theo loại tiền + 1 file tỷ giá (.XLS) → tính
bảng kê 6 cột theo CV 2353/NHNo-KHNV. "Tính toán" chỉ xem trước (không ghi DB);
bấm "Lưu vào lịch sử" riêng mới lưu, có cảnh báo nếu kỳ đã tồn tại.

Mỗi kỳ lưu gắn theo (report_date, branch_code) — mã chi nhánh tự suy từ tên file
cân đối (vd '1200USD20260720.XLS' → chi nhánh '1200'; không có tiền tố → '9999' =
toàn hệ thống/TSC). Kỳ mới lưu ở trạng thái "vàng" (chờ xác nhận); Trưởng/Phó phòng
Kế toán (không phải chính người vừa tạo/sửa) xác nhận → "xanh". Kỳ đã xanh không
ghi đè được cho tới khi bị bỏ xác nhận.
"""
import asyncio

from nicegui import ui
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth, _handle_api_error,
)


def _fmt_date_vn(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return ""
    return iso.replace("T", " ")[:16]


# DB/API luôn trả số đầy đủ (VND/USD thật) — chỉ quy đổi Triệu VND / Ngàn USD
# lúc hiển thị (màn hình + Excel xuất ra), không đổi giá trị lưu trữ.
_UNIT_NOTE = "Đơn vị: cột VND — Triệu VND; cột USD — Ngàn USD"
# TK413-VND đã gộp vào "VND dưới 12 tháng" — không hiện cột riêng (khác TK413-USD).
_COLS = [
    ("vnd_duoi12", "VND dưới 12 tháng (triệu)", 1_000_000),
    ("vnd_tu12",   "VND từ 12 tháng (triệu)",   1_000_000),
    ("usd_duoi12", "USD dưới 12 tháng (ngàn)",  1_000),
    ("usd_tu12",   "USD từ 12 tháng (ngàn)",    1_000),
    ("tk413_usd",  "TK413-USD (ngàn)",          1_000),
]

_FORMULA_NOTE_1 = (
    "1. Thực hiện theo CV 2353/NHNo-KHNV ngày 03/04/2020 về thực hiện Thông tư "
    "30/2019/TT-NHNN — danh mục tài khoản tại phụ lục đính kèm."
)
_FORMULA_NOTE_2 = (
    "2. Đối với cách tính DTBB bằng ngoại tệ: tỷ giá BQ mua chuyển khoản cho USD — sai số "
    "~0,0001% do làm tròn số, nếu sai số quá nhiều, cần xem lại file trích xuất hoặc liên "
    "hệ admin."
)
_FORMULA_NOTE_3 = (
    "3. File cân đối được trích xuất tại màn hình GLCB41, CĐ1000 (Sub Branch, Including "
    "1056); lưu tên theo đúng cấu trúc <mã tiền><YYYYMMDD> (vd VND20260715...); trích "
    "xuất thêm CN 9300 (đặt tên file theo mẫu 9300USD20260715); trích xuất file TIGIA tại "
    "màn hình CSER01 của đúng ngày cần tính toán dữ liệu."
)

def _fmt_col(value: float, divisor: int) -> str:
    return f"{value / divisor:,.2f}"


@ui.page("/dtbb")
async def dtbb_page():
    if not _require_auth():
        return
    user = api.get_current_user()
    user_id = user.get("id") if user else None
    # Gate bằng mã quyền, y hệt sidebar và backend (_QUYEN_DUNG trong api/dtbb.py) —
    # ba nơi đọc cùng một mã nên không thể lệch nhau. Trước đây gate theo mã phòng
    # ACCT; xem mục "Phân quyền" trong docs/DESIGN.md.
    if not api.has_feature("menu.dtbb"):
        ui.navigate.to("/home")
        return
    can_be_ksv = api.has_feature("dtbb.confirm")

    state = {"files": {}, "result": None, "error_files": set()}

    with ui.row().classes("w-full"):
        await _sidebar("dtbb")
        with _content_area():
            _page_header("Đối chiếu số liệu cơ sở DTBB")

            with ui.card().classes("w-full p-4 mb-4 bg-blue-50 border border-blue-200"):
                with ui.row().classes("items-start gap-2 no-wrap"):
                    ui.icon("info").classes("text-blue-600 text-lg shrink-0 mt-0.5")
                    with ui.column().classes("gap-0.5"):
                        ui.label(_FORMULA_NOTE_1).classes("text-xs text-blue-900 leading-relaxed")
                        ui.label(_FORMULA_NOTE_2).classes("text-xs text-blue-900 leading-relaxed")
                        ui.label(_FORMULA_NOTE_3).classes("text-xs text-blue-900 leading-relaxed")

            # ══ Card 1: Upload ═══════════════════════════════════════════════
            with ui.card().classes("w-full p-5 mb-4"):
                ui.label("Tải lên file cân đối theo loại tiền + file tỷ giá").classes(
                    "text-base font-semibold text-red-800 mb-1"
                )
                ui.label(
                    "Chọn (hoặc kéo thả) toàn bộ file .XLS của kỳ cần tính — cả file cân đối "
                    "từng loại tiền lẫn file tỷ giá. Hệ thống tự nhận diện, không cần phân loại. "
                    "Mỗi lượt chỉ gồm file của đúng 1 chi nhánh (mã chi nhánh tự đọc từ tên file)."
                ).classes("text-xs text-gray-500 mb-3")

                file_area = ui.grid(columns=3).classes("w-full gap-1 mb-3")

                def _render_files():
                    file_area.clear()
                    with file_area:
                        if not state["files"]:
                            ui.label("Chưa có file nào").classes("text-xs text-gray-500 italic")
                        for name in sorted(state["files"]):
                            is_bad = name in state["error_files"]
                            row_cls = "items-center gap-2 no-wrap rounded px-1"
                            if is_bad:
                                row_cls += " bg-red-50 border border-red-300"
                            with ui.row().classes(row_cls):
                                icon = ui.icon("error" if is_bad else "description").classes(
                                    "text-sm " + ("text-red-600" if is_bad else "text-gray-500")
                                )
                                if is_bad:
                                    icon.tooltip(
                                        "File này gây lỗi ở lần tính gần nhất — xem thông báo chi tiết"
                                    )
                                ui.label(name).classes(
                                    "text-xs flex-1 " + ("text-red-800 font-medium" if is_bad else "")
                                )
                                ui.button(
                                    icon="close", on_click=lambda n=name: _remove_file(n)
                                ).props("flat dense round size=sm").classes("text-gray-400")

                def _remove_file(name: str):
                    state["files"].pop(name, None)
                    state["error_files"].discard(name)
                    _render_files()

                async def on_upload(e):
                    name = e.name
                    if not name.lower().endswith(".xls"):
                        ui.notify(f"'{name}' không phải file .XLS, bỏ qua", type="warning")
                        return
                    # Đọc file (I/O) là việc đồng bộ — chạy thẳng trong handler sẽ chặn
                    # event loop của tiến trình frontend DÙNG CHUNG cho mọi người dùng
                    # đang mở web, không riêng người đang upload (đúng khuôn mẫu
                    # asyncio.to_thread đã dùng ở doi_soat_citad.py). File càng lớn/càng
                    # nhiều file liên tiếp thì càng khựng rõ cho người khác.
                    state["files"][name] = await asyncio.to_thread(e.content.read)
                    # Tải lại đúng tên file trước đó từng báo lỗi — xoá cờ đỏ ngay, không
                    # để hiển thị lỗi cũ trong khi nội dung mới có thể đã đúng (chỉ sai
                    # hiển thị, không ảnh hưởng số liệu thật vì Tính toán luôn dùng bytes
                    # mới nhất — nhưng dễ gây hiểu nhầm "chưa sửa được").
                    state["error_files"].discard(name)
                    _render_files()

                uploader = ui.upload(
                    multiple=True, auto_upload=True, on_upload=on_upload,
                ).props('accept=".xls,.XLS" flat dense label="Chọn file .XLS..."').classes("w-full")

                _render_files()

                with ui.row().classes("items-center gap-3 mt-3"):
                    calc_btn = ui.button("Tính toán", icon="calculate").classes("bg-red-800 text-white")
                    clear_btn = ui.button("Xoá hết", icon="delete_sweep").props("outline color=grey")

                    def _clear_all():
                        state["files"] = {}
                        state["result"] = None
                        state["error_files"] = set()
                        result_area.clear()
                        _render_files()
                        uploader.reset()

                    clear_btn.on("click", _clear_all)

            # ══ Card 2: Kết quả xem trước ═══════════════════════════════════════
            result_area = ui.column().classes("w-full")

            async def do_calculate():
                if not state["files"]:
                    ui.notify("Chưa chọn file nào", type="warning")
                    return
                calc_btn.props("loading disable")
                result_area.clear()
                try:
                    files_payload = [
                        ("files", (name, content, "application/octet-stream"))
                        for name, content in state["files"].items()
                    ]
                    result = await asyncio.to_thread(api.post_upload, "/api/dtbb/calculate", files_payload)
                    state["result"] = result
                    state["error_files"] = set()  # tính thành công — xoá đánh dấu lỗi cũ (nếu có)
                    _render_files()
                    _render_result(result, readonly=False)
                except Exception as e:
                    # ApiFileError kèm .filenames — tô đỏ đúng file gây lỗi trong danh sách
                    # đã chọn, không phải đoán/regex lại chuỗi thông báo.
                    state["error_files"] = set(getattr(e, "filenames", None) or [])
                    _render_files()
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tính toán: {e}", type="negative", multi_line=True, close_button=True)
                finally:
                    calc_btn.props(remove="loading disable")

            calc_btn.on("click", do_calculate)

            def _render_result(r: dict, readonly: bool):
                with result_area:
                    with ui.card().classes("w-full p-5 mb-4"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.label(
                                f"Cơ sở tính DTBB ngày {_fmt_date_vn(r['report_date'])} "
                                f"— chi nhánh {r['branch_code']} (từ {r['file_count']} file)"
                                + ("  [xem lại từ lịch sử]" if readonly else "")
                            ).classes("text-base font-semibold text-red-800")

                        if r.get("unconverted_ccy"):
                            with ui.row().classes(
                                "items-start gap-2 bg-orange-50 border border-orange-300 rounded p-2 mb-3"
                            ):
                                ui.icon("warning").classes("text-orange-600 text-base shrink-0")
                                ui.label(
                                    "Mã tiền có số dư nhưng KHÔNG quy đổi được (thiếu tỷ giá — không "
                                    "cộng vào tổng USD bên dưới): " + ", ".join(r["unconverted_ccy"])
                                ).classes("text-xs text-orange-900")

                        if r.get("netted_9300_ccy"):
                            with ui.row().classes(
                                "items-start gap-2 bg-blue-50 border border-blue-300 rounded p-2 mb-3"
                            ):
                                ui.icon("difference").classes("text-blue-700 text-base shrink-0")
                                ui.label(
                                    "Chi nhánh 9999 — đã trừ số liệu chi nhánh 9300 theo từng dòng tài "
                                    "khoản cho mã tiền: " + ", ".join(r["netted_9300_ccy"])
                                ).classes("text-xs text-blue-900")

                        if not readonly:
                            # all_ccy_codes/currencies_used chỉ có ở kết quả tính trực tiếp
                            # (đọc từ file tygia vừa upload) — kỳ nạp lại từ lịch sử không có
                            # file gốc nên không tái tạo được danh sách này.
                            ui.label("Các loại tiền đã có file (tô vàng) / chưa có (trắng):").classes(
                                "text-xs text-gray-500 mb-1"
                            )
                            used = set(r["currencies_used"])
                            with ui.row().classes("w-full gap-1 flex-wrap mb-3"):
                                for ccy in r["all_ccy_codes"]:
                                    co = ccy in used
                                    ui.label(ccy).classes(
                                        "px-2 py-1 rounded text-xs font-medium border "
                                        + ("bg-yellow-300 border-yellow-500 text-yellow-900"
                                           if co else "bg-white border-gray-300 text-gray-400")
                                    )

                        _am_labels = [label for key, label, _ in _COLS if r[key] < 0]
                        if _am_labels:
                            # Chỉ cảnh báo, KHÔNG chặn — số âm có thể hợp lệ (nghiệp vụ
                            # trừ chi nhánh 9300 theo từng dòng tài khoản), nhưng cũng có
                            # thể do file nguồn sai — cần người xem tự soát trước khi lưu.
                            with ui.row().classes(
                                "items-start gap-2 bg-red-50 border border-red-300 rounded p-2 mb-3"
                            ):
                                ui.icon("error_outline").classes("text-red-600 text-base shrink-0")
                                ui.label(
                                    "Có giá trị tổng bị ÂM — kiểm tra lại trước khi lưu (số âm có "
                                    "thể hợp lệ nếu do trừ CN 9300, nhưng cũng có thể do file nguồn "
                                    "sai): " + ", ".join(_am_labels)
                                ).classes("text-xs text-red-900")

                        ui.label(_UNIT_NOTE).classes("text-xs italic text-gray-500 mb-2")
                        with ui.row().classes("w-full gap-3 flex-wrap"):
                            for key, label, divisor in _COLS:
                                with ui.card().classes("p-3 flex-1 min-w-[160px]"):
                                    ui.label(label).classes("text-xs text-gray-500 mb-1")
                                    ui.label(_fmt_col(r[key], divisor)).classes(
                                        "text-lg font-bold text-gray-800"
                                    )

                        if r.get("details"):
                            # Hiện cả khi vừa tính (readonly=False) lẫn khi xem lại từ lịch
                            # sử — tô đỏ dòng nào có giá trị âm để soát ngay tại đây, không
                            # phải chỉ dựa vào khung cảnh báo tổng ở trên.
                            ui.label("Chi tiết theo mã tiền:").classes(
                                "text-xs text-gray-500 mt-3 mb-1"
                            )
                            columns = [
                                {"name": "ccy", "label": "Mã tiền", "field": "ccy", "align": "left"},
                                {"name": "rate", "label": "Tỷ giá → VND", "field": "rate"},
                                {"name": "g1", "label": "Dưới 12 tháng (nguyên tệ)", "field": "g1"},
                                {"name": "g2", "label": "Từ 12 tháng (nguyên tệ)", "field": "g2"},
                                {"name": "tk413", "label": "TK413 (nguyên tệ)", "field": "tk413"},
                            ]
                            # rate_usd_to_vnd = 0 cho kỳ lưu trước khi có cột này — không tái
                            # tạo được USD quy đổi, ẩn hẳn 2 cột thay vì hiện số sai/chia 0.
                            rate_usd = r.get("rate_usd_to_vnd") or 0
                            if rate_usd:
                                columns += [
                                    {"name": "usd_g1", "label": "USD quy đổi (dưới 12)", "field": "usd_g1"},
                                    {"name": "usd_g2", "label": "USD quy đổi (từ 12)", "field": "usd_g2"},
                                ]

                            def _usd_quydoi(d: dict) -> tuple[float | None, float | None]:
                                """USD tự thân không quy đổi (giữ nguyên); VND và mã tiền chưa
                                quy đổi được (rate=None) → None (hiện "—", không cộng vào tổng)."""
                                if d["ccy"] == "USD":
                                    return d["group1_native"], d["group2_native"]
                                if d["ccy"] == "VND" or d.get("rate_to_vnd") is None:
                                    return None, None
                                r2u = d["rate_to_vnd"] / rate_usd
                                return d["group1_native"] * r2u, d["group2_native"] * r2u

                            rows = []
                            tong_g1 = tong_g2 = 0.0  # USD quy đổi từ ngoại tệ khác — KHÔNG gồm USD
                            for d in r["details"]:
                                row = {
                                    "ccy": d["ccy"],
                                    "rate": f"{d['rate_to_vnd']:,.2f}" if d.get("rate_to_vnd") is not None else "—",
                                    "g1": f"{d['group1_native']:,.2f}",
                                    "g2": f"{d['group2_native']:,.2f}",
                                    "tk413": f"{d['tk413_native']:,.2f}",
                                    # Tô đỏ cả dòng nếu bất kỳ giá trị nào âm — số âm có thể
                                    # hợp lệ (trừ CN 9300) nhưng cũng có thể do file sai, cần
                                    # người xem chú ý đúng dòng thay vì chỉ thấy cảnh báo tổng.
                                    "is_negative": (
                                        d["group1_native"] < 0 or d["group2_native"] < 0
                                        or d["tk413_native"] < 0
                                    ),
                                }
                                if rate_usd:
                                    ug1, ug2 = _usd_quydoi(d)
                                    row["usd_g1"] = f"{ug1:,.2f}" if ug1 is not None else "—"
                                    row["usd_g2"] = f"{ug2:,.2f}" if ug2 is not None else "—"
                                    if d["ccy"] != "USD" and ug1 is not None:
                                        tong_g1 += ug1
                                        tong_g2 += ug2
                                rows.append(row)
                            if rate_usd:
                                tong_row = {
                                    "ccy": "Tổng ngoại tệ khác", "rate": "", "g1": "", "g2": "", "tk413": "",
                                    "usd_g1": f"{tong_g1:,.2f}", "usd_g2": f"{tong_g2:,.2f}",
                                    "is_negative": False,
                                }
                                # Đặt ngay trên dòng USD để dễ đối chiếu (USD gốc cạnh tổng
                                # quy đổi từ ngoại tệ khác) — details không cố định thứ tự
                                # VND/USD ở đầu, phải tìm đúng vị trí USD trong rows đã build.
                                usd_idx = next(
                                    (i for i, row in enumerate(rows) if row["ccy"] == "USD"), len(rows)
                                )
                                rows.insert(usd_idx, tong_row)
                            detail_table = ui.table(columns=columns, rows=rows, row_key="ccy").classes(
                                "w-full"
                            ).props("dense flat")
                            detail_table.add_slot("body", r"""
                                <q-tr :props="props" :class="props.row.is_negative ? 'bg-red-50 text-red-900' : ''">
                                  <q-td v-for="col in props.cols" :key="col.name" :props="props">{{ col.value }}</q-td>
                                </q-tr>
                            """)

                        if not readonly:
                            save_btn = ui.button(
                                "Lưu vào lịch sử", icon="save",
                                on_click=lambda: do_save(r, save_btn),
                            ).classes("bg-red-800 text-white mt-4")

            async def do_save(r: dict, save_btn, confirm_overwrite: bool = False):
                save_btn.props("loading disable")
                body = {**r, "confirm_overwrite": confirm_overwrite}
                try:
                    resp = await asyncio.to_thread(api.post, "/api/dtbb/save", body)
                    if resp.get("needs_confirmation"):
                        save_btn.props(remove="loading disable")
                        _confirm_overwrite_dialog(r, save_btn, resp)
                        return
                    ui.notify(
                        f"Đã {'ghi đè' if resp.get('overwritten') else 'lưu'} kỳ "
                        f"{_fmt_date_vn(r['report_date'])} (chi nhánh {r['branch_code']}) vào lịch sử — "
                        "trạng thái vàng, chờ Trưởng/Phó phòng Kế toán xác nhận.",
                        type="positive", multi_line=True,
                    )
                    await _refresh_history()
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi lưu: {e}", type="negative", multi_line=True, close_button=True)
                finally:
                    save_btn.props(remove="loading disable")

            def _confirm_overwrite_dialog(r: dict, save_btn, resp: dict):
                with ui.dialog() as dialog, ui.card().classes("p-5"):
                    ui.label(
                        f"Kỳ {_fmt_date_vn(r['report_date'])} (chi nhánh {r['branch_code']}) đã có dữ liệu"
                    ).classes("font-semibold text-red-800 mb-2")
                    who = resp.get("existing_touched_by_name") or "?"
                    when = _fmt_dt(resp.get("existing_touched_at"))
                    ui.label(f"Lưu lần gần nhất bởi {who} lúc {when}. Ghi đè bằng dữ liệu vừa tính?").classes(
                        "text-sm text-gray-600 mb-4"
                    )
                    with ui.row().classes("gap-2 justify-end w-full"):
                        ui.button("Huỷ", on_click=lambda: dialog.close()).props("outline color=grey")

                        async def _confirm():
                            dialog.close()
                            await do_save(r, save_btn, confirm_overwrite=True)
                        ui.button("Ghi đè", icon="save", on_click=_confirm).classes(
                            "bg-red-800 text-white"
                        )
                dialog.open()

            # ══ Card 3: Lịch sử ══════════════════════════════════════════════
            ui.separator().classes("my-4")
            ui.label("Dữ liệu cơ sở DTBB đã lưu").classes("text-base font-semibold text-red-800 mb-2")
            history_area = ui.column().classes("w-full")

            async def download_period(report_date: str, branch_code: str):
                try:
                    data = await asyncio.to_thread(
                        api.get_bytes, f"/api/dtbb/export/{report_date}/{branch_code}"
                    )
                    ui.download(data, filename=f"dtbb_{report_date}_{branch_code}.xlsx")
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải file: {e}", type="negative")

            async def load_period(report_date: str, branch_code: str):
                try:
                    detail = await asyncio.to_thread(
                        api.get, f"/api/dtbb/history/{report_date}/{branch_code}"
                    )
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi nạp lại kỳ: {e}", type="negative")
                    return
                result_area.clear()
                _render_result(detail, readonly=True)
                ui.notify(
                    f"Đã nạp lại kỳ {_fmt_date_vn(report_date)} (chi nhánh {branch_code}) để xem",
                    type="info",
                )

            async def do_confirm(report_id: int, btn):
                btn.props("loading disable")
                try:
                    await asyncio.to_thread(api.post, f"/api/dtbb/{report_id}/confirm")
                    ui.notify("Đã xác nhận kỳ DTBB", type="positive")
                    await _refresh_history()  # vẽ lại toàn bộ dòng — btn cũ bị huỷ, không cần gỡ loading
                except Exception as e:
                    btn.props(remove="loading disable")
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi xác nhận: {e}", type="negative", multi_line=True, close_button=True)

            async def do_unconfirm(report_id: int, btn):
                btn.props("loading disable")
                try:
                    await asyncio.to_thread(api.post, f"/api/dtbb/{report_id}/unconfirm")
                    ui.notify("Đã bỏ xác nhận — kỳ quay về trạng thái chờ (vàng)", type="info")
                    await _refresh_history()
                except Exception as e:
                    btn.props(remove="loading disable")
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi bỏ xác nhận: {e}", type="negative", multi_line=True, close_button=True)

            async def do_delete(report_id: int, report_date: str, branch_code: str, btn):
                with ui.dialog() as confirm, ui.card():
                    ui.label(
                        f"Xoá kỳ DTBB ngày {_fmt_date_vn(report_date)} — chi nhánh {branch_code}?"
                    ).classes("font-semibold")
                    ui.label("Thao tác này không hoàn tác được.").classes("text-sm text-gray-500")
                    with ui.row().classes("w-full justify-end gap-2 mt-3"):
                        ui.button("Huỷ", on_click=lambda: confirm.submit(False)).props("flat")
                        ui.button("Xoá", on_click=lambda: confirm.submit(True)).classes(
                            "bg-red-700 text-white"
                        )
                if not await confirm:
                    return
                btn.props("loading disable")
                try:
                    await asyncio.to_thread(api.delete, f"/api/dtbb/{report_id}")
                    ui.notify("Đã xoá kỳ DTBB", type="positive")
                    await _refresh_history()  # vẽ lại toàn bộ dòng — btn cũ bị huỷ, không cần gỡ loading
                except Exception as e:
                    btn.props(remove="loading disable")
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi xoá: {e}", type="negative", multi_line=True, close_button=True)

            async def _refresh_history():
                try:
                    items = await asyncio.to_thread(api.get, "/api/dtbb/history")
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(f"Lỗi tải lịch sử: {e}", type="negative")
                    return
                history_area.clear()
                with history_area:
                    if not items:
                        ui.label("Chưa có kỳ nào được lưu").classes("text-xs text-gray-500 italic")
                        return
                    ui.label(_UNIT_NOTE + " · Trạng thái: vàng = chờ xác nhận, xanh = đã xác nhận").classes(
                        "text-xs italic text-gray-500 mb-2"
                    )
                    columns = [
                        {"name": "vnd_duoi12",  "label": "VND<12 (triệu)",    "field": "vnd_duoi12_fmt"},
                        {"name": "vnd_tu12",    "label": "VND≥12 (triệu)",    "field": "vnd_tu12_fmt"},
                        {"name": "usd_duoi12",  "label": "USD<12 (ngàn)",     "field": "usd_duoi12_fmt"},
                        {"name": "usd_tu12",    "label": "USD≥12 (ngàn)",     "field": "usd_tu12_fmt"},
                        {"name": "tk413_usd",   "label": "TK413-USD (ngàn)",  "field": "tk413_usd_fmt"},
                        {"name": "toucher",     "label": "Lưu bởi",           "field": "toucher", "align": "left"},
                    ]
                    for it in items:
                        row = {"toucher": it.get("updated_by_name") or it["created_by_name"]}
                        for key, _, divisor in _COLS:
                            row[f"{key}_fmt"] = _fmt_col(it[key], divisor)
                        toucher_id_touched = it.get("updated_by") or it.get("created_by")
                        report_id = it["id"]
                        is_confirmed = it["status"] == "confirmed"
                        with ui.row().classes("w-full items-center gap-3 mb-2 no-wrap"):
                            with ui.column().classes("w-28 shrink-0 gap-0"):
                                ui.label(_fmt_date_vn(it["report_date"])).classes("text-sm font-medium")
                                ui.label(f"CN {it['branch_code']}").classes("text-xs text-gray-500")
                            ui.icon("circle").classes(
                                ("text-green-500" if is_confirmed else "text-yellow-500") + " text-xs shrink-0"
                            ).tooltip("Đã xác nhận" if is_confirmed else "Chờ xác nhận")
                            ui.table(columns=columns, rows=[row], row_key="toucher").classes(
                                "flex-1"
                            ).props("dense flat hide-bottom")
                            ui.button(
                                icon="visibility",
                                on_click=lambda d=it["report_date"], b=it["branch_code"]: load_period(d, b),
                            ).props("flat dense round").tooltip("Nạp lại xem chi tiết")
                            ui.button(
                                icon="download",
                                on_click=lambda d=it["report_date"], b=it["branch_code"]: download_period(d, b),
                            ).props("flat dense round").tooltip("Tải Excel")
                            if not is_confirmed:
                                btn_delete = ui.button(icon="delete").props(
                                    "flat dense round color=red"
                                ).tooltip("Xoá kỳ này")
                                btn_delete.on(
                                    "click",
                                    lambda rid=report_id, d=it["report_date"], b=it["branch_code"],
                                           btn=btn_delete: do_delete(rid, d, b, btn),
                                )
                            if can_be_ksv:
                                if is_confirmed:
                                    btn_unconfirm = ui.button("Bỏ xác nhận", icon="undo").props(
                                        "flat dense color=orange"
                                    ).tooltip("Đưa về trạng thái vàng")
                                    btn_unconfirm.on(
                                        "click",
                                        lambda rid=report_id, b=btn_unconfirm: do_unconfirm(rid, b),
                                    )
                                elif user_id is not None and user_id != toucher_id_touched:
                                    btn_confirm = ui.button("Xác nhận", icon="check_circle").props(
                                        "flat dense color=green"
                                    )
                                    btn_confirm.on(
                                        "click",
                                        lambda rid=report_id, b=btn_confirm: do_confirm(rid, b),
                                    )

            await _refresh_history()
