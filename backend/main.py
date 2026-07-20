"""FastAPI Application Entry Point"""
import logging
import logging.handlers
import os
import sqlite3
import sys
from contextlib import asynccontextmanager

# Thêm root vào path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


# ── Logging tập trung ──────────────────────────────────────────────────────────
def _setup_logging():
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    if root.handlers:       # Tránh duplicate khi uvicorn --reload
        return
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = logging.handlers.RotatingFileHandler(
        "logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

_setup_logging()

from backend.db.migrations import _create_tables, _ensure_indexes
from backend.api.registry import apply_routers
from backend.database import DB_PATH
from backend.core.config import settings as _settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khởi động: tạo bảng, migrate schema, start backup scheduler."""
    _create_tables(DB_PATH)
    _ensure_indexes()
    from backend.services.backup_service import start_scheduler as _start_backup
    _start_backup(_settings.DATABASE_URL.replace("sqlite:///", ""))
    # Cảnh báo (không chặn khởi động) nếu đồng hồ máy lệch nguồn giờ chuẩn
    import asyncio as _asyncio
    from backend.services.time_sync import check_drift_and_log as _check_drift
    _asyncio.get_event_loop().run_in_executor(None, _check_drift)
    yield


_docs_url = "/docs" if (_settings.ENV != "production" or _settings.ENABLE_API_DOCS) else None
_redoc_url = "/redoc" if (_settings.ENV != "production" or _settings.ENABLE_API_DOCS) else None

app = FastAPI(
    title="PAYMENT CENTER",
    description="Hệ thống quản lý nhân sự và chứng từ hậu kiểm",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

from backend.core.audit_middleware import AuditMiddleware
app.add_middleware(AuditMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

apply_routers(app)

_db_log = logging.getLogger("db.contention")


@app.exception_handler(sqlite3.OperationalError)
async def _db_error_handler(request, exc):
    msg = str(exc).lower()
    if "locked" in msg or "busy" in msg:
        _db_log.warning("SQLite BUSY — %s %s : %s", request.method, request.url.path, msg)
    else:
        _db_log.error("DB OperationalError — %s %s : %s", request.method, request.url.path, msg)
    return JSONResponse(status_code=503, content={"detail": "Hệ thống bận, vui lòng thử lại"})


@app.get("/")
def root():
    return {"message": "PAYMENT CENTER API đang chạy", "docs": "/docs"}
