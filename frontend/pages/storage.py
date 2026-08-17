"""Trang lưu trữ và tra cứu chứng từ."""
import asyncio
import html as _html
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _handle_api_error


def _dept_display(name: str) -> str:
    # Rút gọn tên phòng QLTK Nostro Vostro cho bảng lưu trữ
    if name and "nostro" in name.lower():
        return "Phòng QLTK Nostro, Vostro"
    return name


def _build_summary_html(data: dict) -> str:
    """Bảng tổng hợp cả năm: 1 cột Tháng + mỗi phòng 2 cột con + Tổng cộng 2 cột con."""
    depts = data.get("departments", [])
    rows  = data.get("rows", [])
    year  = data.get("year", "")
    if not depts:
        return ""

    C   = "border:1px solid #000;text-align:center;padding:5px 8px;font-size:13px"
    CZ  = f"{C};color:#bbb"
    CH  = f"{C};background:#dbeafe;font-weight:700"
    CT  = f"{C};background:#fef9c3;font-weight:700"    # ô cột Tổng cộng
    CTH = f"{C};background:#fde68a;font-weight:700"    # header cột Tổng cộng

    n_total = 1 + len(depts) * 2 + 2
    h = [
        '<table id="sv-sum" style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif">',
        f'<tr><td colspan="{n_total}" style="{C};font-size:17px;font-weight:700;padding:10px">'
        f'Tổng hợp lưu trữ năm {year}</td></tr>',
        f'<tr><td rowspan="2" style="{CH}">Tháng</td>',
    ]
    for d in depts:
        h.append(f'<td colspan="2" style="{CH}">{_html.escape(_dept_display(d["name"]))}</td>')
    h.append(f'<td colspan="2" style="{CTH}">Tổng cộng</td></tr><tr>')
    for _ in depts:
        h.append(f'<td style="{CH}">Số chứng từ</td><td style="{CH}">Số tập</td>')
    h.append(f'<td style="{CTH}">Số chứng từ</td><td style="{CTH}">Số tập</td></tr>')

    for r in rows:
        h.append(f'<tr><td style="{C};font-weight:700">Tháng {r["month"]:02d}</td>')
        for c in r["cells"]:
            for v in (c["total_sheets"], c["total_bundles"]):
                h.append(f'<td style="{C if v else CZ}">{v:,}</td>')
        h.append(f'<td style="{CT}">{r["total_sheets"]:,}</td>'
                 f'<td style="{CT}">{r["total_bundles"]:,}</td></tr>')
    h.append("</table>")
    return "".join(h)


_COVER_COLS = [
    {"name": "stt",       "label": "STT",         "field": "stt",       "align": "center", "sortable": True},
    {"name": "ma_vach",   "label": "Mã vạch",     "field": "ma_vach",   "align": "left",   "sortable": True},
    {"name": "ngay_mo",   "label": "Ngày mở",     "field": "ngay_mo",   "align": "center", "sortable": True},
    {"name": "tieu_de",   "label": "Tên hồ sơ",   "field": "tieu_de",   "align": "left"},
    {"name": "ngay_cvkt", "label": "Ngày CVKT",   "field": "ngay_cvkt", "align": "center", "sortable": True},
    {"name": "so_to",     "label": "Số tờ",       "field": "so_to",     "align": "center"},
]


def _build_cover_panel():
    """Tab 'In bìa hồ sơ': nạp Excel tra cứu → chọn hồ sơ → sinh bìa Word."""
    state = {"rows": []}

    with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 mb-4"):
        ui.label("In bìa hồ sơ lưu trữ (mẫu M01/LHS)").classes("font-semibold text-red-800")
        ui.label(
            "Nạp file Excel tra cứu hồ sơ tài liệu (LT_HS_TRACUU_*.xls) xuất từ chương trình "
            "lưu trữ. Mã vạch, Ngày mở, Tên hồ sơ và Ngày CVKT được điền vào mẫu bìa Word."
        ).classes("text-xs text-gray-500 mb-3")

        uploader = ui.upload(
            label="Chọn file Excel tra cứu (.xls / .xlsx)",
            auto_upload=True,
            max_files=1,
            on_upload=lambda e: _on_file(e),
        ).props('accept=".xls,.xlsx" flat bordered').classes("w-full max-w-xl")

    cover_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
    with cover_loading:
        ui.spinner(size="2em", color="red")
        ui.label("Đang xử lý...").classes("text-gray-500 ml-2 text-sm")

    cover_result = ui.column().classes("w-full")

    def _on_file(e):
        raw = e.content.read()
        uploader.reset()
        asyncio.create_task(_parse(raw, e.name))

    async def _parse(raw: bytes, name: str):
        cover_result.clear()
        state["rows"] = []
        cover_loading.classes(remove="hidden")
        try:
            data = await asyncio.to_thread(
                api.post_upload, "/api/bundles/archive-cover-parse",
                {"file": (name, raw, "application/octet-stream")},
            )
        except Exception as ex:
            if _handle_api_error(ex):
                return
            ui.notify(f"Lỗi đọc file: {ex}", type="negative", timeout=8000)
            return
        finally:
            cover_loading.classes(add="hidden")

        state["rows"] = data.get("rows", [])
        _render(data.get("warnings", []), name)

    def _render(warnings: list, name: str):
        rows = state["rows"]
        with cover_result:
            ui.label(f"{name} — {len(rows)} hồ sơ").classes("font-semibold text-red-900")
            for w in warnings:
                with ui.row().classes(
                    "w-full items-center gap-2 bg-amber-50 border border-amber-200 "
                    "rounded-lg px-3 py-2 text-sm text-amber-800"
                ):
                    ui.icon("warning", color="amber-8")
                    ui.label(w)

            table = ui.table(
                columns=_COVER_COLS, rows=rows, row_key="stt", selection="multiple",
                pagination={"rowsPerPage": 25, "sortBy": "stt"},
            ).props(
                'bordered separator="cell" table-header-class="bg-red-800 text-white"'
            ).classes("w-full")
            table.selected = list(rows)   # mặc định in tất cả

            sel_lbl = ui.label().classes("text-sm text-gray-600")

            def _update_count():
                sel_lbl.text = f"Đã chọn {len(table.selected)}/{len(rows)} hồ sơ"

            _update_count()
            table.on_select(lambda _: _update_count())

            def _select(items: list):
                table.selected = list(items)   # setter tự gọi update()
                _update_count()

            async def _download(as_zip: bool):
                selected = list(table.selected)
                if not selected:
                    ui.notify("Chưa chọn hồ sơ nào", type="warning")
                    return
                # Giữ đúng thứ tự STT trong file Excel, không theo thứ tự người dùng tích
                selected.sort(key=lambda r: r["stt"])
                cover_loading.classes(remove="hidden")
                try:
                    content = await asyncio.to_thread(
                        api.post_download, "/api/bundles/archive-cover-print",
                        {"rows": selected, "as_zip": as_zip},
                    )
                    ui.download(content, "bia_ho_so.zip" if as_zip else "bia_ho_so.docx")
                    ui.notify(f"Đã tạo bìa cho {len(selected)} hồ sơ", type="positive")
                except Exception as ex:
                    if _handle_api_error(ex):
                        return
                    ui.notify(f"Lỗi tạo bìa: {ex}", type="negative", timeout=8000)
                finally:
                    cover_loading.classes(add="hidden")

            with ui.row().classes("w-full justify-end items-center gap-2 mt-3"):
                ui.button("Chọn tất cả", icon="select_all",
                          on_click=lambda: _select(rows)).props("flat").classes("text-red-800")
                ui.button("Bỏ chọn", icon="deselect",
                          on_click=lambda: _select([])).props("flat").classes("text-gray-600")
                ui.button("Tải file Word (gộp)", icon="description",
                          on_click=lambda: _download(False)
                          ).classes("bg-red-700 text-white px-4")
                ui.button("Tải ZIP (mỗi hồ sơ 1 file)", icon="folder_zip",
                          on_click=lambda: _download(True)
                          ).classes("bg-green-700 text-white px-4")


@ui.page("/storage")
async def storage_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.storage"):
        ui.navigate.to("/home")
        return
    _ = _sidebar("storage")
    with _content_area():
        _page_header("Lưu trữ", "Tra cứu và bàn giao tập chứng từ")

        from datetime import date as _sd
        import json as _json

        _today_s = _sd.today()

        try:
            _s_depts_raw = await asyncio.to_thread(api.get, "/api/departments/")
            _s_depts = [d for d in _s_depts_raw if d.get("is_source")]
        except Exception:
            _s_depts = []
        _s_dept_opts  = {d["id"]: _dept_display(d["name"]) for d in _s_depts}
        _s_year_opts  = {y: str(y) for y in range(2023, _today_s.year + 3)}
        _s_month_opts = {m: f"Tháng {m:02d}" for m in range(1, 13)}

        # Sentinel "Tất cả" — chỉ dùng ở tab tra cứu, không dùng ở tab bàn giao
        _ALL_DEPTS = 0
        _s_dept_opts_lookup = {_ALL_DEPTS: "Tất cả", **_s_dept_opts}

        with ui.tabs().classes("mb-2") as storage_tabs:
            t_lookup   = ui.tab("Tra cứu lưu trữ")
            t_handover = ui.tab("Bàn giao cho lưu trữ")
            t_cover    = ui.tab("In bìa hồ sơ")

        with ui.tab_panels(storage_tabs, value=t_lookup).classes("w-full"):

            # ── Tab 1: Tra cứu ────────────────────────────────────────────────
            with ui.tab_panel(t_lookup):

                with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 mb-4"):
                    with ui.row().classes("items-end gap-4 flex-wrap"):
                        s_dept  = ui.select(_s_dept_opts_lookup, label="Phòng nghiệp vụ",
                                            value=_s_depts[0]["id"] if _s_depts else None).classes("w-72")
                        s_year  = ui.select(_s_year_opts, label="Năm",
                                            value=_today_s.year).classes("w-28")
                        s_month = ui.select(_s_month_opts, label="Tháng",
                                            value=_today_s.month).classes("w-36")
                        ui.button("Tải dữ liệu", icon="search",
                                  on_click=lambda: load_storage()).classes("bg-red-700 text-white px-4")

                    # "Tất cả" = tổng hợp cả năm → không có ý nghĩa chọn tháng
                    s_dept.on_value_change(
                        lambda: s_month.set_visibility(s_dept.value != _ALL_DEPTS)
                    )

                storage_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
                with storage_loading:
                    ui.spinner(size="2em", color="red")
                    ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
                result_area = ui.column().classes("w-full")

                def _print_table(html_table: str):
                    print_html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>
  body{{font-family:Arial,sans-serif;margin:10mm}}
  table{{border-collapse:collapse;width:100%}}
  @page{{size:A4 landscape;margin:10mm}}
  @media print{{button{{display:none}}}}
</style>
</head><body>
<div style="text-align:right;margin-bottom:6px">
  <button onclick="window.print()" style="padding:6px 16px;background:#1d4ed8;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px">🖨 In</button>
</div>
{html_table}
</body></html>"""
                    escaped = _json.dumps(print_html)
                    ui.run_javascript(
                        f"var w=window.open('','_blank');"
                        f"w.document.write({escaped});"
                        f"w.document.close();"
                    )

                def _build_html(data: dict) -> str:
                    rows       = data.get("rows", [])
                    dept_name  = data.get("department_name", "")
                    period     = data.get("period", "")
                    tot_sheets = data.get("total_sheets", 0)
                    tot_bndls  = data.get("total_bundles", 0)

                    if not rows:
                        return ""

                    n_day = max((len(r["days"]) for r in rows), default=1)
                    n_day = max(n_day, 2)
                    n_sh  = max((len(r["bundle_sheets"]) for r in rows), default=1)
                    # +1 để mọi dòng luôn còn ít nhất 1 ô trống nhập thêm số chứng từ; tối thiểu 5 cột
                    n_sh  = max(n_sh + 1, 5)

                    C  = "border:1px solid #000;text-align:center;padding:5px 8px;font-size:13px"
                    CE = "border:1px solid #000;text-align:center;padding:5px 8px;font-size:13px;color:#bbb"
                    CH = f"{C};background:#dbeafe;font-weight:700"
                    CF = f"{C};background:#dbeafe;font-weight:700"
                    ED = "outline:none"

                    n_total = n_day + n_sh + 1
                    html = f"""<table id="sv-table" style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif">
<tr><td colspan="{n_total}" style="{C};font-size:17px;font-weight:700;padding:10px">
  {_dept_display(dept_name)} {period}
</td></tr>
<tr>
  <td colspan="{n_day}" style="{CH}">Ngày</td>
  <td colspan="{n_sh}"  style="{CH}">Số chứng từ</td>
  <td style="{CH}">Số tập</td>
</tr>
"""
                    for r in rows:
                        bids = r.get("bundle_ids", [])
                        # data-bids: JSON array, data-ncols: số cột sheet thực tế
                        html += f'<tr data-bids=\'{_json.dumps(bids)}\' data-ncols="{len(r["bundle_sheets"])}">'
                        for i in range(n_day):
                            v = str(r["days"][i]) if i < len(r["days"]) else ""
                            s = C if v else CE
                            html += f'<td contenteditable="true" data-col="day" style="{s};{ED}">{v}</td>'
                        for i in range(n_sh):
                            bid = bids[i] if i < len(bids) else ""
                            v   = str(r["bundle_sheets"][i]) if i < len(r["bundle_sheets"]) else ""
                            s   = C if v else CE
                            da  = f' data-bid="{bid}"' if bid else ""
                            html += f'<td contenteditable="true" data-col="sheet"{da} style="{s};{ED}">{v}</td>'
                        html += f'<td style="{C};font-weight:700">{r["n_bundles"]}</td>'
                        html += "</tr>\n"

                    html += f"""<tr>
  <td colspan="{n_day}" style="{CF};text-align:right">Cộng tổng:</td>
  <td colspan="{n_sh}"  style="{CF};font-size:15px">{tot_sheets:,}</td>
  <td style="{CF};font-size:15px">{tot_bndls}</td>
</tr>
</table>"""
                    return html

                async def load_summary():
                    storage_loading.classes(remove="hidden")
                    try:
                        data = await asyncio.to_thread(api.get, "/api/bundles/storage-summary",
                                                       {"year": s_year.value})
                    except Exception as e:
                        _handle_api_error(e)
                        return
                    finally:
                        storage_loading.classes(add="hidden")

                    html_table = _build_summary_html(data)
                    with result_area:
                        if not html_table:
                            ui.label("Không có phòng nghiệp vụ nào").classes(
                                "text-gray-500 text-center py-8 w-full"
                            )
                            return
                        with ui.row().classes("w-full justify-start gap-2 mb-3"):
                            ui.button("In danh sách (A4 ngang)", icon="print",
                                      on_click=lambda: _print_table(html_table)
                                      ).classes("bg-green-700 text-white px-4")
                        with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 overflow-x-auto"):
                            ui.html(html_table)

                async def load_storage():
                    result_area.clear()
                    if not s_year.value:
                        return
                    if s_dept.value == _ALL_DEPTS:
                        await load_summary()
                        return
                    if not s_dept.value or not s_month.value:
                        return
                    storage_loading.classes(remove="hidden")
                    try:
                        data = await asyncio.to_thread(api.get, "/api/bundles/storage-view", {
                            "department_id": s_dept.value,
                            "year": s_year.value,
                            "month": s_month.value,
                        })
                    except Exception as e:
                        _handle_api_error(e)
                        storage_loading.classes(add="hidden")
                        return
                    storage_loading.classes(add="hidden")

                    html_table = _build_html(data)

                    with result_area:
                        if not html_table:
                            ui.label(
                                f"Không có dữ liệu cho {_s_dept_opts.get(s_dept.value,'')} "
                                f"tháng {s_month.value:02d}/{s_year.value}"
                            ).classes("text-gray-500 text-center py-8 w-full")
                            return

                        async def do_save():
                            # Đọc ô "Số chứng từ": ô có data-bid = tập cũ (0 = xoá),
                            # ô trống được nhập = tập mới (new_sheets).
                            # Đọc ô "Ngày": days = toàn bộ ngày còn lại của dòng sau khi sửa.
                            result = await ui.run_javascript("""
                                var rows = [];
                                document.querySelectorAll('#sv-table tr[data-bids]').forEach(function(tr) {
                                    var bundle_ids = [], bundle_sheets = [], new_sheets = [], days = [];
                                    tr.querySelectorAll('td[data-col="day"]').forEach(function(td) {
                                        var d = parseInt(td.innerText.trim().replace(/[^0-9]/g,''), 10);
                                        if (!isNaN(d) && d > 0) days.push(d);
                                    });
                                    tr.querySelectorAll('td[data-col="sheet"]').forEach(function(td) {
                                        var v = parseInt(td.innerText.trim().replace(/[^0-9]/g,''), 10);
                                        if (isNaN(v)) v = 0;
                                        var bid = td.getAttribute('data-bid');
                                        if (bid) { bundle_ids.push(parseInt(bid, 10)); bundle_sheets.push(v); }
                                        else if (v > 0) { new_sheets.push(v); }
                                    });
                                    if (bundle_ids.length || new_sheets.length)
                                        rows.push({bundle_ids: bundle_ids, bundle_sheets: bundle_sheets,
                                                   new_sheets: new_sheets, days: days});
                                });
                                return rows;
                            """)
                            if not result:
                                ui.notify("Không có dữ liệu để lưu", type="warning")
                                return
                            try:
                                await asyncio.to_thread(api.patch, "/api/bundles/storage-view",
                                                        {"rows": result})
                            except Exception as e:
                                # Lỗi (ngày không hợp lệ, hết phiên...) — giữ nguyên số đang nhập
                                _handle_api_error(e)
                                return
                            ui.notify("Đã lưu thay đổi", type="positive")
                            # Tải lại để Ngày + Số tập + tổng cuối tự cập nhật theo
                            await load_storage()

                        with ui.row().classes("w-full justify-start gap-2 mb-3"):
                            ui.button("Lưu thay đổi", icon="save",
                                      on_click=do_save).classes("bg-red-700 text-white px-4")
                            ui.button("In danh sách (A4 ngang)", icon="print",
                                      on_click=lambda: _print_table(html_table)
                                      ).classes("bg-green-700 text-white px-4")
                            ui.label("Sửa trực tiếp trên bảng: ô Ngày và ô Số chứng từ "
                                     "(số chứng từ = 0 để xoá tập)").classes(
                                "text-xs text-gray-500 self-center ml-2")

                        with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 overflow-x-auto"):
                            ui.html(html_table)

                await load_storage()

            # ── Tab 2: Bàn giao cho lưu trữ ──────────────────────────────────
            with ui.tab_panel(t_handover):

                with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 mb-4"):
                    ui.label("Tạo dữ liệu bàn giao cho lưu trữ").classes("font-semibold text-red-800 mb-3")
                    with ui.row().classes("items-end gap-4 flex-wrap"):
                        ha_dept = ui.select(_s_dept_opts, label="Phòng nghiệp vụ *",
                                            value=_s_depts[0]["id"] if _s_depts else None).classes("w-72")
                        ha_year = ui.select(_s_year_opts, label="Năm *",
                                            value=_today_s.year).classes("w-28")
                        ui.button("Xem trước", icon="preview",
                                  on_click=lambda: load_archive_preview()
                                  ).classes("bg-red-700 text-white px-4")
                        ui.button("Tải về Excel", icon="download",
                                  on_click=lambda: download_archive()
                                  ).classes("bg-green-700 text-white px-4")

                ha_result = ui.column().classes("w-full")

                ha_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
                with ha_loading:
                    ui.spinner(size="2em", color="red")
                    ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")

                async def load_archive_preview():
                    ha_result.clear()
                    if not ha_dept.value or not ha_year.value:
                        ui.notify("Vui lòng chọn phòng và năm", type="warning")
                        return
                    ha_loading.classes(remove="hidden")
                    try:
                        data = await asyncio.to_thread(api.get, "/api/bundles/handover-archive", {
                            "department_id": ha_dept.value,
                            "year": ha_year.value,
                        })
                    except Exception as e:
                        _handle_api_error(e)
                        ha_loading.classes(add="hidden")
                        return
                    ha_loading.classes(add="hidden")

                    records = data.get("records", [])
                    total   = data.get("total", 0)

                    with ha_result:
                        dept_lbl = _s_dept_opts.get(ha_dept.value, "")
                        ui.label(
                            f"Phòng {dept_lbl} – Năm {ha_year.value}: {total} hồ sơ"
                        ).classes("font-semibold text-red-900 mb-3")

                        if not records:
                            ui.label(
                                f"Không có dữ liệu cho {dept_lbl} năm {ha_year.value}"
                            ).classes("text-gray-500 text-sm text-center py-6 w-full")
                            return

                        preview = records[:30]
                        with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden"):
                            with ui.row().classes(
                                "w-full px-3 py-2 bg-red-50 font-semibold text-xs text-red-700"
                                " border-b border-red-100"
                            ):
                                ui.label("NGAY_MO_HS").classes("w-28")
                                ui.label("NGAY_KT_HS").classes("w-28")
                                ui.label("TIEUDE_HS").classes("flex-1")
                            for rec in preview:
                                with ui.row().classes(
                                    "w-full px-3 py-2 border-b border-gray-100 items-start"
                                ):
                                    ui.label(rec["ngay_mo"]).classes(
                                        "w-28 text-sm font-mono text-gray-600 shrink-0"
                                    )
                                    ui.label(rec["ngay_kt"]).classes(
                                        "w-28 text-sm font-mono text-gray-600 shrink-0"
                                    )
                                    ui.label(rec["tieu_de"]).classes("flex-1 text-sm")
                        if total > 30:
                            ui.label(f"... và {total - 30} hồ sơ khác (xem đầy đủ trong file Excel)").classes(
                                "text-gray-500 text-sm text-center py-2"
                            )

                async def download_archive():
                    if not ha_dept.value or not ha_year.value:
                        ui.notify("Vui lòng chọn phòng và năm", type="warning")
                        return
                    ha_loading.classes(remove="hidden")
                    try:
                        content = await asyncio.to_thread(
                            api.download, "/api/bundles/handover-archive-excel", {
                                "department_id": ha_dept.value,
                                "year": ha_year.value,
                            }
                        )
                        dept_lbl = _s_dept_opts.get(ha_dept.value, str(ha_dept.value))
                        filename = f"ban_giao_luu_tru_{dept_lbl}_{ha_year.value}.xlsx"
                        ui.download(content, filename)
                        ui.notify("Đang tải file Excel...", type="positive")
                    except Exception as e:
                        _handle_api_error(e)
                    finally:
                        ha_loading.classes(add="hidden")

            # ── Tab 3: In bìa hồ sơ ──────────────────────────────────────────
            with ui.tab_panel(t_cover):
                _build_cover_panel()
