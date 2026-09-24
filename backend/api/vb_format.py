"""API Chuẩn hoá văn bản theo QĐ 979/QyĐ-NHNo-PC.

## Vì sao tách hai bước: chuẩn hoá rồi mới tải về

Một request trả thẳng file .docx thì không còn chỗ nào để trả **nhật ký sửa
đổi** — mà nhật ký mới là thứ người dùng cần đọc trước khi quyết định lấy hay
không lấy bản đã sửa. Nên `/chuan-hoa` trả JSON kèm một token, file kết quả nằm
trên đĩa, `/tai-ve/{token}` mới đưa file. Người dùng đọc nhật ký, thấy máy sửa
đúng ý thì bấm tải; thấy sửa sai chỗ nào thì vào tab Cấu hình chỉnh rồi chạy lại.

## Mỗi lượt là một PHIÊN lưu lại để rà soát (24/09/2026)

`data/temp_vb_format/<YYYYMMDD_HHMMSS>_<token>/`:

    goc.docx        file người dùng tải lên, nguyên văn
    cau_hinh.json   cấu hình quy chuẩn ĐÃ ÁP cho lượt này (cấu hình đổi được về sau)
    phien.json      ai, lúc nào, tên file, trạng thái (dang_chay | xong | loi), vết lỗi
    ket_qua.docx    chỉ có khi xong
    bao_cao.json    nhật ký sửa đổi đúng như người dùng thấy trên màn hình

Người dùng báo "máy sửa sai" thì mở đúng thư mục đó là có đủ đầu vào để chạy lại
`chuan_hoa()` và dò lỗi — trước đây file bị xoá lúc 23h, lượt LỖI còn không để lại
file gốc. Lượt lỗi vẫn lưu `goc.docx` + vết lỗi: đó mới là thứ cần nhất khi sửa.
`phien.json` ghi `dang_chay` TRƯỚC khi chuẩn hoá — backend chết giữa chừng thì phiên
vẫn còn file gốc và nhìn là biết lượt đó không bao giờ xong.

Giữ `VB_FORMAT_LUU_NGAY` ngày (mặc định 30), dọn lúc 23h cùng lịch chung
(`backend/services/temp_cleanup_service.py`). Tên thư mục bắt đầu bằng ngày giờ để
sắp theo tên là theo thời gian. Nhật ký hệ thống chỉ ghi ngày giờ + 8 ký tự đầu
token (`_ma_phien()`) — đủ để tìm thư mục, không đủ để tải file.
"""
import json
import logging
import re
import sqlite3
import traceback
import uuid
from pathlib import Path
from urllib.parse import quote

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.concurrency import run_heavy
from backend.core.config import settings
from backend.core.deps import require_feature
from backend.core.don_dep import moc_don_gan_nhat, xoa_thu_muc_cu
from backend.core.uploads import read_limited, safe_filename
from backend.database import _vn_now, get_db, write_audit
from backend.schemas.vb_format import CauHinhIn, CauHinhOut, KetQuaChuanHoa, MauVB
from backend.services.vb_format import quy_chuan, store
from backend.services.vb_format.chuan_hoa import chuan_hoa as _chuan_hoa

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vb-format", tags=["vb-format"])

BASE_DIR = Path(__file__).resolve().parents[2]
TEMP_DIR = BASE_DIR / "data" / "temp_vb_format"
MAU_DIR = BASE_DIR / "templates" / "vb_mau"

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Word 2007+ trở lên. Bản .doc cũ là định dạng nhị phân khác hẳn, python-docx
# không đọc được — chặn ngay ở đây để người dùng nhận thông báo dễ hiểu thay vì
# một traceback về "file is not a zip file".
_DUOI_HOP_LE = (".docx",)
# Token do máy chủ sinh (`uuid4().hex`). Kiểm đúng khuôn trước khi đem đi `glob` —
# token "*" mà lọt vào là tải được kết quả phiên của người khác.
_KHUON_TOKEN = re.compile(r"[0-9a-f]{32}")


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


def _don_file_cu(cutoff: float | None = None) -> None:
    """Xoá phiên quá `VB_FORMAT_LUU_NGAY` ngày. `cutoff` là mốc 23h chung của lịch dọn.

    Lùi (số ngày − 1) ngày từ mốc đó: đặt 1 là hành vi cũ (dọn lúc 23h cùng ngày),
    đặt 30 là phiên hôm nay sống tới 23h của ngày thứ 30 tính cả hôm nay.
    """
    moc = moc_don_gan_nhat() if cutoff is None else cutoff
    xoa_thu_muc_cu(TEMP_DIR, moc - (settings.VB_FORMAT_LUU_NGAY - 1) * 86400)


def _ghi_json(duong_dan: Path, du_lieu) -> None:
    duong_dan.write_text(json.dumps(du_lieu, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")


def _ghi_phien(thu_muc: Path, cac_file: dict) -> None:
    """Ghi các file của phiên: `bytes` ghi thẳng, còn lại ghi JSON. Chạy trong luồng —
    file tải lên tới `MAX_UPLOAD_MB`, ổ chậm thì ghi trên event loop là đứng cả backend."""
    thu_muc.mkdir(parents=True, exist_ok=True)
    for ten, noi_dung in cac_file.items():
        if isinstance(noi_dung, bytes):
            (thu_muc / ten).write_bytes(noi_dung)
        else:
            _ghi_json(thu_muc / ten, noi_dung)


def _ma_phien(thu_muc: Path) -> str:
    """Tên phiên để ghi Nhật ký / log: ngày giờ + 8 ký tự đầu token.

    KHÔNG ghi nguyên token: `/tai-ve/{token}` chỉ đòi `menu.vb_format`, nên ai đọc được
    Nhật ký hệ thống mà có token là tải được văn bản người khác suốt thời gian lưu phiên.
    8 ký tự vẫn đủ để người rà soát tìm đúng thư mục (`dir *_<8 ký tự>*`).
    """
    return thu_muc.name[:24]


def _tim_phien(token: str) -> Path | None:
    if not _KHUON_TOKEN.fullmatch(token):
        return None
    return next(TEMP_DIR.glob(f"*_{token}"), None)


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


# ── Mẫu trình bày sẵn (Phụ lục V) ────────────────────────────────────────────
_mau_cache: list[dict] | None = None


def _muc_luc_mau() -> list[dict]:
    """Mục lục 18 mẫu, đọc một lần. Thư mục mẫu là dữ liệu tĩnh trong repo.

    Thiếu file thì trả danh sách rỗng chứ không ném lỗi: mẫu trắng là tiện ích
    phụ, không đáng để hỏng cả màn Chuẩn hoá. Nhưng có ghi log ERROR — người
    vận hành cần biết để chạy `scripts/tach_mau_vb.py`, còn người dùng thì thấy
    ngay dòng nhắc trên màn hình.
    """
    global _mau_cache
    if _mau_cache is None:
        f = MAU_DIR / "muc_luc.json"
        try:
            _mau_cache = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            _log.error("Không đọc được mục lục mẫu trình bày %s: %s", f, e)
            _mau_cache = []
    return _mau_cache


@router.get("/mau", response_model=list[MauVB])
def danh_sach_mau(_=Depends(require_feature("menu.vb_format"))):
    return [MauVB(so=m["so"], ten=m["ten"]) for m in _muc_luc_mau()]


@router.get("/mau/{so}")
def tai_mau(so: int, _=Depends(require_feature("menu.vb_format"))):
    """Tải một mẫu trắng. Tên file lấy từ mục lục, KHÔNG nhận từ client."""
    mau = next((m for m in _muc_luc_mau() if m["so"] == so), None)
    if mau is None:
        raise HTTPException(404, f"Không có mẫu số {so}.")
    duong_dan = MAU_DIR / mau["file"]
    if not duong_dan.exists():
        _log.error("Mục lục có mẫu %s nhưng thiếu file %s", so, duong_dan)
        raise HTTPException(404, f"Thiếu file mẫu số {so} trên máy chủ.")
    return Response(content=duong_dan.read_bytes(), media_type=_DOCX_MIME,
                    headers=_dl_headers(f"Mau {so:02d} - {mau['ten']}.docx"))


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

    # ── Mở phiên: lưu đầu vào TRƯỚC khi chạy ──
    cfg = store.doc_cau_hinh(db)
    token = uuid.uuid4().hex
    ten_ra = f"{Path(ten_goc).stem}_da_chuan_hoa.docx"
    luc = _vn_now()
    thu_muc = TEMP_DIR / f"{luc:%Y%m%d_%H%M%S}_{token}"
    phien = {
        "luc": luc.isoformat(timespec="seconds"),
        "nguoi_id": current["id"],
        "nguoi": current.get("full_name") or current.get("username"),
        "ten_goc": ten_goc,
        "ten_ra": ten_ra,
        "trang_thai": "dang_chay",
    }
    await anyio.to_thread.run_sync(_ghi_phien, thu_muc, {
        "goc.docx": du_lieu, "cau_hinh.json": cfg, "phien.json": phien})

    # ── Chuẩn hoá ──
    try:
        # Đọc + ghi cả cây XML của một văn bản là việc nặng và giữ GIL suốt —
        # đi qua bể `run_heavy` để vài người cùng chạy không làm nghẽn những
        # request nhẹ khác (xem backend/core/concurrency.py).
        ket_qua, bao_cao = await run_heavy(_chuan_hoa, du_lieu, cfg)
    except Exception as e:                                        # noqa: BLE001
        _log.exception("Chuẩn hoá văn bản thất bại: %s — phiên %s", ten_goc, _ma_phien(thu_muc))
        vet_loi = traceback.format_exc()
        await anyio.to_thread.run_sync(_ghi_phien, thu_muc, {
            "phien.json": {**phien, "trang_thai": "loi", "loi": vet_loi}})
        raise HTTPException(
            400,
            "Không đọc được file Word này. Hãy mở bằng Word, chọn Lưu thành "
            f".docx rồi tải lại. (Chi tiết: {e})",
        ) from e

    # ── Đóng phiên ──
    await anyio.to_thread.run_sync(_ghi_phien, thu_muc, {
        "ket_qua.docx": ket_qua, "bao_cao.json": bao_cao,
        "phien.json": {**phien, "trang_thai": "xong"}})

    write_audit(db, current["id"], "vb_format.chuan_hoa", "file", None,
                f"Chuẩn hoá «{ten_goc}»: sửa {bao_cao['thong_ke']['doan_da_sua']}"
                f"/{bao_cao['thong_ke']['tong_doan']} đoạn — phiên {_ma_phien(thu_muc)}")
    db.commit()

    return KetQuaChuanHoa(token=token, ten_file=ten_ra, **bao_cao)


@router.get("/tai-ve/{token}")
def tai_ve(
    token: str,
    _=Depends(require_feature("menu.vb_format")),
):
    thu_muc = _tim_phien(token)
    if thu_muc is None or not (thu_muc / "ket_qua.docx").exists():
        raise HTTPException(
            404, f"File không tồn tại hoặc đã hết hạn (giữ {settings.VB_FORMAT_LUU_NGAY} ngày).")
    ten = "van_ban_da_chuan_hoa.docx"
    try:
        ten = json.loads((thu_muc / "phien.json").read_text(encoding="utf-8"))["ten_ra"] or ten
    except (OSError, ValueError, KeyError) as e:
        _log.warning("Phiên %s thiếu/hỏng phien.json, tải về với tên mặc định: %s", thu_muc.name, e)
    return Response(content=(thu_muc / "ket_qua.docx").read_bytes(), media_type=_DOCX_MIME,
                    headers=_dl_headers(ten))
