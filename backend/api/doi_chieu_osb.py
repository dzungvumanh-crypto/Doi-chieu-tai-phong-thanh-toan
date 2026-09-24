"""API endpoints cho tính năng Đối chiếu OSB — GL02 (IPCAS) <-> OSB chi tiết hạch toán."""

import threading
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core import phien_doi_chieu
from backend.core.deps import require_feature
from backend.core.uploads import MAX_REQUEST_BYTES, safe_filename, save_upload_to
from backend.services import doi_chieu_osb_job as job
from backend.services.doi_chieu_osb.config import TAI_KHOAN

router = APIRouter(prefix="/api/doi_chieu_osb", tags=["doi_chieu_osb"])


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
    files: list[UploadFile],
    ma_tk: str = Form(...),
    ngay: str = Form(...),
    _=Depends(require_feature("doi_chieu_osb.process")),
):
    """Nhận đúng 1 file `.zip` (GL02) + N file `.xlsx` (OSB, thường 2 file/ngày) + `ma_tk` +
    `ngay` (YYYYMMDD). Trả `task_token` ngay, xử lý ở luồng riêng — xem `/progress/{task_token}`.
    """
    if not files:
        raise HTTPException(400, "Cần chọn ít nhất 1 file (1 file .zip GL02 + 1 hoặc nhiều file "
                                  ".xlsx OSB).")

    ma_tk = ma_tk.strip()
    if ma_tk not in TAI_KHOAN:
        raise HTTPException(
            400,
            f"Tài khoản trung gian OSB '{ma_tk}' không được hỗ trợ — chỉ nhận: "
            f"{', '.join(sorted(TAI_KHOAN))}.",
        )
    ngay = ngay.strip()
    if not (len(ngay) == 8 and ngay.isdigit()):
        raise HTTPException(400, f"Ngày không hợp lệ (cần dạng YYYYMMDD): {ngay}")

    # Chốt chặn dùng chung — xem backend/core/phien_doi_chieu.py. Đặt TRƯỚC khi nhận file để
    # client còn đọc được 409 (Starlette đã nhận xong thân request tới đây).
    with phien_doi_chieu.gianh_cho("doi_chieu_osb") as nghen:
        if nghen:
            raise HTTPException(409, nghen)
        task_token = job.init_progress()
    thu_muc = job.tao_thu_muc_upload(task_token)

    gl02_path = None
    osb_paths: list = []
    da_co: set[str] = set()
    tong = 0
    try:
        for f in files:
            ten = safe_filename(f.filename, "file.dat")
            # Chọn trùng một file hai lần thì lặng lẽ ghi đè nhau trên đĩa — chặn thẳng, đừng
            # để 1 trong 2 file biến mất mà không ai biết (mirror cham459901.py).
            if ten in da_co:
                raise HTTPException(400, f"File '{ten}' bị chọn hai lần — mỗi file chỉ chọn "
                                          f"một lần.")
            da_co.add(ten)

            try:
                tong += await save_upload_to(f, thu_muc / ten, MAX_REQUEST_BYTES - tong)
            except HTTPException:
                raise HTTPException(
                    413,
                    f"Tổng dung lượng các file vượt quá "
                    f"{MAX_REQUEST_BYTES // (1024 * 1024)} MB.",
                )

            duoi = ten.lower()
            if duoi.endswith(".zip"):
                if gl02_path is not None:
                    raise HTTPException(400, "Chỉ nhận đúng 1 file .zip (GL02) mỗi lượt.")
                gl02_path = thu_muc / ten
            elif duoi.endswith(".xlsx"):
                osb_paths.append(thu_muc / ten)
            else:
                raise HTTPException(
                    400,
                    f"File '{f.filename}' không hợp lệ — chỉ nhận .zip (GL02) và .xlsx (OSB).",
                )
    except BaseException:
        # Upload hỏng/client cắt kết nối/file sai định dạng: xoá thư mục và entry tiến độ
        # ngay, đừng để lại một lượt "đang khởi tạo" không bao giờ chạy tới.
        job.bo_luot(task_token)
        raise

    if gl02_path is None:
        job.bo_luot(task_token)
        raise HTTPException(400, "Thiếu file GL02 (.zip).")
    if not osb_paths:
        job.bo_luot(task_token)
        raise HTTPException(400, "Thiếu file OSB (.xlsx) — cần ít nhất 1 file.")

    # Chạy trong luồng riêng, KHÔNG dùng BackgroundTasks — xem docstring
    # backend/services/doi_chieu_osb_job.py + backend/api/cham459901.py::process (mẫu gốc).
    threading.Thread(
        target=job.run_process,
        args=(gl02_path, osb_paths, ma_tk, ngay, task_token),
        daemon=True,
    ).start()
    return {"task_token": task_token}


@router.get("/progress/{task_token}")
def get_progress(
    task_token: str,
    _=Depends(require_feature("menu.doi_chieu_osb")),
):
    """Poll tiến độ xử lý. Khi done=True: result chứa kết quả, error chứa lỗi."""
    prog = job.get_progress(task_token)
    if prog is None:
        raise HTTPException(404, "Token không tồn tại hoặc đã hết hạn")
    return prog


@router.get("/download/{token}")
def download_result(
    token: str,
    _=Depends(require_feature("menu.doi_chieu_osb")),
):
    """Tải file ZIP kết quả (4 file Excel: Chenh_lech_No/Co_GL02/OSB)."""
    path = job.TEMP_DIR / safe_filename(token, "_") / "ket_qua.zip"
    if not path.exists():
        raise HTTPException(404, "File không tồn tại hoặc đã hết hạn")

    return Response(
        content=path.read_bytes(),
        media_type="application/zip",
        headers=_dl_headers(f"doi_chieu_osb_{token[:8]}.zip"),
    )
