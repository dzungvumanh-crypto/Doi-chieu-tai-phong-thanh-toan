"""Orchestrator: đối chiếu GL02 <-> OSB cho 1 tài khoản trung gian OSB, 1 ngày.

Nhận đường dẫn GL02 zip + danh sách file OSB (2 file/ngày — 1 bản "TK ghi Nợ", 1 bản "TK ghi Có")
+ mã tài khoản trung gian (VD "519910") + ngày (YYYYMMDD) -> chạy hết pipeline, trả DataFrame kết
quả 2 case (Nợ/Có) x 2 phía (GL02/OSB) + bytes ZIP sẵn sàng tải về.
"""
from pathlib import Path
from typing import Callable

from . import export, load_gl02, load_osb, match
from .config import COT_OSB_THEO_CASE, KHOA_GL02_THEO_CASE, NHAN_CHENH_LECH_CO, NHAN_CHENH_LECH_NO

__all__ = ["chay_doi_chieu_osb"]

_CAC_CASE = ((NHAN_CHENH_LECH_NO, "no"), (NHAN_CHENH_LECH_CO, "co"))


def chay_doi_chieu_osb(
    gl02_zip_path: str | Path, osb_paths: list[str | Path], ma_tk: str, ngay: str,
    log_callback: Callable[[str], None] | None = None,
) -> dict:
    """Đối chiếu GL02 <-> OSB cho 1 tài khoản trung gian OSB (VD "519910"), ngày `ngay` (YYYYMMDD).

    Trả:
        {
          "ma_tk": str, "ngay": str,
          "no": {"gl02": DataFrame, "osb": DataFrame},   # Chênh lệch Nợ
          "co": {"gl02": DataFrame, "osb": DataFrame},   # Chênh lệch Có
          "canh_bao": {"remark_ngan": int, "nhom_huy_qua_2": int},
          "zip_bytes": bytes,
        }
    """
    log = log_callback or (lambda m: None)

    gl02_df, n_remark_ngan = load_gl02.read_gl02_zip(gl02_zip_path, ma_tk, ngay, log)
    osb_raw = load_osb.read_osb_files(osb_paths, log)
    osb_df, n_nhom_huy_qua_2 = load_osb.process_osb(osb_raw, log)

    ket_qua: dict = {}
    for ten_case, case_key in _CAC_CASE:
        khoa_gl02_col = KHOA_GL02_THEO_CASE[ten_case]
        cot_tk_osb = COT_OSB_THEO_CASE[ten_case]

        if ten_case == NHAN_CHENH_LECH_NO:
            gl02_sub = gl02_df[gl02_df["CRAMOUNT_NUM"] != 0]
        else:
            gl02_sub = gl02_df[gl02_df["DRAMOUNT_NUM"] != 0]
        osb_sub = osb_df[(osb_df[cot_tk_osb] == ma_tk) & (osb_df["LOAI_GIAO_DICH"] != "Hủy")]

        log(f"[{ten_case}] GL02 subset: {len(gl02_sub):,} dòng | OSB subset: {len(osb_sub):,} dòng")
        gl02_chenh, osb_chenh = match.khop_case(gl02_sub, khoa_gl02_col, osb_sub)
        log(f"[{ten_case}] => GL02 chênh lệch = {len(gl02_chenh):,} dòng, "
            f"OSB chênh lệch = {len(osb_chenh):,} dòng")

        ket_qua[case_key] = {
            "gl02": gl02_chenh.reset_index(drop=True),
            "osb": osb_chenh.reset_index(drop=True),
        }

    zip_bytes = export.build_result_zip(ket_qua)

    return {
        "ma_tk": ma_tk,
        "ngay": ngay,
        **ket_qua,
        "canh_bao": {"remark_ngan": n_remark_ngan, "nhom_huy_qua_2": n_nhom_huy_qua_2},
        "zip_bytes": zip_bytes,
    }
