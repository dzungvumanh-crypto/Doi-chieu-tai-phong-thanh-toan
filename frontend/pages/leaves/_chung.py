"""Hằng số và helper dùng chung cho các phần của trang Nghỉ phép.

Tách khỏi `__init__.py` khi chẻ trang 6.400 dòng: mỗi phần tách ra (chi tiết đơn,
rồi các tab) đều cần mấy helper này, mà import ngược từ `__init__` là vòng tròn.
Nội dung giữ NGUYÊN VĂN từ `frontend/pages/leaves.py` trước khi tách.
"""

import asyncio

import logging



from nicegui import ui


import frontend.ui_kit as ui_kit

_log = logging.getLogger(__name__)

from frontend.shared import _handle_api_error



# ─── LEAVES PAGE ─────────────────────────────────────────────────────────────

# Nhãn + màu chuyển về ui_kit.STATUS. Giữ tên _LEAVE_STATUS cho code cũ trong file.

_LEAVE_STATUS = {

    k: (ui_kit.status_label(k), ui_kit.STATUS[k]["chip"])

    for k in ("pending_ksv", "pending_tong_hop", "pending_gd", "approved", "rejected", "cancelled")

}

# Định nghĩa thật nằm ở ui_kit.LEAVE_TYPE — sidebar cũng đọc map này.
_LEAVE_TYPE = ui_kit.LEAVE_TYPE

# Nhóm hiển thị 3 trạng thái đơn giản trong cột Trạng thái của bảng

_STATUS_GROUP = {

    "pending_ksv":      ("Chờ KSV duyệt",    "bg-orange-100 text-orange-700"),

    "pending_tong_hop": ("Chờ Tổng hợp",      "bg-yellow-100 text-yellow-700"),

    "pending_gd":       ("Chờ Ban lãnh đạo duyệt", "bg-blue-100 text-blue-700"),

    "approved":         ("Hoàn thành",         "bg-green-100 text-green-700"),

    "rejected":         ("Từ chối",            "bg-red-100 text-red-700"),

    "cancelled":        ("Đã hủy",             "bg-gray-100 text-gray-500"),

}





# ─── Popup xem trước đơn + đặt chữ ký ────────────────────────────────────────
# Ảnh trang là bản in THẬT (Word đã dựng PDF, backend render ra PNG), nên chỗ thả
# chữ ký trong popup chính là chỗ nó nằm trên file PDF tải về — không phải bản mô
# phỏng bằng HTML.
_SIGN_PAGE_W_PX = 640          # bề ngang ảnh trang trong popup


def _sign_js(cid: str, ppm: float, ratio: float) -> str:
    """Kéo để di chuyển, kéo 4 góc để phóng to/thu nhỏ (khoá tỉ lệ ảnh).

    Nội dung q-dialog chỉ được gắn vào DOM khi popup mở, mà thứ tự tới nơi của
    lệnh mở và lệnh chạy JS không đảm bảo → dò lại vài nhịp cho tới khi thấy.
    """
    return f"""
(function attach(n) {{
  const wrap = document.getElementById('wrap_{cid}');
  const box  = document.getElementById('sig_{cid}');
  if (!wrap || !box) {{ if (n < 60) setTimeout(() => attach(n + 1), 50); return; }}
  const ppm = {ppm}, ratio = {ratio};
  let mode = null, corner = null, sx = 0, sy = 0, ox = 0, oy = 0, ow = 0, oh = 0;
  const lim = () => [wrap.clientWidth, wrap.clientHeight];
  function down(e, m, c) {{
    mode = m; corner = c; sx = e.clientX; sy = e.clientY;
    ox = box.offsetLeft; oy = box.offsetTop; ow = box.offsetWidth; oh = box.offsetHeight;
    e.preventDefault(); e.stopPropagation();
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }}
  function move(e) {{
    const [W, H] = lim(), dx = e.clientX - sx, dy = e.clientY - sy;
    if (mode === 'move') {{
      box.style.left = Math.max(0, Math.min(W - ow, ox + dx)) + 'px';
      box.style.top  = Math.max(0, Math.min(H - oh, oy + dy)) + 'px';
    }} else {{
      let nw = ow + (corner.indexOf('e') >= 0 ? dx : -dx);
      nw = Math.max(18, Math.min(W, nw));
      let nh = nw * ratio;
      if (nh > H) {{ nh = H; nw = nh / ratio; }}
      let nx = corner.indexOf('e') >= 0 ? ox : ox + ow - nw;
      let ny = corner.indexOf('s') >= 0 ? oy : oy + oh - nh;
      box.style.width  = nw + 'px'; box.style.height = nh + 'px';
      box.style.left = Math.max(0, Math.min(W - nw, nx)) + 'px';
      box.style.top  = Math.max(0, Math.min(H - nh, ny)) + 'px';
    }}
  }}
  function up() {{
    mode = null;
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
  }}
  // Ô ký nằm quá nửa trang A4 — cuộn sẵn tới đó, đừng bắt người dùng tự tìm.
  const sc = wrap.parentElement;
  if (sc) sc.scrollTop = Math.max(0, box.offsetTop - 120);
  box.addEventListener('pointerdown', e => down(e, 'move', null));
  box.querySelectorAll('[data-c]').forEach(h =>
      h.addEventListener('pointerdown', e => down(e, 'size', h.dataset.c)));
  window.__sigbox_{cid} = () => ({{
      x_mm: box.offsetLeft / ppm, y_mm: box.offsetTop / ppm,
      w_mm: box.offsetWidth / ppm, h_mm: box.offsetHeight / ppm }});
}})(0);
"""


def _sign_html(cid: str, pv: dict, ppm: float) -> str:
    def _px(v):
        return round(float(v) * ppm, 1)

    w_px = _px(pv["page_w_mm"])
    h_px = _px(pv["page_h_mm"])
    parts = [
        f'<div id="wrap_{cid}" style="position:relative;width:{w_px}px;height:{h_px}px;'
        f'background:#fff;box-shadow:0 1px 6px rgba(0,0,0,.25);user-select:none;">',
        f'<img src="{pv["page_png"]}" draggable="false" '
        f'style="width:100%;height:100%;display:block;pointer-events:none;">',
    ]
    # Chữ ký của người khác đã ký trước — chỉ để nhìn, không kéo được
    for p in pv.get("placed") or []:
        parts.append(
            f'<img src="{p["data_url"]}" draggable="false" title="{p["label"]}" '
            f'style="position:absolute;left:{_px(p["x_mm"])}px;top:{_px(p["y_mm"])}px;'
            f'width:{_px(p["w_mm"])}px;height:{_px(p["h_mm"])}px;pointer-events:none;">'
        )
    sig, box = pv.get("signature"), pv.get("suggest")
    if sig and box:
        hd = ("position:absolute;width:11px;height:11px;background:#fff;border:2px solid #dc2626;"
              "border-radius:2px;")
        parts.append(
            f'<div id="sig_{cid}" style="position:absolute;left:{_px(box["x_mm"])}px;'
            f'top:{_px(box["y_mm"])}px;width:{_px(box["w_mm"])}px;height:{_px(box["h_mm"])}px;'
            f'outline:1px dashed #dc2626;cursor:move;touch-action:none;">'
            f'<img src="{sig["data_url"]}" draggable="false" '
            f'style="width:100%;height:100%;pointer-events:none;">'
            f'<div data-c="nw" style="{hd}left:-6px;top:-6px;cursor:nwse-resize;"></div>'
            f'<div data-c="ne" style="{hd}right:-6px;top:-6px;cursor:nesw-resize;"></div>'
            f'<div data-c="sw" style="{hd}left:-6px;bottom:-6px;cursor:nesw-resize;"></div>'
            f'<div data-c="se" style="{hd}right:-6px;bottom:-6px;cursor:nwse-resize;"></div>'
            f'</div>'
        )
    parts.append("</div>")
    return "".join(parts)


async def _fetch_preview(call):
    """Gọi API xem trước kèm chỉ báo chờ — lần dựng đầu Word mất khoảng 5–7 giây.

    Trả về: payload nếu xong; None nếu phiên hết hạn (đã chuyển về đăng nhập);
    False nếu lỗi khác (gọi xong tự quyết định làm gì tiếp).
    """
    note = ui.notification("Đang dựng bản xem trước…", spinner=True, timeout=None)
    try:
        return await asyncio.to_thread(call)
    except Exception as e:
        if _handle_api_error(e):
            return None
        ui.notify(f"Không xem trước được đơn: {e}", type="warning", timeout=6000)
        return False
    finally:
        note.dismiss()


async def _open_sign_dialog(pv: dict, title: str, ok_label: str, ok_cls: str = "bg-green-600"):
    """Mở popup. Trả về None nếu huỷ, {} nếu xác nhận mà không ký,
    hoặc dict toạ độ {page,x_mm,y_mm,w_mm,h_mm} nếu có đặt chữ ký."""
    import uuid

    cid = uuid.uuid4().hex[:8]
    ppm = _SIGN_PAGE_W_PX / float(pv["page_w_mm"] or 210)
    box = pv.get("suggest") or {}
    has_sig = bool(pv.get("signature")) and bool(box)
    ratio = (float(box.get("h_mm") or 1) / float(box.get("w_mm") or 1)) if has_sig else 1.0

    # max-width inline + !important: Quasar đặt sẵn `.q-dialog__inner--minimized > div
    # { max-width: 560px }` với độ ưu tiên cao hơn class của Tailwind → không ghi đè
    # kiểu này thì ảnh trang A4 rộng 640px bị bóp lại.
    with ui.dialog() as dlg, ui.card().classes("p-4").style("width:auto;max-width:none !important"):
        with ui.row().classes("w-full items-center justify-between mb-1"):
            ui.label(title).classes("text-base font-bold text-gray-800")
            ui.button(icon="close", on_click=lambda: dlg.submit(None)).props("flat dense round")
        if has_sig:
            ui.label("Kéo chữ ký để đổi chỗ · kéo 4 góc để phóng to / thu nhỏ").classes(
                "text-xs text-gray-500 mb-2")
        else:
            ui.label("Chưa có ảnh chữ ký — vào Quản lý người dùng để tải lên. "
                     "Vẫn tiếp tục được nhưng phiếu sẽ không có chữ ký.").classes(
                "text-xs text-orange-600 mb-2")
        with ui.element("div").classes("overflow-auto").style("max-height:66vh"):
            ui.html(_sign_html(cid, pv, ppm))

        async def _ok():
            if not has_sig:
                dlg.submit({})
                return
            try:
                res = await ui.run_javascript(
                    f"window.__sigbox_{cid} ? window.__sigbox_{cid}() : null", timeout=5.0)
            except Exception:
                res = None
            if not res:
                ui.notify("Chưa đọc được vị trí chữ ký — thử lại sau giây lát", type="warning")
                return
            res["page"] = box.get("page", 0)
            dlg.submit(res)

        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("Hủy", on_click=lambda: dlg.submit(None)).classes("text-gray-500")
            ui.button(ok_label, icon="draw", on_click=_ok).classes(f"{ok_cls} text-white")

    ui.run_javascript(_sign_js(cid, ppm, ratio))
    try:
        return await dlg
    finally:
        dlg.delete()


def _leave_status_badge(status: str, label_override: str | None = None):

    label, cls = _LEAVE_STATUS.get(status, (status, "bg-gray-100 text-gray-500"))
    # Đơn NPBB gốc đã bị đơn điều chỉnh thay thế — nhãn riêng thay nhãn chung
    # chung, xem status_label ở backend (_leave_to_out).
    if label_override:
        label = label_override

    ui.label(label).classes(f"text-xs font-medium px-2 py-0.5 rounded border {cls}")





def _fmt_leave_dates(start_str: str, end_str: str, spread_dates=None) -> str:

    """1 ngày → DD/MM/YYYY; liên tiếp → DD/MM → DD/MM/YYYY; lẻ → DD/MM, DD/MM, DD/MM/YYYY"""

    if not start_str or not end_str:

        return "→"

    try:

        from datetime import date as _date

        s = _date.fromisoformat(start_str[:10])

        e = _date.fromisoformat(end_str[:10])

        if s == e:

            return s.strftime("%d/%m/%Y")

        if spread_dates and len(spread_dates) >= 2:

            parsed = sorted(_date.fromisoformat(d[:10]) for d in spread_dates)

            if len(parsed) <= 4:

                parts = [d.strftime("%d/%m") for d in parsed[:-1]]

                parts.append(parsed[-1].strftime("%d/%m/%Y"))

                return ", ".join(parts)

            else:

                first2 = ", ".join(d.strftime("%d/%m") for d in parsed[:2])

                return f"{first2} +{len(parsed) - 2} ngày"

        return f"{s.strftime('%d/%m')} → {e.strftime('%d/%m/%Y')}"

    except Exception:

        return start_str[:10]


def _fmt_ngay_vn(iso_str: str) -> str:

    """YYYY-MM-DD (hoặc có phần giờ) → DD/MM/YYYY, giữ nguyên chuỗi gốc nếu không parse được."""

    if not iso_str:

        return ""

    try:

        from datetime import date as _date

        return _date.fromisoformat(iso_str[:10]).strftime("%d/%m/%Y")

    except Exception:

        return iso_str




def _loc_lui_qua_moc(tu_nam, from_d, to_d, crd) -> bool:
    """Bộ lọc ngày ở Dashboard có chạm tới trước 01/01/`tu_nam` (mốc đã tải) không.

    Có "đến ngày" mà bỏ trống "từ ngày" nghĩa là mở về quá khứ — cũng tính là lùi quá
    mốc. `tu_nam` None = đã tải toàn bộ, không bao giờ cần tải thêm."""
    if not tu_nam:
        return False
    from datetime import date as _date
    moc = _date(tu_nam, 1, 1)
    if (from_d or to_d) and (from_d is None or from_d < moc):
        return True
    return crd is not None and crd < moc


def _gd_display(leave: dict) -> str:

    """Thêm (TUQ) nếu PGĐ ký thay GĐ."""

    name = leave.get("gd_approver_name") or ""

    if name and leave.get("gd_is_pgd"):

        return f"{name} (TUQ)"

    return name


def _approver_cell(name: str, is_pending: bool, width_cls: str):
    """1 ô "KSV/TH/Ban lãnh đạo xác nhận" trong bảng danh sách đơn — đang chờ
    đúng cấp này duyệt (is_pending) thì hiện icon loading thay vì tên (tên
    join sẵn theo approver_id có thể đã có trước khi người đó thật sự bấm
    duyệt), duyệt xong rồi mới hiện tên; chưa tới lượt/không có bước này thì
    hiện "→" như cũ."""
    with ui.row().classes(f"text-xs {width_cls} items-center gap-1 min-w-0"):
        if is_pending:
            ui.spinner(size="1em", color="orange")
            ui.label("Đang chờ duyệt").classes("text-orange-600 italic truncate")
        else:
            ui.label(name or "→").classes("truncate")
