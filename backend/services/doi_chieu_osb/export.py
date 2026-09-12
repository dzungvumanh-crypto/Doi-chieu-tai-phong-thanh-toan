"""Xuất kết quả đối chiếu OSB: 4 file rời (GL02-side / OSB-side x Nợ / Có), đóng gói 1 ZIP.

Số dòng chênh lệch thực tế RẤT NHỎ (vài dòng/ngày — verify dữ liệu thật 3 ngày trước khi viết
module này) nên dùng `.xlsx` cho cả 4 file (khác quy ước CSV-cho-bulk-detail của dự án — quy ước
đó áp cho bảng vài trăm nghìn dòng, không áp cho vài dòng) — giữ định dạng gần với file "hà chấm"
thủ công để người đọc dễ đối chiếu.
"""
import io
import zipfile

import pandas as pd

from .config import GL02_EXPORT_COLS

__all__ = ["build_result_zip"]

# Cột nội bộ dùng để tính toán, KHÔNG xuất ra file cho người dùng đọc.
_COT_NOI_BO_GL02 = {"DRAMOUNT_NUM", "CRAMOUNT_NUM", "KHOA_CHENH_LECH_CO", "KHOA_CHENH_LECH_NO"}
_COT_NOI_BO_OSB = {"SO_TIEN_NUM", "KHOA_C"}


def _gl02_export_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in GL02_EXPORT_COLS if c in df.columns]
    if "SO_TRACE" in df.columns:
        cols = cols + ["SO_TRACE"]
    out = df[cols].rename(columns={"SO_TRACE": "Số trace"})
    return out


def _osb_export_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in df.columns if c not in _COT_NOI_BO_OSB]
    return df[cols]


def _sheet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    return buf.getvalue()


def build_result_zip(ket_qua: dict) -> bytes:
    """`ket_qua`: `{"no": {"gl02": df, "osb": df}, "co": {"gl02": df, "osb": df}}` (đúng shape trả
    về từ `pipeline.chay_doi_chieu_osb`) -> bytes của 1 file ZIP chứa 4 file `.xlsx`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for case_key, ten_file in (("no", "No"), ("co", "Co")):
            gl02_df = _gl02_export_df(ket_qua[case_key]["gl02"])
            osb_df = _osb_export_df(ket_qua[case_key]["osb"])
            zf.writestr(f"Chenh_lech_{ten_file}_GL02.xlsx", _sheet_bytes(gl02_df))
            zf.writestr(f"Chenh_lech_{ten_file}_OSB.xlsx", _sheet_bytes(osb_df))
    return buf.getvalue()
