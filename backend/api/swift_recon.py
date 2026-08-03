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

CẬP NHẬT (đợt 3 — sửa theo review PR #13, quan trọng, đọc trước khi sửa
tiếp file này):
  - TOÀN BỘ endpoint trong file này khai báo `def` (KHÔNG `async def`).
    Backend chạy 1 tiến trình/1 luồng (uvicorn không kèm --workers), và mọi
    thao tác bên trong (đọc .xls, openpyxl) đều là code CHẶN (blocking) —
    không có chỗ nào await thật sự. Nếu khai `async def`, FastAPI chạy thẳng
    trên event loop duy nhất đó, làm ĐÓNG BĂNG TOÀN BỘ hệ thống (mọi trang
    khác: đăng nhập, dashboard, nghỉ phép...) trong lúc xử lý — đã đo được
    tới 10-12 giây/lần xuất Excel theo biểu mẫu trước khi sửa. Khai `def`
    (đồng bộ) để FastAPI tự đẩy sang thread pool phụ, event loop chính vẫn
    rảnh phục vụ request khác. KHÔNG đổi lại thành `async def` trừ khi thực
    sự thêm `await` một thao tác I/O bất đồng bộ thật bên trong.
  - `get_db()` (backend/database.py) đã tạo connection mới mỗi request với
    `check_same_thread=False` nên chạy trong thread pool an toàn, không cần
    sửa gì thêm ở đó.

Đây là router MỚI của bạn — file này bạn tự quản lý, không cần ai duyệt
logic bên trong. Chỉ có 2 việc còn lại cần Người 1 duyệt riêng:
  1. Đăng ký router này vào backend/api/registry.py
  2. Thêm bảng swift_recon_history vào backend/db/migrations.py
(xem SNIPPETS_TO_PASTE.md)
"""
from __future__ import annotations

import os
import tempfile

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.database import get_db
from backend.core.deps import require_feature
from backend.schemas.swift_recon import ExportFilteredIn
from backend.services.swift_recon import exporters, parsers, reconcile, template_exporters
from backend.services.swift_recon.history_service import (
    get_recon_detail,
    list_recon_history,
    save_recon_history,
)
from backend.services.swift_recon.upload_utils import save_upload_to_path

router = APIRouter(prefix="/api/swift-recon", tags=["swift-recon"])

# Giống hệt ACK_CHECK_DI trong bản gốc — KHÔNG đổi logic đối chiếu.
ACK_CHECK_DI = {
    "a_field": "ACK/NAK", "a_ok_values": {"ACK"},
    "b_field": "Netw. Status", "b_ok_values": {"Network Ack"},
}


# ── Helpers ────────────────────────────────────────────────────────────────
def _load(upload: UploadFile, source: str) -> pd.DataFrame:
    """Lưu file (giải nén nếu là .zip) rồi parse đúng theo `source`
    ('SAA_DEN'|'QL_DEN'|'QL_DI'|'SAA_DI'). Luôn dọn file/thư mục tạm."""
    path, cleanup = save_upload_to_path(upload)
    try:
        return parsers.load_file(path, source)
    finally:
        cleanup()


def _load_many(uploads: list[UploadFile], source: str) -> pd.DataFrame:
    """Parse TỪNG file rồi gộp lại thành 1 DataFrame duy nhất — dùng khi 1
    bên (thường là SAA) phải xuất nhiều lần trong ngày nên có nhiều file.

    Mỗi file được parse riêng bằng ĐÚNG hàm load_file() hiện có (không sửa
    parsers.py), lỗi ở file nào báo rõ tên file đó. Gộp bằng pd.concat đơn
    giản — nếu 2 file vô tình trùng nhau (cùng khoá `_key`), bản ghi trùng
    vẫn được GIỮ NGUYÊN CẢ HAI (không tự động loại trùng), vì:
      - Có thể 2 điện khác nhau nhưng vô tình trùng 6/16 ký tự cuối của khoá
        (hiếm nhưng có thể xảy ra) — tự loại có thể làm mất điện thật.
      - Nếu người dùng lỡ tải trùng 1 file 2 lần, tổng số dòng sẽ tăng gấp
        đôi RÕ RÀNG trên giao diện (mỗi ô upload hiện đúng số dòng từng
        file + tổng cộng) nên dễ phát hiện để tự xoá bớt, thay vì âm thầm
        loại bỏ sai bản ghi hợp lệ.
    """
    if not uploads:
        raise parsers.UnknownFileFormat("Chưa chọn file nào.")
    frames = []
    for up in uploads:
        try:
            frames.append(_load(up, source))
        except parsers.UnknownFileFormat as e:
            raise parsers.UnknownFileFormat(f"[{up.filename}] {e}")
    return pd.concat(frames, ignore_index=True)


def _to_records(df: pd.DataFrame) -> list:
    """DataFrame -> list[dict] JSON-safe (NaN/NaT -> None)."""
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def _join_names(uploads: list[UploadFile]) -> str:
    return "; ".join(u.filename for u in uploads)


def _key_match_summary(df_a: pd.DataFrame, df_b: pd.DataFrame, label_a: str, label_b: str) -> pd.DataFrame:
    """Tổng hợp số lượng điện theo từng loại điện — cột 'Chênh lệch' tính
    bằng SỐ BẢN GHI THỰC SỰ KHÔNG KHỚP KHOÁ (ONLY_A + ONLY_B theo _msg_type,
    lấy từ chính reconcile.match_by_key() — ĐÚNG cơ chế khoá dùng ở tab
    "Kết quả đối chiếu" và file "Chi tiết lệch"), KHÔNG PHẢI hiệu số lượng
    thô (count_a - count_b) như reconcile.summarize_counts() gốc.

    Lý do đổi: hiệu số lượng thô có thể che giấu sai lệch thật — ví dụ 1 loại
    điện có 5 bản ghi ở mỗi bên nhưng KHÔNG PHẢI 5 giao dịch trùng khoá (5
    giao dịch hoàn toàn khác nhau ở 2 bên) vẫn báo "Chênh lệch = 0" nếu tính
    theo số lượng — trong khi tính theo khoá sẽ báo đúng 10 bản ghi lệch.
    Không sửa reconcile.py gốc — chỉ dùng lại match_by_key() đã có sẵn."""
    count_a = df_a.groupby("_msg_type").size().rename(label_a)
    count_b = df_b.groupby("_msg_type").size().rename(label_b)
    merged = pd.concat([count_a, count_b], axis=1).fillna(0).astype(int)
    merged = merged.reset_index().rename(columns={"_msg_type": "Loại điện"})

    mr = reconcile.match_by_key(df_a, df_b)
    only_a_types = df_a.loc[mr.only_a, "_msg_type"] if len(mr.only_a) else pd.Series(dtype=object)
    only_b_types = df_b.loc[mr.only_b, "_msg_type"] if len(mr.only_b) else pd.Series(dtype=object)
    diff_counts = pd.concat([only_a_types, only_b_types]).value_counts()
    merged["Chênh lệch"] = merged["Loại điện"].map(diff_counts).fillna(0).astype(int)
    merged = merged.sort_values(by="Loại điện").reset_index(drop=True)

    total_row = {
        "Loại điện": "TỔNG",
        label_a: int(merged[label_a].sum()),
        label_b: int(merged[label_b].sum()),
        "Chênh lệch": int(merged["Chênh lệch"].sum()),
    }
    return pd.concat([merged, pd.DataFrame([total_row])], ignore_index=True)


# ── Kiểm tra & đọc thử 1 file ngay khi vừa chọn (trước khi bấm Đối chiếu) ───
# Khớp UX bản gốc: mỗi ô upload báo NGAY ✅/❌ + số dòng đọc được, KHÔNG đợi
# đến lúc bấm nút đối chiếu mới biết file có đọc được hay không. Giữ NGUYÊN
# dạng single-file — kiểm tra từng file NGAY LÚC chọn, dù sau này nhiều file
# được gộp lại (mỗi file vẫn cần biết ✅/❌ riêng của chính nó).
@router.post("/parse-preview")
def parse_preview(
    file: UploadFile = File(...),
    source: str = Form("SAA_DEN"),  # SAA_DEN | QL_DEN | QL_DI | SAA_DI
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    if source not in ("SAA_DEN", "QL_DEN", "QL_DI", "SAA_DI"):
        raise HTTPException(400, "source không hợp lệ")
    try:
        df = _load(file, source)
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))
    return {"filename": file.filename, "rows": len(df)}


# ── Đối chiếu điện đến (mỗi bên có thể gồm NHIỀU file) ──────────────────────
@router.post("/reconcile-den")
def reconcile_den(
    saa_files: list[UploadFile] = File(...),
    ql_files: list[UploadFile] = File(...),
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    try:
        df_saa = _load_many(saa_files, "SAA_DEN")
        df_ql = _load_many(ql_files, "QL_DEN")
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))

    merged = reconcile.build_merged_view(df_saa, df_ql, "SAA", "QL")
    summary = _key_match_summary(df_saa, df_ql, "SAA", "QL")
    saa_only = reconcile.diff_only_a(df_saa, df_ql)
    ql_only = reconcile.diff_only_b(df_saa, df_ql)

    total_matched = int((merged["_status"] == "MATCHED").sum()) if len(merged) else 0
    total_diff = len(merged) - total_matched

    history_saved, history_error = True, None
    try:
        save_recon_history(
            db, recon_type="den", performed_by_id=current["id"],
            file_saa_name=_join_names(saa_files), file_ql_name=_join_names(ql_files),
            total_saa=len(df_saa), total_ql=len(df_ql),
            total_matched=total_matched, total_diff=total_diff,
            merged_records=_to_records(merged),
            raw_a_records=_to_records(df_saa),
            raw_b_records=_to_records(df_ql),
            summary_records=_to_records(summary),
            diff_a_only_records=_to_records(saa_only),
            diff_b_only_records=_to_records(ql_only),
        )
    except Exception as e:  # noqa: BLE001 — không để lỗi lưu lịch sử chặn mất kết quả đối chiếu
        history_saved, history_error = False, str(e)

    return {
        "summary": _to_records(summary),
        "records": _to_records(merged),
        "total_a": len(df_saa), "total_b": len(df_ql),
        "total_matched": total_matched, "total_diff": total_diff,
        "history_saved": history_saved, "history_error": history_error,
    }


# ── Đối chiếu điện đi (đúng thứ tự QL trước, SAA sau — như bản desktop) ─────
@router.post("/reconcile-di")
def reconcile_di(
    ql_files: list[UploadFile] = File(...),
    saa_files: list[UploadFile] = File(...),
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    try:
        df_ql = _load_many(ql_files, "QL_DI")
        df_saa = _load_many(saa_files, "SAA_DI")
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))

    merged = reconcile.build_merged_view(df_ql, df_saa, "QL", "SAA", ack_check=ACK_CHECK_DI)
    summary = _key_match_summary(df_ql, df_saa, "QL", "SAA")
    ql_only = reconcile.diff_only_a(df_ql, df_saa)
    saa_only = reconcile.diff_only_b(df_ql, df_saa)
    di_not_ack = reconcile.extract_matched_not_ack(merged, "QL", "SAA")

    total_matched = int((merged["_status"] == "MATCHED").sum()) if len(merged) else 0
    total_diff = len(merged) - total_matched

    history_saved, history_error = True, None
    try:
        save_recon_history(
            db, recon_type="di", performed_by_id=current["id"],
            file_saa_name=_join_names(saa_files), file_ql_name=_join_names(ql_files),
            total_saa=len(df_saa), total_ql=len(df_ql),
            total_matched=total_matched, total_diff=total_diff,
            merged_records=_to_records(merged),
            raw_a_records=_to_records(df_ql),
            raw_b_records=_to_records(df_saa),
            summary_records=_to_records(summary),
            diff_a_only_records=_to_records(ql_only),
            diff_b_only_records=_to_records(saa_only),
            di_not_ack_records=_to_records(di_not_ack),
        )
    except Exception as e:  # noqa: BLE001
        history_saved, history_error = False, str(e)

    return {
        "summary": _to_records(summary),
        "records": _to_records(merged),
        "total_a": len(df_ql), "total_b": len(df_saa),
        "total_matched": total_matched, "total_diff": total_diff,
        "history_saved": history_saved, "history_error": history_error,
    }


# ── Xuất Excel (nhận lại đúng những file frontend đã có sẵn trong state,
#    không bắt người dùng chọn file lần 2 — xem frontend/pages/swift_recon.py) ──
@router.post("/export-summary")
def export_summary(
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
    summary_den = summary_di = None
    try:
        if saa_den and ql_den:
            df_saa_den = _load_many(saa_den, "SAA_DEN")
            df_ql_den = _load_many(ql_den, "QL_DEN")
            summary_den = _key_match_summary(df_saa_den, df_ql_den, "SAA", "QL")

        if ql_di and saa_di:
            df_ql_di = _load_many(ql_di, "QL_DI")
            df_saa_di = _load_many(saa_di, "SAA_DI")
            summary_di = _key_match_summary(df_ql_di, df_saa_di, "QL", "SAA")

        if summary_den is None and summary_di is None:
            raise HTTPException(400, "Chưa có dữ liệu đối chiếu nào để xuất")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
            out_path = out.name
        exporters.export_summary_excel(out_path, summary_den, summary_di)
        with open(out_path, "rb") as f:
            content = f.read()
        os.remove(out_path)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="Tong_hop_doi_chieu_dien.xlsx"'},
        )
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


@router.post("/export-diff")
def export_diff(
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
    saa_den_only = ql_den_only = ql_di_only = saa_di_only = di_not_ack = None
    try:
        if saa_den and ql_den:
            df_saa_den = _load_many(saa_den, "SAA_DEN")
            df_ql_den = _load_many(ql_den, "QL_DEN")
            saa_den_only = reconcile.diff_only_a(df_saa_den, df_ql_den)
            ql_den_only = reconcile.diff_only_b(df_saa_den, df_ql_den)

        if ql_di and saa_di:
            df_ql_di = _load_many(ql_di, "QL_DI")
            df_saa_di = _load_many(saa_di, "SAA_DI")
            ql_di_only = reconcile.diff_only_a(df_ql_di, df_saa_di)
            saa_di_only = reconcile.diff_only_b(df_ql_di, df_saa_di)
            merged_di = reconcile.build_merged_view(df_ql_di, df_saa_di, "QL", "SAA", ack_check=ACK_CHECK_DI)
            di_not_ack = reconcile.extract_matched_not_ack(merged_di, "QL", "SAA")

        if all(x is None for x in (saa_den_only, ql_den_only, ql_di_only, saa_di_only)):
            raise HTTPException(400, "Chưa có dữ liệu đối chiếu nào để xuất")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
            out_path = out.name
        exporters.export_diff_excel(
            out_path, saa_den_only, ql_den_only, ql_di_only, saa_di_only, di_not_ack,
        )
        with open(out_path, "rb") as f:
            content = f.read()
        os.remove(out_path)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="Chi_tiet_lech_doi_chieu_dien.xlsx"'},
        )
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


# ── Xuất Excel THEO BIỂU MẪU (Mẫu 04 / Mẫu 05) — xem cảnh báo giả định ở
#    đầu file template_exporters.py trước khi dùng cho báo cáo chính thức ──
@router.post("/export-summary-template")
def export_summary_template(
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
        if saa_den and ql_den:
            direction, df_a, source_a, df_b, source_b = (
                "den", _load_many(saa_den, "SAA_DEN"), "SAA_DEN", _load_many(ql_den, "QL_DEN"), "QL_DEN",
            )
        elif ql_di and saa_di:
            direction, df_a, source_a, df_b, source_b = (
                "di", _load_many(ql_di, "QL_DI"), "QL_DI", _load_many(saa_di, "SAA_DI"), "SAA_DI",
            )
        else:
            raise HTTPException(400, "Chưa có dữ liệu đối chiếu nào để xuất")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
            out_path = out.name
        template_exporters.export_summary_template(out_path, direction, df_a, source_a, df_b, source_b)
        with open(out_path, "rb") as f:
            content = f.read()
        os.remove(out_path)
        fname = f"Tong_hop_theo_bieu_mau_Dien{direction.upper()}.xlsx"
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except HTTPException:
        raise
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001 — luôn trả JSON lỗi rõ ràng, không để lộ traceback dạng non-JSON
        raise HTTPException(500, f"Lỗi khi xuất Excel Tổng hợp theo biểu mẫu: {e}")


@router.post("/export-diff-template")
def export_diff_template(
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
        if saa_den and ql_den:
            direction, df_a, source_a, df_b, source_b = (
                "den", _load_many(saa_den, "SAA_DEN"), "SAA_DEN", _load_many(ql_den, "QL_DEN"), "QL_DEN",
            )
        elif ql_di and saa_di:
            direction, df_a, source_a, df_b, source_b = (
                "di", _load_many(ql_di, "QL_DI"), "QL_DI", _load_many(saa_di, "SAA_DI"), "SAA_DI",
            )
        else:
            raise HTTPException(400, "Chưa có dữ liệu đối chiếu nào để xuất")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
            out_path = out.name
        template_exporters.export_diff_template(out_path, direction, df_a, source_a, df_b, source_b)
        with open(out_path, "rb") as f:
            content = f.read()
        os.remove(out_path)
        fname = f"Chi_tiet_lech_theo_bieu_mau_Dien{direction.upper()}.xlsx"
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except HTTPException:
        raise
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001 — luôn trả JSON lỗi rõ ràng, không để lộ traceback dạng non-JSON
        raise HTTPException(500, f"Lỗi khi xuất Excel Chi tiết lệch theo biểu mẫu: {e}")


# ── Xuất đúng các bản ghi đang lọc trên giao diện (không phải toàn bộ) ──────
@router.post("/export-filtered")
def export_filtered(
    payload: ExportFilteredIn,
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    if not payload.records:
        raise HTTPException(400, "Không có bản ghi nào để xuất")
    df = pd.DataFrame(payload.records)
    cols = [c for c in payload.columns if c in df.columns]
    if cols:
        df = df[cols]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    df.to_excel(out_path, index=False, sheet_name="BanGhiDangLoc")
    with open(out_path, "rb") as f:
        content = f.read()
    os.remove(out_path)

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
    )


# ── Lịch sử đối chiếu (đọc từ bảng swift_recon_history) ─────────────────────
@router.get("/history")
def get_history(
    limit: int = 100,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    return list_recon_history(db, limit)


@router.get("/history/{history_id}/export-raw")
def export_raw_from_history(
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
    detail = get_recon_detail(db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")

    records = detail["raw_a_records"] if side == "a" else detail["raw_b_records"]
    df = pd.DataFrame(records)
    df = df[[c for c in df.columns if not c.startswith("_")]]  # bỏ cột nội bộ (_key, _msg_type...)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    df.to_excel(out_path, index=False, sheet_name="DuLieuDaImport")
    with open(out_path, "rb") as f:
        content = f.read()
    os.remove(out_path)

    is_den = detail["recon_type"] == "den"
    side_name = ("SAA" if is_den else "QL") if side == "a" else ("QL" if is_den else "SAA")
    fname = f"DuLieu_{side_name}_{detail['recon_type'].upper()}_lichsu_{history_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/history/{history_id}")
def get_history_detail(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    detail = get_recon_detail(db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")
    return detail


@router.get("/history/{history_id}/export-summary")
def export_summary_from_history(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    """Sinh Excel Tổng hợp TỪ ĐÚNG snapshot đã lưu tại thời điểm đối chiếu
    (không tính lại từ raw_a/raw_b) — đảm bảo đúng y hệt dữ liệu audit."""
    detail = get_recon_detail(db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")
    summary_df = pd.DataFrame(detail["summary_records"])

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    exporters.export_summary_excel(
        out_path,
        summary_den=summary_df if detail["recon_type"] == "den" else None,
        summary_di=summary_df if detail["recon_type"] == "di" else None,
    )
    with open(out_path, "rb") as f:
        content = f.read()
    os.remove(out_path)
    fname = f"Tong_hop_doi_chieu_Dien{detail['recon_type'].upper()}_lichsu_{history_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/history/{history_id}/export-diff")
def export_diff_from_history(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    """Sinh Excel Chi tiết lệch TỪ ĐÚNG snapshot đã lưu tại thời điểm đối
    chiếu (không tính lại) — đảm bảo đúng y hệt dữ liệu audit."""
    detail = get_recon_detail(db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")

    only_a = pd.DataFrame(detail["diff_a_only_records"])
    only_b = pd.DataFrame(detail["diff_b_only_records"])
    di_not_ack = pd.DataFrame(detail["di_not_ack_records"]) if detail["di_not_ack_records"] is not None else None

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    if detail["recon_type"] == "den":
        exporters.export_diff_excel(
            out_path, saa_den_only=only_a, ql_den_only=only_b,
            ql_di_only=None, saa_di_only=None, di_matched_not_ack=None,
        )
    else:
        exporters.export_diff_excel(
            out_path, saa_den_only=None, ql_den_only=None,
            ql_di_only=only_a, saa_di_only=only_b, di_matched_not_ack=di_not_ack,
        )
    with open(out_path, "rb") as f:
        content = f.read()
    os.remove(out_path)
    fname = f"Chi_tiet_lech_doi_chieu_Dien{detail['recon_type'].upper()}_lichsu_{history_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
