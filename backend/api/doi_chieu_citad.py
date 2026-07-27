"""API Đối chiếu CITAD ↔ PaymentHub — Phòng Thanh toán.

Port từ tool desktop độc lập `citad-fixed/` (server.py + DoiChieuCITAD.py).
Logic buffer/session/xuất Excel lấy NGUYÊN từ `doi_chieu_citad_service.py`
(không sửa) — xem docstring ở đó.

Đây là router MỚI, tự quản lý. 2 việc cần Người 1 duyệt riêng (xem
SNIPPETS_TO_PASTE.md):
  1. Đăng ký router này vào backend/api/registry.py
  2. Thêm bảng doi_chieu_citad_sessions vào backend/db/migrations.py
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
import io

from backend.database import get_db
from backend.core.deps import require_feature
from backend.schemas.doi_chieu_citad import (
    CitadBufferIn,
    ExportIn,
    PaymentHubBufferIn,
    SessionIn,
)
from backend.services import doi_chieu_citad_service as svc

router = APIRouter(prefix="/api/doi-chieu-citad", tags=["doi-chieu-citad"])

# Khoá đơn giản (không phải JWT) để Extension Chrome gọi được 2 API buffer mà
# không cần đăng nhập — extension chạy trong trình duyệt, không giữ JWT.
# Đặt biến môi trường CITAD_EXTENSION_KEY trong .env; để trống = không yêu
# cầu khoá (giữ đúng hành vi mở của bản gốc, chỉ nên dùng khi test local).
_EXTENSION_KEY = os.getenv("CITAD_EXTENSION_KEY", "")


def _check_extension_key(x_extension_key: str = Header(default="")):
    if _EXTENSION_KEY and x_extension_key != _EXTENSION_KEY:
        raise HTTPException(status_code=403, detail="Sai hoặc thiếu khoá Extension")


# ── CITAD buffer ─────────────────────────────────────────────────────────
@router.post("/citad-buffer", dependencies=[Depends(_check_extension_key)])
def save_citad_buffer(data: CitadBufferIn):
    svc.buffer_save_citad(data.dict())
    return {"ok": True}


@router.get("/citad-buffer", dependencies=[Depends(_check_extension_key)])
def get_citad_buffer():
    return svc.buffer_get_citad()


@router.delete("/citad-buffer", dependencies=[Depends(_check_extension_key)])
def clear_citad_buffer():
    svc.buffer_clear_citad()
    return {"ok": True}


# ── PaymentHub buffer ────────────────────────────────────────────────────
@router.post("/paymenthub-buffer", dependencies=[Depends(_check_extension_key)])
def save_ph_buffer(data: PaymentHubBufferIn):
    svc.buffer_save_ph(data.items)
    return {"ok": True}


@router.get("/paymenthub-buffer", dependencies=[Depends(_check_extension_key)])
def get_ph_buffer():
    return svc.buffer_get_ph()


@router.delete("/paymenthub-buffer", dependencies=[Depends(_check_extension_key)])
def clear_ph_buffer():
    svc.buffer_clear_ph()
    return {"ok": True}


# ── Session theo ngày (thay cho SQLite riêng của bản gốc) ───────────────
@router.get("/sessions")
def list_sessions(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    return svc.session_list(db, current["id"])


@router.get("/session/{ngay}")
def get_session(
    ngay: str, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))
):
    return svc.session_get(db, ngay, current["id"]) or {}


@router.post("/session")
def save_session(
    data: SessionIn, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))
):
    svc.session_save(db, data.ngay, current["id"], data.dict())
    return {"ok": True}


@router.delete("/session/{ngay}")
def delete_session(
    ngay: str, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))
):
    svc.session_delete(db, ngay, current["id"])
    return {"ok": True}


# ── Xuất Excel ────────────────────────────────────────────────────────────
@router.post("/export")
def export_excel(data: ExportIn, current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    buf = svc.build_xlsx(data)
    fname = f"Doi_chieu_CITAD_{data.sheet_name}.xlsx"
    return StreamingResponse(
        io.BytesIO(buf),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
