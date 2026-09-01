"""Đọc & tiền xử lý dữ liệu HUB (`doichieugd_*.zip`) — định tuyến theo mã ngân hàng.

⚠️ Số trong tên file (`__NN_DEN_9999_N`) LÀ MÃ NGÂN HÀNG (04=201/05=202/06=203/07=311),
KHÔNG phải 2 nguồn khác nhau của cùng luồng — sửa từ giả định sai ở vòng khảo sát 1.
"""

import io
import zipfile
from typing import Callable

import pandas as pd

from backend.services.ach.so_tien import doc_so_tien

from .config import HUB_FILE_CODE, HUB_REQUIRED_COLS


def hub_filename(ngay: str, ma_nh: str) -> str:
    """VD `hub_filename('20260821', '202')` -> `doichieugd_20260821__05_DEN_9999_N.zip`."""
    if ma_nh not in HUB_FILE_CODE:
        raise ValueError(f"Mã ngân hàng không hợp lệ: {ma_nh}")
    return f"doichieugd_{ngay}__{HUB_FILE_CODE[ma_nh]}_DEN_9999_N.zip"


def hub_filename_glob(ngay: str, ma_nh: str) -> str:
    """Như `hub_filename`, nhưng trả glob pattern chấp nhận hậu tố sau tên chuẩn (VD
    `..._N_v2.zip`) — cùng rủi ro tên file không đúng quy ước như CSV CORE/OSB đã gặp (dữ liệu
    export thủ công), xem `doi_chieu_song_phuong_common.py::tim_file_glob`."""
    if ma_nh not in HUB_FILE_CODE:
        raise ValueError(f"Mã ngân hàng không hợp lệ: {ma_nh}")
    return f"doichieugd_{ngay}__{HUB_FILE_CODE[ma_nh]}_DEN_9999_N*.zip"


def _doc_csv_hub_thu_cong(raw: bytes) -> pd.DataFrame:
    """Đọc CSV HUB bằng cách tách dòng thủ công — dùng khi `pd.read_csv` raise lỗi tokenize.

    Dữ liệu thật (NH 311, 22.8.2026) có 2/712.637 dòng cột `NOI_DUNG` chứa dấu `"` chưa escape
    đúng chuẩn CSV (VD tên công ty in ngoặc kép lồng trong nội dung), khiến cả pandas C-engine
    lẫn module `csv` chuẩn của Python đều tách nhầm thành >14 cột hoặc raise lỗi — dấu ngoặc kép
    bị lệch cân không có cách nào phân giải "đúng" duy nhất bằng luật CSV thuần tuý.

    13 cột đầu (`NGAY_GIAO_DICH`...`NH_GUI`) không bao giờ chứa dấu phẩy/ngoặc kép (đã xác nhận
    qua toàn bộ dữ liệu thật quan sát được) — tách theo đúng 13 dấu phẩy đầu tiên, phần còn lại
    luôn là `NOI_DUNG` nguyên vẹn, không phụ thuộc việc ngoặc kép của cột này có cân bằng hay
    không. Giữ được đầy đủ dòng + đúng mọi cột dùng làm khoá đối chiếu (`NOI_DUNG` không dùng
    trong bất kỳ khoá nào, chỉ hiển thị tham khảo)."""
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    header = lines[0].split(",")
    n = len(header)
    rows = []
    for i, line in enumerate(lines[1:], start=2):
        if not line:
            continue
        parts = line.split(",", n - 1)
        if len(parts) != n:
            raise ValueError(f"Dòng {i} không tách được đủ {n} cột (có {len(parts)}): {line[:200]!r}")
        rows.append(parts)
    df = pd.DataFrame(rows, columns=header, dtype=str)
    df["NOI_DUNG"] = df["NOI_DUNG"].str.strip().str.strip('"')
    return df


def load_hub_zip(zip_bytes: bytes, log: Callable[[str], None] = lambda msg: None) -> pd.DataFrame:
    """Đọc 1 file ZIP HUB (đúng 1 CSV bên trong), strip dấu nháy đơn đầu MSGREF/TXID."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise ValueError(f"ZIP HUB phải chứa đúng 1 file, thấy {len(names)}: {names}")
        with zf.open(names[0]) as f:
            raw = f.read()

    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except pd.errors.ParserError as e:
        log(f"[CẢNH BÁO] CSV HUB có dòng lỗi định dạng ({e}) — chuyển sang đọc thủ công (tách "
            f"theo 13 dấu phẩy đầu, giữ nguyên NOI_DUNG) để không mất dòng.")
        df = _doc_csv_hub_thu_cong(raw)

    missing = HUB_REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"File HUB thiếu cột bắt buộc: {', '.join(sorted(missing))}")

    df["MSGREF"] = df["MSGREF"].str.lstrip("'")
    df["TXID"] = df["TXID"].str.lstrip("'")
    return df


def filter_before_reconcile(df: pd.DataFrame, log: Callable[[str], None] = lambda msg: None) -> pd.DataFrame:
    """Loại 2 loại dòng HUB trước khi đối chiếu (mục 1.2/2.2 tài liệu `đối chiếu kênh hub
    Song phương.docx`, cả 2 mục dùng chung điểm lọc này).

    1) Dòng có `-` trong TXID — bản ghi huỷ/đảo (VD trạng thái WFPG/CGBR) tham chiếu ngược
       một bản ghi gốc (VD WTSC/RTSC) qua TXID dạng ghép `<txid_gốc>-<chuỗi khác>` — không
       phải giao dịch độc lập (xem docs/TU-DIEN-LENH-THANH-TOAN.md mục 4.5).
    2) Cặp (TXID, TRACE) trùng nhau giữa 2 dòng khác nhau — cũng là giao dịch huỷ, theo
       xác nhận Business Owner 2026-08-26 + verify dữ liệu thật 25/08/2026 (NH 202: đúng
       2 cặp/4 dòng, trạng thái RFED, không có nhóm >2). TXID/TRACE rỗng bị loại khỏi
       bước gom nhóm — nhiều dòng RJCT có TRACE rỗng sẽ "trùng" giả nếu không loại trước.
    """
    mask_gach = df["TXID"].str.contains("-", regex=False)
    n_gach = int(mask_gach.sum())
    if n_gach:
        log(f"Loại {n_gach} dòng HUB có '-' trong TXID (bản ghi huỷ/đảo, không đối chiếu trực tiếp)")
    df = df[~mask_gach].reset_index(drop=True)

    trace_norm = df["TRACE"].str.strip().str.lstrip("'0")
    co_khoa = (df["TXID"] != "") & (trace_norm != "")
    khoa = df["TXID"] + "\x00" + trace_norm
    dem = khoa[co_khoa].value_counts()
    so_luong_nhom = khoa.map(dem).fillna(0)
    mask_huy = co_khoa & (so_luong_nhom >= 2)
    n_huy = int(mask_huy.sum())
    if n_huy:
        log(f"Loại {n_huy} dòng HUB có cặp (TXID, TRACE) trùng với dòng khác (giao dịch huỷ)")
    nhom_bat_thuong = khoa[mask_huy & (so_luong_nhom > 2)].unique()
    if len(nhom_bat_thuong):
        log(f"[CẢNH BÁO] {len(nhom_bat_thuong)} nhóm (TXID, TRACE) có hơn 2 dòng trùng nhau — bất thường, cần điều tra")

    return df[~mask_huy].reset_index(drop=True)


def loai_rjct_hub_core(df: pd.DataFrame, log: Callable[[str], None] = lambda msg: None) -> pd.DataFrame:
    """Loại riêng dòng RJCT trên HUB đã qua `filter_before_reconcile()` — tách ra từ
    `filter_before_reconcile_core()` (2026-08-31) để bước Hub↔Core có thể áp lên 1 DataFrame HUB
    đã đọc+lọc base SẴN từ bước Kênh↔Hub (tránh đọc+giải nén+lọc lại từ đầu cùng 1 file HUB,
    xem `doi_chieu_song_phuong_core/pipeline.py::doi_chieu_hub_core` tham số `hub_t_override`)."""
    mask_rjct = df["TRANG_THAI_LENH"].astype(str).str.strip() == "RJCT"
    n_rjct = int(mask_rjct.sum())
    if n_rjct:
        log(f"Loại {n_rjct} dòng HUB có TRANG_THAI_LENH='RJCT' (nhánh hub↔core)")
    return df[~mask_rjct].reset_index(drop=True)


def filter_before_reconcile_core(df: pd.DataFrame, log: Callable[[str], None] = lambda msg: None) -> pd.DataFrame:
    """Tiền xử lý HUB cho nhánh đối chiếu HUB↔CORE (Bước 2.1 tài liệu `đối chiếu Song phương.docx`).

    Tái dùng `filter_before_reconcile()` (loại `-` trong TXID + cặp TXID/TRACE trùng) rồi loại
    thêm RJCT (`loai_rjct_hub_core`). KHÁC nhánh kênh↔hub: ở đó RJCT vẫn giữ lại (để hiện "KHÔNG
    CÓ" trong Bảng 3), ở đây tài liệu yêu cầu loại hẳn — vì vậy tách hàm riêng, không đổi hành vi
    `filter_before_reconcile` hiện có (module kênh↔hub đã duyệt Phase 9, không được ảnh hưởng).
    """
    df = filter_before_reconcile(df, log)
    return loai_rjct_hub_core(df, log)


def build_key_hub_core(df: pd.DataFrame) -> pd.Series:
    """Khoá đối chiếu HUB↔CORE (Bước 1.4/2.2): `CHI_NHANH + TRACE(lstrip '0') + SO_TIEN` — mô
    phỏng đúng công thức `ach/b6_xu_ly_mis_den.py:138-144`, verify dữ liệu thật (xem
    `doi_chieu_song_phuong_core/config.py`)."""
    trace_norm = df["TRACE"].fillna("").str.strip().str.lstrip("'0")
    so_tien = doc_so_tien(df["SO_TIEN"], nguon="hub_core", ten_cot="SO_TIEN")
    return df["CHI_NHANH"].astype(str).str.strip() + trace_norm + so_tien.astype(str)
