"""API endpoints cho tính năng Chấm 459901 — phân loại bút toán TK 459901."""

from datetime import datetime
from urllib.parse import quote

import threading

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.uploads import read_limited, safe_filename
from backend.core.deps import require_feature
from backend.services import cham459901_service

router = APIRouter(prefix="/api/cham459901", tags=["cham459901"])

VALID_TYPES = {"huy", "di", "khac"}


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
    _=Depends(require_feature("cham_459901.process")),
):
    """Nhận file ZIP, khởi chạy phân loại trong background, trả task_token ngay."""
    zip_bytes = await read_limited(file, ten="File ZIP dữ liệu")
    task_token = cham459901_service.init_progress()
    # Chạy trong luồng riêng, KHÔNG dùng BackgroundTasks: Starlette chạy hàm
    # đồng bộ của BackgroundTasks trong threadpool CHUNG 40 token của anyio và
    # giữ token đó suốt thời gian xử lý (phút, không phải giây). Vài lượt chạy
    # cùng lúc là bể cạn, mọi endpoint `def` khác của hệ thống phải xếp hàng
    # theo. Luồng riêng thì việc nặng chạy ngoài bể, đúng cách ACH đang làm
    # (backend/services/ach_service.py). Tiến độ vẫn theo dõi qua /progress.
    threading.Thread(target=cham459901_service.run_process, args=(zip_bytes, task_token),
                     daemon=True).start()
    return {"task_token": task_token}


@router.get("/progress/{task_token}")
def get_progress(
    task_token: str,
    _=Depends(require_feature("menu.cham_459901")),
):
    """Poll tiến độ xử lý. Khi done=True: result chứa kết quả hoặc error chứa lỗi."""
    prog = cham459901_service.get_progress(task_token)
    if prog is None:
        raise HTTPException(404, "Token không tồn tại hoặc đã hết hạn")
    return prog


@router.get("/download/{token}/{file_type}")
def download_result(
    token: str,
    file_type: str,
    _=Depends(require_feature("menu.cham_459901")),
):
    """Tải 1 trong 3 file Excel kết quả (huy / di / khac)."""
    if file_type not in VALID_TYPES:
        raise HTTPException(400, f"file_type phải là: {', '.join(sorted(VALID_TYPES))}")

    # `token` là chuỗi client đặt và được ghép vào đường dẫn — cắt mọi thành
    # phần thư mục trước, đừng dựa vào việc bộ định tuyến không khớp dấu "/".
    # Lấy thư mục từ chính service, KHÔNG gõ lại đường dẫn: viết cứng ở đây thì
    # đổi TEMP_DIR bên service là endpoint này lặng lẽ tìm sai chỗ, người dùng chỉ
    # thấy "File không tồn tại hoặc đã hết hạn".
    path = cham459901_service.TEMP_DIR / safe_filename(token, "_") / f"{file_type}.xlsx"
    if not path.exists():
        raise HTTPException(404, "File không tồn tại hoặc đã hết hạn")

    date_str = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")
    filename = f"459901_{file_type}_{date_str}.xlsx"

    return Response(
        content=path.read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_dl_headers(filename),
    )
