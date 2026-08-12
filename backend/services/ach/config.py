"""Hằng số cấu hình cho pipeline đối chiếu ACH."""
import os

ZIP_PASSWORD = os.environ.get('DOI_CHIEU_ZIP_PASSWORD', 'DACwLdHi').encode()

COLS_NPO = [
    'TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
    'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE',
    'REMARK', 'DRAMOUNT', 'CRAMOUNT', 'CRTDTM',
]

# Ngày đối chiếu mặc định (dùng làm fallback khi không có ngày truyền vào)
from datetime import datetime
_DEFAULT_DATE = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
NGAY_DT       = _DEFAULT_DATE
