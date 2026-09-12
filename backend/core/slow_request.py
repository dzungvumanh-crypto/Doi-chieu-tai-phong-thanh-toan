"""Ghi WARNING cho request chạy lâu hơn ngưỡng — để biết chỗ nào cần tối ưu.

Vì sao cần: hệ thống có log `db.contention` cho lỗi khoá CSDL, nhưng KHÔNG có gì
đo thời gian của request bình thường. Không có số thì mọi việc "tối ưu hiệu năng"
đều là đoán (xem mục 1.2 kế hoạch cải tiến).

Hai điểm thiết kế:

* **ASGI thuần, đo tới lúc gửi xong THÂN phản hồi.** `BaseHTTPMiddleware` chỉ đo
  tới lúc có header — file tải về 100 MB stream trong 30 giây sẽ hiện ra như một
  request 20 ms. Ở đây mốc dừng là `http.response.body` cuối cùng.
* **Ngưỡng riêng cho việc chậm CÓ CHỦ ĐÍCH.** Một ngưỡng phẳng 1,5 giây sẽ kêu
  liên tục ở những đường vốn dĩ lâu (dựng bản in qua Word 5–7 giây lần đầu, nộp
  file đối chiếu hàng trăm MB), và log kêu liên tục thì không ai đọc nữa.
"""
import logging
import time

from backend.core.config import settings

_log = logging.getLogger("slow.request")

# (tiền tố đường dẫn, ngưỡng ms, vì sao) — khớp theo tiền tố DÀI NHẤT.
# Đây là những đường CHẬM LÀ BÌNH THƯỜNG; chậm hơn cả mức này mới đáng kêu.
_NGUONG_RIENG = (
    ("/api/leaves/preview", 8000),               # Word dựng bản in: lần đầu 5–7 s (DESIGN.md)
    ("/api/ach", 10000),                         # nộp + chạy đối chiếu, file hàng trăm MB
    ("/api/ilo1000", 10000),
    ("/api/cham459901", 10000),
    ("/api/doi_chieu_song_phuong", 10000),
    ("/api/doi_chieu_song_phuong_kenh_core", 10000),
    ("/api/doi_chieu_song_phuong_kenh_core_di", 10000),   # đoạn riêng, KHÔNG nằm trong tiền tố trên
    ("/api/doi-chieu-citad", 10000),
    ("/api/doi-chieu-citad-nostro", 10000),
    ("/api/doi-soat-citad", 10000),
    ("/api/swift-recon", 10000),
)

# Đoạn đường dẫn chứa một trong các từ này = dựng file (Excel/Word/PDF/ZIP) — việc
# nặng có chủ đích ở bất kỳ module nào. Xét theo TỪNG ĐOẠN và dùng "chứa" chứ không
# "bắt đầu bằng": tên route thật có đủ kiểu — `/export-db`, `/export-summary`,
# `/parse-preview`, `/extension-download`, `/month-summary/export`.
_TU_VIEC_NANG = ("export", "preview", "download")
_MS_NANG = 8000


def _khop_tien_to(path: str, pre: str) -> bool:
    """Khớp theo ĐOẠN, không theo ký tự: `/api/ach` không được nuốt `/api/achilles`."""
    return path == pre or path.startswith(pre + "/")


def _nguong_ms(path: str) -> int | None:
    """Ngưỡng cho đường dẫn này, None = không theo dõi."""
    for p in settings.SLOW_REQUEST_EXCLUDE:
        if _khop_tien_to(path, p):      # cùng luật đoạn: khai /api/ach không tắt /api/achilles
            return None
    # Tiền tố DÀI NHẤT thắng — không phải ngưỡng lớn nhất: thêm một tiền tố con có
    # ngưỡng thấp hơn thì phải là cái đó quyết định.
    khop = [(len(pre), ms) for pre, ms in _NGUONG_RIENG if _khop_tien_to(path, pre)]
    if khop:
        return max(khop)[1]
    if any(tu in doan for doan in path.split("/") for tu in _TU_VIEC_NANG):
        return _MS_NANG
    return settings.SLOW_REQUEST_MS


class SlowRequestMiddleware:
    """Đo từ lúc nhận request tới lúc gửi xong byte cuối của phản hồi."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        nguong = _nguong_ms(scope.get("path", ""))
        if nguong is None:
            return await self.app(scope, receive, send)

        t0 = time.perf_counter()
        tt = {"ma": 0, "da_ghi": False}

        def ghi(ket_qua: str):
            ms = (time.perf_counter() - t0) * 1000
            if ms >= nguong:
                _log.warning(
                    "Request chậm: %s %s — %d ms (ngưỡng %d ms, %s)",
                    scope.get("method", "?"), scope.get("path", "?"),
                    round(ms), nguong, ket_qua,
                )

        async def send_do(message):
            if message["type"] == "http.response.start":
                tt["ma"] = message["status"]
            await send(message)
            # Chỉ tính khi đã gửi hết thân
            if message["type"] == "http.response.body" and not message.get("more_body"):
                tt["da_ghi"] = True
                ghi(f"HTTP {tt['ma']}")

        try:
            await self.app(scope, receive, send_do)
        except Exception:
            # Lỗi không ai bắt: phản hồi 500 do ServerErrorMiddleware dựng, mà nó nằm
            # NGOÀI middleware này nên không mảnh thân nào đi qua send_do. "Chạy 30 giây
            # rồi sập" đúng là ca cần thấy nhất — không ghi ở đây thì nó vô hình.
            # Cố ý bắt Exception chứ không BaseException: client ngắt giữa chừng ném
            # CancelledError, đó là lỗi đường truyền chứ không phải request chậm.
            if not tt["da_ghi"]:
                ghi("ném ngoại lệ")
            raise
