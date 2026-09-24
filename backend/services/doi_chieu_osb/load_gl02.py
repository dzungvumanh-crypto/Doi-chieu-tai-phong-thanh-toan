"""Đọc + giải mã GL02 zip (sổ cái IPCAS, tài khoản trung gian OSB) cho module `doi_chieu_osb`.

Kiến trúc mirror `backend/services/ach/b2_xu_ly_gl02.py`: ưu tiên công cụ ngoài (7-Zip/WinRAR) qua
`backend/services/ach/zip_utils.py` — nhanh hơn nhiều với ZipCrypto cổ điển trên file GL02 thật
(xem skill `bank-reconciliation`) — fallback `pyzipper` thuần khi máy không cài công cụ nào (chậm
hơn nhưng đúng, đây là pattern đã được chấp nhận trong dự án cho GL02, không phát minh cơ chế mới
ở module này). KHÔNG dùng cơ chế numba ZipCrypto của `doi_chieu_song_phuong_service.py` — giữ đơn
giản, đồng bộ với ACH.

Verify dữ liệu thật (spike test 3 ngày 01/07, 31/07, 04/04/2026, TK 519910, trước khi viết module
này — xem `docs/Implementation-notes.html`): 1 ZIP có thể chứa NHIỀU file CSV thành viên — vừa bản
riêng đúng 1 ngày, vừa bản gộp cả tháng (VD ZIP ngày 31/07/2026 có 10 file CSV, tổng 4,53 triệu
dòng, trong đó có 1 file gộp trọn 01/07→31/07). Đọc TOÀN BỘ file thành viên, GỘP LẠI, dedupe THEO
TOÀN BỘ CỘT (`drop_duplicates()` không `subset` — chỉ loại bản sao THẬT giống hệt nhau giữa các
file, KHÔNG dedupe theo 1-2 cột riêng lẻ vì sẽ xoá nhầm dữ liệu thật, xem lỗi tương tự đã phát
hiện ở `load_osb.py`), rồi mới lọc theo TRDATE = ngày đang cần. Sau khi lọc đầy đủ (LOCAC/CCY/
CUSTOMER/REFERENCE), số dòng chênh lệch tính ra khớp 100% với file "hà chấm" cả 3 ngày.

Verify thêm dữ liệu thật ngày 31/08/2026: 1 ZIP có thể chứa file `.xlsx` thay vì `.csv`
(`1000_gl02_2026083120260831.xlsx`, tên ZIP `GL02_20260603_1000.zip` SAI ngày nhưng nội dung
đúng 31/08 — code đọc theo TRDATE thật bên trong nên không bị ảnh hưởng bởi tên file sai). `.csv`
và `.xlsx` bình đẳng, đọc bằng `pd.read_csv`/`pd.read_excel(engine="calamine")` tương ứng, cùng 1
bộ validate cột bắt buộc sau khi đọc — không có nhánh ưu tiên đuôi nào.
"""
import io
import os
import shutil
import subprocess
import tempfile
import time

import pandas as pd
import pyzipper

from backend.core.config import zip_password
from backend.services.ach.so_tien import doc_so_tien
from backend.services.ach.zip_utils import (
    bao_dung_cong_cu as _bao_dung_cong_cu,
    bao_giai_nen_xong as _bao_giai_nen_xong,
    bao_lui_ve_pyzipper as _bao_lui_ve_pyzipper,
    build_extract_cmd as _build_extract_cmd,
    detect_encoding_from_bytes as _detect_encoding_from_bytes,
    find_zip_tool as _find_zip_tool,
)

from .config import CCY_VND, GL02_REQUIRED_COLS, REFERENCE_LOAI_TRU, SO_TRACE_END, SO_TRACE_START, TAI_KHOAN

_BUOC = "OSB-GL02"
_DUOI_HOP_LE = (".csv", ".xlsx", ".xls")


def _la_file_hop_le(ten_file: str) -> bool:
    return ten_file.lower().endswith(_DUOI_HOP_LE)


def _doc_1_file(raw: bytes, ten_file: str) -> pd.DataFrame:
    """Đọc 1 file thành viên trong ZIP GL02 — `.csv` (đa số ngày) hoặc `.xlsx`/`.xls` (verify thật
    31/08/2026: `1000_gl02_2026083120260831.xlsx`, 17 cột, có thêm 1 cột "trace, tiền" thừa giữa
    REMARK và DRAMOUNT — không cần xử lý gì đặc biệt, `usecols` không có nên cột thừa tự bị bỏ qua
    ở bước validate cột bắt buộc bên dưới). Mirror đúng tinh thần
    `doi_chieu_song_phuong_core/load_core.py::load_core_den_csv()` (2026-09-09: "file core đã
    phân loại sẵn giờ chấp nhận cả .csv lẫn .xlsx") — không có ưu tiên đuôi nào hơn đuôi nào, đúng
    khuôn cột bắt buộc là dùng được, đọc bằng `engine="calamine"` cho Excel (đúng quy ước chuẩn dự
    án — `openpyxl` từng đọc sai/mất dữ liệu âm thầm với file lỗi thẻ `<dimension>`)."""
    if ten_file.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(raw), dtype=str, engine="calamine")
    else:
        enc = _detect_encoding_from_bytes(raw[:512])
        df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding=enc, low_memory=False,
                          encoding_errors="replace")
    df.columns = [c.strip() for c in df.columns]
    missing = GL02_REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"File GL02 '{ten_file}' thiếu cột bắt buộc: {', '.join(sorted(missing))} — KHÔNG "
            f"đoán/tự bỏ qua, cần file GL02 đúng khuôn."
        )
    return df


def _doc_zip_tool(zip_path: str, tool_path: str, tool_type: str, log_callback=None) -> pd.DataFrame:
    _log = log_callback or print
    tmp_dir = tempfile.mkdtemp(prefix="doi_chieu_osb_gl02_")
    try:
        t0 = time.perf_counter()
        cmd = _build_extract_cmd(tool_path, tool_type, zip_path, tmp_dir, zip_password().decode())
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        _bao_giai_nen_xong(_BUOC, zip_path, time.perf_counter() - t0, r.returncode, log_callback)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors="replace"))
        frames = []
        for name in sorted(os.listdir(tmp_dir)):
            if not _la_file_hop_le(name):
                continue
            with open(os.path.join(tmp_dir, name), "rb") as f:
                raw = f.read()
            df = _doc_1_file(raw, name)
            _log(f"[{_BUOC}] {name}: {len(df):,} dòng")
            frames.append(df)
        if not frames:
            raise ValueError(f"ZIP GL02 '{zip_path}' không có file .csv/.xlsx nào bên trong.")
        return pd.concat(frames, ignore_index=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _doc_zip_pyzipper(zip_path: str, log_callback=None) -> pd.DataFrame:
    _log = log_callback or print
    frames = []
    with pyzipper.AESZipFile(zip_path, "r") as z:
        z.setpassword(zip_password())
        names = [n for n in sorted(z.namelist()) if _la_file_hop_le(n)]
        if not names:
            raise ValueError(f"ZIP GL02 '{zip_path}' không có file .csv/.xlsx nào bên trong.")
        for name in names:
            if log_callback:
                log_callback(f"[{_BUOC}] Đang nạp {name} vào bộ nhớ (cách dự phòng)...")
            raw = z.read(name)
            df = _doc_1_file(raw, name)
            _log(f"[{_BUOC}] {name}: {len(df):,} dòng")
            frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _doc_zip(zip_path: str, log_callback=None) -> pd.DataFrame:
    result = _find_zip_tool()
    if result:
        tool_path, tool_type = result
        _bao_dung_cong_cu(_BUOC, zip_path, tool_type, tool_path, log_callback)
        try:
            return _doc_zip_tool(zip_path, tool_path, tool_type, log_callback)
        except Exception as e:
            _bao_lui_ve_pyzipper(_BUOC, zip_path, str(e), log_callback)
    else:
        _bao_lui_ve_pyzipper(_BUOC, zip_path, "", log_callback)
    return _doc_zip_pyzipper(zip_path, log_callback)


def read_gl02_zip(zip_path: str, ma_tk: str, ngay: str,
                   log_callback=None) -> tuple[pd.DataFrame, int]:
    """Đọc GL02 zip (có thể nhiều file CSV thành viên / nhiều ngày gộp chung), lọc đúng 1 tài
    khoản trung gian OSB (`ma_tk`, VD "519910") + đúng ngày `ngay` (YYYYMMDD), dựng Khoá A
    (case "Chênh lệch Có", SoTrace+DRAMOUNT trên DRAMOUNT != 0) và Khoá B (case "Chênh lệch Nợ",
    SoTrace+CRAMOUNT trên CRAMOUNT != 0).

    Trả `(df, n_remark_ngan)` — `n_remark_ngan` là số dòng REMARK < 7 ký tự (rủi ro Số trace rỗng/
    ngắn hơn 6 ký tự — chỉ log cảnh báo, KHÔNG chặn, vì slice Python không bao giờ ném lỗi)."""
    _log = log_callback or (lambda m: None)
    if ma_tk not in TAI_KHOAN:
        raise ValueError(
            f"Tài khoản trung gian OSB '{ma_tk}' chưa được khai trong config.TAI_KHOAN — cần "
            f"thêm cấu hình (customer) trước khi đối chiếu."
        )
    khach_hang = TAI_KHOAN[ma_tk]["customer"]

    # Lọc TRDATE TRƯỚC khi strip/dedupe toàn cột (review Khánh, PR #103): ZIP có thể gộp tới
    # 4,53 triệu dòng nhiều ngày trong khi phần cần dùng chỉ là 1 ngày — strip+dedupe trên toàn
    # bộ trước rồi mới lọc lãng phí gấp nhiều lần. Kết quả cuối Y HỆT thứ tự cũ: 2 dòng trùng
    # khít nhau (mọi cột) đương nhiên cùng TRDATE, nên lọc ngày trước rồi mới dedupe trên tập
    # con cho đúng kết quả như dedupe toàn tập rồi lọc.
    full = _doc_zip(zip_path, log_callback)
    full["TRDATE"] = full["TRDATE"].astype(str).str.strip()
    df = full[full["TRDATE"] == ngay].copy()
    _log(f"[{_BUOC}] TRDATE == {ngay}: {len(df):,} dòng")

    for c in df.columns:
        if c != "TRDATE":
            df[c] = df[c].astype(str).str.strip()

    truoc = len(df)
    df = df.drop_duplicates()
    if truoc != len(df):
        _log(f"[{_BUOC}] {truoc:,} dòng -> dedupe TOÀN CỘT -> {len(df):,} dòng "
             f"(loại {truoc - len(df):,} dòng trùng thật)")

    mask = (
        (df["LOCAC"] == ma_tk)
        & (df["CCY"] == CCY_VND)
        & (df["CUSTOMER"] == khach_hang)
        & (df["REFERENCE"] != REFERENCE_LOAI_TRU)
    )
    df = df[mask].reset_index(drop=True)
    _log(f"[{_BUOC}] sau lọc LOCAC={ma_tk}/CCY={CCY_VND}/CUSTOMER={khach_hang}/loại REFERENCE="
         f"{REFERENCE_LOAI_TRU}: {len(df):,} dòng")

    df["DRAMOUNT_NUM"] = doc_so_tien(df["DRAMOUNT"], "gl02", "DRAMOUNT")
    df["CRAMOUNT_NUM"] = doc_so_tien(df["CRAMOUNT"], "gl02", "CRAMOUNT")

    n_short = int((df["REMARK"].str.len() < 7).sum())
    if n_short:
        _log(f"[{_BUOC}] CẢNH BÁO: {n_short:,} dòng có REMARK < 7 ký tự — Số trace sẽ rỗng/ngắn "
             f"hơn 6 ký tự, rủi ro khoá rỗng.")

    so_trace = df["REMARK"].str[SO_TRACE_START:SO_TRACE_END]
    df["SO_TRACE"] = so_trace
    df["KHOA_CHENH_LECH_CO"] = so_trace + df["DRAMOUNT_NUM"].astype(str)
    df["KHOA_CHENH_LECH_NO"] = so_trace + df["CRAMOUNT_NUM"].astype(str)
    return df, n_short
