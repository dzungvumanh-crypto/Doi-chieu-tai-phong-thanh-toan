"""API endpoints cho tính năng Chấm 459901 — phân loại bút toán TK 459901."""

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import threading

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.config import cham459901_folder_roots
from backend.core.uploads import MAX_REQUEST_BYTES, safe_filename, save_upload_to
from backend.core.deps import require_feature
from backend.services import cham459901_service

router = APIRouter(prefix="/api/cham459901", tags=["cham459901"])

VALID_TYPES = {"huy", "di", "ht1000", "ccn", "ko", "can_cn", "khac"}

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


def _ghi_nhan_trung(kind: str, ten: str, aux: dict, duplicates: dict) -> None:
    """1 loại phụ trợ (HUB đi / HUB đến / tồn) chỉ giữ 1 file — nếu đã có file
    cùng loại từ trước, gom cả 2 tên vào `duplicates` để cảnh báo UI (không
    chặn); file tới sau vẫn được giữ, do caller tự ghi đè `aux[kind]`."""
    if kind in aux:
        duplicates.setdefault(kind, [aux[kind][0]]).append(ten)


async def _nhan_file(
    files: list[UploadFile], thu_muc: Path,
) -> tuple[
    list[tuple[str, Path]], list[str], dict[str, list[str]],
    tuple[str, Path] | None, tuple[str, Path] | None, tuple[str, Path] | None,
]:
    """Ghi từng file xuống `thu_muc`. Phân vào 1 trong 2 nhóm:
      - file GL02 chính (zip hoặc Excel, đuôi hợp lệ) — GỘP nhiều file được, không
        cần đặt tên theo mẫu nào;
      - 1 trong 3 loại phụ trợ (HUB đi / HUB đến / tồn tháng trước), nhận diện qua
        `classify_upload_filename()` — mỗi loại chỉ giữ 1 file.
    File không khớp cả hai (đuôi lạ, không phải mẫu tên phụ trợ) rơi vào
    `unrecognized`, KHÔNG đọc byte của nó (chỉ ghi nhận tên) và không chặn cả lượt.

    Tên gốc người dùng chọn được giữ lại riêng khỏi tên đã `safe_filename()` để
    viết thông báo lỗi — báo lỗi bằng tên đã bị cắt là bắt người dùng đi tìm một
    file không tồn tại trong thư mục của họ.
    """
    tep: list[tuple[str, Path]] = []
    aux: dict[str, tuple[str, Path]] = {}
    duplicates: dict[str, list[str]] = {}
    unrecognized: list[str] = []
    da_co: set[str] = set()
    tong = 0

    for f in files:
        ten_hien_thi = f.filename or "(không tên)"
        ten = safe_filename(f.filename, "file.dat")
        # Chọn trùng một file hai lần thì mọi bút toán bị nhân đôi: cặp
        # Cancel/Normal vẫn khớp nên KHÔNG có lỗi nào, chỉ là số dòng gấp đôi
        # và người dùng không hiểu vì sao. Chặn thẳng, đừng lặng lẽ bỏ qua.
        if ten in da_co:
            raise HTTPException(400, f"File '{ten}' bị chọn hai lần — mỗi file chỉ chọn một lần.")
        da_co.add(ten)

        kind = cham459901_service.classify_upload_filename(ten_hien_thi)
        duoi_ok = ten.lower().endswith(cham459901_service.DUOI_HOP_LE)
        if kind is None and not duoi_ok:
            unrecognized.append(ten_hien_thi)
            continue

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

        if kind is None:
            tep.append((ten_hien_thi, thu_muc / ten))
        else:
            _ghi_nhan_trung(kind, ten_hien_thi, aux, duplicates)
            aux[kind] = (ten_hien_thi, thu_muc / ten)

    return tep, unrecognized, duplicates, aux.get("hub_di"), aux.get("hub_den"), aux.get("ton")


def _quet_thu_muc(p: Path) -> tuple[
    list[tuple[str, Path]], list[str], dict[str, list[str]],
    tuple[str, Path] | None, tuple[str, Path] | None, tuple[str, Path] | None,
]:
    """Bản dùng cho `/process_folder` — file đã nằm sẵn trên server nên dùng
    THẲNG đường dẫn gốc, không copy/không đọc byte vào RAM.

    Lọc theo TÊN trước khi quyết định file nào được xử lý: thư mục người dùng
    trỏ vào có thể chứa file rất nặng không liên quan (báo cáo khác, backup...)
    — chỉ so tên (rẻ), không mở/đọc nội dung file không khớp mẫu.
    """
    tep: list[tuple[str, Path]] = []
    aux: dict[str, tuple[str, Path]] = {}
    duplicates: dict[str, list[str]] = {}
    unrecognized: list[str] = []

    for entry in sorted(p.iterdir(), key=lambda e: e.name):
        if not entry.is_file():
            continue
        kind = cham459901_service.classify_upload_filename(entry.name)
        duoi_ok = entry.name.lower().endswith(cham459901_service.DUOI_HOP_LE)
        if kind is None and not duoi_ok:
            unrecognized.append(entry.name)
            continue
        if kind is None:
            tep.append((entry.name, entry))
        else:
            _ghi_nhan_trung(kind, entry.name, aux, duplicates)
            aux[kind] = (entry.name, entry)

    return tep, unrecognized, duplicates, aux.get("hub_di"), aux.get("hub_den"), aux.get("ton")


@router.post("/process")
async def process(
    files: list[UploadFile],
    _=Depends(require_feature("cham_459901.process")),
):
    """Nhận nhiều file cùng lúc (kéo-thả tự do): file GL02 chính (zip/Excel, tên gì
    cũng được, nhiều file được GỘP) + tùy chọn HUB đi / HUB đến / tồn tháng trước
    (tự nhận diện theo tên). Thiếu 1 trong 2 file HUB → bỏ qua bước 1000 Hoàn trả.
    Trả task_token ngay, xử lý ở luồng riêng.
    """
    if not files:
        raise HTTPException(400, "Cần chọn ít nhất 1 file.")

    task_token = cham459901_service.init_progress()
    thu_muc = cham459901_service.tao_thu_muc_upload(task_token)
    try:
        tep, unrecognized, duplicates, hub_di, hub_den, ton = await _nhan_file(files, thu_muc)
    except BaseException:
        # Upload hỏng hoặc client cắt kết nối: xoá thư mục và entry tiến độ ngay,
        # đừng để lại một lượt "đang khởi tạo" không bao giờ chạy tới.
        cham459901_service.bo_luot(task_token)
        raise

    if not tep:
        cham459901_service.bo_luot(task_token)
        raise HTTPException(
            400,
            _KHONG_TIM_THAY_GL02(
                noi="danh sách đã tải lên",
                duoi=", ".join(cham459901_service.DUOI_HOP_LE),
            ),
        )

    hub_partial = (hub_di is not None) != (hub_den is not None)

    # Chạy trong luồng riêng, KHÔNG dùng BackgroundTasks: Starlette chạy hàm
    # đồng bộ của BackgroundTasks trong threadpool CHUNG 40 token của anyio và
    # giữ token đó suốt thời gian xử lý (phút, không phải giây). Vài lượt chạy
    # cùng lúc là bể cạn, mọi endpoint `def` khác của hệ thống phải xếp hàng
    # theo. Luồng riêng thì việc nặng chạy ngoài bể, đúng cách ACH đang làm
    # (backend/services/ach_service.py). Tiến độ vẫn theo dõi qua /progress.
    threading.Thread(
        target=cham459901_service.run_process,
        args=(tep, task_token, hub_di, hub_den, ton),
        daemon=True,
    ).start()
    return {
        "task_token":   task_token,
        "unrecognized": unrecognized,
        "duplicates":   duplicates,     # {loại phụ trợ: [tên file bị ghi đè]} — rỗng nếu không trùng
        "hub_partial":  hub_partial,    # True nếu chỉ có 1/2 file HUB (cả 2 chân đều bị bỏ qua)
    }


def _thu_muc_hop_le(folder_path: str) -> Path:
    """Đổi đường dẫn người dùng gõ thành Path, chỉ chấp nhận khi nằm TRONG một
    thư mục gốc đã khai trong .env (`CHAM459901_FOLDER_ROOTS`).

    Kiểm phạm vi TRƯỚC khi kiểm tồn tại — thứ tự ngược lại biến endpoint thành
    máy dò "đường dẫn này có thật không" cho mọi chỗ trên máy chủ, vì hai câu
    lỗi khác nhau là đủ để phân biệt. Ngoài phạm vi thì trả cùng một câu, không
    hé lộ thư mục đó có tồn tại hay không.

    `.resolve()` chạy trước khi so sánh nên "gốc_hợp_lệ/../../Windows" và
    symlink trỏ ra ngoài đều bị bắt. Symlink NẰM TRONG thư mục hợp lệ trỏ ra
    ngoài thì không chặn — ai đặt được symlink vào đó cũng đặt được file thật
    vào đó, hàng rào này không phải chỗ giải quyết chuyện ấy.
    """
    try:
        roots = cham459901_folder_roots()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e

    p = Path(folder_path).resolve()
    if not any(p.is_relative_to(r) for r in roots):
        raise HTTPException(
            403,
            "Thư mục nằm ngoài phạm vi cho phép. Chỉ quét được trong: "
            + "; ".join(str(r) for r in roots),
        )
    if not p.is_dir():
        raise HTTPException(400, f"Thư mục không tồn tại: {folder_path}")
    return p


class FolderRequest(BaseModel):
    folder_path: str


@router.post("/process_folder")
def process_folder(
    req: FolderRequest,
    _=Depends(require_feature("cham_459901.process")),
):
    """Chạy trực tiếp từ thư mục server (không upload) — quét toàn bộ file NẰM TRỰC TIẾP
    trong thư mục (không đệ quy vào thư mục con), tự nhận diện theo tên giống route /process.
    Trả task_token ngay, xử lý ở luồng riêng.
    """
    p = _thu_muc_hop_le(req.folder_path)

    tep, unrecognized, duplicates, hub_di, hub_den, ton = _quet_thu_muc(p)

    if not tep:
        raise HTTPException(
            400,
            _KHONG_TIM_THAY_GL02(
                noi="thư mục đã chọn",
                duoi=", ".join(cham459901_service.DUOI_HOP_LE),
            ),
        )

    hub_partial = (hub_di is not None) != (hub_den is not None)
    task_token = cham459901_service.init_progress()
    threading.Thread(
        target=cham459901_service.run_process,
        args=(tep, task_token, hub_di, hub_den, ton),
        daemon=True,
    ).start()
    return {
        "task_token":   task_token,
        "unrecognized": unrecognized,
        "duplicates":   duplicates,
        "hub_partial":  hub_partial,
    }


@router.get("/progress/{task_token}")
def get_progress(
    task_token: str,
    _=Depends(require_feature("menu.cham_459901")),
):
    """Poll tiến độ xử lý. Khi done=True: result chứa kết quả, error chứa lỗi,
    hoặc cancelled=True nếu người dùng đã bấm Dừng."""
    prog = cham459901_service.get_progress(task_token)
    if prog is None:
        raise HTTPException(404, "Token không tồn tại hoặc đã hết hạn")
    return prog


@router.post("/cancel/{task_token}")
def cancel(
    task_token: str,
    _=Depends(require_feature("cham_459901.process")),
):
    """Yêu cầu dừng xử lý — pipeline tự thoát ở checkpoint gần nhất."""
    ok = cham459901_service.cancel_progress(task_token)
    if not ok:
        raise HTTPException(404, "Token không tồn tại hoặc đã kết thúc")
    return {"ok": True}


@router.delete("/result/{token}")
def delete_result(
    token: str,
    _=Depends(require_feature("cham_459901.process")),
):
    """Xóa thư mục kết quả trên server — dùng khi người dùng phát hiện sai sót, muốn làm lại."""
    ok = cham459901_service.delete_result(safe_filename(token, "_"))
    if not ok:
        raise HTTPException(404, "Kết quả không tồn tại hoặc đã hết hạn")
    return {"ok": True}


@router.get("/download/{token}/{file_type}")
def download_result(
    token: str,
    file_type: str,
    _=Depends(require_feature("menu.cham_459901")),
):
    """Tải 1 trong 7 file Excel kết quả (huy / di / ht1000 / ccn / ko / can_cn / khac)."""
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
