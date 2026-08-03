# -*- coding: utf-8 -*-
"""
backend/api/swift_recon.py
---------------------------
API đối chiếu điện SWIFT (SAA <-> Màn hình quản lý điện) — Phòng Swift.

Logic đối chiếu thuần lấy NGUYÊN từ parsers.py / reconcile.py / exporters.py
gốc (không sửa logic) — xem backend/services/swift_recon/.

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
from backend.core.concurrency import run_heavy
from backend.core.deps import require_feature
from backend.schemas.swift_recon import ExportFilteredIn
from backend.services.swift_recon import exporters, parsers, reconcile
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


def _to_records(df: pd.DataFrame) -> list:
    """DataFrame -> list[dict] JSON-safe (NaN/NaT -> None)."""
    return df.where(pd.notnull(df), None).to_dict(orient="records")


# ── Kiểm tra & đọc thử 1 file ngay khi vừa chọn (trước khi bấm Đối chiếu) ───
# Khớp UX bản gốc: mỗi ô upload báo NGAY ✅/❌ + số dòng đọc được, KHÔNG đợi
# đến lúc bấm nút đối chiếu mới biết file có đọc được hay không.
@router.post("/parse-preview")
async def parse_preview(
    file: UploadFile = File(...),
    source: str = Form("SAA_DEN"),  # SAA_DEN | QL_DEN | QL_DI | SAA_DI
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    if source not in ("SAA_DEN", "QL_DEN", "QL_DI", "SAA_DI"):
        raise HTTPException(400, "source không hợp lệ")
    try:
        df = await run_heavy(_load, file, source)
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))
    return {"filename": file.filename, "rows": len(df)}


# ── Đối chiếu điện đến ───────────────────────────────────────────────────────
@router.post("/reconcile-den")
async def reconcile_den(
    saa_file: UploadFile = File(...),
    ql_file: UploadFile = File(...),
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    # Toàn bộ phần nặng (đọc file, giải nén, pandas, lưu lịch sử) chạy trong
    # threadpool — chạy thẳng ở đây sẽ giữ event loop và làm treo cả hệ thống.
    def _work() -> dict:
        df_saa = _load(saa_file, "SAA_DEN")
        df_ql = _load(ql_file, "QL_DEN")

        merged = reconcile.build_merged_view(df_saa, df_ql, "SAA", "QL")
        summary = reconcile.summarize_counts(df_saa, df_ql, "SAA", "QL")
        saa_only = reconcile.diff_only_a(df_saa, df_ql)
        ql_only = reconcile.diff_only_b(df_saa, df_ql)

        total_matched = int((merged["_status"] == "MATCHED").sum()) if len(merged) else 0
        total_diff = len(merged) - total_matched

        history_saved, history_error = True, None
        try:
            save_recon_history(
                db, recon_type="den", performed_by_id=current["id"],
                file_saa_name=saa_file.filename, file_ql_name=ql_file.filename,
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

    try:
        return await run_heavy(_work)
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


# ── Đối chiếu điện đi (đúng thứ tự QL trước, SAA sau — như bản desktop) ─────
@router.post("/reconcile-di")
async def reconcile_di(
    ql_file: UploadFile = File(...),
    saa_file: UploadFile = File(...),
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    def _work() -> dict:
        df_ql = _load(ql_file, "QL_DI")
        df_saa = _load(saa_file, "SAA_DI")

        merged = reconcile.build_merged_view(df_ql, df_saa, "QL", "SAA", ack_check=ACK_CHECK_DI)
        summary = reconcile.summarize_counts(df_ql, df_saa, "QL", "SAA")
        ql_only = reconcile.diff_only_a(df_ql, df_saa)
        saa_only = reconcile.diff_only_b(df_ql, df_saa)
        di_not_ack = reconcile.extract_matched_not_ack(merged, "QL", "SAA")

        total_matched = int((merged["_status"] == "MATCHED").sum()) if len(merged) else 0
        total_diff = len(merged) - total_matched

        history_saved, history_error = True, None
        try:
            save_recon_history(
                db, recon_type="di", performed_by_id=current["id"],
                file_saa_name=saa_file.filename, file_ql_name=ql_file.filename,
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

    try:
        return await run_heavy(_work)
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


# ── Xuất Excel (nhận lại đúng những file frontend đã có sẵn trong state,
#    không bắt người dùng chọn file lần 2 — xem frontend/pages/swift_recon.py) ──
@router.post("/export-summary")
async def export_summary(
    saa_den: UploadFile | None = File(None),
    ql_den: UploadFile | None = File(None),
    ql_di: UploadFile | None = File(None),
    saa_di: UploadFile | None = File(None),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    def _work() -> bytes:
        summary_den = summary_di = None
        if saa_den and ql_den:
            df_saa_den = _load(saa_den, "SAA_DEN")
            df_ql_den = _load(ql_den, "QL_DEN")
            summary_den = reconcile.summarize_counts(df_saa_den, df_ql_den, "SAA", "QL")

        if ql_di and saa_di:
            df_ql_di = _load(ql_di, "QL_DI")
            df_saa_di = _load(saa_di, "SAA_DI")
            summary_di = reconcile.summarize_counts(df_ql_di, df_saa_di, "QL", "SAA")

        if summary_den is None and summary_di is None:
            raise HTTPException(400, "Chưa có dữ liệu đối chiếu nào để xuất")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
            out_path = out.name
        exporters.export_summary_excel(out_path, summary_den, summary_di)
        with open(out_path, "rb") as f:
            content = f.read()
        os.remove(out_path)
        return content

    try:
        content = await run_heavy(_work)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="Tong_hop_doi_chieu_dien.xlsx"'},
        )
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


@router.post("/export-diff")
async def export_diff(
    saa_den: UploadFile | None = File(None),
    ql_den: UploadFile | None = File(None),
    ql_di: UploadFile | None = File(None),
    saa_di: UploadFile | None = File(None),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    def _work() -> bytes:
        saa_den_only = ql_den_only = ql_di_only = saa_di_only = di_not_ack = None
        if saa_den and ql_den:
            df_saa_den = _load(saa_den, "SAA_DEN")
            df_ql_den = _load(ql_den, "QL_DEN")
            saa_den_only = reconcile.diff_only_a(df_saa_den, df_ql_den)
            ql_den_only = reconcile.diff_only_b(df_saa_den, df_ql_den)

        if ql_di and saa_di:
            df_ql_di = _load(ql_di, "QL_DI")
            df_saa_di = _load(saa_di, "SAA_DI")
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
        return content

    try:
        content = await run_heavy(_work)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="Chi_tiet_lech_doi_chieu_dien.xlsx"'},
        )
    except parsers.UnknownFileFormat as e:
        raise HTTPException(422, str(e))


# ── Xuất đúng các bản ghi đang lọc trên giao diện (không phải toàn bộ) ──────
@router.post("/export-filtered")
async def export_filtered(
    payload: ExportFilteredIn,
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    if not payload.records:
        raise HTTPException(400, "Không có bản ghi nào để xuất")

    def _work() -> bytes:
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
        return content

    content = await run_heavy(_work)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{payload.filename}"'},
    )


# ── Lịch sử đối chiếu (đọc từ bảng swift_recon_history) ─────────────────────
@router.get("/history")
async def get_history(
    limit: int = 100,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    return await run_heavy(list_recon_history, db, limit)


@router.get("/history/{history_id}/export-raw")
async def export_raw_from_history(
    history_id: int,
    side: str = "a",  # "a" hoặc "b"
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    """Tải lại dữ liệu ĐÃ IMPORT (không phải file .xls gốc byte-for-byte —
    xem ghi chú ở cuối file — mà là đúng các dòng/cột đã đọc được từ file đó
    tại thời điểm đối chiếu), dưới dạng .xlsx dễ mở lại."""
    if side not in ("a", "b"):
        raise HTTPException(400, "side phải là 'a' hoặc 'b'")

    def _work() -> tuple[bytes, dict]:
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
        return content, detail

    content, detail = await run_heavy(_work)

    is_den = detail["recon_type"] == "den"
    side_name = ("SAA" if is_den else "QL") if side == "a" else ("QL" if is_den else "SAA")
    fname = f"DuLieu_{side_name}_{detail['recon_type'].upper()}_lichsu_{history_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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
        return content, detail["recon_type"]

    content, recon_type = await run_heavy(_work)
    fname = f"Tong_hop_doi_chieu_Dien{recon_type.upper()}_lichsu_{history_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/history/{history_id}/export-diff")
async def export_diff_from_history(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.swift_recon")),
):
    """Sinh Excel Chi tiết lệch TỪ ĐÚNG snapshot đã lưu tại thời điểm đối
    chiếu (không tính lại) — đảm bảo đúng y hệt dữ liệu audit."""
    def _work() -> tuple[bytes, str]:
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
        return content, detail["recon_type"]

    content, recon_type = await run_heavy(_work)
    fname = f"Chi_tiet_lech_doi_chieu_Dien{recon_type.upper()}_lichsu_{history_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
