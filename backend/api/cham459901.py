"""API endpoints cho tính năng Chấm 459901 — phân loại bút toán TK 459901."""

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import threading

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.uploads import MAX_REQUEST_BYTES, safe_filename, save_upload_to
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


async def _nhan_file(files: list[UploadFile], thu_muc) -> list[tuple[str, Path]]:
    """Ghi từng file xuống `thu_muc`, trả [(tên người dùng chọn, đường dẫn)].

    Tên gốc được giữ lại để viết thông báo lỗi: `safe_filename()` có thể cắt nó
    khác đi, mà báo lỗi bằng tên đã cắt là bắt người dùng đi tìm một file không
    tồn tại trong thư mục của họ.
    """
    tep: list[tuple[str, Path]] = []
    da_co: set[str] = set()
    tong = 0
    for f in files:
        ten = safe_filename(f.filename, "file.dat")
        # Chọn trùng một file hai lần thì mọi bút toán bị nhân đôi: cặp
        # Cancel/Normal vẫn khớp nên KHÔNG có lỗi nào, chỉ là số dòng gấp đôi
        # và người dùng không hiểu vì sao. Chặn thẳng, đừng lặng lẽ bỏ qua.
        if ten in da_co:
            raise HTTPException(400, f"File '{ten}' bị chọn hai lần — mỗi file chỉ chọn một lần.")
        da_co.add(ten)

        # Chặn đuôi lạ NGAY ĐÂY để người dùng biết liền, thay vì ghi hết file
        # rồi mới báo lỗi qua đường /progress. Danh sách đuôi lấy từ service —
        # gõ lại ở đây là hai chỗ tự do lệch nhau.
        if not ten.lower().endswith(cham459901_service.DUOI_HOP_LE):
            raise HTTPException(
                400,
                f"File '{ten}' không thuộc định dạng nhận được — chỉ nhận "
                f"{', '.join(cham459901_service.DUOI_HOP_LE)}.",
            )

        # Trần cho từng file = phần còn lại của cả lượt, nên dừng đúng lúc tổng
        # vượt trần. Thông điệp phải tự viết: save_upload_to() nêu con số nó
        # nhận được, mà ở đây con số đó là phần CÒN LẠI — người đọc không hiểu.
        try:
            tong += await save_upload_to(f, thu_muc / ten, MAX_REQUEST_BYTES - tong)
        except HTTPException:
            raise HTTPException(
                413,
                f"Tổng dung lượng các file vượt quá "
                f"{MAX_REQUEST_BYTES // (1024 * 1024)} MB. Hãy chia làm nhiều lượt.",
            )
        tep.append((f.filename or ten, thu_muc / ten))
    return tep


@router.post("/process")
async def process(
    files: list[UploadFile],
    _=Depends(require_feature("cham_459901.process")),
):
    """Nhận một hoặc nhiều file ZIP/Excel, chạy phân loại nền, trả task_token ngay.

    Nhiều file được GỘP thành một lượt phân loại (xem `process_files`).
    """
    if not files:
        raise HTTPException(400, "Cần chọn ít nhất 1 file.")

    # Ghi THẲNG từng khối xuống thư mục của lượt, không gom vào RAM trước: một
    # lượt có thể là vài ZIP mấy trăm MB, mà `process_files()` đằng nào cũng chỉ
    # cần đường dẫn. Xem save_upload_to() trong backend/core/uploads.py.
    task_token = cham459901_service.init_progress()
    thu_muc = cham459901_service.tao_thu_muc_upload(task_token)
    try:
        tep = await _nhan_file(files, thu_muc)
    except BaseException:
        # Upload hỏng hoặc client cắt kết nối: xoá thư mục và entry tiến độ ngay,
        # đừng để lại một lượt "đang khởi tạo" không bao giờ chạy tới.
        cham459901_service.bo_luot(task_token)
        raise
    # Chạy trong luồng riêng, KHÔNG dùng BackgroundTasks: Starlette chạy hàm
    # đồng bộ của BackgroundTasks trong threadpool CHUNG 40 token của anyio và
    # giữ token đó suốt thời gian xử lý (phút, không phải giây). Vài lượt chạy
    # cùng lúc là bể cạn, mọi endpoint `def` khác của hệ thống phải xếp hàng
    # theo. Luồng riêng thì việc nặng chạy ngoài bể, đúng cách ACH đang làm
    # (backend/services/ach_service.py). Tiến độ vẫn theo dõi qua /progress.
    threading.Thread(target=cham459901_service.run_process, args=(tep, task_token),
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
