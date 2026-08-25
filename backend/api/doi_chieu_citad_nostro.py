"""API Đối chiếu CITAD ↔ PaymentHub — Phòng QLTK Nostro, Vostro.

Router SONG SONG, độc lập với `backend/api/doi_chieu_citad.py` (Phòng
Thanh toán) — không sửa router đó, không dùng chung bảng/buffer/session.

Extension Chrome là gói RIÊNG (`extension_citad_nv/`) — KHÔNG dùng chung
`extension_citad/` của Phòng Thanh toán (theo đúng yêu cầu nghiệp vụ: 2
phòng không trùng Extension). Chỉ tái dùng CHUNG cơ chế "mã kết nối" (bảng
`doi_chieu_citad_extension_tokens`, trung lập theo staff_id — xem
`doi_chieu_citad_nostro_service.py`) nên 1 mã tạo ra vẫn dán được vào CẢ 2
Extension nếu 1 người dùng cả 2 module.

Endpoint `/extension-token*`, `/extension-download`, `/extension-version`
bên dưới khai báo RIÊNG (không gọi sang router `/api/doi-chieu-citad/...`
của Phòng Thanh toán) vì mỗi router gate bằng feature code khác nhau
(`menu.doi_chieu_citad_nostro` ở đây, `menu.doi_chieu_citad` bên đó) — user
Nostro không có quyền `menu.doi_chieu_citad` nên gọi thẳng endpoint bên đó
sẽ bị 403.

Chỉ MỚI 2 endpoint buffer (citad/paymenthub — cấu trúc dữ liệu khác hẳn bản
gốc) + toàn bộ nhóm session/lịch sử/export (khoá theo `ky`, không phải
`ngay`).
"""
from __future__ import annotations

import io
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from backend.database import get_db
from backend.core import audit_queue
from backend.core.net import header_ip_dang_tin
from backend.core.concurrency import run_heavy
from backend.core.deps import require_feature
from backend.schemas.doi_chieu_citad_nostro import (
    CitadBufferIn,
    ExportIn,
    PaymentHubBufferIn,
    SessionIn,
)
# Trung lập, không định nghĩa lại — dùng thẳng schema gốc cho 4 endpoint
# mã kết nối Extension (mô tả bên dưới).
from backend.schemas.doi_chieu_citad import ExtensionTokenOut, ExtensionTokenStatus
from backend.services import doi_chieu_citad_nostro_service as svc


def _safe_filename(name: str) -> str:
    return re.sub(r'[\r\n"\\]', '_', name)


router = APIRouter(prefix="/api/doi-chieu-citad-nostro", tags=["doi-chieu-citad-nostro"])


def _resolve_extension_owner(
    request: Request, x_extension_token: str = Header(default=""), db=Depends(get_db)
) -> str:
    """Bản sao của `_resolve_extension_owner` trong
    `backend/api/doi_chieu_citad.py` — cùng cơ chế mã kết nối (token dùng
    chung, xem service), tự ghi audit riêng (đường buffer này nằm trong
    `_SKIP_PREFIXES` của `backend/core/audit_middleware.py`, xem file đó)."""
    resolved = svc.resolve_extension_token(db, x_extension_token)
    client_ip = request.client.host if request.client else None
    ip_hdr = header_ip_dang_tin(client_ip, request.headers.get("X-Client-IP"))
    if not resolved:
        audit_queue.enqueue(
            request.method, request.url.path, 403, "", ip_hdr, client_ip,
            actor_id=None,
            detail="THẤT BẠI: mã kết nối Extension không hợp lệ hoặc đã bị thu hồi",
        )
        raise HTTPException(
            status_code=403,
            detail="Mã kết nối Extension không hợp lệ hoặc đã bị thu hồi — "
            "vào /doi_chieu_citad_nostro, mục 'Kết nối Extension' để tạo mã mới.",
        )
    _staff_id, owner = resolved
    return owner


# ── CITAD buffer ─────────────────────────────────────────────────────────
@router.post("/citad-buffer")
def save_citad_buffer(data: CitadBufferIn, owner: str = Depends(_resolve_extension_owner)):
    svc.buffer_save_citad(owner, data.model_dump())
    return {"ok": True}


@router.get("/citad-buffer")
def get_citad_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    return svc.buffer_get_citad(current["username"])


@router.delete("/citad-buffer")
def clear_citad_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    svc.buffer_clear_citad(current["username"])
    return {"ok": True}


# ── PaymentHub buffer ────────────────────────────────────────────────────
@router.post("/paymenthub-buffer")
def save_ph_buffer(data: PaymentHubBufferIn, owner: str = Depends(_resolve_extension_owner)):
    svc.buffer_save_ph(owner, data.items)
    return {"ok": True}


@router.get("/paymenthub-buffer")
def get_ph_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    return svc.buffer_get_ph(current["username"])


@router.delete("/paymenthub-buffer")
def clear_ph_buffer(current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    svc.buffer_clear_ph(current["username"])
    return {"ok": True}


# ── Mã kết nối Extension — endpoint RIÊNG, gate bằng menu.doi_chieu_citad_nostro
# (khác endpoint /api/doi-chieu-citad/extension-token* của Phòng Thanh toán,
# gate bằng menu.doi_chieu_citad — user Nostro không có quyền đó nên KHÔNG
# gọi được endpoint của họ). Cùng gọi thẳng các hàm service dùng CHUNG
# (bảng token trung lập, xem doi_chieu_citad_nostro_service.py) nên 1 mã kết
# nối vẫn dùng được cho cả 2 module — chỉ khác đường gọi để đúng quyền.
@router.get("/extension-token/status", response_model=ExtensionTokenStatus)
def extension_token_status(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    return svc.get_extension_token_status(db, current["id"])


@router.post("/extension-token", response_model=ExtensionTokenOut)
def create_extension_token(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    token = svc.generate_extension_token(db, current["id"])
    return {"token": token}


@router.delete("/extension-token")
def delete_extension_token(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    svc.revoke_extension_token(db, current["id"])
    return {"ok": True}


@router.get("/extension-download")
def download_extension(current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    try:
        content = svc.build_extension_zip()
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))
    return Response(
        content=content,
        media_type="application/zip",
        # Tên KHÁC gói của Phòng Thanh toán ("extension_citad.zip") — 2 gói
        # Extension riêng, tải về cùng thư mục mà trùng tên là cài nhầm.
        headers={"Content-Disposition": 'attachment; filename="extension_citad_nv.zip"'},
    )


@router.get("/extension-version")
def extension_version(current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    return {"version": svc.get_extension_latest_version()}


# ── Session theo kỳ đối chiếu — 1 bản CHUNG cho cả phòng ──────────────────
# QUAN TRỌNG: {ky:path} là path converter "tham lam" (khớp cả dấu "/" trong
# ky="dd/mm/yyyy-dd/mm/yyyy") — mọi route có tiền tố "/session/{ky:path}"
# phải đăng ký route cụ thể hơn ("/history") TRƯỚC route trần này, giống hệt
# lưu ý trong backend/api/doi_chieu_citad.py.
@router.get("/sessions")
def list_sessions(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    return svc.session_list(db)


@router.get("/reconciliation-days")
def get_reconciliation_days(
    tu_ngay: str | None = None,
    den_ngay: str | None = None,
    nguoi_cham: str | None = None,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro")),
):
    return svc.get_reconciliation_days(db, tu_ngay, den_ngay, nguoi_cham)


@router.get("/period-check")
def period_check(
    tu_ngay: str,
    den_ngay: str,
    exclude_ky: str | None = None,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro")),
):
    """Cảnh báo (không chặn) trước khi Lưu: kỳ sắp lưu có chồng lên kỳ đã
    lưu trước đó không, và có hở khoảng trống với kỳ liền trước không —
    xem `svc.check_period_overlap`. `exclude_ky`: bỏ qua chính kỳ đang sửa
    (frontend truyền khi Lưu đè lại đúng kỳ đang xem)."""
    return svc.check_period_overlap(db, tu_ngay, den_ngay, exclude_ky)


@router.get("/session/{ky:path}/history")
def get_reconciliation_history(
    ky: str, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    return svc.get_reconciliation_history(db, ky)


@router.get("/session/{ky:path}")
def get_session(
    ky: str, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    return svc.session_get(db, ky) or {}


@router.post("/session")
def save_session(
    data: SessionIn, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    # Chặn `ky` rỗng/sai định dạng ngay tại đây — lưu được rồi thì bản ghi
    # vừa vô hình ở tab Lịch sử vừa không xoá được qua UI (xem normalize_ky).
    # Ghi lại `ky` đã chuẩn hoá vào cả JSON để bản lưu và khoá bảng khớp nhau.
    try:
        ky = svc.normalize_ky(data.ky)
    except ValueError as e:
        raise HTTPException(400, str(e))
    payload = data.model_dump()
    payload["ky"] = ky
    svc.session_save(db, ky, current["id"], payload)
    return {"ok": True}


@router.delete("/session/{ky:path}")
def delete_session(
    ky: str, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    svc.session_delete(db, ky)
    return {"ok": True}


@router.get("/history-entry/{history_id}")
def get_history_entry(
    history_id: int, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    data = svc.get_history_entry_data(db, history_id)
    if data is None:
        raise HTTPException(404, "Không tìm thấy bản ghi lịch sử này")
    return data


# ── Xuất Excel ────────────────────────────────────────────────────────────
@router.post("/export")
async def export_excel(data: ExportIn, current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    buf = await run_heavy(svc.build_xlsx_nostro, data)
    fname = _safe_filename(f"Doi_chieu_CITAD_PaymentHub_Nostro_{data.sheet_name}.xlsx")
    return StreamingResponse(
        io.BytesIO(buf),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
