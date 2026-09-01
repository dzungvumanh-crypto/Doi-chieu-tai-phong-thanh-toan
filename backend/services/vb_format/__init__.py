"""Chuẩn hoá thể thức và kỹ thuật trình bày văn bản theo QĐ 979/QyĐ-NHNo-PC."""
from .chuan_hoa import chuan_hoa
from .quy_chuan import (
    DAI_CO_CHU, MAU_DANH_DAU, NHAN_THANH_PHAN, hop_nhat, mac_dinh,
)

__all__ = [
    "chuan_hoa", "mac_dinh", "hop_nhat",
    "NHAN_THANH_PHAN", "DAI_CO_CHU", "MAU_DANH_DAU",
]
