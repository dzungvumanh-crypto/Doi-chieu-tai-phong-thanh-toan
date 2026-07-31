"""Nhận diện lệnh OSB (Điểm 2 — đối chiếu QT, Điểm 4 — đối chiếu chéo ngày) —
module dùng chung, tách sớm ngay sau Điểm 1 để tránh cắm giá trị OSB ở 2 nơi
khác nhau, dễ lệch nhau (xem Implementation-notes.html mục 60, D1).

Giá trị đã verify trên dữ liệu thật (mục 56/58) — KHÁC mô tả nghiệp vụ gốc:
chiều đi là CHỮ 'O' (không phải số 0), chiều đến đúng là số '1'.
"""
import pandas as pd

OSB_DI_VALUE  = 'O'
OSB_DEN_VALUE = '1'


def la_lenh_osb_di(df: pd.DataFrame) -> pd.Series:
    """True nếu dòng MIS_đi là lệnh OSB (cột LOAI_LENH_OSB == 'O' sau khi strip)."""
    return df['LOAI_LENH_OSB'].astype(str).str.strip() == OSB_DI_VALUE


def la_lenh_osb_den(df: pd.DataFrame) -> pd.Series:
    """True nếu dòng MIS_đến là lệnh OSB (cột LOAI_LENH_OSB == '1' sau khi strip)."""
    return df['LOAI_LENH_OSB'].astype(str).str.strip() == OSB_DEN_VALUE
