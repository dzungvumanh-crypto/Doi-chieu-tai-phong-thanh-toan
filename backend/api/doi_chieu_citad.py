"""API Đối chiếu CITAD ↔ PaymentHub — Phòng Thanh toán.

Port từ tool desktop độc lập (server.py + DoiChieuCITAD.py — xem
`extension_citad/README.md` để biết bối cảnh gốc). Logic buffer/session/xuất
Excel lấy từ `doi_chieu_citad_service.py` — xem docstring ở đó.

Đây là router MỚI, tự quản lý. 2 việc cần Người 1 duyệt riêng:
  1. Đăng ký router này vào backend/api/registry.py
  2. Thêm bảng doi_chieu_citad_sessions + doi_chieu_citad_extension_tokens
     vào backend/db/migrations.py

## Xác thực buffer — thiết kế lại sau review bảo mật

Bản đầu dùng 1 khoá tĩnh dùng chung (`CITAD_EXTENSION_KEY`) cho toàn Phòng
Thanh toán + field `owner` do CHÍNH Extension tự khai trong payload. Review
chỉ ra: ai có khoá cũng ghi được buffer dưới BẤT KỲ tên nào — kể cả cố tình
chèn số liệu giả để dòng chênh lệch ra đúng 0 rồi người lập bảng ký duyệt mà
không biết. Đây là lỗ hổng nặng nhất trong toàn bộ PR.

Thiết kế mới — **mã kết nối (extension token) cá nhân**:
- Người dùng đăng nhập web TTTT thật (JWT) → vào `/doi_chieu_citad` → bấm
  "Tạo mã kết nối" → nhận 1 token ngẫu nhiên (chỉ hiện ĐÚNG 1 lần) → dán vào
  Extension (`extension_citad/content.js`, hằng số `EXTENSION_TOKEN`).
- Backend chỉ lưu SHA-256 hash của token (`doi_chieu_citad_extension_tokens`,
  1 dòng/staff — tạo mã mới tự thu hồi mã cũ).
- `POST /citad-buffer`, `POST /paymenthub-buffer`: xác thực bằng header
  `X-Extension-Token`, backend TRA CỨU `owner` từ token hợp lệ trong DB —
  KHÔNG còn nhận `owner` do client tự khai trong payload nữa.
- `GET`/`DELETE` buffer, mọi endpoint session/export/token: người dùng đã
  đăng nhập gọi qua `frontend/api_client.py` (JWT) — `require_feature` +
  `current["username"]` như mọi router khác.

Token bị lộ chỉ ảnh hưởng đúng 1 người (không phải cả phòng), thu hồi được
riêng lẻ, không cần đổi khoá chung. Vẫn còn 1 rủi ro CHƯA giải quyết bằng
code: token truyền qua HTTP thường (không TLS) vẫn đọc được nếu bắt gói tin
trên mạng nội bộ — bắt buộc backend production phải chạy sau HTTPS, xem
cảnh báo tự động trong `extension_citad/content.js`.
"""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response, StreamingResponse

from backend.database import get_db
from backend.core.deps import require_feature
from backend.schemas.doi_chieu_citad import (
    CitadBufferIn,
    ExportIn,
    ExtensionTokenOut,
    ExtensionTokenStatus,
    PaymentHubBufferIn,
    SessionIn,
)
from backend.services import doi_chieu_citad_service as svc

router = APIRouter(prefix="/api/doi-chieu-citad", tags=["doi-chieu-citad"])


def _resolve_extension_owner(x_extension_token: str = Header(default=""), db=Depends(get_db)) -> str:
    """Dependency cho 2 endpoint POST buffer — trả về username chủ token
    hợp lệ, KHÔNG bao giờ tin owner do client tự khai."""
    owner = svc.resolve_extension_token(db, x_extension_token)
    if not owner:
        raise HTTPException(
            status_code=403,
            detail="Mã kết nối Extension không hợp lệ hoặc đã bị thu hồi — "
            "vào /doi_chieu_citad, mục 'Kết nối Extension' để tạo mã mới.",
        )
    return owner


# ── CITAD buffer ─────────────────────────────────────────────────────────
# POST: Extension gọi (xác thực bằng token cá nhân, không JWT). GET/DELETE:
# người dùng web gọi (JWT, tự động chỉ thấy/xoá buffer của chính mình).
@router.post("/citad-buffer")
def save_citad_buffer(data: CitadBufferIn, owner: str = Depends(_resolve_extension_owner)):
    svc.buffer_save_citad(owner, data.model_dump())
    return {"ok": True}


@router.get("/citad-buffer")
def get_citad_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    return svc.buffer_get_citad(current["username"])


@router.delete("/citad-buffer")
def clear_citad_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    svc.buffer_clear_citad(current["username"])
    return {"ok": True}


# ── PaymentHub buffer ────────────────────────────────────────────────────
@router.post("/paymenthub-buffer")
def save_ph_buffer(data: PaymentHubBufferIn, owner: str = Depends(_resolve_extension_owner)):
    svc.buffer_save_ph(owner, data.items)
    return {"ok": True}


@router.get("/paymenthub-buffer")
def get_ph_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    return svc.buffer_get_ph(current["username"])


@router.delete("/paymenthub-buffer")
def clear_ph_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    svc.buffer_clear_ph(current["username"])
    return {"ok": True}


# ── Mã kết nối Extension (thay CITAD_EXTENSION_KEY dùng chung) ───────────
@router.get("/extension-token/status", response_model=ExtensionTokenStatus)
def extension_token_status(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    return svc.get_extension_token_status(db, current["id"])


@router.post("/extension-token", response_model=ExtensionTokenOut)
def create_extension_token(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    """Tạo mã mới — TỰ ĐỘNG thu hồi mã cũ (1 token/người). Trả plaintext
    ĐÚNG 1 LẦN, backend chỉ lưu hash, không xem lại được."""
    token = svc.generate_extension_token(db, current["id"])
    return {"token": token}


@router.delete("/extension-token")
def delete_extension_token(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    svc.revoke_extension_token(db, current["id"])
    return {"ok": True}


@router.get("/extension-download")
def download_extension(current: dict = Depends(require_feature("menu.doi_chieu_citad"))):
    """Tải extension_citad/ dạng .zip để người dùng tự giải nén + Load
    unpacked — Chrome không cho web tự cài extension, đây chỉ là bước tải
    file cho tiện, không thay thế được thao tác cài thủ công."""
    try:
        content = svc.build_extension_zip()
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="extension_citad.zip"'},
    )


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
