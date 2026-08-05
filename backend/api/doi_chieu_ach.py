"""API endpoints Đối chiếu ACH — GL02 (IPCAS) vs MIS PaymentHub.

Luồng: POST /session (lấy token) → POST /upload/{token} từng file → POST
/start/{token} → GET /progress/{token} (poll) → /download/... .

Vì sao tải từng file thay vì gửi 1 lần cả bộ: bộ dữ liệu 1 ngày gồm ~6 file
(2 ZIP MIS ĐI, 2 ZIP MIS ĐẾN, GL02, GW) thường 150–250 MB. Gửi 1 request nghĩa
là tiến trình NiceGUI phải giữ trọn số byte đó trong RAM rồi backend giữ thêm
một bản nữa. Tải từng file, ghi thẳng ra đĩa theo khối 1 MB, đỉnh RAM chỉ bằng
đúng 1 file.
"""

import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.services.doi_chieu_ach import service as svc

router = APIRouter(prefix="/api/doi_chieu_ach", tags=["doi_chieu_ach"])


class StartRequest(BaseModel):
    # Bỏ trống = suy ngày đối chiếu từ tên file PDF
    ngay_doi_chieu: str = ""

# ZIP (GL02, MIS), XLSX (GW), PDF (sao kê ACH → lấy session + ngày đối chiếu)
_DUOI_HOP_LE = {".zip", ".xlsx", ".pdf"}
_CHUNK = 1024 * 1024


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


def _input_dir(token: str):
    """Thư mục input của token; 404 nếu token lạ hoặc đã hết hạn."""
    try:
        return svc.duong_dan_input(token)
    except KeyError:
        raise HTTPException(404, "Phiên xử lý không tồn tại hoặc đã hết hạn")


# ── Chuẩn bị & tải file ──────────────────────────────────────────────────────

@router.post("/session")
def create_session(_=Depends(require_feature("doi_chieu_ach.process"))):
    """Mở một phiên xử lý mới, trả token để tải file lên."""
    return {"token": svc.tao_job()}


@router.post("/upload/{token}")
async def upload_file(
    token: str,
    file: UploadFile = File(...),
    _=Depends(require_feature("doi_chieu_ach.process")),
):
    """Ghi 1 file vào thư mục tạm của phiên."""
    input_dir = _input_dir(token)
    if svc.da_bat_dau(token):
        raise HTTPException(409, "Phiên này đã bắt đầu xử lý, không nhận thêm file")

    # Trình duyệt gửi kèm đường dẫn tương đối khi chọn cả thư mục — chỉ lấy tên
    name = os.path.basename((file.filename or "").replace("\\", "/"))
    if not name or name.startswith("~$"):
        raise HTTPException(400, "Tên file không hợp lệ")
    if os.path.splitext(name)[1].lower() not in _DUOI_HOP_LE:
        raise HTTPException(400, f"'{name}': chỉ nhận file .zip, .xlsx, .pdf")

    size = 0
    with open(input_dir / name, "wb") as out:
        while chunk := await file.read(_CHUNK):
            out.write(chunk)
            size += len(chunk)

    return {"name": name, "size": size}


@router.delete("/upload/{token}/{filename}")
def delete_file(
    token: str,
    filename: str,
    _=Depends(require_feature("doi_chieu_ach.process")),
):
    """Bỏ 1 file đã tải lên (chọn nhầm)."""
    _input_dir(token)
    if svc.da_bat_dau(token):
        raise HTTPException(409, "Phiên này đã bắt đầu xử lý")
    try:
        da_xoa = svc.xoa_file_input(token, filename)
    except OSError:
        # Máy chủ không xoá được thì phải nói thật — báo "đã xoá" trong khi file
        # vẫn nằm đó sẽ khiến người dùng chạy đối chiếu với file mình tưởng đã bỏ
        raise HTTPException(
            409,
            f"Máy chủ chưa xoá được '{os.path.basename(filename)}' (file đang bị "
            f"chương trình khác giữ). Chờ vài giây rồi thử lại.",
        )
    if not da_xoa:
        raise HTTPException(404, "File không tồn tại")
    return {"ok": True}


@router.get("/files/{token}")
def list_files(
    token: str,
    _=Depends(require_feature("doi_chieu_ach.process")),
):
    """Danh sách file backend thực sự đang giữ — dùng để đối chiếu với giao diện."""
    _input_dir(token)
    return {"files": svc.liet_ke_input(token)}


# ── Chạy & theo dõi ──────────────────────────────────────────────────────────

@router.post("/start/{token}")
def start(
    token: str,
    body: StartRequest,
    _=Depends(require_feature("doi_chieu_ach.process")),
):
    """Đưa phiên vào hàng đợi xử lý. Trả ngay, tiến độ xem qua /progress."""
    _input_dir(token)
    if svc.da_bat_dau(token):
        raise HTTPException(409, "Phiên này đã được chạy rồi")
    if not svc.liet_ke_input(token):
        raise HTTPException(400, "Chưa có file nào được tải lên")

    svc.chay_nen(token, body.ngay_doi_chieu.strip() or None)
    return {"ok": True}


@router.get("/progress/{token}")
def get_progress(
    token: str,
    _=Depends(require_feature("menu.doi_chieu_ach")),
):
    """Poll tiến độ. done=True kèm result (kết quả) hoặc error (lỗi)."""
    prog = svc.get_progress(token)
    if prog is None:
        raise HTTPException(404, "Phiên xử lý không tồn tại hoặc đã hết hạn")
    return prog


@router.post("/cancel/{token}")
def cancel(
    token: str,
    _=Depends(require_feature("doi_chieu_ach.process")),
):
    """Yêu cầu dừng. Engine dừng ở mốc kiểm tra gần nhất, không dừng tức thì."""
    if not svc.huy_job(token):
        raise HTTPException(404, "Không tìm thấy phiên xử lý đang chạy")
    return {"ok": True}


# ── Tải kết quả ──────────────────────────────────────────────────────────────

@router.get("/download/{token}/{filename}")
def download_file(
    token: str,
    filename: str,
    _=Depends(require_feature("menu.doi_chieu_ach")),
):
    try:
        content = svc.doc_file_ket_qua(token, filename)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    name = os.path.basename(filename)
    media = ("text/csv; charset=utf-8" if name.lower().endswith(".csv")
             else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return Response(content=content, media_type=media, headers=_dl_headers(name))


@router.get("/download-all/{token}")
def download_all(
    token: str,
    _=Depends(require_feature("menu.doi_chieu_ach")),
):
    try:
        content = svc.dong_goi_zip(token)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    return Response(
        content=content,
        media_type="application/zip",
        headers=_dl_headers("ket_qua_doi_chieu_ach.zip"),
    )
