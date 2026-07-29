"""Trang Đối chiếu CITAD (NHNN) ↔ PaymentHub (Agribank) — Phòng Thanh toán.

Port từ `citad-fixed/DoiChieuCITAD.py` (tkinter). Giữ nguyên mô hình dữ liệu
và công thức tính chênh lệch gốc:
  - gD[cong][cur][fk]  — 5 cổng CITAD × 3 loại tiền × 8 trường
  - phD[cur][fk]       — PaymentHub × 3 loại tiền × 8 trường
  - napas[fk] / ebank[fk] — bổ sung Napas/Ebanking
  - Tổng CITAD = tổng 5 cổng + Napas IH Đến (den_ih_m, den_ih_t)
  - Tổng PaymentHub = tổng 3 loại tiền của PaymentHub
  - Chênh lệch = Tổng CITAD − Tổng PaymentHub  (đúng theo `_calc()` gốc)

Nút "Nạp CITAD"/"Nạp PaymentHub" đọc buffer do Extension Chrome gửi lên
(xem `extension_citad/`) — thay vì poll timer như bản tkinter, người dùng
bấm nút để nạp giống hệt hành vi gốc. Buffer được tách theo `owner`
(username TTTT cấu hình trong Extension) nên nhiều người dùng chung backend
không ghi đè/xoá dữ liệu của nhau (khác bản gốc — bản gốc chạy 1 server
cục bộ/máy nên vốn chỉ có 1 người dùng).

Napas/Ebanking chỉ có 2 field "IH Đến — Món/Tiền" thực sự được dùng trong
`_calc()`/session/export ở bản gốc (đã kiểm tra `_calc()`, `_get_session_data`,
`_export_excel` trong `citad-fixed/DoiChieuCITAD.py` gốc) — UI chỉ hiện đúng
2 ô này, không vẽ 8 field × 2 dòng như bản gốc (grid gốc có 12/16 ô không hề
được đọc ở đâu, chỉ gây hiểu nhầm).
"""
import asyncio
import datetime
import json
from urllib.parse import quote

from nicegui import ui
import frontend.api_client as api
from frontend.shared import _sidebar, _content_area, _page_header, _card, _require_auth, _handle_api_error

# ID cố định của extension_citad — suy ra tất định từ khoá "key" gắn cứng
# trong extension_citad/manifest.json (không phụ thuộc máy/thư mục cài đặt
# lúc "Load unpacked"). Dùng để gọi chrome.runtime.sendMessage từ trang này
# sang extension qua "externally_connectable" (xem extension_citad/background.js).
# Nếu thay khoá "key" trong manifest.json thì PHẢI cập nhật lại hằng số này.
_EXTENSION_ID = "dhollmjgbbjdcedijlmklmknndcachjh"


def _date_picker_input(label: str, initial: str = None):
    """Ô nhập ngày dd/mm/yyyy kèm icon mở lịch chọn — QDate tự khoanh viền
    ngày hôm nay, không cần cấu hình thêm."""
    initial = initial or datetime.date.today().strftime('%d/%m/%Y')
    with ui.input(label, value=initial).props('dense outlined').classes('w-44') as date_input:
        with date_input.add_slot('append'):
            ui.icon('edit_calendar').on('click', lambda: menu.open()).classes('cursor-pointer')
    with ui.menu() as menu:
        ui.date(value=initial, mask='DD/MM/YYYY').bind_value(date_input)
    return date_input

CONGS = [1, 9, 18, 17, 12]
CURS = ['VNĐ', 'USD', 'EUR']
FK = ['di_ih_m', 'di_ih_t', 'di_il_m', 'di_il_t', 'den_ih_m', 'den_ih_t', 'den_il_m', 'den_il_t']
FK_LBL = ['ĐI IH Món', 'ĐI IH Tiền', 'ĐI IL Món', 'ĐI IL Tiền',
          'ĐẾN IH Món', 'ĐẾN IH Tiền', 'ĐẾN IL Món', 'ĐẾN IL Tiền']


def nv(v):
    try:
        return float(str(v).replace(',', '').replace(' ', '')) if v not in (None, '') else 0.0
    except Exception:
        return 0.0


def fmt(v):
    v = nv(v)
    return '' if v == 0 else f'{int(v):,}'


@ui.page("/doi_chieu_citad")
def doi_chieu_citad_page():
    if not _require_auth():
        return
    if not api.has_feature("menu.doi_chieu_citad"):
        ui.navigate.to("/home")
        return

    # Dữ liệu số (float) — nguồn sự thật để tính chênh lệch, tách khỏi text hiển thị trên ô nhập
    data = {
        "gD": {c: {u: {f: 0.0 for f in FK} for u in CURS} for c in CONGS},
        "phD": {u: {f: 0.0 for f in FK} for u in CURS},
        "napas": {"den_ih_m": 0.0, "den_ih_t": 0.0},
        "ebank": {"den_ih_m": 0.0, "den_ih_t": 0.0},
    }
    inputs = {
        "gE": {c: {u: {} for u in CURS} for c in CONGS},
        "phE": {u: {} for u in CURS},
        "napasE": {},
        "ebankE": {},
    }
    diff_labels = {"citad": {}, "phub": {}, "diff": {}}

    ngay_input = None
    lap_bang_input = None
    kiem_soat_input = None

    def recalc():
        ci = {f: 0.0 for f in FK}
        for c in CONGS:
            for u in CURS:
                for f in FK:
                    ci[f] += data["gD"][c][u][f]
        # Chỉ cộng Napas, KHÔNG cộng Ebanking — đúng hành vi _calc() gốc,
        # xem ghi chú chi tiết trong doi_chieu_citad_service.py::build_xlsx.
        ci["den_ih_m"] += data["napas"]["den_ih_m"]
        ci["den_ih_t"] += data["napas"]["den_ih_t"]

        ph = {f: 0.0 for f in FK}
        for u in CURS:
            for f in FK:
                ph[f] += data["phD"][u][f]

        for f in FK:
            ci_val, ph_val = ci[f], ph[f]
            df_val = ci_val - ph_val
            diff_labels["citad"][f].text = fmt(ci_val) if ci_val else '—'
            diff_labels["phub"][f].text = fmt(ph_val) if ph_val else '—'
            if df_val == 0 and ci_val == 0 and ph_val == 0:
                diff_labels["diff"][f].text = '—'
                diff_labels["diff"][f].classes(remove='text-red-600 text-green-700')
            elif df_val == 0:
                diff_labels["diff"][f].text = '✓ 0'
                diff_labels["diff"][f].classes(remove='text-red-600', add='text-green-700')
            else:
                sign = '+' if df_val > 0 else ''
                diff_labels["diff"][f].text = f'{sign}{int(df_val):,}'
                diff_labels["diff"][f].classes(remove='text-green-700', add='text-red-600')

    def build_grid(container, entry_store: dict, data_store: dict, row_keys: list):
        with container:
            with ui.grid(columns=len(FK) + 1).classes("w-full gap-1"):
                ui.label("Loại tiền").classes("text-xs font-bold text-gray-500")
                for lbl in FK_LBL:
                    ui.label(lbl).classes("text-xs font-bold text-gray-500 text-center")
                for cur in row_keys:
                    ui.label(cur).classes("text-sm font-bold self-center")
                    entry_store[cur] = {}
                    for fk in FK:
                        def _on_change(e, _c=cur, _f=fk, _dd=data_store):
                            _dd[_c][_f] = nv(e.value)
                            recalc()
                        inp = ui.input(value='', on_change=_on_change).props(
                            'dense outlined input-class="text-right"'
                        ).classes("w-full")
                        entry_store[cur][fk] = inp

    def build_napas_ebank_grid(container):
        """Chỉ 2 field IH Đến (Món/Tiền) — DUY NHẤT được dùng trong recalc()/
        session/export (xem docstring đầu file). Không vẽ 6 field còn lại
        của mỗi dòng để tránh ô nhập "chết" không có tác dụng gì."""
        with container:
            with ui.grid(columns=3).classes("w-full gap-2 max-w-lg"):
                ui.label("").classes("text-xs")
                ui.label("IH Đến — Món").classes("text-xs font-bold text-gray-500 text-center")
                ui.label("IH Đến — Tiền").classes("text-xs font-bold text-gray-500 text-center")
                for label, store, entry_store in [
                    ("Napas", data["napas"], inputs["napasE"]),
                    ("Ebanking", data["ebank"], inputs["ebankE"]),
                ]:
                    ui.label(label).classes("text-sm font-bold self-center")
                    for fk in ("den_ih_m", "den_ih_t"):
                        def _on_change(e, _f=fk, _dd=store):
                            _dd[_f] = nv(e.value)
                            recalc()
                        inp = ui.input(value='', on_change=_on_change).props(
                            'dense outlined input-class="text-right"'
                        ).classes("w-full")
                        entry_store[fk] = inp

    def apply_session_data(sess: dict):
        if not sess:
            return
        if sess.get("ngay"):
            ngay_input.value = sess["ngay"]
        lap_bang_input.value = sess.get("lap_bang", "")
        kiem_soat_input.value = sess.get("kiem_soat", "")
        gD = sess.get("gD", {})
        for c in CONGS:
            for u in CURS:
                for f in FK:
                    v = (gD.get(str(c), {}) or {}).get(u, {}).get(f, 0)
                    data["gD"][c][u][f] = nv(v)
                    inputs["gE"][c][u][f].value = fmt(v)
        phD = sess.get("phD", {})
        for u in CURS:
            for f in FK:
                v = (phD.get(u, {}) or {}).get(f, 0)
                data["phD"][u][f] = nv(v)
                inputs["phE"][u][f].value = fmt(v)
        # Napas/Ebanking chỉ có 2 field IH Đến trong session gốc (napas_m/napas_t)
        data["napas"]["den_ih_m"] = nv(sess.get("napas_m", 0))
        data["napas"]["den_ih_t"] = nv(sess.get("napas_t", 0))
        inputs["napasE"]["den_ih_m"].value = fmt(data["napas"]["den_ih_m"])
        inputs["napasE"]["den_ih_t"].value = fmt(data["napas"]["den_ih_t"])
        data["ebank"]["den_ih_m"] = nv(sess.get("ebank_m", 0))
        data["ebank"]["den_ih_t"] = nv(sess.get("ebank_t", 0))
        inputs["ebankE"]["den_ih_m"].value = fmt(data["ebank"]["den_ih_m"])
        inputs["ebankE"]["den_ih_t"].value = fmt(data["ebank"]["den_ih_t"])
        recalc()

    def get_session_payload() -> dict:
        gD = {str(c): {u: {f: data["gD"][c][u][f] for f in FK} for u in CURS} for c in CONGS}
        phD = {u: {f: data["phD"][u][f] for f in FK} for u in CURS}
        return {
            "ngay": ngay_input.value,
            "lap_bang": lap_bang_input.value,
            "kiem_soat": kiem_soat_input.value,
            "gD": gD,
            "phD": phD,
            "napas_m": data["napas"]["den_ih_m"],
            "napas_t": data["napas"]["den_ih_t"],
            "ebank_m": data["ebank"]["den_ih_m"],
            "ebank_t": data["ebank"]["den_ih_t"],
        }

    async def load_citad_buffer():
        try:
            items = await asyncio.to_thread(api.get, "/api/doi-chieu-citad/citad-buffer")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        if not items:
            ui.notify("Chưa có dữ liệu CITAD. Dùng Extension trên trang CITAD!", type="warning")
            return
        count = 0
        for item in items:
            cong = int(item.get("cong", 0) or 0)
            loai = item.get("loai", "")
            chieu = item.get("chieu", "")
            tien = item.get("tien", "VNĐ")
            so_mon = item.get("soMon", 0)
            so_tien = item.get("soTien", 0)
            if cong not in CONGS or tien not in CURS:
                continue
            fk_m, fk_t = f"{chieu}_{loai}_m", f"{chieu}_{loai}_t"
            if fk_m in FK:
                data["gD"][cong][tien][fk_m] = nv(so_mon)
                data["gD"][cong][tien][fk_t] = nv(so_tien)
                inputs["gE"][cong][tien][fk_m].value = fmt(so_mon)
                inputs["gE"][cong][tien][fk_t].value = fmt(so_tien)
                count += 1
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad/citad-buffer")
        except Exception:
            pass
        recalc()
        ui.notify(f"Đã nạp {count} mục từ CITAD", type="positive")

    async def load_phub_buffer():
        try:
            items = await asyncio.to_thread(api.get, "/api/doi-chieu-citad/paymenthub-buffer")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        if not items:
            ui.notify("Chưa có dữ liệu PaymentHub. Dùng Extension!", type="warning")
            return
        count = 0
        for item in items:
            loai, chieu = item.get("loai", ""), item.get("chieu", "")
            tien = item.get("tien", "VNĐ")
            so_mon, so_tien = item.get("soMon", 0), item.get("soTien", 0)
            src = item.get("source", "")
            if src == "napas":
                data["napas"]["den_ih_m"] = nv(so_mon)
                data["napas"]["den_ih_t"] = nv(so_tien)
                inputs["napasE"]["den_ih_m"].value = fmt(so_mon)
                inputs["napasE"]["den_ih_t"].value = fmt(so_tien)
                count += 1
                continue
            if tien not in CURS:
                continue
            fk_m, fk_t = f"{chieu}_{loai}_m", f"{chieu}_{loai}_t"
            if fk_m in FK:
                data["phD"][tien][fk_m] = nv(so_mon)
                data["phD"][tien][fk_t] = nv(so_tien)
                inputs["phE"][tien][fk_m].value = fmt(so_mon)
                inputs["phE"][tien][fk_t].value = fmt(so_tien)
                count += 1
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad/paymenthub-buffer")
        except Exception:
            pass
        recalc()
        ui.notify(f"Đã nạp {count} mục từ PaymentHub", type="positive")

    async def do_save_session():
        try:
            await asyncio.to_thread(api.post, "/api/doi-chieu-citad/session", get_session_payload())
            ui.notify(f"Đã lưu ngày {ngay_input.value}", type="positive")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi lưu: {e}", type="negative")

    async def do_load_session():
        try:
            # quote(safe="") vì ngay có dạng dd/mm/yyyy — nếu không encode dấu
            # "/", httpx sẽ tách nó thành nhiều path segment và route
            # /session/{ngay} (1 segment) sẽ không khớp, luôn trả 404.
            ngay_enc = quote(ngay_input.value, safe="")
            sess = await asyncio.to_thread(api.get, f"/api/doi-chieu-citad/session/{ngay_enc}")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi tải: {e}", type="negative")
            return
        if not sess:
            ui.notify(f"Không tìm thấy dữ liệu ngày {ngay_input.value}", type="warning")
            return
        apply_session_data(sess)
        ui.notify(f"Đã tải ngày {ngay_input.value}", type="positive")

    def do_reset():
        for c in CONGS:
            for u in CURS:
                for f in FK:
                    data["gD"][c][u][f] = 0.0
                    inputs["gE"][c][u][f].value = ''
        for u in CURS:
            for f in FK:
                data["phD"][u][f] = 0.0
                inputs["phE"][u][f].value = ''
        for f in ("den_ih_m", "den_ih_t"):
            data["napas"][f] = 0.0
            data["ebank"][f] = 0.0
            inputs["napasE"][f].value = ''
            inputs["ebankE"][f].value = ''
        recalc()
        ui.notify("Đã xoá toàn bộ dữ liệu", type="info")

    async def do_export():
        gD = {str(c): {u: {f: data["gD"][c][u][f] for f in FK} for u in CURS} for c in CONGS}
        phD = {u: {f: data["phD"][u][f] for f in FK} for u in CURS}
        payload = {
            "day_str": ngay_input.value,
            "sheet_name": (ngay_input.value or "Sheet1").replace("/", "_"),
            "lb": lap_bang_input.value,
            "ks": kiem_soat_input.value,
            "gD": gD,
            "phD": phD,
            "nm": data["napas"]["den_ih_m"],
            "nt": data["napas"]["den_ih_t"],
            "em": data["ebank"]["den_ih_m"],
            "et": data["ebank"]["den_ih_t"],
        }
        try:
            content = await asyncio.to_thread(api.post_download, "/api/doi-chieu-citad/export", payload)
            ui.download(content, f"Doi_chieu_CITAD_{payload['sheet_name']}.xlsx")
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi xuất Excel: {e}", type="negative")

    # ── Kết nối Extension (mã kết nối cá nhân — xem docstring api/doi_chieu_citad.py) ──
    ext_status_label = None

    async def refresh_extension_status():
        try:
            status = await asyncio.to_thread(api.get, "/api/doi-chieu-citad/extension-token/status")
        except Exception:
            return
        if status.get("connected"):
            last = status.get("last_used_at") or "chưa dùng lần nào"
            ext_status_label.text = f"🟢 Đã kết nối — lần dùng gần nhất: {last}"
            ext_status_label.classes(remove="text-gray-500", add="text-green-700")
        else:
            ext_status_label.text = "⚪ Chưa kết nối Extension"
            ext_status_label.classes(remove="text-green-700", add="text-gray-500")

    async def _try_auto_connect_extension(token: str) -> bool:
        """Gửi trực tiếp {server, token} vào extension qua
        chrome.runtime.sendMessage (chỉ hoạt động nếu extension_citad đã
        được cài — Chrome tự chặn theo whitelist origin khai trong
        manifest.json::externally_connectable, xem background.js). Trả về
        False (không throw) cho MỌI lý do thất bại — chưa cài extension,
        trình duyệt không phải Chrome/Edge, hoặc bị chặn — để luôn còn
        đường lùi là dán tay."""
        payload = json.dumps({"type": "SET_CONFIG", "server": api.BACKEND_URL, "token": token})
        js = f"""
            return await new Promise((resolve) => {{
                if (!(window.chrome && chrome.runtime && chrome.runtime.sendMessage)) {{
                    resolve({{ok: false, error: 'no_chrome_runtime'}});
                    return;
                }}
                try {{
                    chrome.runtime.sendMessage({_EXTENSION_ID!r}, {payload}, (response) => {{
                        if (chrome.runtime.lastError) {{
                            resolve({{ok: false, error: chrome.runtime.lastError.message}});
                        }} else {{
                            resolve(response || {{ok: false, error: 'empty_response'}});
                        }}
                    }});
                }} catch (e) {{
                    resolve({{ok: false, error: String(e)}});
                }}
            }});
        """
        try:
            result = await ui.run_javascript(js, timeout=3.0)
        except Exception:
            return False
        return bool(isinstance(result, dict) and result.get("ok"))

    async def do_create_extension_token():
        try:
            result = await asyncio.to_thread(api.post, "/api/doi-chieu-citad/extension-token", {})
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")
            return
        token = result["token"]
        auto_ok = await _try_auto_connect_extension(token)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            if auto_ok:
                ui.label("✓ Đã tự động kết nối vào Extension").classes("text-lg font-bold text-green-700")
                ui.label(
                    "Mã kết nối mới đã được gửi thẳng vào Extension đang cài trên trình duyệt "
                    "này — không cần dán tay. Có thể dùng ngay các nút \"Lấy dữ liệu\" trên "
                    "trang CITAD/PaymentHub."
                ).classes("text-sm text-gray-500")
                ui.button("Đóng", on_click=dialog.close).classes("bg-green-700 text-white mt-2")
            else:
                ui.label("Mã kết nối Extension mới").classes("text-lg font-bold")
                ui.label(
                    "Không tự động kết nối được (chưa cài Extension trên trình duyệt này, hoặc "
                    "trình duyệt không hỗ trợ) — chỉ hiện mã ĐÚNG 1 LẦN, sao chép ngay, rồi bấm "
                    "icon Extension trên thanh công cụ Chrome → \"Tuỳ chọn\" → dán vào ô Mã kết "
                    "nối. Tạo mã mới sẽ tự động huỷ mã cũ."
                ).classes("text-sm text-gray-500")
                token_input = ui.input(value=token).props("readonly outlined dense").classes("w-full font-mono")
                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                    ui.button(
                        "Sao chép", icon="content_copy",
                        on_click=lambda: ui.run_javascript(
                            f"navigator.clipboard.writeText({token_input.value!r})"
                        ),
                    ).props("outline")
                    ui.button("Đóng", on_click=dialog.close).classes("bg-red-800 text-white")
        dialog.open()
        await refresh_extension_status()

    async def do_revoke_extension_token():
        try:
            await asyncio.to_thread(api.delete, "/api/doi-chieu-citad/extension-token")
            ui.notify("Đã thu hồi mã kết nối", type="positive")
            await refresh_extension_status()
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")

    async def do_download_extension():
        try:
            content = await asyncio.to_thread(api.get_bytes, "/api/doi-chieu-citad/extension-download")
            ui.download(content, "extension_citad.zip")
            ui.notify(
                "Đã tải xong — giải nén rồi vào chrome://extensions, bật Developer mode, "
                "bấm Load unpacked và chọn thư mục vừa giải nén.",
                type="positive", multi_line=True, timeout=8000,
            )
        except Exception as e:
            if _handle_api_error(e):
                return
            ui.notify(f"Lỗi: {e}", type="negative")

    with ui.row().classes("w-full"):
        _sidebar("doi_chieu_citad")
        with _content_area():
            _page_header(
                "Đối chiếu CITAD ↔ PaymentHub",
                "Đối chiếu số liệu CITAD (NHNN) với PaymentHub (Agribank) theo từng ngày",
            )

            with _card("Kết nối Extension (nạp số liệu tự động từ CITAD/PaymentHub)"):
                with ui.row().classes("w-full items-center gap-3 p-2 flex-wrap"):
                    ext_status_label = ui.label("Đang kiểm tra...").classes("text-sm text-gray-500")
                    ui.button("Tải Extension (.zip)", icon="download", on_click=do_download_extension).props(
                        "outline"
                    )
                    ui.button("Tạo mã kết nối mới", icon="vpn_key", on_click=do_create_extension_token).props("outline")
                    ui.button("Thu hồi", icon="link_off", on_click=do_revoke_extension_token).props(
                        "outline color=red dense"
                    )
                ui.label(
                    "Lần đầu dùng: (1) Tải Extension → giải nén → chrome://extensions → Developer mode → "
                    "Load unpacked, chọn thư mục vừa giải nén — bước này vẫn phải tự làm 1 lần, Chrome không "
                    "cho web tự cài extension. (2) Bấm \"Tạo mã kết nối mới\" ở trên — nếu Extension đã cài "
                    "trên đúng trình duyệt này, mã sẽ tự động được gửi thẳng vào Extension, không cần dán tay. "
                    "Chỉ khi không tự kết nối được (trình duyệt khác, hoặc Extension chưa cài) mới cần sao "
                    "chép và dán thủ công vào trang Tuỳ chọn của Extension như hướng dẫn hiện ra. Mỗi người tự "
                    "tạo 1 mã riêng, không dùng chung với người khác. Chi tiết trong file README.md nằm sẵn "
                    "trong bản .zip vừa tải."
                ).classes("text-xs text-gray-500 px-2 -mt-2")
                ui.timer(0.1, refresh_extension_status, once=True)

            with ui.row().classes("w-full items-end gap-3 flex-wrap mb-2"):
                ngay_input = _date_picker_input("Ngày")
                lap_bang_input = ui.input("Lập bảng").props("dense outlined").classes("w-48")
                kiem_soat_input = ui.input("Kiểm soát").props("dense outlined").classes("w-48")
                ui.button("Nạp CITAD", icon="cloud_download", on_click=load_citad_buffer).props("outline")
                ui.button("Nạp PaymentHub", icon="cloud_download", on_click=load_phub_buffer).props("outline")
                ui.button("Lưu", icon="save", on_click=do_save_session).classes("bg-green-700 text-white")
                ui.button("Tải", icon="folder_open", on_click=do_load_session).props("outline")
                ui.button("Xoá", icon="delete", on_click=do_reset).props("outline color=red")
                ui.button("Xuất Excel", icon="grid_on", on_click=do_export).classes("bg-red-800 text-white")

            with _card("PaymentHub – Agribank"):
                build_grid(ui.column().classes("w-full"), inputs["phE"], data["phD"], CURS)

            for cong in CONGS:
                with _card(f"Cổng {cong} – CITAD (NHNN)"):
                    build_grid(ui.column().classes("w-full"), inputs["gE"][cong], data["gD"][cong], CURS)

            with _card("Napas / Ebanking (bổ sung)"):
                build_napas_ebank_grid(ui.column().classes("w-full"))

            with _card("Bảng chênh lệch (CITAD − PaymentHub)"):
                with ui.grid(columns=len(FK) + 1).classes("w-full gap-1"):
                    ui.label("").classes("text-xs")
                    for lbl in FK_LBL:
                        ui.label(lbl).classes("text-xs font-bold text-gray-500 text-center")
                    for key, label, color in [
                        ("citad", "CITAD", "text-sky-600"),
                        ("phub", "PaymentHub", "text-purple-600"),
                        ("diff", "CHÊNH LỆCH", "text-red-600"),
                    ]:
                        ui.label(label).classes(f"text-sm font-bold self-center {color}")
                        for fk in FK:
                            lbl = ui.label("—").classes("text-sm text-right self-center")
                            diff_labels[key][fk] = lbl

            recalc()
