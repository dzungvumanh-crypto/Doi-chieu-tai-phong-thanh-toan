"""API Đối chiếu CITAD ↔ PaymentHub — Phòng Thanh toán.

Port từ tool desktop độc lập (server.py + DoiChieuCITAD.py — xem
`extension_citad/README.md` để biết bối cảnh gốc). Logic buffer/session/xuất
Excel lấy từ `doi_chieu_citad_service.py` — xem docstring ở đó.

Đây là router MỚI, tự quản lý. 2 việc cần Người 1 duyệt riêng:
  1. Đăng ký router này vào backend/api/registry.py
  2. Thêm bảng doi_chieu_citad_sessions vào backend/db/migrations.py

## Xác thực 2 nhóm endpoint khác nhau

- `POST /citad-buffer`, `POST /paymenthub-buffer`: Extension Chrome gọi,
  KHÔNG có JWT (chạy trong content script, không đăng nhập TTTT) — xác thực
  bằng header `X-Extension-Key` khớp biến môi trường `CITAD_EXTENSION_KEY`.
  Biến này BẮT BUỘC phải đặt (fail-fast lúc import, giống `SECRET_KEY` trong
  `backend/core/config.py`) — nếu để mặc định rỗng thì bất kỳ ai chạm được
  cổng backend cũng ghi/đè được buffer của người khác.
- `GET`/`DELETE /citad-buffer`, `GET`/`DELETE /paymenthub-buffer`, mọi
  endpoint session/export: người dùng đã đăng nhập trên web gọi qua
  `frontend/api_client.py` (có sẵn JWT) — xác thực bằng
  `require_feature("menu.doi_chieu_citad")` như mọi router khác trong hệ
  thống, và tự động chỉ thao tác trên buffer/session của CHÍNH người đó
  (`current["username"]` / `current["id"]`).
"""
from __future__ import annotations

import io
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

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

# Fail fast — không dùng fallback rỗng để tránh buffer bị mở công khai khi
# quên set env var (xem docstring module + backend/core/config.py::SECRET_KEY
# cho cùng 1 kiểu bảo vệ đã áp dụng trong dự án).
_EXTENSION_KEY = os.getenv("CITAD_EXTENSION_KEY", "").strip()
if not _EXTENSION_KEY:
    raise RuntimeError(
        "Biến môi trường CITAD_EXTENSION_KEY chưa được đặt.\n"
        "Đây là khoá để Extension Chrome (Đối chiếu CITAD) gọi được API buffer "
        "mà không cần đăng nhập — KHÔNG được để trống, kể cả môi trường dev.\n"
        "Tạo key mạnh: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "Sau đó thêm vào .env: CITAD_EXTENSION_KEY=<giá_trị_vừa_tạo>\n"
        "Rồi đặt đúng giá trị này vào extension_citad/content.js và "
        "content_paymenthub.js (biến EXTENSION_KEY)."
    )


def _check_extension_key(x_extension_key: str = Header(default="")):
    if x_extension_key != _EXTENSION_KEY:
        raise HTTPException(status_code=403, detail="Sai hoặc thiếu khoá Extension")


# ── CITAD buffer ─────────────────────────────────────────────────────────
# POST: Extension gọi (khoá riêng, không JWT). GET/DELETE: người dùng web gọi
# (JWT, tự động chỉ thấy/xoá buffer của chính mình qua current["username"]).
@router.post("/citad-buffer", dependencies=[Depends(_check_extension_key)])
def save_citad_buffer(data: CitadBufferIn):
    svc.buffer_save_citad(data.model_dump())
    return {"ok": True}


@router.get("/citad-buffer")
def get_citad_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    return svc.buffer_get_citad(current["username"])


@router.delete("/citad-buffer")
def clear_citad_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    svc.buffer_clear_citad(current["username"])
    return {"ok": True}


# ── PaymentHub buffer ────────────────────────────────────────────────────
@router.post("/paymenthub-buffer", dependencies=[Depends(_check_extension_key)])
def save_ph_buffer(data: PaymentHubBufferIn):
    svc.buffer_save_ph(data.owner, data.items)
    return {"ok": True}


@router.get("/paymenthub-buffer")
def get_ph_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    return svc.buffer_get_ph(current["username"])


@router.delete("/paymenthub-buffer")
def clear_ph_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    svc.buffer_clear_ph(current["username"])
    return {"ok": True}


# ── Session theo ngày (thay cho SQLite riêng của bản gốc) ───────────────
@router.get("/sessions")
def list_sessions(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    return svc.session_list(db, current["id"])


@router.get("/session/{ngay:path}")
def get_session(
    ngay: str, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))
):
    return svc.session_get(db, ngay, current["id"]) or {}


@router.post("/session")
def save_session(
    data: SessionIn, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))
):
    svc.session_save(db, data.ngay, current["id"], data.model_dump())
    return {"ok": True}


@router.delete("/session/{ngay:path}")
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
