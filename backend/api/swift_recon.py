# -*- coding: utf-8 -*-
"""
backend/api/swift_recon.py
---------------------------
API đối chiếu điện SWIFT (SAA <-> Màn hình quản lý điện) — Phòng Swift.

Logic đối chiếu thuần lấy NGUYÊN từ parsers.py / reconcile.py / exporters.py
gốc (không sửa logic) — xem backend/services/swift_recon/.

CẬP NHẬT (đợt 2):
  - Hỗ trợ NHIỀU FILE mỗi bên (SAA có thể xuất nhiều lần trong ngày) — các
    endpoint reconcile-*/export-* giờ nhận `saa_files`/`ql_files` (danh sách)
    thay vì 1 file duy nhất. Toàn bộ file cùng bên được PARSE RIÊNG rồi GỘP
    (concat) lại thành 1 tập bản ghi duy nhất trước khi đối chiếu — không sửa
    gì trong parsers.py.
  - 2 endpoint MỚI: export-summary-template / export-diff-template — xuất
    theo đúng biểu mẫu Mẫu 04/05 (xem template_exporters.py).

CẬP NHẬT (đợt 3 — quan trọng, đọc trước khi sửa tiếp file này):
  Mọi endpoint ở đây khai `async def` và đẩy TOÀN BỘ phần nặng (đọc .xls,
  giải nén, pandas, openpyxl, ghi lịch sử) vào `await run_heavy(_work)`.

  ĐỪNG chạy thẳng code nặng trên event loop: backend chạy 1 tiến trình/1
  luồng, làm vậy là đóng băng cả hệ thống (đăng nhập, dashboard, nghỉ phép...)
  — đã đo tới 10-12 giây mỗi lần xuất Excel theo biểu mẫu.

  Cũng ĐỪNG đổi sang `def`: FastAPI sẽ đẩy vào bể threadpool CHUNG 40 token
  và bỏ qua `CapacityLimiter` riêng cho việc nặng trong
  `backend/core/concurrency.py` (MAX_HEAVY=4) — đúng cái mà module đó sinh ra
  để chặn (40 việc nặng đồng thời từng làm `/api/auth/me` kẹt 38 giây).
  Chỉ `async def` + `await run_heavy(...)` mới vừa không chiếm event loop,
  vừa nằm trong giới hạn việc nặng dùng chung toàn hệ thống.

CẬP NHẬT (đợt 4, 18/09/2026 — card 152):
  Phần nặng (đọc file, đối chiếu, sinh Excel) chạy ở TIẾN TRÌNH RIÊNG qua
  `chay_tach(tach.<hàm>, ...)` — `backend/services/swift_recon/tach.py`. Ở trong
  `run_heavy()` chỉ còn phần nhẹ: ghi file tải lên ra đĩa, đọc/ghi lịch sử CSDL,
  kiểm tra 400/404. Hai ngoại lệ cố ý, vì mở tiến trình (~0,85 s) đắt hơn chính việc:
  đọc thử 1 file, và xuất Excel từ bản ghi có sẵn dưới `_NGUONG_TACH_DONG` dòng.
  Khi có ≥ 2 file lỗi, lỗi báo ra có thể là file khác bản cũ: mọi file được ghi ra
  đĩa TRƯỚC rồi con mới đọc (bản cũ ghi–đọc xen kẽ). Cả hai lỗi đều thật, vẫn 422. Thêm việc nặng mới thì viết ở `tach.py`, đừng viết thẳng ở đây —
  `tests/test_doi_chieu_chay_tien_trinh_rieng.py` canh chỗ đó.

Đây là router MỚI của bạn — file này bạn tự quản lý, không cần ai duyệt
logic bên trong. Chỉ có 2 việc còn lại cần Người 1 duyệt riêng:
  1. Đăng ký router này vào backend/api/registry.py
  2. Thêm bảng swift_recon_history vào backend/db/migrations.py
(xem SNIPPETS_TO_PASTE.md)
"""
from __future__ import annotations

import contextlib
from typing import Iterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.database import get_db
from backend.core.concurrency import run_heavy
from backend.core.deps import require_feature
from backend.core.tien_trinh_doi_chieu import chay_tach
from backend.core.uploads import safe_filename
from backend.schemas.swift_recon import ExportFilteredIn
from backend.services.swift_recon import parsers, tach
from backend.services.swift_recon.history_service import (
    get_recon_detail,
    list_recon_history,
    save_recon_history,
)
from backend.services.swift_recon.upload_utils import save_upload_to_path

router = APIRouter(prefix="/api/swift-recon", tags=["swift-recon"])

_TEN = "SWIFT recon"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ── Helpers ────────────────────────────────────────────────────────────────
def _dl_headers(filename: str) -> dict:
    """Content-Disposition theo RFC 6266 — tên ASCII để lui về, kèm bản UTF-8."""
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


@contextlib.contextmanager
def _tep_tam(uploads: list[UploadFile], kem_ten: bool = True) -> Iterator[tach.Tep]:
    """Ghi các file tải lên ra đĩa (giải nén nếu .zip) để tiến trình con đọc theo đường
    dẫn — con không nhận được `UploadFile`. LUÔN dọn file/thư mục tạm khi ra khỏi khối.

    `kem_ten`: lỗi định dạng khi giải nén báo kèm "[tên file]" — giống hệt bản cũ, nơi bước
    lưu và bước đọc nằm chung một `try` trong `_load_many`. Đọc thử 1 file thì không kèm."""
    da_luu: tach.Tep = []
    don: list = []
    try:
        for up in uploads:
            try:
                duong_dan, cleanup = save_upload_to_path(up)
            except parsers.UnknownFileFormat as e:
                raise parsers.UnknownFileFormat(f"[{up.filename}] {e}") if kem_ten else e
            don.append(cleanup)
            da_luu.append((up.filename, duong_dan))
        yield da_luu
    finally:
        for c in don:
            c()


def _join_names(uploads: list[UploadFile]) -> str:
    return "; ".join(u.filename for u in uploads)


# Xuất Excel từ bản ghi CÓ SẴN (đang lọc, snapshot lịch sử): ~0,28 s / 1.000 dòng, còn mở
# tiến trình con ~0,85 s (đo 18/09/2026) — dưới ngưỡng này tách chỉ làm người dùng chờ thêm
# (bảng tổng hợp vài chục dòng: 0,06 s → 0,9 s). Xuất từ file TẢI LÊN thì luôn tách: đọc
# file đã nặng sẵn.
_NGUONG_TACH_DONG = 3000


def _xuat_tu_ban_ghi(ham, so_dong: int, **kw) -> bytes:
    if so_dong < _NGUONG_TACH_DONG:
        return ham(**kw, log_callback=None, cancel_event=None)
    return chay_tach(ham, ten=_TEN, **kw)


def _tai_ve(content: bytes, headers: dict) -> Response:
    return Response(content=content, media_type=_XLSX, headers=headers)


# ── Kiểm tra & đọc thử 1 file ngay khi vừa chọn (trước khi bấm Đối chiếu) ───
# Khớp UX bản gốc: mỗi ô upload báo NGAY ✅/❌ + số dòng đọc được, KHÔNG đợi
# đến lúc bấm nút đối chiếu mới biết file có đọc được hay không. Giữ NGUYÊN
# dạng single-file — kiểm tra từng file NGAY LÚC chọn, dù sau này nhiều file
# được gộp lại (mỗi file vẫn cần biết ✅/❌ riêng của chính nó).
@router.post("/parse-preview")
async def parse_preview(
    file: UploadFile = File(...),
    source: str = Form("SAA_DEN"),  # SAA_DEN | QL_DEN | QL_DI | SAA_DI
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    if source not in ("SAA_DEN", "QL_DEN", "QL_DI", "SAA_DI"):
        raise HTTPException(400, "source không hợp lệ")

    # CỐ Ý không tách tiến trình: đọc 1 file chỉ giữ GIL ~0,4 s (đo 5.000 điện) mà mở tiến
    # trình con tốn ~0,8 s — tách là người dùng chờ gấp 3 lần MỖI lần chọn file.
    def _work() -> int:
        with _tep_tam([file], kem_ten=False) as tep:
            return tach.xem_truoc(tep[0][1], source, None, None)

    try:
        rows = await run_heavy(_work)
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))
    return {"filename": file.filename, "rows": rows}


# ── Đối chiếu (mỗi bên có thể gồm NHIỀU file) ──────────────────────────────
def _doi_chieu_va_luu(chieu: str, files_a, files_b, files_saa, files_ql, db, current) -> dict:
    """Phần nặng ở tiến trình con; ghi lịch sử ở đây vì con không mở CSDL."""
    with _tep_tam(files_a) as tep_a, _tep_tam(files_b) as tep_b:
        kq = chay_tach(tach.doi_chieu, ten=_TEN, chieu=chieu, tep_a=tep_a, tep_b=tep_b)

    history_saved, history_error = True, None
    try:
        save_recon_history(
            db, recon_type=chieu, performed_by_id=current["id"],
            file_saa_name=_join_names(files_saa), file_ql_name=_join_names(files_ql),
            **kq.pop("luu_lich_su"),
        )
    except Exception as e:  # noqa: BLE001 — không để lỗi lưu lịch sử chặn mất kết quả đối chiếu
        history_saved, history_error = False, str(e)
    return {**kq, "history_saved": history_saved, "history_error": history_error}


@router.post("/reconcile-den")
async def reconcile_den(
    saa_files: list[UploadFile] = File(...),
    ql_files: list[UploadFile] = File(...),
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    try:
        return await run_heavy(_doi_chieu_va_luu, "den", saa_files, ql_files,
                               saa_files, ql_files, db, current)
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


# Điện đi: đúng thứ tự QL trước, SAA sau — như bản desktop
@router.post("/reconcile-di")
async def reconcile_di(
    ql_files: list[UploadFile] = File(...),
    saa_files: list[UploadFile] = File(...),
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    try:
        return await run_heavy(_doi_chieu_va_luu, "di", ql_files, saa_files,
                               saa_files, ql_files, db, current)
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


# ── Xuất Excel (nhận lại đúng những file frontend đã có sẵn trong state,
#    không bắt người dùng chọn file lần 2 — xem frontend/pages/swift_recon.py) ──
def _xuat_tu_tep(ham, saa_den, ql_den, ql_di, saa_di) -> bytes:
    """Chặn 400 TRƯỚC khi ghi file/mở tiến trình con (HTTPException không nên đi qua
    ranh giới tiến trình), rồi chạy `ham` của `tach` trên các file đã ghi ra đĩa."""
    den, di = bool(saa_den and ql_den), bool(ql_di and saa_di)
    if not (den or di):
        raise HTTPException(400, "Chưa có dữ liệu đối chiếu nào để xuất")
    # Chỉ ghi file của cặp ĐỦ hai bên — bản cũ không đọc file của cặp thiếu, nên file hỏng ở
    # đó không được thành lỗi 422
    with contextlib.ExitStack() as st:
        tep = {k: st.enter_context(_tep_tam(v if du else []))
               for k, v, du in (("saa_den", saa_den, den), ("ql_den", ql_den, den),
                                ("ql_di", ql_di, di), ("saa_di", saa_di, di))}
        return chay_tach(ham, ten=_TEN, tep=tep)


@router.post("/export-summary")
async def export_summary(
    # LƯU Ý: dùng default_factory=list (KHÔNG dùng Optional/None làm mặc định) —
    # FastAPI 0.109.1 (bản đang pin trong requirements.txt) có lỗi không tự
    # bọc list khi multipart chỉ gửi ĐÚNG 1 file cho field kiểu Optional[List[UploadFile]],
    # báo lỗi 422 'Input should be a valid list'. default_factory=list tránh được lỗi này.
    saa_den: list[UploadFile] = File(default_factory=list),
    ql_den: list[UploadFile] = File(default_factory=list),
    ql_di: list[UploadFile] = File(default_factory=list),
    saa_di: list[UploadFile] = File(default_factory=list),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    try:
        content = await run_heavy(_xuat_tu_tep, tach.xuat_tong_hop, saa_den, ql_den, ql_di, saa_di)
        return _tai_ve(content, {"Content-Disposition": 'attachment; filename="Tong_hop_doi_chieu_dien.xlsx"'})
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


@router.post("/export-diff")
async def export_diff(
    # LƯU Ý: dùng default_factory=list — xem giải thích ở export_summary().
    saa_den: list[UploadFile] = File(default_factory=list),
    ql_den: list[UploadFile] = File(default_factory=list),
    ql_di: list[UploadFile] = File(default_factory=list),
    saa_di: list[UploadFile] = File(default_factory=list),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    try:
        content = await run_heavy(_xuat_tu_tep, tach.xuat_chi_tiet, saa_den, ql_den, ql_di, saa_di)
        return _tai_ve(content, {"Content-Disposition": 'attachment; filename="Chi_tiet_lech_doi_chieu_dien.xlsx"'})
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


# ── Xuất Excel THEO BIỂU MẪU (Mẫu 04 / Mẫu 05) — xem cảnh báo giả định ở
#    đầu file template_exporters.py trước khi dùng cho báo cáo chính thức ──
def _xuat_theo_mau(loai: str, saa_den, ql_den, ql_di, saa_di) -> tuple[bytes, str]:
    """Chọn đúng CHIỀU đang xuất từ các ô file frontend gửi lên (frontend chỉ gửi file
    của 1 chiều mỗi lần), rồi đọc + ghi mẫu ở tiến trình con."""
    if saa_den and ql_den:
        direction, a, source_a, b, source_b = "den", saa_den, "SAA_DEN", ql_den, "QL_DEN"
    elif ql_di and saa_di:
        direction, a, source_a, b, source_b = "di", ql_di, "QL_DI", saa_di, "SAA_DI"
    else:
        raise HTTPException(400, "Chưa có dữ liệu đối chiếu nào để xuất")
    with _tep_tam(a) as tep_a, _tep_tam(b) as tep_b:
        content = chay_tach(tach.xuat_theo_mau, ten=_TEN, loai=loai, direction=direction,
                            tep_a=tep_a, source_a=source_a, tep_b=tep_b, source_b=source_b)
    return content, direction


@router.post("/export-summary-template")
async def export_summary_template(
    # LƯU Ý: dùng default_factory=list — xem giải thích ở export_summary().
    saa_den: list[UploadFile] = File(default_factory=list),
    ql_den: list[UploadFile] = File(default_factory=list),
    ql_di: list[UploadFile] = File(default_factory=list),
    saa_di: list[UploadFile] = File(default_factory=list),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    try:
        content, direction = await run_heavy(_xuat_theo_mau, "tong_hop", saa_den, ql_den, ql_di, saa_di)
    except HTTPException:
        raise
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001 — luôn trả JSON lỗi rõ ràng, không để lộ traceback dạng non-JSON
        raise HTTPException(500, f"Lỗi khi xuất Excel Tổng hợp theo biểu mẫu: {e}")

    fname = f"Tong_hop_theo_bieu_mau_Dien{direction.upper()}.xlsx"
    return _tai_ve(content, {"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/export-diff-template")
async def export_diff_template(
    # LƯU Ý: dùng default_factory=list — xem giải thích ở export_summary().
    saa_den: list[UploadFile] = File(default_factory=list),
    ql_den: list[UploadFile] = File(default_factory=list),
    ql_di: list[UploadFile] = File(default_factory=list),
    saa_di: list[UploadFile] = File(default_factory=list),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    try:
        content, direction = await run_heavy(_xuat_theo_mau, "chi_tiet", saa_den, ql_den, ql_di, saa_di)
    except HTTPException:
        raise
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001 — luôn trả JSON lỗi rõ ràng, không để lộ traceback dạng non-JSON
        raise HTTPException(500, f"Lỗi khi xuất Excel Chi tiết lệch theo biểu mẫu: {e}")

    fname = f"Chi_tiet_lech_theo_bieu_mau_Dien{direction.upper()}.xlsx"
    return _tai_ve(content, {"Content-Disposition": f'attachment; filename="{fname}"'})


# ── Xuất đúng các bản ghi đang lọc trên giao diện (không phải toàn bộ) ──────
@router.post("/export-filtered")
async def export_filtered(
    payload: ExportFilteredIn,
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    if not payload.records:
        raise HTTPException(400, "Không có bản ghi nào để xuất")

    content = await run_heavy(_xuat_tu_ban_ghi, tach.xuat_ban_ghi, len(payload.records),
                              records=payload.records, columns=payload.columns)
    # `payload.filename` do trình duyệt gửi lên. Ghép thẳng vào header thì
    # một dấu nháy kép trong tên là vỡ cú pháp Content-Disposition, còn chữ
    # có dấu là 500 (header phải mã hoá được bằng latin-1). Dùng chung hàm
    # dựng header RFC 6266 như mọi endpoint tải file khác.
    return _tai_ve(content, _dl_headers(safe_filename(payload.filename, "Ban_ghi_dang_loc.xlsx")))


# ── Lịch sử đối chiếu (đọc từ bảng swift_recon_history) ─────────────────────
# Đọc CSDL ở luồng của backend; chỉ phần dựng Excel sang tiến trình con.
@router.get("/history")
async def get_history(
    limit: int = 100,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    return await run_heavy(list_recon_history, db, limit)


def _doc_lich_su(db, history_id: int) -> dict:
    detail = get_recon_detail(db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")
    return detail


@router.get("/history/{history_id}/export-raw")
async def export_raw_from_history(
    history_id: int,
    side: str = "a",  # "a" hoặc "b"
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    """Tải lại dữ liệu ĐÃ IMPORT (không phải file .xls gốc byte-for-byte —
    xem ghi chú ở cuối file — mà là đúng các dòng/cột đã đọc được từ file đó
    tại thời điểm đối chiếu, GỘP TỪ TẤT CẢ file đã dùng lần đó nếu là nhiều
    file), dưới dạng .xlsx dễ mở lại."""
    if side not in ("a", "b"):
        raise HTTPException(400, "side phải là 'a' hoặc 'b'")

    def _work() -> tuple[bytes, dict]:
        detail = _doc_lich_su(db, history_id)
        records = detail["raw_a_records"] if side == "a" else detail["raw_b_records"]
        return _xuat_tu_ban_ghi(tach.xuat_du_lieu_tho, len(records), records=records), detail

    content, detail = await run_heavy(_work)

    is_den = detail["recon_type"] == "den"
    side_name = ("SAA" if is_den else "QL") if side == "a" else ("QL" if is_den else "SAA")
    fname = f"DuLieu_{side_name}_{detail['recon_type'].upper()}_lichsu_{history_id}.xlsx"
    return _tai_ve(content, {"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/history/{history_id}")
async def get_history_detail(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    detail = await run_heavy(get_recon_detail, db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")
    return detail


@router.get("/history/{history_id}/export-summary")
async def export_summary_from_history(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    """Sinh Excel Tổng hợp TỪ ĐÚNG snapshot đã lưu tại thời điểm đối chiếu
    (không tính lại từ raw_a/raw_b) — đảm bảo đúng y hệt dữ liệu audit."""
    def _work() -> tuple[bytes, str]:
        detail = _doc_lich_su(db, history_id)
        return _xuat_tu_ban_ghi(
            tach.xuat_tong_hop_lich_su, len(detail["summary_records"]),
            recon_type=detail["recon_type"], summary_records=detail["summary_records"],
        ), detail["recon_type"]

    content, recon_type = await run_heavy(_work)
    fname = f"Tong_hop_doi_chieu_Dien{recon_type.upper()}_lichsu_{history_id}.xlsx"
    return _tai_ve(content, {"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/history/{history_id}/export-diff")
async def export_diff_from_history(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    """Sinh Excel Chi tiết lệch TỪ ĐÚNG snapshot đã lưu tại thời điểm đối
    chiếu (không tính lại) — đảm bảo đúng y hệt dữ liệu audit."""
    def _work() -> tuple[bytes, str]:
        detail = _doc_lich_su(db, history_id)
        so_dong = sum(len(detail[k] or []) for k in
                      ("diff_a_only_records", "diff_b_only_records", "di_not_ack_records"))
        return _xuat_tu_ban_ghi(
            tach.xuat_chi_tiet_lich_su, so_dong, recon_type=detail["recon_type"],
            only_a=detail["diff_a_only_records"], only_b=detail["diff_b_only_records"],
            di_not_ack=detail["di_not_ack_records"],
        ), detail["recon_type"]

    content, recon_type = await run_heavy(_work)
    fname = f"Chi_tiet_lech_doi_chieu_Dien{recon_type.upper()}_lichsu_{history_id}.xlsx"
    return _tai_ve(content, {"Content-Disposition": f'attachment; filename="{fname}"'})
