"""Tóm tắt nội dung request để nhật ký hệ thống nói được "đã sửa cái gì".

Trước đây mỗi dòng audit chỉ có method + path + mã HTTP, nên cột "Chi tiết"
trống ở 79% số dòng (đo trên máy thật: 2.292/2.885). Người tra soát biết
"ai đã sửa tập chứng từ" nhưng không biết **sửa gì**.

Ba giới hạn cố ý, đừng nới ra:

* **Chỉ đọc body JSON nhỏ** — file tải lên (multipart) và body lớn bị bỏ qua.
  Middleware đọc body là giữ nguyên cả body trong RAM để trả lại cho route;
  ôm một file ACH 50 MB chỉ để ghi nhật ký là đổi trí nhớ lấy vài dòng chữ.
* **Che khoá nhạy cảm** — mật khẩu, token, ảnh chữ ký không bao giờ vào DB
  nhật ký. Nhật ký bị xuất Excel và tải về được, coi như đã công khai.
* **Cắt ngắn** — một dòng nhật ký là để đọc, không phải để lưu trữ bản sao
  dữ liệu. Muốn biết đủ thì tra chính bảng dữ liệu.
"""
import json
from urllib.parse import parse_qsl

MAX_BODY = 8 * 1024        # ngưỡng đọc body (theo Content-Length)
MAX_DETAIL = 800           # độ dài tối đa chuỗi tóm tắt ghi vào DB
MAX_VALUE = 80             # độ dài tối đa một giá trị đơn lẻ
MAX_ITEMS = 6              # số phần tử liệt kê trong danh sách

# So khớp kiểu "chứa chuỗi con" trên tên khoá đã hạ chữ thường — tên khoá mới
# lỡ đặt là `new_password` hay `signature_image` vẫn dính, không cần khai thêm.
KHOA_NHAY_CAM = (
    "password", "passwd", "mat_khau", "matkhau", "mk_moi", "mk_cu",
    "token", "secret", "api_key", "apikey", "hash",
    "image", "anh_", "signature", "chu_ky", "base64", "avatar",
)


def _nhay_cam(key: str) -> bool:
    k = (key or "").lower()
    return any(x in k for x in KHOA_NHAY_CAM)


def nen_doc_body(headers) -> bool:
    """Có nên đọc body của request này không (theo header, chưa đụng tới body)."""
    ct = (headers.get("content-type") or "").lower()
    if not ct.startswith("application/json"):
        return False           # multipart / octet-stream / form → bỏ qua
    try:
        cl = int(headers.get("content-length") or 0)
    except ValueError:
        return False           # chunked, không biết trước độ dài → bỏ qua
    return 0 < cl <= MAX_BODY


# ── Dựng chuỗi từ dữ liệu đã parse ───────────────────────────────────────────
def _gia_tri(v, depth: int) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "có" if v else "không"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        s = v.strip().replace("\n", " ")
        return s if len(s) <= MAX_VALUE else s[:MAX_VALUE] + "…"
    if isinstance(v, list):
        if not v:
            return "[rỗng]"
        if all(isinstance(x, (str, int, float, bool)) for x in v):
            phan = [_gia_tri(x, depth) for x in v[:MAX_ITEMS]]
            them = f" …+{len(v) - MAX_ITEMS}" if len(v) > MAX_ITEMS else ""
            return "[" + ", ".join(phan) + them + "]"
        return f"[{len(v)} mục]"
    if isinstance(v, dict):
        if depth <= 0:
            return f"{{{len(v)} trường}}"
        return "{" + _cap_khoa(v, depth - 1) + "}"
    return str(v)[:MAX_VALUE]


def _cap_khoa(d: dict, depth: int) -> str:
    phan = []
    for k, v in d.items():
        phan.append(f"{k}=***" if _nhay_cam(k) else f"{k}={_gia_tri(v, depth)}")
    return ", ".join(phan)


def tom_tat(query_string: str, body: bytes | None) -> str:
    """Chuỗi mô tả 'đã gửi lên cái gì'. Trả "" nếu không có gì đáng ghi."""
    phan = []

    if query_string:
        qs = ", ".join(
            f"{k}=***" if _nhay_cam(k) else f"{k}={_gia_tri(v, 0)}"
            for k, v in parse_qsl(query_string, keep_blank_values=True)
        )
        if qs:
            phan.append(f"?{qs}")

    if body:
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            data = None
        if isinstance(data, dict):
            phan.append(_cap_khoa(data, 1))
        elif isinstance(data, list):
            phan.append(_gia_tri(data, 1))
        elif data is not None:
            phan.append(_gia_tri(data, 0))

    s = " · ".join(x for x in phan if x)
    return s if len(s) <= MAX_DETAIL else s[:MAX_DETAIL] + "…"
