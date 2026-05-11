"""Cấu hình ứng dụng"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent.parent
load_dotenv(BASE_DIR / ".env")

# Fail fast — không dùng fallback để tránh JWT bị forge khi quên set env var
_secret_key = os.getenv("SECRET_KEY", "")
if not _secret_key:
    raise RuntimeError(
        "Biến môi trường SECRET_KEY chưa được đặt.\n"
        "Tạo key mạnh: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "Sau đó: set SECRET_KEY=<giá_trị_vừa_tạo>  (Windows) hoặc export SECRET_KEY=... (Linux/Mac)"
    )

class Settings:
    APP_NAME: str = "KSNB&HTVH Manager"
    SECRET_KEY: str = _secret_key
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 8

    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/ksnb.db"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    FRONTEND_PORT: int = 8080

    TEMPLATE_DIR: Path = BASE_DIR / "templates"
    MAX_SHEETS_PER_BUNDLE: int = 350

settings = Settings()
