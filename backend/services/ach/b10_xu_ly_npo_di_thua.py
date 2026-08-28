import pandas as pd

from .so_tien import doc_so_tien


def tach_dien_huy(df_npo_di_thua: pd.DataFrame, log_callback=None):
    """Điểm 3 (2026-07-31, rà soát + sign-off ở Implementation-notes.html mục 57/60)
    — tách "điện đi huỷ trong ngày"/"điện đi huỷ khác ngày" khỏi NPO_đi thừa (đầu
    ra bước 10, KHÔNG đổi cách sinh ra).

    B1: `CHECK_TRUNG = TRBRCD + SO_TRACE` (không ký tự phân tách, theo tiền lệ
    `KEY_DI`). `SO_TRACE` đã có sẵn trên `df_npo_di_thua` (tính từ
    `b2_xu_ly_gl02.py::xu_ly_gl02()`), không tính lại.

    B2: nhóm theo `CHECK_TRUNG`, nhóm nào `sum(CRAMOUNT) == 0` → toàn bộ nhóm là
    "điện đi huỷ trong ngày". Mọi dòng trong `df_npo_di_thua` luôn có CRAMOUNT != 0
    (định nghĩa NPO_đi ở `xu_ly_gl02()`), nên 1 dòng đơn lẻ không bao giờ tổng được
    0 — điều kiện `len(nhóm) >= 2` tự động thỏa, không cần kiểm tra riêng. Mở "cặp
    2 dòng" (mô tả gốc) thành "nhóm ≥2 dòng" — verify dữ liệu thật cho thấy 100%
    nhóm tìm được là đúng 2 dòng `TRTP=Normal` (dương) + `TRTP=Cancel` (âm) đối
    ứng cùng REFERENCE, thuật toán chỉ tổng quát hoá cho trường hợp lớn hơn.

    B3: trên phần còn lại (không thuộc nhóm huỷ-trong-ngày), lọc `TRTP == 'Cancel'`
    → "điện đi huỷ khác ngày" (verify dữ liệu thật: NPO_đi thừa chỉ có 2 giá trị
    TRTP là 'Normal'/'Cancel').

    B4: phần còn lại (không phải 2 nhóm trên) vẫn là NPO_đi thừa như cũ.

    KHÔNG loại trừ dòng có `SO_TRACE` mặc định `'0'` (REFERENCE không trích được
    trace, ví dụ dòng OSB tổng hợp) khỏi `CHECK_TRUNG` trước khi group — Business
    Owner đã sign-off chấp nhận rủi ro lý thuyết này (mục 60, B1): trên dữ liệu
    thật chưa từng có ≥2 dòng cùng rơi vào giá trị mặc định này trong 1 lần chạy.

    Trả về (df_huy_trong_ngay, df_huy_khac_ngay, df_npo_di_thua_con_lai).
    """
    _log = log_callback or print

    df = df_npo_di_thua.copy()
    df['CRAMOUNT'] = doc_so_tien(df['CRAMOUNT'], nguon='NPO_DI_THUA', ten_cot='CRAMOUNT')
    df['_CHECK_TRUNG'] = df['TRBRCD'].astype(str).str.strip() + df['SO_TRACE'].astype(str)

    tong_nhom     = df.groupby('_CHECK_TRUNG')['CRAMOUNT'].transform('sum')
    so_dong_nhom  = df.groupby('_CHECK_TRUNG')['_CHECK_TRUNG'].transform('size')
    mask_huy_trong_ngay = (tong_nhom == 0) & (so_dong_nhom >= 2)

    df = df.drop(columns=['_CHECK_TRUNG'])
    df_huy_trong_ngay = df[mask_huy_trong_ngay].copy()

    con_lai = df[~mask_huy_trong_ngay]
    mask_huy_khac_ngay = con_lai['TRTP'].astype(str).str.strip() == 'Cancel'
    df_huy_khac_ngay       = con_lai[mask_huy_khac_ngay].copy()
    df_npo_di_thua_con_lai = con_lai[~mask_huy_khac_ngay].copy()

    _log(
        f'[B10][Điểm 3] Điện đi huỷ trong ngày: {len(df_huy_trong_ngay):,} dòng | '
        f'Điện đi huỷ khác ngày: {len(df_huy_khac_ngay):,} dòng | '
        f'NPO_đi thừa còn lại: {len(df_npo_di_thua_con_lai):,} dòng'
    )
    return (
        df_huy_trong_ngay.reset_index(drop=True),
        df_huy_khac_ngay.reset_index(drop=True),
        df_npo_di_thua_con_lai.reset_index(drop=True),
    )
