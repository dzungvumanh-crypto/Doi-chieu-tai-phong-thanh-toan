"""Phần NẶNG của SWIFT recon — chạy ở tiến trình riêng qua `chay_tach()`.

Đọc file SAA/Quản lý điện, đối chiếu, sinh Excel đều là pandas/openpyxl/XML thuần Python —
chạy trong tiến trình web là giữ GIL, request khác đứng chờ (card 150, 152). API
(`backend/api/swift_recon.py`) giữ phần nhẹ: ghi file tải lên ra đĩa, đọc/ghi lịch sử
trong CSDL, kiểm tra 400/404 — rồi gọi các hàm ở đây.

Logic chuyển NGUYÊN VĂN từ API cũ, chỉ đổi nguồn vào: đường dẫn file (tiến trình con
không nhận được `UploadFile`) và danh sách bản ghi lịch sử (con không mở CSDL).
Mọi hàm công khai nhận `log_callback`, `cancel_event` theo hợp đồng của `chay_tach`.
"""
from __future__ import annotations

import os
import tempfile

import pandas as pd

from backend.services.swift_recon import exporters, parsers, reconcile, template_exporters

# Giống hệt ACK_CHECK_DI trong bản gốc — KHÔNG đổi logic đối chiếu.
ACK_CHECK_DI = {
    "a_field": "ACK/NAK", "a_ok_values": {"ACK"},
    "b_field": "Netw. Status", "b_ok_values": {"Network Ack"},
}

# (tên file người dùng thấy, đường dẫn trên đĩa)
Tep = list[tuple[str, str]]


# ── Helper ──

def _xuat_xlsx(ghi) -> bytes:
    """Chạy `ghi(path)` để sinh Excel ra file tạm, trả bytes, LUÔN xoá file tạm.

    try/finally chứ không phải `os.remove()` đặt sau lệnh ghi: hàm ghi ném lỗi
    (dữ liệu bất thường, đĩa đầy, openpyxl vỡ) là file .xlsx nằm lại %TEMP%
    vĩnh viễn — mỗi lượt xuất lỗi một file, không tiến trình nào dọn. Cùng lý
    do đã ghi ở `backend/api/doi_soat_citad.py::_build_doisoat_xlsx`.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    try:
        ghi(out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def _doc_nhieu(tep: Tep, source: str) -> pd.DataFrame:
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
    if not tep:
        raise parsers.UnknownFileFormat("Chưa chọn file nào.")
    frames = []
    for ten, duong_dan in tep:
        try:
            frames.append(parsers.load_file(duong_dan, source))
        except parsers.UnknownFileFormat as e:
            raise parsers.UnknownFileFormat(f"[{ten}] {e}")
    return pd.concat(frames, ignore_index=True)


def _to_records(df: pd.DataFrame) -> list:
    """DataFrame -> list[dict] JSON-safe (NaN/NaT -> None)."""
    return df.where(pd.notnull(df), None).to_dict(orient="records")


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


# ── Điểm vào của chay_tach — đọc thử, đối chiếu ──

def xem_truoc(duong_dan: str, source: str, log_callback, cancel_event) -> int:
    """Số dòng đọc được từ 1 file — kiểm tra ngay khi người dùng vừa chọn file. API gọi
    thẳng trong `run_heavy` (không qua `chay_tach`) — việc nhỏ, xem `parse_preview`."""
    return len(parsers.load_file(duong_dan, source))


def doi_chieu(chieu: str, tep_a: Tep, tep_b: Tep, log_callback, cancel_event) -> dict:
    """Đối chiếu 1 chiều. ĐẾN: A = SAA, B = QL. ĐI: A = QL, B = SAA (đúng thứ tự QL trước,
    SAA sau như bản desktop) kèm kiểm Ack.

    Trả phần API trả thẳng cho frontend + `luu_lich_su` (bản ghi cho bảng lịch sử — API
    ghi CSDL, con không mở CSDL)."""
    if chieu == "den":
        df_a, df_b = _doc_nhieu(tep_a, "SAA_DEN"), _doc_nhieu(tep_b, "QL_DEN")
        label_a, label_b, ack = "SAA", "QL", None
    else:
        df_a, df_b = _doc_nhieu(tep_a, "QL_DI"), _doc_nhieu(tep_b, "SAA_DI")
        label_a, label_b, ack = "QL", "SAA", ACK_CHECK_DI

    merged = reconcile.build_merged_view(df_a, df_b, label_a, label_b, ack_check=ack)
    summary = _key_match_summary(df_a, df_b, label_a, label_b)
    only_a = reconcile.diff_only_a(df_a, df_b)
    only_b = reconcile.diff_only_b(df_a, df_b)
    di_not_ack = reconcile.extract_matched_not_ack(merged, "QL", "SAA") if chieu == "di" else None

    total_matched = int((merged["_status"] == "MATCHED").sum()) if len(merged) else 0
    total_diff = len(merged) - total_matched
    records, summary_records = _to_records(merged), _to_records(summary)

    lich_su = dict(
        total_saa=len(df_a) if chieu == "den" else len(df_b),
        total_ql=len(df_b) if chieu == "den" else len(df_a),
        total_matched=total_matched, total_diff=total_diff,
        merged_records=records,
        raw_a_records=_to_records(df_a),
        raw_b_records=_to_records(df_b),
        summary_records=summary_records,
        diff_a_only_records=_to_records(only_a),
        diff_b_only_records=_to_records(only_b),
    )
    if di_not_ack is not None:
        lich_su["di_not_ack_records"] = _to_records(di_not_ack)

    return {
        "summary": summary_records,
        "records": records,
        "total_a": len(df_a), "total_b": len(df_b),
        "total_matched": total_matched, "total_diff": total_diff,
        "luu_lich_su": lich_su,
    }


# ── Điểm vào của chay_tach — xuất Excel từ file tải lên ──

def xuat_tong_hop(tep: dict[str, Tep], log_callback, cancel_event) -> bytes:
    """`tep` có các khoá saa_den/ql_den/ql_di/saa_di (thiếu = không gửi). API đã chặn 400
    khi không đủ cặp nào — ở đây chỉ còn đọc + ghi."""
    summary_den = summary_di = None
    if tep.get("saa_den") and tep.get("ql_den"):
        summary_den = _key_match_summary(
            _doc_nhieu(tep["saa_den"], "SAA_DEN"), _doc_nhieu(tep["ql_den"], "QL_DEN"), "SAA", "QL")
    if tep.get("ql_di") and tep.get("saa_di"):
        summary_di = _key_match_summary(
            _doc_nhieu(tep["ql_di"], "QL_DI"), _doc_nhieu(tep["saa_di"], "SAA_DI"), "QL", "SAA")
    return _xuat_xlsx(lambda p: exporters.export_summary_excel(p, summary_den, summary_di))


def xuat_chi_tiet(tep: dict[str, Tep], log_callback, cancel_event) -> bytes:
    saa_den_only = ql_den_only = ql_di_only = saa_di_only = di_not_ack = None
    if tep.get("saa_den") and tep.get("ql_den"):
        df_saa_den = _doc_nhieu(tep["saa_den"], "SAA_DEN")
        df_ql_den = _doc_nhieu(tep["ql_den"], "QL_DEN")
        saa_den_only = reconcile.diff_only_a(df_saa_den, df_ql_den)
        ql_den_only = reconcile.diff_only_b(df_saa_den, df_ql_den)

    if tep.get("ql_di") and tep.get("saa_di"):
        df_ql_di = _doc_nhieu(tep["ql_di"], "QL_DI")
        df_saa_di = _doc_nhieu(tep["saa_di"], "SAA_DI")
        ql_di_only = reconcile.diff_only_a(df_ql_di, df_saa_di)
        saa_di_only = reconcile.diff_only_b(df_ql_di, df_saa_di)
        merged_di = reconcile.build_merged_view(df_ql_di, df_saa_di, "QL", "SAA", ack_check=ACK_CHECK_DI)
        di_not_ack = reconcile.extract_matched_not_ack(merged_di, "QL", "SAA")

    return _xuat_xlsx(lambda p: exporters.export_diff_excel(
        p, saa_den_only, ql_den_only, ql_di_only, saa_di_only, di_not_ack,
    ))


def xuat_theo_mau(loai: str, direction: str, tep_a: Tep, source_a: str, tep_b: Tep, source_b: str,
                  log_callback, cancel_event) -> bytes:
    """Mẫu 04 (loai='tong_hop') / Mẫu 05 (loai='chi_tiet') — xem cảnh báo giả định ở đầu
    template_exporters.py."""
    df_a, df_b = _doc_nhieu(tep_a, source_a), _doc_nhieu(tep_b, source_b)
    ham = (template_exporters.export_summary_template if loai == "tong_hop"
           else template_exporters.export_diff_template)
    return _xuat_xlsx(lambda p: ham(p, direction, df_a, source_a, df_b, source_b))


def xuat_ban_ghi(records: list, columns: list, log_callback, cancel_event) -> bytes:
    """Xuất đúng các bản ghi đang lọc trên giao diện (không phải toàn bộ)."""
    df = pd.DataFrame(records)
    cols = [c for c in columns if c in df.columns]
    if cols:
        df = df[cols]
    return _xuat_xlsx(lambda p: df.to_excel(p, index=False, sheet_name="BanGhiDangLoc"))


# ── Điểm vào của chay_tach — xuất Excel từ snapshot lịch sử (API đã đọc CSDL) ──

def xuat_du_lieu_tho(records: list, log_callback, cancel_event) -> bytes:
    df = pd.DataFrame(records)
    df = df[[c for c in df.columns if not c.startswith("_")]]  # bỏ cột nội bộ (_key, _msg_type...)
    return _xuat_xlsx(lambda p: df.to_excel(p, index=False, sheet_name="DuLieuDaImport"))


def xuat_tong_hop_lich_su(recon_type: str, summary_records: list, log_callback, cancel_event) -> bytes:
    summary_df = pd.DataFrame(summary_records)
    return _xuat_xlsx(lambda p: exporters.export_summary_excel(
        p,
        summary_den=summary_df if recon_type == "den" else None,
        summary_di=summary_df if recon_type == "di" else None,
    ))


def xuat_chi_tiet_lich_su(recon_type: str, only_a: list, only_b: list, di_not_ack: list | None,
                          log_callback, cancel_event) -> bytes:
    df_a, df_b = pd.DataFrame(only_a), pd.DataFrame(only_b)
    df_not_ack = pd.DataFrame(di_not_ack) if di_not_ack is not None else None

    def _ghi(p):
        if recon_type == "den":
            exporters.export_diff_excel(
                p, saa_den_only=df_a, ql_den_only=df_b,
                ql_di_only=None, saa_di_only=None, di_matched_not_ack=None,
            )
        else:
            exporters.export_diff_excel(
                p, saa_den_only=None, ql_den_only=None,
                ql_di_only=df_a, saa_di_only=df_b, di_matched_not_ack=df_not_ack,
            )

    return _xuat_xlsx(_ghi)
