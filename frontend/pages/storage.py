"""Trang lưu trữ và tra cứu chứng từ."""
import asyncio
from nicegui import ui, app
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _require_auth, _redirect_if_cv, _handle_api_error

@ui.page("/storage")
async def storage_page():
    if not _require_auth():
        return
    if _redirect_if_cv():
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
        _s_dept_opts  = {d["id"]: d["name"] for d in _s_depts}
        _s_year_opts  = {y: str(y) for y in range(2023, _today_s.year + 3)}
        _s_month_opts = {m: f"Tháng {m:02d}" for m in range(1, 13)}

        with ui.tabs().classes("mb-2") as storage_tabs:
            t_lookup   = ui.tab("Tra cứu lưu trữ")
            t_handover = ui.tab("Bàn giao cho lưu trữ")

        with ui.tab_panels(storage_tabs, value=t_lookup).classes("w-full"):

            # ── Tab 1: Tra cứu ────────────────────────────────────────────────
            with ui.tab_panel(t_lookup):

                with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-4 mb-4"):
                    with ui.row().classes("items-end gap-4 flex-wrap"):
                        s_dept  = ui.select(_s_dept_opts, label="Phòng nghiệp vụ",
                                            value=_s_depts[0]["id"] if _s_depts else None).classes("w-72")
                        s_year  = ui.select(_s_year_opts, label="Năm",
                                            value=_today_s.year).classes("w-28")
                        s_month = ui.select(_s_month_opts, label="Tháng",
                                            value=_today_s.month).classes("w-36")
                        ui.button("Tải dữ liệu", icon="search",
                                  on_click=lambda: load_storage()).classes("bg-red-700 text-white px-4")

                storage_loading = ui.row().classes("w-full justify-center items-center py-6 hidden")
                with storage_loading:
                    ui.spinner(size="2em", color="red")
                    ui.label("Đang tải...").classes("text-gray-500 ml-2 text-sm")
                result_area = ui.column().classes("w-full")

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
                    n_sh  = max(n_sh, 3)

                    C  = "border:1px solid #000;text-align:center;padding:5px 8px;font-size:13px"
                    CE = "border:1px solid #000;text-align:center;padding:5px 8px;font-size:13px;color:#bbb"
                    CH = f"{C};background:#dbeafe;font-weight:700"
                    CF = f"{C};background:#dbeafe;font-weight:700"
                    ED = "outline:none"

                    n_total = n_day + n_sh + 1
                    html = f"""<table id="sv-table" style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif">
<tr><td colspan="{n_total}" style="{C};font-size:17px;font-weight:700;padding:10px">
  Phòng {dept_name} {period}
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
                            html += f'<td contenteditable="true" style="{s};{ED}">{v}</td>'
                        for i in range(n_sh):
                            bid = bids[i] if i < len(bids) else ""
                            v   = str(r["bundle_sheets"][i]) if i < len(r["bundle_sheets"]) else ""
                            s   = C if v else CE
                            da  = f' data-bid="{bid}"' if bid else ""
                            html += f'<td contenteditable="true"{da} style="{s};{ED}">{v}</td>'
                        html += f'<td style="{C};font-weight:700">{r["n_bundles"]}</td>'
                        html += "</tr>\n"

                    html += f"""<tr>
  <td colspan="{n_day}" style="{CF};text-align:right">Cộng tổng:</td>
  <td colspan="{n_sh}"  style="{CF};font-size:15px">{tot_sheets:,}</td>
  <td style="{CF};font-size:15px">{tot_bndls}</td>
</tr>
</table>"""
                    return html

                async def load_storage():
                    result_area.clear()
                    if not s_dept.value or not s_year.value or not s_month.value:
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
                            ).classes("text-gray-400 text-center py-8 w-full")
                            return

                        async def do_save():
                            # Đọc giá trị ô "Số chứng từ" từ DOM qua data-bid
                            result = await ui.run_javascript("""
                                var rows = [];
                                document.querySelectorAll('#sv-table tr[data-bids]').forEach(function(tr) {
                                    var bids = JSON.parse(tr.getAttribute('data-bids'));
                                    if (!bids.length) return;
                                    var sheets = [];
                                    tr.querySelectorAll('td[data-bid]').forEach(function(td) {
                                        var v = parseInt(td.innerText.trim().replace(/[^0-9]/g,''), 10);
                                        sheets.push(isNaN(v) ? 0 : v);
                                    });
                                    if (sheets.length) rows.push({bundle_ids: bids, bundle_sheets: sheets});
                                });
                                return rows;
                            """)
                            if not result:
                                ui.notify("Không có dữ liệu để lưu", type="warning")
                                return
                            try:
                                await asyncio.to_thread(api.patch, "/api/bundles/storage-view",
                                                        {"rows": result})
                                ui.notify("Đã lưu thay đổi", type="positive")
                            except Exception as e:
                                if _handle_api_error(e): return

                        with ui.row().classes("w-full justify-end gap-2 mb-3"):
                            ui.button("Lưu thay đổi", icon="save",
                                      on_click=do_save).classes("bg-red-700 text-white px-4")
                            def do_print():
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
                            ui.button("In danh sách (A4 ngang)", icon="print",
                                      on_click=do_print).classes("bg-green-700 text-white px-4")

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
                            ).classes("text-gray-400 text-sm text-center py-6 w-full")
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
                                "text-gray-400 text-sm text-center py-2"
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
