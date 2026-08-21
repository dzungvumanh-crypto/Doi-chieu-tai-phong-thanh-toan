"""Hằng số cấu hình cho pipeline đối chiếu ACH."""

# Mật khẩu ZIP KHÔNG còn là hằng số ở đây (trước là chuỗi nằm cứng trong mã, đã
# đi vào lịch sử git). Đọc từ .env qua hàm dùng chung, và đọc ĐÚNG LÚC GIẢI NÉN
# chứ không lúc import — thiếu biến môi trường thì báo lỗi rõ cho người vận
# hành, không làm cả backend không khởi động được.
from backend.core.config import zip_password  # noqa: F401  (b2/b4/b6 import lại từ đây)

COLS_NPO = [
    'TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
    'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE',
    'REMARK', 'DRAMOUNT', 'CRAMOUNT', 'CRTDTM',
]

# Ngày đối chiếu mặc định (dùng làm fallback khi không có ngày truyền vào)
from datetime import datetime
_DEFAULT_DATE = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
NGAY_DT       = _DEFAULT_DATE
