"""API endpoints cho tính năng Chấm 459901 — phân loại bút toán TK 459901."""

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.deps import require_feature
from backend.services import cham459901_service

router = APIRouter(prefix="/api/cham459901", tags=["cham459901"])

VALID_TYPES = {"huy", "di", "ht1000", "ccn", "ko", "can_cn", "khac"}


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
    by_kind: dict[str, list[str]] = {"zip": [], "hub_di": [], "hub_den": []}
    bytes_by_kind: dict[str, bytes] = {}
    unrecognized: list[str] = []

    for f in files:
        kind = cham459901_service.classify_upload_filename(f.filename or "")
        data = await f.read()
        name = f.filename or "(không tên)"
        if kind is None:
            unrecognized.append(name)
            continue
        by_kind[kind].append(name)
        bytes_by_kind[kind] = data  # trùng loại → giữ file cuối cùng, đã cảnh báo qua "duplicates"

    if not by_kind["zip"]:
        raise HTTPException(400, "Không tìm thấy file GL02*.zip trong danh sách đã tải lên")

    duplicates = {k: v for k, v in by_kind.items() if len(v) > 1}

    hub_di_bytes  = bytes_by_kind.get("hub_di")
    hub_den_bytes = bytes_by_kind.get("hub_den")
    hub_partial = (hub_di_bytes is None) != (hub_den_bytes is None)  # có đúng 1/2 file HUB

    task_token = cham459901_service.init_progress()
    background_tasks.add_task(
        cham459901_service.run_process, bytes_by_kind["zip"], task_token,
        hub_di_bytes, hub_den_bytes,
    )
    return {
        "task_token":   task_token,
        "unrecognized": unrecognized,
        "duplicates":   duplicates,     # {loại: [tên file bị ghi đè]} — rỗng nếu không trùng
        "hub_partial":  hub_partial,    # True nếu chỉ có 1/2 file HUB (file kia bị bỏ qua)
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
