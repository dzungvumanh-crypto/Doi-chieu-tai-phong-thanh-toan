"""Trang trí chủ đề Quốc khánh 2-9 — dùng chung cho trang login và trang chủ.

Tự bật/tắt theo ngày (xem `_BAT_DAU` / `_KET_THUC`), không cần deploy để gỡ sau lễ.
Toàn bộ hoạ tiết vẽ bằng CSS + SVG nội tuyến: máy trạm trong mạng nội bộ có thể
không ra được internet, tải ảnh từ ngoài sẽ hỏng lặng lẽ.
"""
from datetime import date
from nicegui import ui

# ── Khoảng ngày hiển thị ──────────────────────────────────────────────────────
_NAM_KHAI_SINH = 1945          # 2/9/1945
_BAT_DAU  = (8, 25)            # bật từ 25/8
_KET_THUC = (9, 3)             # hết ngày 3/9 (2/9 + 1 ngày đệm)

# Màu cờ Tổ quốc — KHÔNG lấy từ ui_kit.COLORS: đó là tông đỏ Agribank (#8B0000),
# đổi nhận diện ngân hàng sẽ kéo theo đổi màu cờ, hai thứ không liên quan nhau.
_DO_CO   = "#DA251D"
_VANG_CO = "#FFCD00"


def dang_dip_le(hom_nay: date | None = None) -> bool:
    d = hom_nay or date.today()
    return _BAT_DAU <= (d.month, d.day) <= _KET_THUC


def so_nam(hom_nay: date | None = None) -> int:
    return (hom_nay or date.today()).year - _NAM_KHAI_SINH


def hai_dong(hom_nay: date | None = None) -> tuple[str, str]:
    """Khẩu hiệu tách sẵn hai dòng tại chữ "VÀ".

    Không để trình duyệt tự ngắt: khẩu hiệu ~156 ký tự chữ hoa cần ~1.400px trên
    một dòng — tràn cả màn 1366. Tự ngắt sẽ rơi vào giữa cụm ngày tháng hoặc giữa
    tên nước tuỳ bề rộng cửa sổ; cắt cụt kèm "…" thì mất chữ của khẩu hiệu.
    """
    nam = (hom_nay or date.today()).year
    n = so_nam(hom_nay)
    return (
        f"NHIỆT LIỆT CHÀO MỪNG {n} NĂM CÁCH MẠNG THÁNG TÁM THÀNH CÔNG "
        f"(19/8/{_NAM_KHAI_SINH} - 19/8/{nam})",
        f"VÀ QUỐC KHÁNH NƯỚC CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM "
        f"(2/9/{_NAM_KHAI_SINH} - 2/9/{nam})!",
    )


def cau_chuc(hom_nay: date | None = None) -> str:
    return " ".join(hai_dong(hom_nay))


# ── Hoạ tiết ──────────────────────────────────────────────────────────────────
# Sao năm cánh dựng bằng clip-path thay vì ảnh: co giãn theo mọi kích thước,
# không thêm request nào, và đổi màu chỉ bằng background.
_CLIP_SAO = ("polygon(50% 3%, 61% 38%, 98% 38%, 68% 60%, 79% 95%, "
             "50% 73%, 21% 95%, 32% 60%, 2% 38%, 39% 38%)")

_LOGIN_CSS = f"""
<style>
/* ── Nền dịp lễ ─────────────────────────────────────────────────────────────
   Đỏ cờ bừng sáng quanh card rồi sẫm dần ra rìa. Không tô đỏ cờ phẳng toàn
   trang: chữ trắng trên #DA251D chỉ đạt 4,9:1, còn panel đường dẫn phủ thêm
   một lớp trắng 9% lên nền nên tụt xuống sát ngưỡng đọc được. Vùng sáng nhất
   ở đây là #B81C1B — chữ trắng đạt 6,5:1, chữ link (92% trắng) 5,1:1.
   !important vì login.py đặt background thẳng vào thuộc tính style của thẻ. */
html, body {{ background: #7C1015 !important; }}
.pc-main {{
  background:
    radial-gradient(120% 90% at 50% 30%,
      rgba(218, 37, 29, 0.55) 0%, rgba(218, 37, 29, 0.18) 45%, rgba(218, 37, 29, 0) 72%),
    linear-gradient(180deg, #8E1219 0%, #6E0F14 55%, #520A0F 100%) !important;
}}

/* Nền sáng hơn nền cũ → kéo chữ link lên cho khỏi tụt dưới ngưỡng AA */
.pc-link {{ color: rgba(255, 255, 255, 0.92) !important; }}

/* Dải cờ trên đỉnh — thay thanh vàng Agribank trong dịp lễ */
.pc-topbar {{
  height: 5px !important;
  background: linear-gradient(90deg,
    {_DO_CO} 0%, {_VANG_CO} 20%, {_VANG_CO} 80%, {_DO_CO} 100%) !important;
}}

/* Sao vàng làm hoạ tiết nền. Nằm trong .pc-bg (z-index 0, pointer-events:none)
   nên không che ô nhập; độ mờ giữ thấp để chữ trắng trên nền đỏ không bị giảm
   tương phản. */
.pc-sao {{
  position: absolute; background: {_VANG_CO};
  -webkit-clip-path: {_CLIP_SAO}; clip-path: {_CLIP_SAO};
}}
.pc-sao--to {{
  width: 560px; height: 560px; top: 50%; left: 50%;
  transform: translate(-50%, -54%); opacity: 0.085;
}}
.pc-sao--nho {{
  width: 170px; height: 170px; right: 6%; bottom: 8%;
  transform: rotate(14deg); opacity: 0.075;
}}

.pc-le-chuc {{
  color: #FFE08A; font-size: 15px; font-weight: 700;
  letter-spacing: 0.02em; text-align: center; line-height: 1.35;
  display: flex; align-items: center; justify-content: center; gap: 12px;
}}
.pc-le-chuc .pc-le-txt {{ display: flex; flex-direction: column; }}
.pc-le-chuc::before, .pc-le-chuc::after {{
  content: ""; width: 26px; height: 26px; flex: none;
  background: {_VANG_CO}; opacity: 0.9;
  -webkit-clip-path: {_CLIP_SAO}; clip-path: {_CLIP_SAO};
}}
</style>
"""


def trang_tri_login() -> None:
    """Gọi bên trong khối .pc-bg của trang login, sau khi đã nạp CSS gốc."""
    if not dang_dip_le():
        return
    ui.element("div").classes("pc-sao pc-sao--to")
    ui.element("div").classes("pc-sao pc-sao--nho")


def css_login() -> None:
    if dang_dip_le():
        ui.add_head_html(_LOGIN_CSS)


def dong_chuc_login() -> None:
    if not dang_dip_le():
        return
    with ui.element("div").classes("pc-le-chuc mb-5"):
        with ui.element("div").classes("pc-le-txt"):
            for dong in hai_dong():
                ui.label(dong)


# ── Trang chủ ─────────────────────────────────────────────────────────────────
# Sao mờ rải trong nền dải banner chứ không đặt ở nền vùng nội dung: vùng đó bị
# các card trắng phủ gần kín nên watermark sẽ không ai nhìn thấy.
# Sao 20px + khoảng trống nằm ngay trong viewBox (150x100 cho hình 30x20) thay vì
# kéo giãn bằng background-size: đặt size 26x18 cho một SVG vuông làm sao béo ngang.
# Khoảng trắng mã hoá thành %20 — data URI để trần dấu cách là chỗ trình duyệt cũ
# hay bỏ cuộc.
_SAO_NEN = (
    "url(\"data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'"
    "%20width='30'%20height='20'%20viewBox='0%200%20150%20100'%3E"
    "%3Cpolygon%20points='75,3%2086,38%20123,38%2093,60%20104,95%2075,73"
    "%2046,95%2057,60%2027,38%2064,38'%20fill='%23DA251D'%20opacity='0.10'"
    "/%3E%3C/svg%3E\")"
)

_HOME_CSS = f"""
<style>
/* ── Nền dịp lễ cho vùng nội dung ───────────────────────────────────────────
   Ấm dần lên phía trên rồi trở lại đúng #F9FAFB (bg-gray-50) ở đáy, nên card
   trắng vẫn nổi và biểu đồ echart giữ nguyên nền sáng để đọc số. Chỉ đổi nền
   vùng nội dung — KHÔNG đụng sidebar: sidebar dùng chung cho 19 trang, đổi ở
   đó là đổi toàn hệ thống chứ không còn là trang chủ nữa. */
#app-content {{
  background: linear-gradient(180deg,
    #FFF0DE 0%, #FFF7EC 22%, #FCFBF7 58%, #F9FAFB 100%) !important;
}}

/* Cao 44px — trang chủ khoá đúng 1 viewport (h-screen), mỗi pixel thêm vào đây
   là một pixel lấy đi của biểu đồ bên dưới. Khẩu hiệu đầy đủ phải xuống 2 dòng
   (xem hai_dong()), 44px là mức vừa khít cho 2 dòng chữ 14px.
   Chữ căn giữa nên mọi thứ phải đối xứng: viền hai bên thay cho viền trái, và
   gradient đậm ở hai đầu — nhạt ở giữa, để chữ nổi trên chỗ nhạt nhất. */
.hm-le {{
  height: 44px; display: flex; align-items: center; justify-content: center;
  gap: 10px; padding: 0 12px; border-radius: 8px;
  border-left: 3px solid {_VANG_CO}; border-right: 3px solid {_VANG_CO};
  background: linear-gradient(90deg, rgba(218, 37, 29, 0.16) 0%,
                rgba(255, 205, 0, 0.14) 50%, rgba(218, 37, 29, 0.16) 100%),
              {_SAO_NEN} left center repeat-x;
  color: #7F1D1D; font-size: 14px; font-weight: 700; letter-spacing: 0.01em;
  line-height: 1.25; text-align: center; overflow: hidden;
}}
.hm-le .q-icon {{ color: {_DO_CO}; font-size: 20px; flex: none; }}
/* Màn hẹp: dòng dài hơn dải thì cắt ở cuối kèm dấu "…". Không có min-width:0 thì
   flex item không co được, chữ sẽ bị cắt cụt ở CẢ HAI đầu vì đang căn giữa. */
.hm-le .hm-le-chu {{ min-width: 0; display: flex; flex-direction: column; }}
.hm-le .hm-le-chu > * {{
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
</style>
"""


def css_trang_chu() -> None:
    """Nạp sớm, cùng chỗ với CSS khác của trang — add_head_html gọi sau khi client
    đã kết nối thì NiceGUI chèn bằng JS, dải banner sẽ nháy một nhịp chưa có kiểu."""
    if dang_dip_le():
        ui.add_head_html(_HOME_CSS)


def dai_trang_chu() -> None:
    if not dang_dip_le():
        return
    with ui.element("div").classes("hm-le w-full flex-none"):
        ui.icon("star")
        with ui.element("div").classes("hm-le-chu"):
            for dong in hai_dong():
                ui.label(dong)
        ui.icon("star")
