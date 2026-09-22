"""API endpoints cho Chấm TK 459901-1000-000000000 — 3 nhóm: Cân ITT / Điện KO offline / GD khác.

Anh em của `cham459901.py` (TK 459901-1000-000007709): cùng khuôn, khác prefix/mã quyền/thư mục tạm.
"""

import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core import phien_doi_chieu
from backend.core.uploads import MAX_REQUEST_BYTES, safe_filename, save_upload_to
from backend.core.deps import require_feature
from backend.services import cham459901_000000000_service as svc

router = APIRouter(prefix="/api/cham459901_000000000", tags=["cham459901_000000000"])

# file_type → tên dùng khi tải về (kèm mã TK để người dùng phân biệt với module 000007709)
_TEN_TAI = {
    "can_itt": "GD_can_ITT",
    "ko":      "GD_dien_KO_offline",
    "khac":    "GD_khac",
}

_KHONG_TIM_THAY_GL02 = (
    "Không tìm thấy file GL02 (.zip hoặc Excel) trong {noi} — "
    "chỉ nhận {duoi}."
).format


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


async def _nhan_file(
    files: list[UploadFile], thu_muc: Path,
) -> tuple[list[tuple[str, Path]], list[str], dict[str, list[str]], tuple[str, Path] | None]:
    """Ghi từng file xuống `thu_muc`, phân vào 1 trong 2 nhóm:
      - file GL02 chính (zip hoặc Excel, đuôi hợp lệ) — GỘP nhiều file được, tên gì cũng được;
      - file tồn tháng trước, nhận diện qua `classify_upload_filename()` — chỉ giữ 1 file.
    File không khớp cả hai (đuôi lạ) rơi vào `unrecognized`, KHÔNG đọc byte của nó.

    Tên gốc người dùng chọn được giữ riêng khỏi tên đã `safe_filename()` để viết thông báo lỗi.
    """
    tep: list[tuple[str, Path]] = []
    ton: tuple[str, Path] | None = None
    duplicates: dict[str, list[str]] = {}
    unrecognized: list[str] = []
    da_co: set[str] = set()
    tong = 0

    for f in files:
        ten_hien_thi = f.filename or "(không tên)"
        ten = safe_filename(f.filename, "file.dat")
        # Chọn trùng một file hai lần thì mọi bút toán bị nhân đôi mà KHÔNG có lỗi nào
        # (Nợ/Có vẫn cân) — chặn thẳng, đừng lặng lẽ bỏ qua. So theo chữ THƯỜNG: `A.xlsx` và `a.xlsx` là một
        # file trên đĩa Windows (NTFS không phân biệt hoa/thường) nên file sau sẽ đè file trước.
        if ten.lower() in da_co:
            raise HTTPException(400, f"File '{ten}' bị chọn hai lần — mỗi file chỉ chọn một lần.")
        da_co.add(ten.lower())

        # File khoá `~$...` của Office: bỏ qua, không đọc byte, không chặn cả lượt
        if svc.la_tep_khoa_office(ten_hien_thi):
            unrecognized.append(ten_hien_thi)
            continue

        kind = svc.classify_upload_filename(ten_hien_thi)
        duoi_ok = ten.lower().endswith(svc.DUOI_HOP_LE)
        if kind is None and not duoi_ok:
            unrecognized.append(ten_hien_thi)
            continue

        # Trần cho từng file = phần còn lại của cả lượt. Thông điệp phải tự viết:
        # save_upload_to() nêu con số nó nhận được, mà ở đây đó là phần CÒN LẠI.
        try:
            tong += await save_upload_to(f, thu_muc / ten, MAX_REQUEST_BYTES - tong)
        except HTTPException:
            raise HTTPException(
                413,
                f"Tổng dung lượng các file vượt quá "
                f"{MAX_REQUEST_BYTES // (1024 * 1024)} MB. Hãy chia làm nhiều lượt.",
            )

        if kind is None:
            tep.append((ten_hien_thi, thu_muc / ten))
        else:
            # Chỉ 1 file tồn: có sẵn từ trước thì gom cả 2 tên để cảnh báo UI (không chặn),
            # file tới sau được giữ.
            if ton is not None:
                duplicates.setdefault(kind, [ton[0]]).append(ten_hien_thi)
            ton = (ten_hien_thi, thu_muc / ten)

    return tep, unrecognized, duplicates, ton


@router.post("/process")
async def process(
    files: list[UploadFile],
    _=Depends(require_feature("cham_459901_000000000.process")),
):
    """Nhận nhiều file cùng lúc (kéo-thả tự do): file GL02 chính (zip/Excel, tên gì cũng được,
    nhiều file được GỘP) + tùy chọn file tồn tháng trước (`459_TON...` / `459-mã 0...`, tự
    nhận diện theo tên). Trả task_token ngay, xử lý ở luồng riêng.
    """
    if not files:
        raise HTTPException(400, "Cần chọn ít nhất 1 file.")

    # Chốt chặn dùng chung — xem backend/core/phien_doi_chieu.py. Đặt TRƯỚC khi nhận file
    # để client còn đọc được 409.
    with phien_doi_chieu.gianh_cho("cham459901_000000000") as nghen:
        if nghen:
            raise HTTPException(409, nghen)
        task_token = svc.init_progress()
    try:
        # Nằm TRONG try: `mkdir` lỗi (đĩa đầy/quyền) mà đứng ngoài thì mục tiến độ mồ côi giữ cửa chốt 409 tới 4 giờ
        thu_muc = svc.tao_thu_muc_upload(task_token)
        tep, unrecognized, duplicates, ton = await _nhan_file(files, thu_muc)
    except BaseException:
        # Upload hỏng hoặc client cắt kết nối: xoá thư mục và entry tiến độ ngay
        svc.bo_luot(task_token)
        raise

    if not tep:
        svc.bo_luot(task_token)
        raise HTTPException(
            400,
            _KHONG_TIM_THAY_GL02(
                noi="danh sách đã tải lên",
                duoi=", ".join(svc.DUOI_HOP_LE),
            ),
        )

    # Luồng riêng, KHÔNG dùng BackgroundTasks: BackgroundTasks giữ 1 token của bể luồng
    # chung 40 suốt thời gian xử lý (phút) — xem cham459901.py::process.
    threading.Thread(
        target=svc.run_process,
        args=(tep, task_token, ton),
        daemon=True,
    ).start()
    return {
        "task_token":   task_token,
        "unrecognized": unrecognized,
        "duplicates":   duplicates,     # {loại phụ trợ: [tên file bị ghi đè]} — rỗng nếu không trùng
    }


@router.get("/progress/{task_token}")
def get_progress(
    task_token: str,
    _=Depends(require_feature("menu.cham_459901_000000000")),
):
    """Poll tiến độ xử lý. Khi done=True: result chứa kết quả, error chứa lỗi,
    hoặc cancelled=True nếu người dùng đã bấm Dừng."""
    prog = svc.get_progress(task_token)
    if prog is None:
        raise HTTPException(404, "Token không tồn tại hoặc đã hết hạn")
    return prog


@router.post("/cancel/{task_token}")
def cancel(
    task_token: str,
    _=Depends(require_feature("cham_459901_000000000.process")),
):
    """Yêu cầu dừng xử lý — pipeline tự thoát ở checkpoint gần nhất."""
    if not svc.cancel_progress(task_token):
        raise HTTPException(404, "Token không tồn tại hoặc đã kết thúc")
    return {"ok": True}


@router.delete("/result/{token}")
def delete_result(
    token: str,
    _=Depends(require_feature("cham_459901_000000000.process")),
):
    """Xóa thư mục kết quả trên server — dùng khi người dùng phát hiện sai sót, muốn làm lại."""
    if not svc.delete_result(safe_filename(token, "_")):
        raise HTTPException(404, "Kết quả không tồn tại hoặc đã hết hạn")
    return {"ok": True}


@router.get("/download/{token}/{file_type}")
def download_result(
    token: str,
    file_type: str,
    _=Depends(require_feature("menu.cham_459901_000000000")),
):
    """Tải 1 trong 3 file Excel kết quả (can_itt / ko / khac)."""
    if file_type not in _TEN_TAI:
        raise HTTPException(400, f"file_type phải là: {', '.join(sorted(_TEN_TAI))}")

    # `token` là chuỗi client đặt và được ghép vào đường dẫn — cắt mọi thành phần thư mục
    # trước. Thư mục lấy từ chính service, KHÔNG gõ lại đường dẫn ở đây.
    path = svc.TEMP_DIR / safe_filename(token, "_") / f"{file_type}.xlsx"
    if not path.exists():
        raise HTTPException(404, "File không tồn tại hoặc đã hết hạn")

    date_str = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")
    filename = f"{svc.TEN_TK}_{_TEN_TAI[file_type]}_{date_str}.xlsx"

    return Response(
        content=path.read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_dl_headers(filename),
    )
