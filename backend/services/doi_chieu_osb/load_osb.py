"""Đọc + xử lý file OSB (chi tiết hạch toán) cho module `doi_chieu_osb`.

Tái dùng `load_osb_file()` của `doi_chieu_song_phuong_core` (import thẳng, KHÔNG chép lại) —
hàm đó đã kiểm chứng đúng sheet ("Sheet 1") + dòng header (`header=2`) + raise `ValueError` khi
sai khuôn (không tự đoán lại cấu trúc file).
"""
import numpy as np
import pandas as pd

from backend.services.ach.so_tien import doc_so_tien
from backend.services.doi_chieu_song_phuong_core.load_osb import load_osb_file

from .config import OSB_REQUIRED_COLS_BO_SUNG

_BUOC = "OSB-GL02"


def _kiem_tra_cot_bo_sung(df: pd.DataFrame, ten_file) -> None:
    missing = OSB_REQUIRED_COLS_BO_SUNG - set(df.columns)
    if missing:
        raise ValueError(
            f"File OSB '{ten_file}' thiếu cột bắt buộc cho đối chiếu OSB: "
            f"{', '.join(sorted(missing))}."
        )


def read_osb_files(paths, log_callback=None) -> pd.DataFrame:
    """Đọc N file OSB của 1 ngày (thường 2 file/ngày — 1 bản toàn "TK ghi Nợ"=<TK trung gian>,
    1 bản toàn "TK ghi Có"=<TK trung gian>), gộp lại.

    ⚠️ Dedupe CHỈ KHI TOÀN BỘ CỘT giống hệt nhau (`drop_duplicates()` không `subset`) — KHÔNG
    dedupe theo riêng "Mã giao dịch". Đã verify bằng dữ liệu thật (spike test trước khi viết
    module này): 1 "Mã giao dịch" có thể lặp lại NHIỀU LẦN hợp lệ trong cùng 1 file — điển hình
    nhất là cặp Hủy (cùng Mã giao dịch, cùng Số tiền TRÁI DẤU, nhưng "IPCAS Trace" khác nhau — 1
    chân có trace thật, chân kia trace rỗng). `drop_duplicates(subset=["Mã giao dịch"])` xoá mất 1
    chân của MỌI cặp Hủy, khiến bước đánh dấu Hủy phía sau không bao giờ thấy đủ ≥2 dòng/nhóm để
    nhận ra — 0 dòng Hủy nào được đánh dấu, và case "Chênh lệch Có" ngày 01/07/2026 bung ra 393
    dòng "chênh lệch" giả (đúng bằng số cặp Hủy bị xoá nhầm) thay vì 5 dòng thật khi so với hà
    chấm. Dedupe toàn cột không gặp vấn đề này vì 2 chân của 1 cặp Hủy luôn khác nhau ít nhất ở
    cột "IPCAS Trace"/"Số tiền"."""
    _log = log_callback or (lambda m: None)
    frames = []
    for p in paths:
        df = load_osb_file(p)
        _kiem_tra_cot_bo_sung(df, p)
        _log(f"[{_BUOC}] {p}: {len(df):,} dòng")
        frames.append(df)
    full = pd.concat(frames, ignore_index=True)
    truoc = len(full)
    full = full.drop_duplicates()
    if truoc != len(full):
        _log(f"[{_BUOC}] gộp {truoc:,} dòng -> dedupe TOÀN CỘT -> {len(full):,} dòng "
             f"(loại {truoc - len(full):,} dòng trùng thật)")
    return full


def process_osb(df: pd.DataFrame, log_callback=None) -> tuple[pd.DataFrame, int]:
    """Đánh dấu "Hủy" (nhóm theo "Mã giao dịch", ĐÚNG 2 dòng VÀ tổng Số tiền = 0 -> cả nhóm = Hủy)
    + dựng Khoá C ("IPCAS Trace" + Số tiền).

    ⚠️ Điều kiện "ĐÚNG 2 dòng" (không phải "≥2 dòng") — xác nhận trực tiếp với Hà (người chấm tay,
    tác giả note gốc) 2026-09-13: "Cặp GD được xác định là Huỷ thì luôn luôn là 1 cặp có 2 dòng.
    Nếu có nhiều hơn 2 dòng cùng chung 1 'Mã giao dịch' và tổng tiền = 0 thì sẽ KHÔNG đánh dấu các
    GD đó là Huỷ, để người chấm chấm thủ công." Nhóm >2 dòng tổng=0 CỐ Ý không vào `huy_keys` — các
    dòng đó vẫn đi tiếp vào bước khớp bình thường (không bị loại khỏi subset như dòng Hủy thật);
    nếu không tìm được cặp khớp, chúng tự nhiên hiện ra như "chênh lệch" để người chấm xử lý tay —
    KHÔNG cần thêm nhánh xử lý đặc biệt nào khác.

    Trả `(df, n_nhom_huy_qua_2)` — số nhóm >2 dòng tổng=0 (CỐ Ý không đánh dấu Hủy, không phải lỗi
    hệ thống — chỉ log để người vận hành biết có bao nhiêu nhóm cần tự chấm tay)."""
    _log = log_callback or (lambda m: None)
    df = df.copy()
    df["Mã giao dịch"] = df["Mã giao dịch"].astype(str).str.strip()
    df["IPCAS Trace"] = df["IPCAS Trace"].fillna("").astype(str).str.strip()
    df["TK ghi nợ"] = df["TK ghi nợ"].astype(str).str.strip()
    df["TK ghi có"] = df["TK ghi có"].astype(str).str.strip()
    df["SO_TIEN_NUM"] = doc_so_tien(df["Số tiền"], "osb", "Số tiền")

    grp = df.groupby("Mã giao dịch")["SO_TIEN_NUM"].agg(["sum", "count"])
    huy_keys = set(grp[(grp["count"] == 2) & (grp["sum"] == 0)].index)
    over2 = grp[(grp["count"] > 2) & (grp["sum"] == 0)]
    n_over2 = len(over2)
    if n_over2:
        _log(f"[{_BUOC}] {n_over2:,} nhóm 'Mã giao dịch' có > 2 dòng VÀ tổng Số tiền = 0 — CỐ Ý "
             f"KHÔNG đánh dấu Hủy (Hà xác nhận 2026-09-13: cặp Hủy luôn đúng 2 dòng, >2 dòng phải "
             f"để người chấm xử lý tay, không phải lỗi hệ thống): "
             f"{over2.reset_index().to_dict('records')[:10]}")

    df["LOAI_GIAO_DICH"] = np.where(df["Mã giao dịch"].isin(huy_keys), "Hủy", "")
    _log(f"[{_BUOC}] đánh dấu Hủy: {len(huy_keys):,} nhóm, "
         f"{int((df['LOAI_GIAO_DICH'] == 'Hủy').sum()):,} dòng")

    df["KHOA_C"] = df["IPCAS Trace"] + df["SO_TIEN_NUM"].astype(str)
    return df, n_over2
