"""Hằng số dùng chung cho pipeline Đối chiếu ACH.

Khác bản gốc (DOI-CHIEU-ACH/config.py): bỏ NGAY_DOI_CHIEU / TPAY_TU / TPAY_DEN.
Bản gốc là app CLI 1 người dùng nên ngày đối chiếu để cứng trong file này; ở đây
ngày do người dùng nhập hoặc suy ra từ tên file PDF, và mốc TPAY được tính cục bộ
trong engine rồi truyền tường minh xuống B4 — không có state toàn cục nào bị mutate.
"""
import os

# Mật khẩu ZIP xuất từ IPCAS — đặt biến môi trường để đổi mà không sửa code
ZIP_PASSWORD = os.environ.get("DOI_CHIEU_ZIP_PASSWORD", "DACwLdHi").encode()

# Cột giữ lại khi đọc file GL02 — nguồn duy nhất, B2 và engine cùng dùng
COLS_NPO = [
    "TRDATE", "TRBRCD", "USERID", "JOURSEQ", "DYTRSEQ", "LOCAC", "CCY",
    "BUSCD", "UNIT", "TRCD", "CUSTOMER", "TRTP", "REFERENCE",
    "REMARK", "DRAMOUNT", "CRAMOUNT", "CRTDTM",
]
