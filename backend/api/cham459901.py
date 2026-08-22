"""API endpoints cho tính năng Chấm 459901 — phân loại bút toán TK 459901."""

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.services import cham459901_service

router = APIRouter(prefix="/api/cham459901", tags=["cham459901"])

VALID_TYPES = {"huy", "di", "ht1000", "ccn", "ko", "can_cn", "khac"}


def _classify_files(
    files_bytes: dict[str, bytes],
) -> tuple[dict[str, bytes], list[str], dict[str, list[str]], bool]:
    """Phân loại theo tên file (GL02 zip / HUB đi / HUB đến / tồn tháng trước) — dùng chung
    cho route upload (nhiều file kéo-thả) và route folder (quét thư mục server). Trả về
    (bytes_by_kind, unrecognized, duplicates, hub_partial)."""
    by_kind: dict[str, list[str]] = {"zip": [], "hub_di": [], "hub_den": [], "ton": []}
    bytes_by_kind: dict[str, bytes] = {}
    unrecognized: list[str] = []

    for name, data in files_bytes.items():
        kind = cham459901_service.classify_upload_filename(name)
        if kind is None:
            unrecognized.append(name)
            continue
        by_kind[kind].append(name)
        bytes_by_kind[kind] = data  # trùng loại → giữ file cuối cùng, đã cảnh báo qua "duplicates"

    duplicates = {k: v for k, v in by_kind.items() if len(v) > 1}
    hub_partial = ("hub_di" in bytes_by_kind) != ("hub_den" in bytes_by_kind)  # đúng 1/2 file HUB

    return bytes_by_kind, unrecognized, duplicates, hub_partial


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
    background_tasks: BackgroundTasks,
    files: list[UploadFile],
    _=Depends(require_feature("cham_459901.process")),
):
    """Nhận nhiều file cùng lúc (kéo-thả tự do) — tự nhận diện GL02*.zip + 2 file HUB đi/đến
    theo tên file, không cần đúng thứ tự/ô riêng. Thiếu CẢ 2 file HUB → bỏ qua bước
    1000 Hoàn trả. Trả task_token ngay, xử lý nền."""
    files_bytes: dict[str, bytes] = {}
    for f in files:
        files_bytes[f.filename or "(không tên)"] = await f.read()

    bytes_by_kind, unrecognized, duplicates, hub_partial = _classify_files(files_bytes)

    if "zip" not in bytes_by_kind:
        raise HTTPException(400, "Không tìm thấy file GL02*.zip trong danh sách đã tải lên")

    task_token = cham459901_service.init_progress()
    background_tasks.add_task(
        cham459901_service.run_process, bytes_by_kind["zip"], task_token,
        bytes_by_kind.get("hub_di"), bytes_by_kind.get("hub_den"), bytes_by_kind.get("ton"),
    )
    return {
        "task_token":   task_token,
        "unrecognized": unrecognized,
        "duplicates":   duplicates,     # {loại: [tên file bị ghi đè]} — rỗng nếu không trùng
        "hub_partial":  hub_partial,    # True nếu chỉ có 1/2 file HUB (file kia bị bỏ qua)
    }


class FolderRequest(BaseModel):
    folder_path: str


@router.post("/process_folder")
def process_folder(
    req: FolderRequest,
    background_tasks: BackgroundTasks,
    _=Depends(require_feature("cham_459901.process")),
):
    """Chạy trực tiếp từ thư mục server (không upload) — quét toàn bộ file NẰM TRỰC TIẾP
    trong thư mục (không đệ quy vào thư mục con), tự nhận diện theo tên giống route /process.
    Trả task_token ngay, xử lý nền."""
    p = Path(req.folder_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f"Thư mục không tồn tại: {req.folder_path}")

    files_bytes: dict[str, bytes] = {
        entry.name: entry.read_bytes() for entry in p.iterdir() if entry.is_file()
    }

    bytes_by_kind, unrecognized, duplicates, hub_partial = _classify_files(files_bytes)

    if "zip" not in bytes_by_kind:
        raise HTTPException(400, "Không tìm thấy file GL02*.zip trong thư mục đã chọn")

    task_token = cham459901_service.init_progress()
    background_tasks.add_task(
        cham459901_service.run_process, bytes_by_kind["zip"], task_token,
        bytes_by_kind.get("hub_di"), bytes_by_kind.get("hub_den"), bytes_by_kind.get("ton"),
    )
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
    ok = cham459901_service.delete_result(token)
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

    path = cham459901_service.TEMP_DIR / token / f"{file_type}.xlsx"
    if not path.exists():
        raise HTTPException(404, "File không tồn tại hoặc đã hết hạn")

    date_str = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")
    filename = f"459901_{file_type}_{date_str}.xlsx"

    return Response(
        content=path.read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_dl_headers(filename),
    )
