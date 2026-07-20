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
    BACKEND_HOST: str = "0.0.0.0"
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

settings = Settings()
