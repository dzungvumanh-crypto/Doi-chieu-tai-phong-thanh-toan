"""Shared utilities, helpers và constants dùng chung cho tất cả pages."""
import asyncio
import logging
import os
from nicegui import ui, app
import frontend.api_client as api
import frontend.ui_kit as ui_kit

_log = logging.getLogger(__name__)

# ─── Colors ──────────────────────────────────────────────────────────────────
# Định nghĩa thật nằm ở ui_kit.py — giữ tên COLORS ở đây cho code cũ và
# phần re-export trong frontend/main.py.
COLORS = ui_kit.COLORS

# ─── Navigation structure ─────────────────────────────────────────────────────
# Mỗi department có thể có items con. Thêm item mới: chèn vào "items" của phòng tương ứng.
DEPARTMENTS = [
    {
        "id": "ksnb",
        "label": "Phòng KSNB & HTVH",
        "icon": "manage_search",
        "items": [
            ("handovers", "Bàn giao chứng từ", "receipt_long"),
            ("bundles",   "Đóng chứng từ",     "folder_zip"),
            ("storage",   "Lưu trữ",            "inventory_2"),
            {
                "label": "Báo cáo",
                "icon": "assessment",
                "items": [
                    ("reports",          "Báo cáo hậu kiểm",          "fact_check"),
                    ("handover_reports", "Báo cáo bàn giao chứng từ", "assignment_late"),
                ],
            },
        ],
    },
    {"id": "swift", "label": "Phòng Swift", "icon": "swap_horiz",
     "items": [
         ("swift_recon", "Đối chiếu điện SWIFT", "compare_arrows"),
     ]},
    {
        "id": "payment", "label": "Phòng Thanh toán", "icon": "payments",
        "items": [
            ("duty_schedule", "Phân lịch trực", "edit_calendar"),
            {
                "label": "Đối chiếu",
                "icon": "compare_arrows",
                "items": [
                    ("cham_459901",           "Chấm 459901",            "task_alt"),
                    ("doi_chieu_song_phuong", "Đối chiếu Song phương",  "account_balance"),
                    ("doi_chieu_citad",       "Đối chiếu CITAD",        "account_balance_wallet"),
                    ("doi_soat_citad",        "Đối soát CITAD ↔ IPCAS", "fact_check"),
                ],
            },
        ],
    },
    # ── Phòng chưa có chức năng — giữ làm marker mở rộng, items rỗng nên không render ──
    {"id": "ktoan",   "label": "Phòng Kế toán",             "icon": "calculate",       "items": []},
    {"id": "nostro",  "label": "Phòng QLTK Nostro, Vostro", "icon": "account_balance", "items": []},
    {
        "id": "tonghop",
        "label": "Phòng Tổng hợp",
        "icon": "summarize",
        "items": [
            ("leaves", "Nghỉ phép", "event_busy"),
            {
                "label": "Báo cáo",
                "icon": "assessment",
                "items": [
                    ("th_reports", "Báo cáo dữ liệu thanh toán", "payments"),
                ],
            },
        ],
    },
    # ── Chưa có chức năng — xem ghi chú ở nhóm phòng rỗng phía trên ──
    {"id": "bgd", "label": "Ban Giám đốc", "icon": "business_center", "items": []},
]

# Hai nhóm dưới đây trước nằm inline trong _sidebar(). Tách ra module-level để
# breadcrumb đọc được — nếu không sẽ phải chép lại nhãn ở chỗ thứ hai và hai
# bản sao sẽ lệch nhau ngay lần đổi tên đầu tiên.
DEPT_NHATKY = {
    "id": "nhatky",
    "label": "Nhật ký hệ thống",
    "icon": "terminal",
    "items": [
        ("audit-logs", "Nhật ký hệ thống",        "history"),
        ("logs",       "Lịch sử lỗi & cảnh báo", "error_outline"),
        ("login-logs", "Nhật ký đăng nhập",       "login"),
    ],
}

DEPT_PHANQUYEN = {
    "id": "phanquyen",
    "label": "Phân quyền chức năng",
    "icon": "admin_panel_settings",
    "items": [
        ("groups",         "Nhóm user",           "groups"),
        ("group-features", "Phân quyền theo nhóm", "tune"),
    ],
}

# Chuyên viên chỉ thấy 2 mục này (flat, không theo phòng ban)
MENU_ITEMS_CV = [
    ("handovers", "Bàn giao chứng từ", "receipt_long"),
    ("leaves",    "Nghỉ phép",          "event_busy"),
]


def _build_breadcrumbs() -> dict[str, list[str]]:
    """route key → đường dẫn menu. Dựng 1 lần lúc import từ chính cây menu."""
    def _clean(parts: list[str]) -> list[str]:
        # Bỏ đoạn trùng liền kề: nhóm "Nhật ký hệ thống" có item cùng tên,
        # để nguyên sẽ ra "Nhật ký hệ thống / Nhật ký hệ thống".
        out: list[str] = []
        for p in parts:
            if not out or out[-1] != p:
                out.append(p)
        return out

    paths: dict[str, list[str]] = {}
    for dept in [*DEPARTMENTS, DEPT_NHATKY, DEPT_PHANQUYEN]:
        for item in dept["items"]:
            if isinstance(item, tuple):
                paths[item[0]] = _clean([dept["label"], item[1]])
            else:
                for k, lbl, _ in item["items"]:
                    paths[k] = _clean([dept["label"], item["label"], lbl])
    return paths


# Trang không nằm trong menu (login, /home, /user-management...) không có khoá
# ở đây → _page_header bỏ qua breadcrumb, hiển thị như cũ.
BREADCRUMBS = _build_breadcrumbs()

# CSS flyout menu — submenu hiện bên phải khi hover, không đẩy item phía dưới
_SIDEBAR_CSS = """<style>
.dept-item { position: relative; z-index: 0; }
.dept-item:hover { z-index: 1000; }
.dept-flyout, .sub-flyout {
  display: none;
  position: fixed;
  background-color: #7f1d1d;
  z-index: 9999;
  min-width: 13rem;
  flex-direction: column;
  box-shadow: 6px 4px 20px rgba(0,0,0,0.5);
  border-radius: 0 8px 8px 0;
  border-left: 3px solid #991b1b;
  overflow: visible;
}
.dept-item:hover .dept-flyout { display: flex; }
.flyout-group { position: relative; z-index: 0; }
.flyout-group:hover { z-index: 10001; }
.sub-flyout { z-index: 10000; }
.flyout-group:hover .sub-flyout { display: flex; }

/* ── Gradient nền sidebar ── */
.sidebar-gradient {
  background: linear-gradient(135deg, #991b1b 0%, #7f1d1d 50%, #450a0a 100%);
}

/* ── Thu gọn sidebar (chỉ hiện icon) ── */
#app-sidebar { transition: width 0.2s ease; }
#app-content { transition: margin-left 0.2s ease, width 0.2s ease; }
body.sb-collapsed #app-sidebar { width: 4.5rem !important; }
body.sb-collapsed #app-content { margin-left: 4.5rem !important; width: calc(100% - 4.5rem) !important; }
body.sb-collapsed .sidebar-label { display: none !important; }
body.sb-collapsed .sidebar-row { justify-content: center !important; padding-left: 0 !important; padding-right: 0 !important; }
body.sb-collapsed .sidebar-icon { margin-right: 0 !important; }

/* ── Khối "Công việc chờ xử lý" khi sidebar thu gọn: giữ icon + số ──
   Badge KHÔNG mang class .sidebar-label nên không bị ẩn cùng nhãn chữ. Ở chế độ
   thu gọn .sidebar-row bị ép justify-content:center, icon và badge dồn sát nhau
   nên phải kéo badge nhô lên góc phải cho khỏi chồng lên icon. */
body.sb-collapsed .pending-box .sidebar-row { position: relative; }
body.sb-collapsed .pending-badge {
  position: absolute;
  top: 0.1rem;
  right: 0.7rem;
  font-size: 10px;
  min-width: 1.05rem;
  height: 1.05rem;
  box-shadow: 0 0 0 2px #7f1d1d;
}
/* Khối rỗng thì không để lại khoảng trắng ở đầu menu */
body.sb-collapsed .pending-box .q-separator { margin-left: 0.75rem; margin-right: 0.75rem; }

/* Nút toggle: đang mở hiện icon "đóng", đang thu gọn hiện icon "mở" */
.sb-ico-expand { display: none; }
body.sb-collapsed .sb-ico-expand { display: inline; }
body.sb-collapsed .sb-ico-collapse { display: none; }

/* ── Vùng menu tự cuộn khi cao hơn màn hình — luôn vừa với viewport ── */
#sidebar-menu-scroll { scrollbar-width: thin; scrollbar-color: #b91c1c #7f1d1d; }
#sidebar-menu-scroll::-webkit-scrollbar { width: 6px; }
#sidebar-menu-scroll::-webkit-scrollbar-thumb { background: #b91c1c; border-radius: 3px; }
</style>
<script>
function toggleSidebar() {
  var collapsed = document.body.classList.toggle('sb-collapsed');
  try { localStorage.setItem('sb-collapsed', collapsed ? '1' : '0'); } catch (e) {}
}
/* Màn hẹp (máy trạm 1366px) thu gọn sidebar sẵn để nhường chỗ cho bảng;
   chỉ áp khi người dùng chưa từng tự bấm nút toggle */
var SB_NARROW_PX = 1440;
document.addEventListener('DOMContentLoaded', function () {
  var pref = null;
  try { pref = localStorage.getItem('sb-collapsed'); } catch (e) {}
  var collapsed = pref === null ? window.innerWidth <= SB_NARROW_PX : pref === '1';
  if (collapsed) document.body.classList.add('sb-collapsed');
});

/* ── Flyout menu con: position:fixed để thoát vùng overflow của sidebar cuộn,
   JS tự tính tọa độ và đổi hướng mở lên/xuống theo khoảng trống còn lại ── */
function _sidebarFlyoutOf(item) {
  return item.querySelector(':scope > .dept-flyout') || item.querySelector(':scope > .sub-flyout');
}
document.addEventListener('mouseover', function (e) {
  var item = e.target.closest('.dept-item, .flyout-group');
  if (!item || item.contains(e.relatedTarget)) return;
  var flyout = _sidebarFlyoutOf(item);
  if (!flyout) return;
  var rect = item.getBoundingClientRect();
  flyout.style.left = rect.right + 'px';
  flyout.style.top = rect.top + 'px';
  flyout.style.bottom = 'auto';
  if (flyout.getBoundingClientRect().bottom > window.innerHeight) {
    flyout.style.top = 'auto';
    flyout.style.bottom = (window.innerHeight - rect.bottom) + 'px';
  }
}, true);
</script>"""


# ─── Helpers ─────────────────────────────────────────────────────────────────
async def _logout():
    await asyncio.to_thread(api.logout_session)
    api.clear_auth()
    ui.navigate.to("/login")


def _query_params() -> dict:
    """Tham số trên URL trang hiện tại. Rỗng nếu client không mang request (shared client)."""
    req = getattr(ui.context.client, "request", None)
    return dict(req.query_params) if req is not None else {}


def _qp_int(params: dict, key: str):
    """Đọc tham số số nguyên. Giá trị rác → None để caller dùng mặc định."""
    try:
        return int(params[key])
    except (KeyError, TypeError, ValueError):
        return None


def _dmy(iso: str) -> str:
    """'2026-08-01' → '01/08/2026'. Chuỗi lạ thì trả nguyên — không nuốt."""
    parts = (iso or "").split("-")
    return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else (iso or "")


# ─── Khối "Công việc chờ xử lý" ───────────────────────────────────────────────
# key → (nhãn, icon, khoá đếm trong /pending-counts, feature cần có để mở được)
_PENDING_DEFS = [
    ("handovers", "Chứng từ chờ xác nhận",  "receipt_long", "menu.handovers"),
    ("leaves",    "Đơn nghỉ phép chờ duyệt", "event_busy",   "menu.leaves"),
]


def _pending_section():
    """Khối đầu sidebar. Dựng sẵn ở trạng thái ẩn, số về tới đâu hiện tới đó.

    Nạp bất đồng bộ bằng ui.timer thay vì gọi API ngay trong _sidebar(): sidebar
    là hàm đồng bộ dựng ở mọi trang, gọi mạng tại đây sẽ chặn render toàn bộ 19
    trang. Đánh đổi: khối xuất hiện trễ ~105ms sau khi trang vẽ xong (100ms trễ
    của timer + ~4ms gọi /pending-counts, đã đo). Thời gian load trang không đổi.
    """
    box = ui.column().classes("w-full gap-0 pending-box")
    box.set_visibility(False)
    rows: dict = {}

    with box:
        ui.label("Công việc chờ xử lý").classes(
            "sidebar-label px-4 pt-3 pb-1 text-[11px] font-semibold uppercase "
            "tracking-wide text-red-300"
        )
        for key, label, icon, _feat in _PENDING_DEFS:
            row = ui.row().classes(
                "sidebar-row w-full items-center px-4 py-2 cursor-pointer hover:bg-red-800"
            ).on("click", lambda k=key: ui.navigate.to(f"/pending/{k}"))
            row.set_visibility(False)
            with row:
                ui.icon(icon).classes("sidebar-icon text-lg mr-3 text-red-100 shrink-0")
                ui.label(label).classes("sidebar-label text-sm flex-1 leading-tight")
                badge = ui.label("").classes(
                    "pending-badge text-xs font-bold bg-yellow-400 text-red-900 rounded-full "
                    "min-w-[1.25rem] h-[1.25rem] flex items-center justify-center px-1 shrink-0"
                )
            rows[key] = (row, badge)
        ui.separator().classes("border-red-700 mt-2")

    async def _load():
        try:
            counts = await asyncio.to_thread(api.get, "/api/dashboard/pending-counts")
        except Exception as e:
            # Sidebar hỏng không được kéo cả trang xuống — trang tự có heartbeat
            # xử lý phiên hết hạn. Ghi log để lỗi không biến mất im lặng.
            _log.warning("Không nạp được số việc chờ xử lý: %s", e)
            return
        any_visible = False
        for key, _lbl, _ico, feat in _PENDING_DEFS:
            cnt = (counts or {}).get(key, 0)
            # Có việc nhưng không có quyền mở màn hình đó thì đừng dựng link chết
            if not isinstance(cnt, int) or cnt <= 0 or not api.has_feature(feat):
                continue
            row, badge = rows[key]
            badge.set_text(str(cnt))
            row.set_visibility(True)
            any_visible = True
        box.set_visibility(any_visible)

    ui.timer(0.1, _load, once=True)


def _nav_item(key: str, label: str, icon: str, current_page: str):
    """Mục menu phẳng (không thuộc phòng ban).

    Không gắn badge số ở đây nữa — số việc chờ chỉ hiện ở khối "Công việc chờ
    xử lý" đầu sidebar, để cùng một thông tin không xuất hiện hai chỗ.
    """
    is_active = current_page == key
    bg = "bg-red-700" if is_active else "hover:bg-red-800"
    with ui.row().classes(
        f"sidebar-row w-full items-center px-4 py-2.5 cursor-pointer {bg}"
    ).on("click", lambda k=key: ui.navigate.to(f"/{k}")):
        ui.icon(icon).classes("sidebar-icon text-lg mr-3 text-red-100 shrink-0")
        ui.label(label).classes("sidebar-label text-sm flex-1")


def _item_visible(item, check_features: bool) -> bool:
    """Kiểm tra một item (tuple hoặc sub-group dict) có visible không."""
    if isinstance(item, tuple):
        k, _, _ = item
        return not check_features or api.has_feature(f"menu.{k}")
    # dict = sub-group: visible nếu ít nhất 1 child visible
    return any(
        not check_features or api.has_feature(f"menu.{k}")
        for k, _, _ in item["items"]
    )


def _dept_group(dept: dict, current_page: str, check_features: bool = True):
    """Nhóm phòng ban — hover để xem flyout menu bên phải (không đẩy các mục dưới xuống).
    check_features=True: lọc items theo api.has_feature(); False: hiện tất cả (dùng cho admin menu cứng).
    Item có thể là tuple (key, label, icon) hoặc dict sub-group {"label", "icon", "items"}.
    """
    visible_items = [i for i in dept["items"] if _item_visible(i, check_features)]
    if not visible_items:
        return  # gồm cả phòng chưa có chức năng (items rỗng) — không render header chết

    # Tổng hợp tất cả route keys (kể cả trong sub-group) để detect active state
    dept_keys: set[str] = set()
    for item in visible_items:
        if isinstance(item, tuple):
            dept_keys.add(item[0])
        else:
            dept_keys.update(k for k, _, _ in item["items"])
    is_active_dept = current_page in dept_keys

    with ui.element("div").classes("dept-item w-full"):
        # ── Header phòng (luôn hiển thị, không click) ──
        active_cls = " bg-red-800" if is_active_dept else ""
        with ui.element("div").classes(
            f"sidebar-row flex items-center px-3 py-2.5 cursor-default select-none hover:bg-red-800 w-full{active_cls}"
        ):
            ui.icon(dept["icon"]).classes("sidebar-icon text-base mr-2 text-red-200 shrink-0")
            ui.label(dept["label"]).classes("sidebar-label text-xs font-semibold text-red-100 flex-1 leading-tight")
            if visible_items:
                ui.icon("chevron_right").classes("sidebar-label text-sm text-red-400 shrink-0")

        # ── Flyout submenu (xuất hiện bên phải khi hover) ──
        if visible_items:
            with ui.element("div").classes("dept-flyout"):
                with ui.element("div").classes("px-3 py-1.5 border-b border-red-700").style("background:#4c0519"):
                    ui.label(dept["label"]).classes("text-xs font-semibold text-red-300")
                for item in visible_items:
                    if isinstance(item, tuple):
                        # ── Item thông thường ──
                        key, label, icon = item
                        is_active = current_page == key
                        bg = "bg-red-700" if is_active else "hover:bg-red-800"
                        with ui.row().classes(
                            f"w-full items-center px-4 py-2.5 cursor-pointer {bg}"
                        ).on("click", lambda k=key: ui.navigate.to(f"/{k}")):
                            ui.icon(icon).classes("text-base mr-2 text-red-100 shrink-0")
                            ui.label(label).classes("text-sm flex-1")
                    else:
                        # ── Sub-group (nested flyout) ──
                        sub_children = [
                            (k, lbl, ico) for k, lbl, ico in item["items"]
                            if not check_features or api.has_feature(f"menu.{k}")
                        ]
                        if not sub_children:
                            continue
                        is_active_sub = any(current_page == k for k, _, _ in sub_children)
                        sub_bg = "bg-red-700" if is_active_sub else "hover:bg-red-800"
                        with ui.element("div").classes("flyout-group w-full"):
                            with ui.row().classes(
                                f"w-full items-center px-4 py-2.5 cursor-default select-none {sub_bg}"
                            ):
                                ui.icon(item["icon"]).classes("text-base mr-2 text-red-100 shrink-0")
                                ui.label(item["label"]).classes("text-sm flex-1")
                                ui.icon("chevron_right").classes("text-sm text-red-400 shrink-0")
                            with ui.element("div").classes("sub-flyout"):
                                with ui.element("div").classes(
                                    "px-3 py-1.5 border-b border-red-700"
                                ).style("background:#4c0519"):
                                    ui.label(item["label"]).classes("text-xs font-semibold text-red-300")
                                for k, lbl, ico in sub_children:
                                    is_active = current_page == k
                                    bg = "bg-red-700" if is_active else "hover:bg-red-800"
                                    with ui.row().classes(
                                        f"w-full items-center px-4 py-2.5 cursor-pointer {bg}"
                                    ).on("click", lambda kk=k: ui.navigate.to(f"/{kk}")):
                                        ui.icon(ico).classes("text-base mr-2 text-red-100 shrink-0")
                                        ui.label(lbl).classes("text-sm flex-1")


def _sidebar(current_page: str) -> dict:
    # Trả về dict rỗng — badge số đã chuyển hết vào khối "Công việc chờ xử lý".
    # Giữ kiểu trả về để 19 trang đang gọi không phải sửa chữ ký.
    badge_refs: dict = {}
    ui_kit.install()          # token màu + font Inter cho 19 trang có sidebar
    ui.add_head_html(_SIDEBAR_CSS)

    with ui.column().props("id=app-sidebar").classes(
        "w-64 h-screen sidebar-gradient text-white fixed left-0 top-0 shadow-xl z-[200] "
        "overflow-hidden flex flex-col"
    ):
        # ── Nút thu gọn / mở rộng menu ──
        with ui.row().classes(
            "w-full items-center px-3 py-2 border-b border-red-700 shrink-0"
        ):
            ui.html(
                '<button type="button" id="sb-toggle" onclick="toggleSidebar()" '
                'title="Thu gọn / mở rộng menu" aria-label="Thu gọn / mở rộng menu" '
                'style="background:transparent;border:none;cursor:pointer;color:#fecaca;'
                'display:flex;align-items:center;justify-content:center;width:2rem;height:2rem;'
                'border-radius:6px;flex-shrink:0;" '
                "onmouseover=\"this.style.background='rgba(255,255,255,0.12)'\" "
                "onmouseout=\"this.style.background='transparent'\">"
                '<i class="material-icons sb-ico-collapse" style="font-size:20px;">menu_open</i>'
                '<i class="material-icons sb-ico-expand" style="font-size:20px;">menu</i></button>'
            )

        # ── Logo ──
        with ui.row().classes(
            "sidebar-row w-full items-center px-3 py-3 border-b border-red-700 shrink-0"
        ):
            ui.image("/static/agribank_logo.png").classes("sidebar-icon w-10 h-10 shrink-0")
            ui.label("PAYMENT CENTER").classes(
                "sidebar-label font-semibold text-sm text-white ml-2 leading-snug"
            )

        # ── User info (click → /user-management nếu không phải chuyen_vien) ──
        user = api.get_current_user()
        user_role = user.get("role", "") if user else ""
        if user:
            role_map = {
                "giam_doc":      "Giám đốc",
                "pho_giam_doc":  "Phó Giám đốc",
                "admin":         "Quản trị viên cấp 1",
                "admin_l2":      "Quản trị viên cấp 2",
                "hau_kiem_vien": "Hậu kiểm viên",
                "truong_phong":  "Trưởng phòng",
                "pho_phong":     "Phó phòng",
                "chuyen_vien":   "Chuyên viên",
            }
            clickable = user_role != "chuyen_vien"
            col_cls = "sidebar-label px-4 py-3 border-b border-red-700 w-full shrink-0"
            if clickable:
                col_cls += " cursor-pointer hover:bg-red-800"
            col = ui.column().classes(col_cls)
            if clickable:
                col.on("click", lambda: ui.navigate.to("/user-management"))
            with col:
                with ui.row().classes("items-center gap-1"):
                    ui.label(user.get("full_name", "")).classes("font-semibold text-sm")
                    if clickable:
                        ui.icon("manage_accounts").classes("text-yellow-300 text-sm")
                ui.label(role_map.get(user.get("role"), "")).classes("text-yellow-300 text-xs")

        # ── Vùng menu (tự cuộn nội bộ nếu cao hơn màn hình) ──
        with ui.column().props("id=sidebar-menu-scroll").classes(
            "w-full flex-1 py-1 overflow-y-auto min-h-0"
        ):
            # Việc đang chờ — nằm trên cùng, tự ẩn khi không có việc nào
            _pending_section()

            # Trang chủ — luôn hiển thị
            _nav_item("home", "Trang chủ", "home", current_page)

            # Phân cấp theo phòng ban (flyout) — hiện theo feature
            for dept in DEPARTMENTS:
                _dept_group(dept, current_page, check_features=True)

            ui.separator().classes("border-red-700 my-1")

            # Quản lý User — admin luôn thấy, user khác cần feature
            if user_role == "admin" or api.has_feature("menu.staff"):
                _nav_item("staff", "Quản lý User", "manage_accounts", current_page)

            # Nhật ký hệ thống — admin luôn thấy, user khác cần feature
            if user_role == "admin" or api.has_feature("menu.logs"):
                _dept_group(DEPT_NHATKY, current_page, check_features=False)

            # Phân quyền chức năng — chỉ admin (hard-coded, không phải feature)
            if user_role == "admin":
                _dept_group(DEPT_PHANQUYEN, current_page, check_features=False)

        # ── Đăng xuất ──
        with ui.row().classes(
            "sidebar-row w-full items-center px-4 py-3 cursor-pointer hover:bg-red-800 "
            "border-t border-red-700 shrink-0"
        ).on("click", _logout):
            ui.icon("logout").classes("sidebar-icon text-xl mr-3 text-red-300")
            ui.label("Đăng xuất").classes("sidebar-label text-sm")

    return badge_refs


def _content_area():
    return (
        ui.column()
        .props("id=app-content")
        .classes("ml-64 min-h-screen bg-gray-50 p-6 overflow-x-auto")
        .style("width: calc(100% - 16rem)")
    )


def _current_breadcrumb() -> list[str]:
    """Đường dẫn menu của trang đang mở, suy ra từ route — trang tự khai báo
    thì 19 chỗ gọi _page_header đều phải sửa và dễ ghi sai."""
    try:
        route = ui.context.client.page.path
    except Exception as e:
        _log.warning("Không đọc được route cho breadcrumb: %s", e)
        return []
    crumbs = BREADCRUMBS.get(route.strip("/"), [])
    return crumbs if len(crumbs) > 1 else []   # 1 đoạn = trùng tiêu đề, bỏ


def _page_header(title: str, subtitle: str = ""):
    # Breadcrumb và tiêu đề nằm chung một dòng — tách hai dòng thì tên trang bị
    # lặp lại hai lần. Đoạn cuối lấy từ `title` (trang tự khai), không lấy nhãn
    # menu, nên không có chuyện hai nguồn lệch nhau.
    ancestors = _current_breadcrumb()[:-1]
    with ui.column().classes("mb-6"):
        with ui.row().classes("items-baseline gap-1.5 flex-wrap"):
            for name in ancestors:
                ui.label(name).classes("text-sm text-gray-500")
                ui.label("/").classes("text-sm text-gray-300")
            ui.label(title).classes("text-2xl font-bold text-red-900")
        if subtitle:
            ui.label(subtitle).classes("text-gray-500 text-sm mt-1")


def _card(title: str = ""):
    with ui.card().classes("w-full shadow-sm rounded-xl bg-white p-0 overflow-hidden") as card:
        if title:
            with ui.row().classes("w-full bg-red-50 px-4 py-3 border-b border-red-100"):
                ui.label(title).classes("font-semibold text-red-800")
    return card


def _require_auth():
    """Redirect về login nếu chưa đăng nhập."""
    if not api.get_current_user():
        ui.navigate.to("/login")
        return False

    client = ui.context.client

    async def _tab_check():
        try:
            await client.connected()
        except Exception:
            return
        tab_id = client.tab_id
        tab_data = app.storage._tabs.get(tab_id) if tab_id else None
        if not (tab_data and tab_data.get("session_alive")):
            api.clear_auth()
            client.open("/login")
    asyncio.ensure_future(_tab_check())

    # ── Kiểm tra session bị thay thế mỗi 60 giây ──
    async def _session_heartbeat():
        try:
            await asyncio.to_thread(api.get, "/api/auth/me")
        except api.DisplacedSessionError:
            api.clear_auth()
            ui.notify("Tài khoản này đang được đăng nhập từ thiết bị khác", type="warning", timeout=4000)
            client.open("/login?reason=displaced")
        except Exception:
            pass  # network hiccup — bỏ qua
    ui.timer(60, _session_heartbeat)

    return True


def _redirect_if_cv():
    """Chặn chuyên viên theo VAI TRÒ — chỉ còn dùng cho /user-management.

    Mọi trang khác đã chuyển sang `api.has_feature("menu.*")`, tức nhóm quyền.
    Giữ hàm này ở trang Quản lý người dùng vì đó là trang duy nhất không có mã
    feature nào để kiểm. Đừng gọi lại ở trang mới: chặn theo vai trò ở frontend
    trong khi backend chặn theo feature nghĩa là admin cấp quyền qua nhóm nhưng
    người dùng vẫn bị đá ra, không kèm thông báo nào.
    """
    user = api.get_current_user()
    if user and user.get("role") == "chuyen_vien":
        ui.navigate.to("/home")
        return True
    return False


def _handle_api_error(e: Exception) -> bool:
    """Xử lý lỗi API. Trả True nếu cần redirect (caller nên return)."""
    if isinstance(e, api.DisplacedSessionError):
        ui.notify(str(e), type="warning", timeout=4000)
        ui.navigate.to("/login?reason=displaced")
        return True
    if isinstance(e, api.SessionExpiredError):
        ui.notify(str(e), type="warning")
        ui.navigate.to("/login")
        return True
    ui.notify(str(e), type="negative")
    return False
