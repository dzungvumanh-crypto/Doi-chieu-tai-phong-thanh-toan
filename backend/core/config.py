"""Cấu hình ứng dụng"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

# Fail fast — không dùng fallback để tránh JWT bị forge khi quên set env var
_secret_key = os.getenv("SECRET_KEY", "")
if not _secret_key:
    raise RuntimeError(
        "Biến môi trường SECRET_KEY chưa được đặt.\n"
        "Tạo key mạnh: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "Sau đó: set SECRET_KEY=<giá_trị_vừa_tạo>  (Windows) hoặc export SECRET_KEY=... (Linux/Mac)"
    )

class Settings:
    APP_NAME: str = "PAYMENT CENTER"
    SECRET_KEY: str = _secret_key
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 8

    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/ksnb.db"

    # Thư mục backup phụ (nên ở ổ/máy khác) — để trống nếu không dùng.
    # Ví dụ: BACKUP_EXTRA_DIR=D:\Backup_KSNB  hoặc  \\192.168.1.50\backup
    BACKUP_EXTRA_DIR: str = os.getenv("BACKUP_EXTRA_DIR", "").strip()
    # Địa chỉ backend lắng nghe. `run.py` đọc chính biến này để truyền cho uvicorn,
    # nên đổi ở .env là đổi thật — trước đây nó là hằng số cứng, ai sửa .env cũng
    # không có tác dụng gì, mà cảnh báo khởi động lại dựa vào nó nên báo sai.
    #   0.0.0.0   = nghe mọi giao diện (cần khi có máy khác gọi thẳng API)
    #   127.0.0.1 = chỉ nghe nội bộ máy — kín hơn, đủ dùng khi frontend cùng máy
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "0.0.0.0").strip() or "0.0.0.0"
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
    FRONTEND_PORT: int = int(os.getenv("FRONTEND_PORT", "8080"))

    TEMPLATE_DIR: Path = BASE_DIR / "templates"
    MAX_SHEETS_PER_BUNDLE: int = 350

    # Môi trường: development | production
    ENV: str = os.getenv("ENV", "development")

    # Origins được phép — phân cách bằng dấu phẩy, ví dụ: http://localhost:8080,http://192.168.1.100:8080
    # Mặc định suy ra từ FRONTEND_PORT nếu không set riêng
    ALLOWED_ORIGINS: list = [
        o.strip()
        for o in os.getenv("ALLOWED_ORIGINS", f"http://localhost:{os.getenv('FRONTEND_PORT', '8080')}").split(",")
        if o.strip()
    ]

    # Bật /docs, /redoc — chỉ bật khi debug; mặc định tắt ở production
    ENABLE_API_DOCS: bool = os.getenv("ENABLE_API_DOCS", "").lower() in ("1", "true", "yes")

    # Nguồn thời gian chuẩn (NTP) — chỉ dùng để CẢNH BÁO lệch giờ, không tự sửa.
    # Mạng nội bộ bị cô lập: đặt NTP_SERVER về NTP nội bộ (vd domain controller)
    # hoặc NTP_ENABLED=false để tắt hẳn.
    NTP_ENABLED: bool = os.getenv("NTP_ENABLED", "true").lower() not in ("0", "false", "no")
    NTP_SERVER: str = os.getenv("NTP_SERVER", "pool.ntp.org").strip()
    NTP_TIMEOUT_SEC: float = float(os.getenv("NTP_TIMEOUT_SEC", "3"))
    NTP_DRIFT_THRESHOLD_SEC: int = int(os.getenv("NTP_DRIFT_THRESHOLD_SEC", "5"))

# ── Mật khẩu file ZIP do hệ thống nguồn cấp ──────────────────────────────────
# Ba module dùng chung một mật khẩu: Đối chiếu ACH, Chấm 459901, Đối chiếu
# Song phương. Trước đây nó nằm CỨNG trong mã (`ZIP_PASSWORD = b"..."`) ở cả ba
# nơi, tức là đã đi vào lịch sử git — xoá khỏi mã hôm nay cũng không xoá được
# khỏi lịch sử, ai từng clone repo là có.
#
# Cố ý KHÔNG fail-fast lúc khởi động như SECRET_KEY: ba module này là tính năng
# tuỳ chọn, thiếu mật khẩu không phải lý do để cả hệ thống không lên. Đổi lại
# phải nêu rõ nguyên nhân ĐÚNG LÚC dùng, nếu không người vận hành chỉ thấy
# "giải nén thất bại" và đi tìm nhầm chỗ (file hỏng? sai đường dẫn?).
def zip_password() -> bytes:
    """Mật khẩu giải nén file nguồn. Raise nếu chưa cấu hình."""
    raw = (os.getenv("DOI_CHIEU_ZIP_PASSWORD") or "").strip()
    if not raw:
        raise RuntimeError(
            "Chưa đặt DOI_CHIEU_ZIP_PASSWORD trong file .env — không giải nén được "
            "file nguồn của Đối chiếu ACH / Chấm 459901 / Đối chiếu Song phương. "
            "Thêm vào .env:  DOI_CHIEU_ZIP_PASSWORD=<mật_khẩu_do_đơn_vị_cấp_file_cung_cấp>"
        )
    return raw.encode()


# ── Thư mục được phép quét cho "Chấm 459901 → Chọn thư mục server" ───────────
# Route /api/cham459901/process_folder nhận đường dẫn do người dùng gõ rồi ĐỌC
# file trên chính máy chủ. Không giới hạn gốc thì nó thành hai thứ khác hẳn ý
# định ban đầu: một máy dò "thư mục này có tồn tại không" cho mọi đường dẫn trên
# máy chủ (hai câu lỗi khác nhau là đủ để phân biệt), và — nếu thư mục tình cờ
# có một file .zip/.xlsx — một cách liệt kê TÊN toàn bộ file còn lại trong đó
# qua danh sách `unrecognized` trả về.
#
# Fail-closed: chưa cấu hình thì route báo lỗi nói rõ phải thêm gì vào .env,
# KHÔNG mặc định về BASE_DIR. Mặc định "cho tạm một chỗ" là kiểu hàng rào mà
# người vận hành không biết mình đang dựa vào cho tới lúc nó không đủ.
# Nhiều thư mục ngăn nhau bằng dấu ";" (quy ước Windows).
def cham459901_folder_roots() -> list[Path]:
    """Các thư mục gốc được phép quét. Raise nếu chưa cấu hình."""
    raw = (os.getenv("CHAM459901_FOLDER_ROOTS") or "").strip()
    if not raw:
        raise RuntimeError(
            "Chưa đặt CHAM459901_FOLDER_ROOTS trong file .env — chức năng "
            "\"Chọn thư mục server\" của Chấm 459901 bị khoá. Thêm vào .env "
            "thư mục chứa dữ liệu (nhiều thư mục ngăn bằng dấu ;), ví dụ:  "
            "CHAM459901_FOLDER_ROOTS=D:\\DuLieu\\459901"
        )
    return [Path(x.strip()).resolve() for x in raw.split(";") if x.strip()]


settings = Settings()
