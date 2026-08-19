"""Đọc các file CITAD (UUID CSV) và concat thành 1 DataFrame."""

import io
from pathlib import Path

import pandas as pd

from .config import CITAD_COLS_KEEP, CITAD_HEADER

_N_FIELDS = len(CITAD_HEADER)  # 11: ID,SERIAL_NO,RELATION_NO,O_CI_ID,R_CI_ID,TRX_DATE,CI_CODE,CI_NAME,AMOUNT,TRX_STATUS,TELLERID


def _detect_encoding(path: Path) -> str:
    with path.open('rb') as f:
        header = f.read(512)
    if header[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    try:
        header.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'cp1252'


def _fix_ragged_line(line: str) -> str:
    """
    CI_NAME (field thứ 8, index 7) đôi khi chứa dấu phẩy chưa escape — tên
    ngân hàng quốc tế viết theo thông lệ "X Bank, Ltd CN <chi nhánh>" (VD
    "Ngân hàng MUFG Bank, Ltd CN Hà Nội"). Dấu phẩy này làm dòng CSV có NHIỀU
    field hơn header (VD 12 thay vì 11) → pandas coi là dòng lỗi và ÂM THẦM
    BỎ QUA CẢ DÒNG (on_bad_lines='skip'), mất hẳn giao dịch chứ không chỉ sai
    cột AMOUNT như nhìn qua tưởng — xác nhận qua dữ liệu thật 04-06/7/2026,
    người dùng phát hiện 4 giao dịch CITAD bị thiếu hoàn toàn vì lý do này.
    Ghép lại: 7 field đầu (ID..CI_CODE) và 3 field cuối (AMOUNT,TRX_STATUS,
    TELLERID) luôn đúng vị trí — phần dư ở giữa chắc chắn thuộc CI_NAME.
    """
    parts = line.split(',')
    if len(parts) <= _N_FIELDS:
        return line
    head = parts[:7]
    tail = parts[-3:]
    ci_name = ','.join(parts[7:-3])
    # Bọc trong dấu ngoặc kép để CSV parser đọc lại coi là 1 field duy nhất —
    # nếu chỉ nối chuỗi bằng dấu phẩy như cũ, dấu phẩy gốc trong tên vẫn còn
    # nguyên trong text, pandas parse lại vẫn đếm ra thừa field như trước.
    ci_name_quoted = '"' + ci_name.replace('"', '""') + '"'
    return ','.join(head + [ci_name_quoted] + tail)


def _load_one(path: Path) -> pd.DataFrame:
    enc = _detect_encoding(path)
    with path.open('r', encoding=enc, errors='replace') as f:
        raw_lines = f.read().splitlines()
    if not raw_lines:
        return pd.DataFrame(columns=CITAD_COLS_KEEP)
    fixed_lines = [raw_lines[0]] + [_fix_ragged_line(l) for l in raw_lines[1:] if l.strip()]

    df = pd.read_csv(io.StringIO('\n'.join(fixed_lines)), dtype=str, low_memory=False, on_bad_lines='skip')
    df.columns = df.columns.str.strip()
    # Giữ cột cần thiết
    cols = [c for c in CITAD_COLS_KEEP if c in df.columns]
    df = df[cols].copy()

    # ── AMOUNT lỗi export (VD "Ltd CN TP HCM") → lấy từ TRX_STATUS ──
    # PHẢI sửa ở TỪNG file cổng, TRƯỚC KHI gộp 5 cổng + dedup theo SERIAL_NO:
    # nếu sửa sau khi gộp, drop_duplicates(keep='first') có thể giữ lại đúng
    # dòng bị lỗi của 1 cổng trong khi dòng đúng ở cổng khác (cùng SERIAL_NO)
    # bị loại — xác nhận nghiệp vụ 2026-07-16.
    if 'AMOUNT' in df.columns and 'TRX_STATUS' in df.columns:
        amount_str = df['AMOUNT'].fillna('').astype(str).str.strip()
        ltd_mask = amount_str.str.lower().str.contains('ltd', na=False)
        df.loc[ltd_mask, 'AMOUNT'] = df.loc[ltd_mask, 'TRX_STATUS'].fillna('').astype(str).str.strip()

    return df


def load_citad(paths: list[Path], ngay_int: int | None = None) -> pd.DataFrame:
    """
    Đọc nhiều file CITAD CSV (mỗi file đã tự sửa AMOUNT="ltd") và ghép lại.
    `ngay_int`: nếu truyền, chỉ giữ dòng có TRX_DATE == ngay_int — bắt buộc khi
    1 file citad gộp chung dữ liệu NHIỀU ngày (xác nhận qua dữ liệu thật
    14-15/7/2026: cả 5 file cổng đều trộn lẫn TRX_DATE 14 và 15).
    """
    if not paths:
        return pd.DataFrame(columns=CITAD_COLS_KEEP)
    frames = [_load_one(p) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    # Deduplicate theo SERIAL_NO (cổng khác nhau có thể trùng)
    df = df.drop_duplicates(subset=['SERIAL_NO'], keep='first')
    if ngay_int is not None and 'TRX_DATE' in df.columns:
        df = df[df['TRX_DATE'].fillna('').astype(str).str.strip() == str(ngay_int)].copy()
    return df
