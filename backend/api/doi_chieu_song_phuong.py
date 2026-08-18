"""API endpoints Đối chiếu Song phương — định tuyến lệnh IPCAS theo NH + chiều."""

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import threading

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.uploads import read_limited, safe_filename
from backend.core.deps import require_feature
from backend.services import doi_chieu_song_phuong_service as svc

router = APIRouter(prefix="/api/doi_chieu_song_phuong", tags=["doi_chieu_song_phuong"])

VALID_KEYS = {f"{ma}_{d}" for ma in svc.BANK_NAME for d in svc.DIRECTIONS}


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


@router.post("/process")
async def process(
    file: UploadFile,
    _=Depends(require_feature("doi_chieu_song_phuong.process")),
):
    """Nhận ZIP, khởi chạy định tuyến trong background, trả task_token ngay."""
    zip_bytes  = await read_limited(file, ten="File ZIP dữ liệu")
    task_token = svc.init_progress()
    # Chạy trong luồng riêng, KHÔNG dùng BackgroundTasks: Starlette chạy hàm
    # đồng bộ của BackgroundTasks trong threadpool CHUNG 40 token của anyio và
    # giữ token đó suốt thời gian xử lý (phút, không phải giây). Vài lượt chạy
    # cùng lúc là bể cạn, mọi endpoint `def` khác của hệ thống phải xếp hàng
    # theo. Luồng riêng thì việc nặng chạy ngoài bể, đúng cách ACH đang làm
    # (backend/services/ach_service.py). Tiến độ vẫn theo dõi qua /progress.
    threading.Thread(target=svc.run_process, args=(zip_bytes, task_token),
                     daemon=True).start()
    return {"task_token": task_token}


@router.get("/progress/{task_token}")
def get_progress(
    task_token: str,
    _=Depends(require_feature("menu.doi_chieu_song_phuong")),
):
    """Poll tiến độ. Khi done=True: result chứa kết quả hoặc error chứa lỗi."""
    prog = svc.get_progress(task_token)
    if prog is None:
        raise HTTPException(404, "Token không tồn tại hoặc đã hết hạn")
    return prog


@router.get("/download/{token}/{file_key}")
def download_result(
    token: str,
    file_key: str,
    _=Depends(require_feature("menu.doi_chieu_song_phuong")),
):
    """Tải 1 trong 8 file CSV kết quả (vd 201_DEN, 311_DI)."""
    if file_key not in VALID_KEYS:
        raise HTTPException(400, "file_key không hợp lệ")

    # `token` là chuỗi client đặt và được ghép vào đường dẫn — xem chú thích
    # cùng kiểu ở backend/api/cham459901.py.
    path = svc.TEMP_DIR / safe_filename(token, "_") / f"{file_key}.csv"
    if not path.exists():
        raise HTTPException(404, "File không tồn tại hoặc đã hết hạn")

    date_str = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")
    filename = f"{file_key}_{date_str}.csv"

    return Response(
        content=path.read_bytes(),
        media_type="text/csv; charset=utf-8",
        headers=_dl_headers(filename),
    )
