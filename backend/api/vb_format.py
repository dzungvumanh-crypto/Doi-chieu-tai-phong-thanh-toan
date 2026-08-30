"""API Chuẩn hoá văn bản theo QĐ 979/QyĐ-NHNo-PC.

## Vì sao tách hai bước: chuẩn hoá rồi mới tải về

Một request trả thẳng file .docx thì không còn chỗ nào để trả **nhật ký sửa
đổi** — mà nhật ký mới là thứ người dùng cần đọc trước khi quyết định lấy hay
không lấy bản đã sửa. Nên `/chuan-hoa` trả JSON kèm một token, file kết quả nằm
trên đĩa, `/tai-ve/{token}` mới đưa file. Người dùng đọc nhật ký, thấy máy sửa
đúng ý thì bấm tải; thấy sửa sai chỗ nào thì vào tab Cấu hình chỉnh rồi chạy lại.

File kết quả sống hết ngày làm việc và bị dọn lúc 23h cùng các tính năng khác
(`backend/core/don_dep.py`).
"""
import logging
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.concurrency import run_heavy
from backend.core.deps import require_feature
from backend.core.don_dep import moc_don_gan_nhat
from backend.core.uploads import read_limited, safe_filename
from backend.database import get_db, write_audit
from backend.schemas.vb_format import CauHinhIn, CauHinhOut, KetQuaChuanHoa
from backend.services.vb_format import quy_chuan, store
from backend.services.vb_format.chuan_hoa import chuan_hoa as _chuan_hoa

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vb-format", tags=["vb-format"])

BASE_DIR = Path(__file__).resolve().parents[2]
TEMP_DIR = BASE_DIR / "data" / "temp_vb_format"

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Word 2007+ trở lên. Bản .doc cũ là định dạng nhị phân khác hẳn, python-docx
# không đọc được — chặn ngay ở đây để người dùng nhận thông báo dễ hiểu thay vì
# một traceback về "file is not a zip file".
_DUOI_HOP_LE = (".docx",)


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


def _don_file_cu(cutoff: float | None = None) -> None:
    """Xoá kết quả cũ hơn mốc 23h gần nhất. Gọi được ở mọi thời điểm."""
    if not TEMP_DIR.exists():
        return
    cutoff = moc_don_gan_nhat() if cutoff is None else cutoff
    for f in TEMP_DIR.iterdir():
        try:
            if f.stat().st_mtime < cutoff:
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
        except OSError as e:
            _log.warning("Không xoá được file tạm %s: %s", f, e)


# ── Cấu hình quy chuẩn ───────────────────────────────────────────────────────
@router.get("/cau-hinh", response_model=CauHinhOut)
def lay_cau_hinh(
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_feature("menu.vb_format")),
):
    """Cấu hình đang áp dụng + mọi thứ màn Cấu hình cần để dựng form."""
    row = db.execute(
        """SELECT c.updated_at, u.full_name
           FROM vb_format_config c
           LEFT JOIN user_tttt u ON u.id = c.updated_by
           WHERE c.id = 1"""
    ).fetchone()
    return CauHinhOut(
        cau_hinh=store.doc_day_du(db),
        mac_dinh=quy_chuan.mac_dinh(),
        nhan=quy_chuan.NHAN_THANH_PHAN,
        dai_co_chu={k: list(v) for k, v in quy_chuan.DAI_CO_CHU.items()},
        mau_danh_dau=quy_chuan.MAU_DANH_DAU,
        cap_nhat_luc=str(row["updated_at"]) if row and row["updated_at"] else None,
        cap_nhat_boi=row["full_name"] if row and row["full_name"] else None,
    )


@router.put("/cau-hinh")
def luu_cau_hinh(
    body: CauHinhIn,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("vb_format.config")),
):
    cfg = body.model_dump(exclude_none=True)
    ket_qua = store.ghi_cau_hinh(db, cfg, current["id"])
    write_audit(db, current["id"], "vb_format.cau_hinh.sua", "vb_format_config", 1,
                "Sửa thông số quy chuẩn trình bày văn bản")
    db.commit()
    return {"cau_hinh": ket_qua}


@router.post("/cau-hinh/mac-dinh")
def khoi_phuc_mac_dinh(
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("vb_format.config")),
):
    ket_qua = store.dat_lai_mac_dinh(db, current["id"])
    write_audit(db, current["id"], "vb_format.cau_hinh.mac_dinh", "vb_format_config", 1,
                "Khôi phục quy chuẩn mặc định theo QĐ 979")
    db.commit()
    return {"cau_hinh": ket_qua}


# ── Chuẩn hoá ────────────────────────────────────────────────────────────────
@router.post("/chuan-hoa", response_model=KetQuaChuanHoa)
async def chuan_hoa_file(
    file: UploadFile,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("menu.vb_format")),
):
    ten_goc = safe_filename(file.filename, "van_ban.docx")
    if not ten_goc.lower().endswith(_DUOI_HOP_LE):
        raise HTTPException(
            400,
            "Chỉ nhận file Word định dạng .docx. File .doc đời cũ cần mở bằng "
            "Word rồi chọn Lưu thành .docx trước khi tải lên.",
        )
    du_lieu = await read_limited(file)
    if not du_lieu:
        raise HTTPException(400, "File rỗng.")

    cfg = store.doc_cau_hinh(db)
    try:
        # Đọc + ghi cả cây XML của một văn bản là việc nặng và giữ GIL suốt —
        # đi qua bể `run_heavy` để vài người cùng chạy không làm nghẽn những
        # request nhẹ khác (xem backend/core/concurrency.py).
        ket_qua, bao_cao = await run_heavy(_chuan_hoa, du_lieu, cfg)
    except HTTPException:
        raise
    except Exception as e:                                        # noqa: BLE001
        _log.exception("Chuẩn hoá văn bản thất bại: %s", ten_goc)
        raise HTTPException(
            400,
            "Không đọc được file Word này. Hãy mở bằng Word, chọn Lưu thành "
            f".docx rồi tải lại. (Chi tiết: {e})",
        ) from e

    _don_file_cu()
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    ten_ra = f"{Path(ten_goc).stem}_da_chuan_hoa.docx"
    thu_muc = TEMP_DIR / token
    thu_muc.mkdir()
    (thu_muc / "ket_qua.docx").write_bytes(ket_qua)
    (thu_muc / "ten.txt").write_text(ten_ra, encoding="utf-8")

    write_audit(db, current["id"], "vb_format.chuan_hoa", "file", None,
                f"Chuẩn hoá «{ten_goc}»: sửa {bao_cao['thong_ke']['doan_da_sua']}"
                f"/{bao_cao['thong_ke']['tong_doan']} đoạn")
    db.commit()

    return KetQuaChuanHoa(token=token, ten_file=ten_ra, **bao_cao)


@router.get("/tai-ve/{token}")
def tai_ve(
    token: str,
    _=Depends(require_feature("menu.vb_format")),
):
    # `token` đi thẳng vào đường dẫn — cắt mọi thành phần thư mục trước, đừng
    # tin việc bộ định tuyến không khớp dấu "/".
    thu_muc = TEMP_DIR / safe_filename(token, "_")
    duong_dan = thu_muc / "ket_qua.docx"
    if not duong_dan.exists():
        raise HTTPException(404, "File không tồn tại hoặc đã hết hạn (dọn lúc 23h hằng ngày).")
    ten = "van_ban_da_chuan_hoa.docx"
    ten_file = thu_muc / "ten.txt"
    if ten_file.exists():
        ten = ten_file.read_text(encoding="utf-8").strip() or ten
    return Response(content=duong_dan.read_bytes(), media_type=_DOCX_MIME,
                    headers=_dl_headers(ten))
