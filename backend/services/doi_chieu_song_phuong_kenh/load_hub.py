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


def hub_filename(ngay: str, ma_nh: str, chieu: str = "DEN") -> str:
    """VD `hub_filename('20260821', '202')` -> `doichieugd_20260821__05_DEN_9999_N.zip`.
    `chieu='DI'` -> hậu tố `_DI_9999_N.zip` (2026-09-03, thêm hỗ trợ chiều đi — tên file HUB thật
    của chiều đi dùng đúng quy ước này, chỉ khác `_DEN_`/`_DI_`, xem
    `doichieugd_20260901__04_DI_9999_N.zip` dữ liệu mẫu thật)."""
    if ma_nh not in HUB_FILE_CODE:
        raise ValueError(f"Mã ngân hàng không hợp lệ: {ma_nh}")
    return f"doichieugd_{ngay}__{HUB_FILE_CODE[ma_nh]}_{chieu}_9999_N.zip"


def hub_filename_glob(ngay: str, ma_nh: str, chieu: str = "DEN") -> str:
    """Như `hub_filename`, nhưng trả glob pattern chấp nhận hậu tố sau tên chuẩn (VD
    `..._N_v2.zip`) — cùng rủi ro tên file không đúng quy ước như CSV CORE/OSB đã gặp (dữ liệu
    export thủ công), xem `doi_chieu_song_phuong_common.py::tim_file_glob`."""
    if ma_nh not in HUB_FILE_CODE:
        raise ValueError(f"Mã ngân hàng không hợp lệ: {ma_nh}")
    return f"doichieugd_{ngay}__{HUB_FILE_CODE[ma_nh]}_{chieu}_9999_N*.zip"


def _doc_csv_hub_thu_cong(raw: bytes) -> pd.DataFrame:
    """Đọc CSV HUB bằng cách tách dòng thủ công — dùng khi `pd.read_csv` raise lỗi tokenize.

    Dữ liệu thật (NH 311, 22.8.2026) có 2/712.637 dòng cột `NOI_DUNG` chứa dấu `"` chưa escape
    đúng chuẩn CSV (VD tên công ty in ngoặc kép lồng trong nội dung), khiến cả pandas C-engine
    lẫn module `csv` chuẩn của Python đều tách nhầm thành nhiều cột hơn thật hoặc raise lỗi — dấu
    ngoặc kép bị lệch cân không có cách nào phân giải "đúng" duy nhất bằng luật CSV thuần tuý.

    Định vị `NOI_DUNG` THEO TÊN CỘT trong header, KHÔNG giả định vị trí cố định (2026-09-03, sửa
    theo khảo sát dữ liệu thật chiều đi — xem PLAN.md mục 3.5) — HUB "đến" có 14 cột, `NOI_DUNG`
    là cột CUỐI; HUB "đi" có 17 cột, `NGAY_KENH_TRA` nằm SAU `NOI_DUNG`. Bản cũ giả định `NOI_DUNG`
    luôn ở cuối (`line.split(",", n-1)`), đúng cho "đến" nhưng sẽ nuốt mất `NGAY_KENH_TRA` vào
    trong `NOI_DUNG` nếu áp dụng y nguyên cho "đi". Cách làm mới: tách `n_truoc` cột đầu (trước
    NOI_DUNG, không bao giờ chứa dấu phẩy/ngoặc kép — đã xác nhận qua toàn bộ dữ liệu thật quan
    sát được) bằng `split(",", n_truoc)`, sau đó tách NGƯỢC `n_sau` cột cuối (sau NOI_DUNG) từ
    phần còn lại bằng `rsplit(",", n_sau)` — phần giữa còn lại luôn là `NOI_DUNG` nguyên vẹn, bất
    kể ngoặc kép cân hay không, và các cột sau NOI_DUNG (VD `NGAY_KENH_TRA`) không bị nuốt mất."""
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    header = lines[0].split(",")
    n = len(header)
    idx_noi_dung = header.index("NOI_DUNG")
    n_truoc = idx_noi_dung          # số cột TRƯỚC NOI_DUNG
    n_sau = n - idx_noi_dung - 1     # số cột SAU NOI_DUNG (0 cho "đến", 1 cho "đi": NGAY_KENH_TRA)
    rows = []
    for i, line in enumerate(lines[1:], start=2):
        if not line:
            continue
        dau = line.split(",", n_truoc)
        if len(dau) != n_truoc + 1:
            raise ValueError(f"Dòng {i} không tách được đủ {n_truoc} cột đầu (có {len(dau)}): {line[:200]!r}")
        phan_con_lai = dau[-1]
        if n_sau:
            cuoi = phan_con_lai.rsplit(",", n_sau)
            if len(cuoi) != n_sau + 1:
                raise ValueError(f"Dòng {i} không tách được đủ {n_sau} cột cuối (có {len(cuoi)}): {line[:200]!r}")
            noi_dung, *sau = cuoi
        else:
            noi_dung, sau = phan_con_lai, []
        parts = dau[:-1] + [noi_dung] + sau
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


# ─── Hub↔Core CHIỀU ĐI (2026-09-03) — khoá dùng SE_TRACE, không phải TRACE trực tiếp ───────────
# Nguồn: `Đối chiếu SP chiều đi.docx` Bước 1.2/1.3. Dữ liệu thật xác nhận cột SE_TRACE nguồn LUÔN
# RỖNG (500.058/500.058 dòng, cả NH 201 lẫn 311) — giá trị SE_TRACE dùng để so khớp luôn phải tự
# suy ra từ TRACE, không đọc thẳng từ cột gốc. Xem PLAN.md mục 2.2/3.1.


def mask_lenh_fx(df: pd.DataFrame) -> pd.Series:
    """True nếu HUB không có dữ liệu ở CẢ `TRACE` lẫn `SE_TRACE` (Bước 1.2 docx-đi) — các dòng
    này dừng ở đây, gán nhãn `"lệnh fx"`, không tham gia so khớp CORE/OSB tiếp theo."""
    trace_rong = df["TRACE"].fillna("").str.strip() == ""
    se_trace_rong = df["SE_TRACE"].fillna("").str.strip() == ""
    return trace_rong & se_trace_rong


def se_trace_hieu_dung(df: pd.DataFrame) -> pd.Series:
    """Giá trị SE_TRACE THỰC DÙNG để so khớp (Bước 1.3 docx-đi): nếu SE_TRACE gốc rỗng mà có
    TRACE thì dùng TRACE thay thế; dòng thuộc `mask_lenh_fx()` trả về rỗng (không quan trọng vì
    các dòng đó đã dừng waterfall trước khi cần khoá này)."""
    se_trace = df["SE_TRACE"].fillna("").str.strip()
    trace = df["TRACE"].fillna("").str.strip()
    return se_trace.mask(se_trace == "", trace)


def build_key_hub_core_di(df: pd.DataFrame) -> pd.Series:
    """Khoá đối chiếu HUB↔CORE chiều đi (Bước 1.3/2.6 docx-đi): `CHI_NHANH + SE_TRACE(hiệu dụng,
    lstrip '0') + SO_TIEN`.

    ⚠ 2026-09-03 — SỬA LỖI phát hiện khi verify dữ liệu thật (NH 201, 01/09/2026): bản đầu KHÔNG
    lstrip('0') SE_TRACE, chỉ khớp được 0/972 dòng HUB có SE_TRACE bắt đầu bằng '0'; sau khi thêm
    lstrip('0') khớp đúng 912/972 (60 dòng còn lại lệch vì lý do khác, không liên quan số 0 đầu).
    Tổng số khớp "hub T core T" tăng từ 451.838 lên 452.750. Đây ĐÚNG bẫy đã dính ở chiều đến
    (`build_key_hub_core()`/`load_core.py::PREFIX_TRACE_CORE` — "tài liệu không nói rõ nhưng dữ
    liệu thật xác nhận bắt buộc lstrip('0') cả 2 bên mới khớp được") — SO_TRACE phía CORE
    (`load_core.build_so_trace()`) đã lstrip('0') sẵn, phía HUB phải lstrip đối xứng.

    KHÔNG áp dụng lstrip này cho khoá HUB↔OSB (`load_osb.build_key_hub_osb_di()`) — đúng theo
    khuôn "đến" (`build_key_hub_core()` có lstrip, `build_key_hub_osb()` không), 2 khoá phục vụ
    2 mục đích khác nhau."""
    se_trace = se_trace_hieu_dung(df).str.lstrip("0")
    so_tien = doc_so_tien(df["SO_TIEN"], nguon="hub_core_di", ten_cot="SO_TIEN")
    return df["CHI_NHANH"].astype(str).str.strip() + se_trace + so_tien.astype(str)
