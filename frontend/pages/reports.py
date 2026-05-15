"""Trang báo cáo hậu kiểm — upload 4 file, tạo báo cáo phòng (ZIP) + báo cáo tổng hợp (Word)"""
import asyncio
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import (
    _sidebar, _content_area, _page_header, _require_auth,
    _redirect_if_cv, _handle_api_error,
)


def _show_violations(violations: list, file_map: dict = None):
    """
    Hiển thị bảng các user có GD Hậu kiểm sai > 0.
    file_map: {"IPCAS": "tên_file.xls", "Payment": "tên_file.xlsx"}
    """
    with ui.card().classes("w-full border border-red-400 bg-red-50 p-4"):
        with ui.row().classes("items-center gap-2 mb-3"):
            ui.icon("warning", color="red").classes("text-xl")
            ui.label("GD Hậu kiểm sai đang lớn hơn 0. Đề nghị kiểm tra lại các user sau:").classes(
                "text-red-700 font-semibold text-sm"
            )

        ipcas_viols = [v for v in violations if v.get("system") == "IPCAS"]
        pay_viols   = [v for v in violations if v.get("system") == "Payment"]

        for system, rows in [("IPCAS", ipcas_viols), ("Payment", pay_viols)]:
            if not rows:
                continue
            fname = (file_map or {}).get(system, "")
            header = f"Hệ thống {system}"
            if fname:
                header += f" — file: {fname}"
            ui.label(header).classes("text-red-800 font-semibold text-xs mt-2 mb-1")

            # IPCAS có row_num (số dòng trong file Excel); Payment là tổng hợp, không có dòng cụ thể
            has_row = any("row_num" in v for v in rows)
            col_defs = [("Mã user / Username", ""), ("GD HK sai", "w-28 text-center")]
            if has_row:
                col_defs.append(("Dòng trong file", "w-28 text-center"))

            with ui.element("table").classes("w-full text-xs border-collapse"):
                with ui.element("thead"):
                    with ui.element("tr").classes("bg-red-100"):
                        for h, cls in col_defs:
                            with ui.element("th").classes(f"border border-red-300 px-2 py-1 {cls} font-semibold text-red-800"):
                                ui.label(h).classes("text-xs")
                with ui.element("tbody"):
                    for v in rows:
                        with ui.element("tr").classes("bg-white"):
                            with ui.element("td").classes("border border-red-200 px-2 py-1 font-mono"):
                                ui.label(v.get("user_code", "")).classes("text-xs text-red-700 font-semibold")
                            with ui.element("td").classes("border border-red-200 px-2 py-1 text-center"):
                                ui.label(str(v.get("name_5", ""))).classes("text-xs text-red-600 font-bold")
                            if has_row:
                                with ui.element("td").classes("border border-red-200 px-2 py-1 text-center"):
                                    row_num = v.get("row_num")
                                    ui.label(f"Dòng {row_num}" if row_num else "—").classes("text-xs text-gray-600")


def _build_dept_summaries(ipcas_grouped: dict, payment_grouped: dict) -> list:
    """Gom dữ liệu GDV+Teller theo phòng → list dict cho generate_center_word Table 4."""
    all_depts = sorted(set(ipcas_grouped.keys()) | set(payment_grouped.keys()))
    result = []
    for dept in all_depts:
        i_rows = ipcas_grouped.get(dept, [])
        p_rows = payment_grouped.get(dept, [])
        result.append({
            'dept_name':       dept,
            'ipcas_tong_gd':   sum(r.get('gd_hk_dung', 0) for r in i_rows),
            'ipcas_bt_huy':    sum(r.get('bt_huy', 0) for r in i_rows),
            'ipcas_huy_kq':    sum(r.get('huy_kq', 0) for r in i_rows),
            'ipcas_huy_cq':    sum(r.get('huy_cq', 0) for r in i_rows),
            'payment_tong_gd': sum(r.get('gd_hk_dung', 0) for r in p_rows),
            'payment_bt_huy':  sum(r.get('bt_huy', 0) for r in p_rows),
            'payment_huy_kq':  sum(r.get('huy_kq', 0) for r in p_rows),
            'payment_huy_cq':  sum(r.get('huy_cq', 0) for r in p_rows),
        })
    return result


@ui.page("/reports")
def reports_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
        return

    # Đổi icon done → close (đỏ) trong q-uploader. Dùng selector rộng để bắt mọi trường hợp.
    ui.add_head_html("""<script>
    (function(){
        function _fixIcons(){
            document.querySelectorAll('.q-uploader .q-icon').forEach(function(el){
                if(el.textContent.trim()==='done'){
                    el.textContent='close';
                    el.style.color='#dc2626';
                    el.style.fontWeight='bold';
                }
            });
        }
        var _obs=new MutationObserver(_fixIcons);
        function _start(){
            _obs.observe(document.body,{childList:true,subtree:true,characterData:true});
            _fixIcons();
        }
        if(document.readyState==='loading'){
            document.addEventListener('DOMContentLoaded',_start);
        } else { _start(); }
    })();
    </script>""")

    # ── State (1 dict per page instance) ──────────────────────────────────────
    files = {
        "gdv":     None, "gdv_name":     "",
        "teller":  None, "teller_name":  "",
        "hkv":     None, "hkv_name":     "",
        "checker": None, "checker_name": "",
    }

    with ui.row().classes("w-full"):
        _sidebar("reports")
        with _content_area():
            _page_header(
                "Báo cáo hậu kiểm",
                "Tổng hợp kết quả hậu kiểm từ IPCAS và hệ thống Thanh toán tập trung",
            )

            # ── Card upload ────────────────────────────────────────────────────
            with ui.card().classes("w-full p-5 mb-5"):
                ui.label("Tải lên file dữ liệu").classes("text-base font-semibold text-red-800 mb-4")

                # GDV và HKV (cùng IPCAS) xếp cạnh nhau; Teller và Backchecker (Payment) cạnh nhau
                FILE_DEFS = [
                    ("gdv",     "File GDV — IPCAS (.xls)",          ".xls",  "Báo cáo phòng"),
                    ("hkv",     "File HKV — IPCAS (.xls)",           ".xls",  "Báo cáo tổng hợp"),
                    ("teller",  "File Teller — Payment (.xlsx)",     ".xlsx", "Báo cáo phòng"),
                    ("checker", "File Backchecker — Payment (.xlsx)", ".xlsx", "Báo cáo tổng hợp"),
                ]

                with ui.grid(columns=4).classes("w-full gap-5"):
                    for key, label, accept, group in FILE_DEFS:
                        with ui.column().classes("gap-1 min-w-0"):
                            ui.label(label).classes("text-sm font-medium text-gray-700 leading-tight")
                            ui.label(f"({group})").classes("text-xs text-gray-400")

                            def _make_handler(k):
                                def _handler(e):
                                    files[k] = e.content.read()
                                    files[f"{k}_name"] = e.name
                                return _handler

                            ui.upload(
                                on_upload=_make_handler(key),
                                auto_upload=True,
                                max_file_size=20_000_000,
                            ).props(f'accept="{accept}" flat dense label="Chọn file"').classes("w-full")

                ui.separator().classes("my-4")

                # ── Nút tạo báo cáo ───────────────────────────────────────────
                with ui.row().classes("gap-4 flex-wrap"):
                    dept_btn = ui.button(
                        "Tạo báo cáo hậu kiểm theo phòng",
                        icon="table_chart",
                    ).classes("bg-red-800 text-white")

                    word_btn = ui.button(
                        "Tạo thư công tác + BC HK",
                        icon="description",
                    ).classes("bg-red-700 text-white")

            # ── Khu vực kết quả ───────────────────────────────────────────────
            result_area = ui.column().classes("w-full gap-2")

            # ── Handler: Báo cáo phòng (ZIP) ──────────────────────────────────
            async def do_dept_zip():
                if not files["gdv"] and not files["teller"]:
                    ui.notify("Vui lòng tải lên file GDV hoặc Teller", type="warning")
                    return
                dept_btn.props("loading")
                result_area.clear()
                try:
                    upload_files = {}
                    if files["gdv"]:
                        upload_files["gdv_file"] = (
                            files["gdv_name"], files["gdv"], "application/octet-stream"
                        )
                    if files["teller"]:
                        upload_files["teller_file"] = (
                            files["teller_name"], files["teller"], "application/octet-stream"
                        )

                    zip_bytes = await asyncio.to_thread(
                        api.post_upload_bytes, "/api/reports/generate-dept-zip", upload_files
                    )
                    ui.download(zip_bytes, "BC_HK_phong.zip")
                    ui.notify("Đã tạo báo cáo! File ZIP đang được tải về.", type="positive")

                except api.ViolationError as ve:
                    with result_area:
                        _show_violations(ve.violations, {
                            "IPCAS":   files["gdv_name"],
                            "Payment": files["teller_name"],
                        })
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(str(e), type="negative")
                finally:
                    dept_btn.props(remove="loading")

            dept_btn.on("click", do_dept_zip)

            # ── Handler: Thư công tác + BC HK (Word) ─────────────────────────
            async def do_word():
                if not files["hkv"] and not files["checker"]:
                    ui.notify("Vui lòng tải lên file HKV hoặc Backchecker", type="warning")
                    return
                word_btn.props("loading")
                result_area.clear()
                try:
                    hkv_upload = {}
                    if files["hkv"]:
                        hkv_upload["hkv_file"] = (
                            files["hkv_name"], files["hkv"], "application/octet-stream"
                        )
                    if files["checker"]:
                        hkv_upload["checker_file"] = (
                            files["checker_name"], files["checker"], "application/octet-stream"
                        )

                    gdv_upload = {}
                    if files["gdv"]:
                        gdv_upload["gdv_file"] = (
                            files["gdv_name"], files["gdv"], "application/octet-stream"
                        )
                    if files["teller"]:
                        gdv_upload["teller_file"] = (
                            files["teller_name"], files["teller"], "application/octet-stream"
                        )

                    # Parse song song HKV và GDV (GDV optional — lỗi không chặn)
                    coros = [asyncio.to_thread(api.post_upload, "/api/reports/parse-hkv", hkv_upload)]
                    if gdv_upload:
                        coros.append(asyncio.to_thread(api.post_upload, "/api/reports/parse-gdv", gdv_upload))
                    results = await asyncio.gather(*coros, return_exceptions=True)

                    hkv_r = results[0]
                    if isinstance(hkv_r, api.ViolationError):
                        with result_area:
                            _show_violations(hkv_r.violations, {
                                "IPCAS":   files["hkv_name"],
                                "Payment": files["checker_name"],
                            })
                        return
                    if isinstance(hkv_r, Exception):
                        raise hkv_r

                    # Tính dept summaries từ GDV+Teller nếu parse thành công
                    summaries = []
                    if len(results) > 1 and isinstance(results[1], dict):
                        gdv_r = results[1]
                        summaries = _build_dept_summaries(
                            gdv_r.get("ipcas", {}), gdv_r.get("payment", {})
                        )

                    month    = hkv_r.get("month", 0)
                    year     = hkv_r.get("year", 0)
                    hkv_rows = hkv_r.get("hkv_rows", [])
                    hkv_ipcas   = [r for r in hkv_rows if r.get("ipcas_tong_gd", 0) > 0]
                    hkv_payment = [r for r in hkv_rows if r.get("payment_tong_gd", 0) > 0]

                    word_bytes = await asyncio.to_thread(
                        api.post_download,
                        "/api/reports/generate-word",
                        {
                            "month": month, "year": year,
                            "hkv_ipcas": hkv_ipcas,
                            "hkv_payment": hkv_payment,
                            "dept_summaries": summaries,
                        },
                    )
                    fname = f"BC_HK_T{month:02d}{year}.docx"
                    ui.download(word_bytes, fname)
                    ui.notify("Đã tạo báo cáo Word thành công", type="positive")

                except api.ViolationError as ve:
                    with result_area:
                        _show_violations(ve.violations, {
                            "IPCAS":   files["hkv_name"],
                            "Payment": files["checker_name"],
                        })
                except Exception as e:
                    if not _handle_api_error(e):
                        ui.notify(str(e), type="negative")
                finally:
                    word_btn.props(remove="loading")

            word_btn.on("click", do_word)
