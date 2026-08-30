"""API endpoints Đối chiếu Song phương — định tuyến lệnh IPCAS theo NH + chiều.

Hỗ trợ 2 chế độ nhập liệu (giống module Chấm ACH, quyết định 2026-08-28 sau phản hồi upload
1-file-mỗi-lần "rất khó dùng" khi cần xử lý nhiều ngày): tải nhiều file ZIP cùng lúc qua trình
duyệt (`/start_batch`), hoặc chỉ đường dẫn 1 thư mục server chứa nhiều ZIP (`/start_folder`) —
cả 2 đều chạy qua cùng 1 job nền tuần tự (`svc.start_batch`/`start_batch_folder`), poll tiến độ
qua `/poll/{job_id}`, tải kết quả từng ngày qua `/download/{token}/{file_key}` như cũ (mỗi ZIP
vẫn ra 1 `token` riêng, không đổi)."""

import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.services import doi_chieu_song_phuong_service as svc

router = APIRouter(prefix="/api/doi_chieu_song_phuong", tags=["doi_chieu_song_phuong"])

VALID_KEYS = {f"{ma}_{d}" for ma in svc.BANK_NAME for d in svc.DIRECTIONS}
_MAX_UPLOAD = 800 * 1024 * 1024  # 800 MB tổng — mỗi GL02 zip thật ~150-160MB, vài ngày/lần


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


@router.post("/start_batch")
async def start_batch(
    files: list[UploadFile],
    _=Depends(require_feature("doi_chieu_song_phuong.process")),
):
    """Nhận nhiều file ZIP qua trình duyệt, chạy tuần tự trong job nền. Trả job_id."""
    if not files:
        raise HTTPException(400, "Cần chọn ít nhất 1 file ZIP.")

    items: list[tuple[str, bytes]] = []
    total_size = 0
    for f in files:
        data = await f.read()
        total_size += len(data)
        if total_size > _MAX_UPLOAD:
            raise HTTPException(413, "Tổng kích thước file vượt quá 800 MB — dùng chế độ thư mục server thay thế.")
        items.append((f.filename or f"file_{len(items)}.zip", data))

    job_id = svc.start_batch(items)
    return {"job_id": job_id}


class FolderRequest(BaseModel):
    folder_path: str


@router.post("/start_folder")
def start_folder(
    req: FolderRequest,
    _=Depends(require_feature("doi_chieu_song_phuong.process")),
):
    """Chạy tuần tự mọi file *.zip trong 1 thư mục server. Trả job_id."""
    p = Path(req.folder_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f"Thư mục không tồn tại: {req.folder_path}")
    try:
        job_id = svc.start_batch_folder(str(p))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job_id}


@router.get("/poll/{job_id}")
def poll_job(
    job_id: str,
    since: int = 0,
    _=Depends(require_feature("menu.doi_chieu_song_phuong")),
):
    """Poll tiến độ job hàng loạt. `since` = số dòng log đã nhận rồi."""
    job = svc.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job không tồn tại hoặc đã hết hạn.")
    return {
        "status": job["status"],
        "logs": job["logs"][since:],
        "results": job["results"],
        "error": job["error"],
    }


@router.post("/cancel/{job_id}")
def cancel_job(
    job_id: str,
    _=Depends(require_feature("doi_chieu_song_phuong.process")),
):
    ok = svc.cancel_job(job_id)
    if not ok:
        raise HTTPException(404, "Job không tồn tại hoặc đã kết thúc.")
    return {"ok": True}


@router.get("/download/{token}/{file_key}")
def download_result(
    token: str,
    file_key: str,
    _=Depends(require_feature("menu.doi_chieu_song_phuong")),
):
    """Tải 1 trong 8 file CSV kết quả (vd 201_DEN, 311_DI).

    `token` PHẢI là UUID hợp lệ (đúng định dạng `result_token` server luôn tự sinh,
    `process_zip()`) — chặn dò đường dẫn kiểu `token="../../.."` ghép thẳng vào
    `TEMP_DIR / token / ...` (lỗ hổng thật đã vá ở PR#63 cham459901, `delete_result`/
    `download_result` dùng `token` không qua kiểm tra)."""
    if file_key not in VALID_KEYS:
        raise HTTPException(400, "file_key không hợp lệ")
    try:
        uuid.UUID(token)
    except ValueError:
        raise HTTPException(400, "token không hợp lệ")

    path = svc.TEMP_DIR / token / f"{file_key}.csv"
    if not path.exists():
        raise HTTPException(404, "File không tồn tại hoặc đã hết hạn")

    date_str = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")
    filename = f"{file_key}_{date_str}.csv"

    return Response(
        content=path.read_bytes(),
        media_type="text/csv; charset=utf-8",
        headers=_dl_headers(filename),
    )
