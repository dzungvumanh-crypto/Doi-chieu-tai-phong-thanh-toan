"""Cấu hình ứng dụng"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent

class Settings:
    APP_NAME: str = "KSNB&HTVH Manager"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "ksnb-secret-key-change-in-production-2024")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 8

    DATABASE_URL: str = f"sqlite:///{BASE_DIR}/data/ksnb.db"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    FRONTEND_PORT: int = 8080

    TEMPLATE_DIR: Path = BASE_DIR / "templates"
    MAX_SHEETS_PER_BUNDLE: int = 350

settings = Settings()
