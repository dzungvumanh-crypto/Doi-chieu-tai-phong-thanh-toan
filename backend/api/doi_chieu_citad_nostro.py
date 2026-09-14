"""API Đối chiếu CITAD ↔ PaymentHub — Phòng QLTK Nostro, Vostro.

Router SONG SONG, độc lập với `backend/api/doi_chieu_citad.py` (Phòng
Thanh toán) — không sửa router đó, không dùng chung bảng/buffer/session.

Extension Chrome là gói RIÊNG (`extension_citad_nv/`) — KHÔNG dùng chung
`extension_citad/` của Phòng Thanh toán (theo đúng yêu cầu nghiệp vụ: 2
phòng không trùng Extension). Mã kết nối CŨNG tách RIÊNG (bảng
`doi_chieu_citad_nostro_extension_tokens`, xem `doi_chieu_citad_nostro_service.py`)
— trước dùng chung bảng token với Phòng Thanh toán, tạo mã ở module này
vô tình thu hồi mã module kia của cùng 1 người, gây 403 khi dùng song song
2 Extension. Giờ 2 phòng tạo/thu hồi độc lập hoàn toàn.

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

import calendar
import io
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from backend.database import get_db
from backend.core import audit_queue
from backend.core.enums import StaffRole
from backend.core.net import header_ip_dang_tin
from backend.core.concurrency import run_heavy
from backend.core.deps import require_feature
from backend.schemas.doi_chieu_citad_nostro import (
    CitadBufferIn,
    ExportIn,
    LOAI_TIEN,
    MonthSummaryExportIn,
    MonthSummaryIn,
    PaymentHubBufferIn,
    SessionIn,
)
# Trung lập, không định nghĩa lại — dùng thẳng schema gốc cho 4 endpoint
# mã kết nối Extension (mô tả bên dưới).
from backend.schemas.doi_chieu_citad import ExtensionTokenOut, ExtensionTokenStatus
from backend.services import doi_chieu_citad_nostro_service as svc


def _safe_filename(name: str) -> str:
    return re.sub(r'[\r\n"\\]', '_', name)


def _can_delete_any_session(current: dict, db) -> bool:
    """"Xoá được bảng của NGƯỜI KHÁC" — mirror đúng logic
    `require_feature()._check()` (deps.py) nhưng trả `bool` thay vì raise:
    admin qua ngay (siêu quyền cố ý, xem docs/DESIGN.md mục Phân quyền —
    KHÔNG tính là hard-code), người khác phải được cấp mã
    `doi_chieu_citad_nostro.delete_any` qua Phân quyền theo nhóm. Review
    PR #90: bản đầu gate thẳng `current["role"] == "admin"`, trái quy tắc
    "không hard-code quyền" — đã sửa."""
    if current["role"] == StaffRole.ADMIN:
        return True
    row = db.execute(
        """SELECT 1 FROM group_features gf
           JOIN group_members gm ON gm.group_id = gf.group_id
           JOIN user_groups g ON g.id = gm.group_id AND g.is_active = 1
           WHERE gm.staff_id = ? AND gf.feature_code = ?
           LIMIT 1""",
        (current["id"], "doi_chieu_citad_nostro.delete_any"),
    ).fetchone()
    return bool(row)


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


# ── Session theo kỳ đối chiếu — NHIỀU bảng độc lập/kỳ, mỗi bảng 1 chủ ─────
# Từ 11/09/2026: đổi routing theo `ky:path` (path converter "tham lam") sang
# `{session_id:int}` (mirror doi_chieu_citad.py — /session-by-id/{session_id})
# — converter `int` không có vấn đề "tham lam" nên không còn cần lưu ý thứ tự
# đăng ký route như bản `{ky:path}` cũ.
@router.get("/sessions")
def list_sessions(db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))):
    return svc.session_list(db)


@router.get("/reconciliation-days")
def get_reconciliation_days(
    tu_ngay: str | None = None,
    den_ngay: str | None = None,
    nguoi_cham: str | None = None,
    ccy: str | None = None,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro")),
):
    return svc.get_reconciliation_days(db, tu_ngay, den_ngay, nguoi_cham, ccy)


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


@router.get("/session-by-id/{session_id}/history")
def get_reconciliation_history(
    session_id: int, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    return svc.get_reconciliation_history(db, session_id)


@router.get("/session-by-id/{session_id}")
def get_session(
    session_id: int, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    return svc.session_get(db, session_id) or {}


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
    session_id = payload.pop("session_id")
    try:
        new_session_id = svc.session_save(db, ky, current["id"], payload, session_id)
    except svc.SessionForbiddenError as e:
        raise HTTPException(403, str(e))
    except svc.SessionNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        # `ky` trên form khác `ky` của bảng đang lưu tiếp (session_id cũ,
        # người dùng đổi ô ngày mà chưa tách bảng) — review PR #90: trước
        # đây lọt qua thành 500 vì chỉ bắt 2 exception trên.
        raise HTTPException(400, str(e))
    return {"ok": True, "session_id": new_session_id}


@router.delete("/session-by-id/{session_id}")
def delete_session(
    session_id: int, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    is_admin_any = _can_delete_any_session(current, db)
    try:
        svc.session_delete(db, session_id, current["id"], is_admin_any)
    except svc.SessionNotFoundError as e:
        raise HTTPException(404, str(e))
    except svc.SessionForbiddenError as e:
        raise HTTPException(403, str(e))
    return {"ok": True}


@router.get("/history-entry/{history_id}")
def get_history_entry(
    history_id: int, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    data = svc.get_history_entry_data(db, history_id)
    if data is None:
        raise HTTPException(404, "Không tìm thấy bản ghi lịch sử này")
    return data


# ── Tổng hợp tháng — cộng dồn nhiều bảng/kỳ do người dùng tick chọn ────────
@router.get("/month-sessions")
def get_month_sessions(
    nam: int, thang: int, ccy: str | None = None,
    db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro")),
):
    """Trả 1 lần cả 2 thứ màn "Tổng hợp tháng" cần lúc mở: danh sách bảng
    của tháng (để tick chọn) và danh sách ngày còn thiếu (để nhắc chấm bù) —
    gộp chung tránh 2 round-trip. `ccy`: lọc danh sách bảng theo loại tiền
    (giúp tìm bảng) — KHÔNG lọc `missing_days`, vẫn hỏi "ngày nào chưa ai
    chấm" chung cho cả 3 loại tiền, đúng ý nghĩa gốc của trường đó."""
    return {
        "sessions": svc.get_sessions_for_month(db, nam, thang, ccy),
        "missing_days": svc.get_month_missing_days(db, nam, thang),
    }


@router.post("/month-summary")
def month_summary(
    data: MonthSummaryIn, db=Depends(get_db), current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro"))
):
    """Xem trước tổng (không xuất Excel) — gọi lại mỗi khi người dùng
    tick/bỏ tick bảng nào đó trên màn "Tổng hợp tháng". Trả riêng theo từng
    loại tiền: {"VND": {"ci":..., "hub":...}, "USD": {...}, "EUR": {...}}."""
    cD, phD = svc.combine_sessions_cD_phD(db, data.session_ids)
    out = {}
    for ccy in LOAI_TIEN:
        ci, hub = svc.compute_totals({"cD": cD.get(ccy, {}), "phD": phD.get(ccy, {})})
        out[ccy] = {
            "ci": {loai: {fld: float(ci[loai][fld]) for fld in ("soMon", "soTien")} for loai in ci},
            "hub": {loai: {fld: float(hub[loai][fld]) for fld in ("soMon", "soTien")} for loai in hub},
        }
    return out


@router.post("/month-summary/export")
async def export_month_summary(
    data: MonthSummaryExportIn, db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_chieu_citad_nostro")),
):
    if not data.session_ids:
        raise HTTPException(400, "Chưa chọn bảng nào để tính vào tổng tháng.")
    try:
        first = datetime(data.nam, data.thang, 1)
        last_day = calendar.monthrange(data.nam, data.thang)[1]
        last = datetime(data.nam, data.thang, last_day)
    except ValueError as e:
        raise HTTPException(400, f"Tháng/năm không hợp lệ: {e}")
    cD, phD = svc.combine_sessions_cD_phD(db, data.session_ids)
    export_data = ExportIn(
        tu_ngay=first.strftime("%d/%m/%Y"),
        den_ngay=last.strftime("%d/%m/%Y"),
        sheet_name=f"Thang_{data.thang:02d}.{data.nam}",
        lb=data.lb,
        ks=data.ks,
        cD=cD,
        phD=phD,
    )
    buf = await run_heavy(svc.build_xlsx_nostro, export_data)
    fname = _safe_filename(f"Tong_hop_thang_{data.thang:02d}.{data.nam}.xlsx")
    return StreamingResponse(
        io.BytesIO(buf),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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
