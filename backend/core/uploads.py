"""Trần kích thước cho dữ liệu người dùng gửi lên + làm sạch tên file.

Hai việc, cùng một lý do: **không tin gì ở phía client**.

1. `read_limited()` — đọc `UploadFile` theo từng khối và DỪNG ngay khi vượt
   trần. Trước đây mọi endpoint đều gọi `await file.read()` trắng: Starlette
   0.35.1 có tự đổ file xuống đĩa khi quá 1 MB, nhưng `read()` lại kéo ngược
   toàn bộ lên RAM — một người tải file 3 GB là tiến trình chết, cả hệ thống
   ngừng. Đọc theo khối thì chỗ vượt trần bị chặn trước khi kịp cấp phát.

2. `safe_filename()` — tên file trong multipart là chuỗi client tự đặt,
   Starlette truyền NGUYÊN XI, không cắt đường dẫn. `Path(thư_mục) / tên`
   với tên là "C:/Windows/..." hay "../../.." sẽ nhảy RA NGOÀI thư mục đích
   (ngữ nghĩa của pathlib: đoạn tuyệt đối nuốt trọn đoạn trước nó). Ai ghi đè
   được file .py của backend là chạy được code của mình ở lần khởi động sau.

`BodySizeLimitMiddleware` là lớp chặn cuối: bắt theo Content-Length trước khi
một byte thân request nào được đọc, phòng những endpoint quên gọi hai hàm trên.
"""
import os

from fastapi import HTTPException, UploadFile

_MB = 1024 * 1024


def _so_mb(ten_bien: str, mac_dinh: int) -> int:
    """Đọc một biến môi trường kiểu số MB.

    `int(os.getenv(...))` trực tiếp là bẫy: `.env.example` liệt kê biến với ô
    để TRỐNG cho người vận hành điền, ai copy nguyên xi sang `.env` sẽ có
    `MAX_UPLOAD_MB=` — chuỗi rỗng — và `int("")` ném ValueError NGAY LÚC IMPORT.
    Backend không khởi động nổi, thông báo lỗi thì chẳng nhắc gì tới .env.
    Ô trống hoặc giá trị vô nghĩa ở đây đều lui về mặc định.
    """
    thô = (os.getenv(ten_bien) or "").strip()
    if not thô:
        return mac_dinh
    try:
        gia_tri = int(thô)
    except ValueError:
        return mac_dinh
    return gia_tri if gia_tri > 0 else mac_dinh


# Trần mặc định cho MỘT file tải lên. Rộng tay (báo cáo Excel/ZIP cả tháng vẫn
# lọt) nhưng hữu hạn. Chỉnh bằng .env khi nghiệp vụ thật cần khác.
MAX_UPLOAD_BYTES = _so_mb("MAX_UPLOAD_MB", 200) * _MB

# Trần cho TOÀN BỘ thân request. Phải lớn hơn trần một file vì ACH gửi nhiều
# file trong một lượt (xem _MAX_UPLOAD trong backend/api/ach.py).
MAX_REQUEST_BYTES = _so_mb("MAX_REQUEST_MB", 600) * _MB

_CHUNK = _MB

# Tên thiết bị dành riêng của Windows — mở "NUL" để ghi là ghi vào hư không,
# "COM1" là mở cổng nối tiếp. Không phải lỗ hổng chiếm quyền, nhưng đủ để một
# lần tải lên hỏng âm thầm mà không ai hiểu vì sao.
_TEN_THIET_BI = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def _loi_qua_tran(ten: str, max_bytes: int) -> HTTPException:
    return HTTPException(
        413,
        f"{ten} vượt quá giới hạn {max_bytes // _MB} MB. "
        "Hãy tách nhỏ file rồi tải lại.",
    )


async def read_limited(
    upload: UploadFile, max_bytes: int | None = None, ten: str | None = None
) -> bytes:
    """Đọc toàn bộ nội dung `upload`, ném 413 ngay khi vượt trần."""
    max_bytes = MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    ten = ten or f"File '{upload.filename or 'không tên'}'"
    phan = []
    tong = 0
    while True:
        khoi = await upload.read(_CHUNK)
        if not khoi:
            break
        tong += len(khoi)
        if tong > max_bytes:
            raise _loi_qua_tran(ten, max_bytes)
        phan.append(khoi)
    return b"".join(phan)


def read_limited_sync(
    upload: UploadFile, max_bytes: int | None = None, ten: str | None = None
) -> bytes:
    """Bản đồng bộ của `read_limited()` — cho endpoint `def` và hàm chạy trong
    threadpool (không có event loop để `await`)."""
    max_bytes = MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    ten = ten or f"File '{upload.filename or 'không tên'}'"
    phan = []
    tong = 0
    while True:
        khoi = upload.file.read(_CHUNK)
        if not khoi:
            break
        tong += len(khoi)
        if tong > max_bytes:
            raise _loi_qua_tran(ten, max_bytes)
        phan.append(khoi)
    return b"".join(phan)


def safe_filename(raw: str | None, mac_dinh: str = "file.dat") -> str:
    """Rút tên file an toàn để GHÉP VÀO ĐƯỜNG DẪN từ tên client gửi lên.

    Cắt mọi thành phần thư mục (cả `/` lẫn `\`), bỏ ổ đĩa và luồng dữ liệu
    phụ NTFS (`bao_cao.xlsx:ẩn`), bỏ ký tự điều khiển. Trả `mac_dinh` khi
    không còn gì dùng được — không bao giờ trả chuỗi rỗng.
    """
    ten = (raw or "").replace("\\", "/").split("/")[-1]
    ten = ten.split(":")[-1]
    ten = "".join(ch for ch in ten if ch >= " " and ch != "\x7f").strip()
    ten = ten.strip(". ")                      # ".." , "..." , "tên." đều thành rỗng/an toàn
    if not ten:
        return mac_dinh
    if ten.split(".")[0].upper() in _TEN_THIET_BI:
        ten = "_" + ten
    return ten[:200]


class BodySizeLimitMiddleware:
    """Chặn request có Content-Length vượt trần TRƯỚC khi đọc thân request.

    Middleware ASGI thuần (không phải BaseHTTPMiddleware): nó chỉ nhìn phần
    đầu, không cần dựng Request/Response cho từng lượt gọi.

    Không thay thế `read_limited()`: client có thể gửi kiểu `chunked` không
    kèm Content-Length, khi đó ở đây không biết gì để chặn. Đây là lớp lưới an
    toàn cho endpoint quên đặt trần, không phải lớp phòng thủ duy nhất.
    """

    def __init__(self, app, max_bytes: int = MAX_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for khoa, gia_tri in scope.get("headers", []):
            if khoa == b"content-length":
                try:
                    if int(gia_tri) > self.max_bytes:
                        await self._tu_choi(send)
                        return
                except ValueError:
                    pass
                break
        await self.app(scope, receive, send)

    async def _tu_choi(self, send):
        import json

        than = json.dumps(
            {"detail": f"Dữ liệu gửi lên vượt quá {self.max_bytes // _MB} MB."},
            ensure_ascii=False,
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(than)).encode()),
                (b"connection", b"close"),
            ],
        })
        await send({"type": "http.response.body", "body": than})
