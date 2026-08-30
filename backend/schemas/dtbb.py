from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DtbbCurrencyOut(BaseModel):
    ccy: str
    rate_to_vnd: Optional[float] = None  # None cho VND/USD (không quy đổi) hoặc mã không quy đổi được
    group1_native: float
    group2_native: float
    tk413_native: float
    class Config: from_attributes = True


class DtbbCalculateResult(BaseModel):
    """Kết quả xem trước — /calculate KHÔNG ghi DB, chỉ trả để người dùng xác nhận."""
    report_date: date
    branch_code: str  # '9999' = toàn hệ thống/TSC khi tên file không mang mã chi nhánh
    file_count: int
    vnd_duoi12: float  # đã gộp TK413-VND — không tách cột riêng
    vnd_tu12: float
    usd_duoi12: float
    usd_tu12: float
    tk413_usd: float
    rate_usd_to_vnd: float  # tỷ giá VND/USD đã dùng (ttbuyrt/taxrt) — để tính "USD quy đổi" theo mã tiền
    all_ccy_codes: List[str]     # toàn bộ mã trong file tygia — FE tô ô vàng/trắng
    currencies_used: List[str]   # mã đã có file cân đối tương ứng
    unconverted_ccy: List[str] = []  # có file + có số dư nhưng KHÔNG quy đổi được (thiếu tỷ giá)
    netted_9300_ccy: List[str] = []  # mã tiền đã bị trừ số liệu chi nhánh 9300 (chỉ khi tính chi nhánh 9999)
    details: List[DtbbCurrencyOut]


class DtbbSaveRequest(BaseModel):
    """FE gửi lại nguyên kết quả /calculate đã xem qua, kèm cờ xác nhận ghi đè nếu cần.

    allow_inf_nan=False chặn NaN/Infinity — không nghiệp vụ nào sinh ra giá trị này
    hợp lệ, chỉ có thể do lỗi tính toán (vd chia cho tỷ giá 0). KHÔNG chặn số âm:
    số âm có thể hợp lệ (nghiệp vụ trừ chi nhánh 9300 theo từng dòng tài khoản có
    thể ra kết quả âm khi tài khoản chỉ tồn tại ở 9300) — xem _merge_9999_minus_9300
    trong calculator.py.
    """
    report_date: date
    branch_code: str
    file_count: int
    vnd_duoi12: float = Field(allow_inf_nan=False)  # đã gộp TK413-VND — không tách cột riêng
    vnd_tu12: float = Field(allow_inf_nan=False)
    usd_duoi12: float = Field(allow_inf_nan=False)
    usd_tu12: float = Field(allow_inf_nan=False)
    tk413_usd: float = Field(allow_inf_nan=False)
    rate_usd_to_vnd: float = Field(default=0.0, allow_inf_nan=False)
    details: List[DtbbCurrencyOut]
    confirm_overwrite: bool = False


class DtbbSaveResponse(BaseModel):
    report_id: Optional[int] = None
    report_date: date
    branch_code: str
    overwritten: bool = False
    needs_confirmation: bool = False
    existing_touched_by_name: Optional[str] = None
    existing_touched_at: Optional[datetime] = None


class DtbbHistoryItem(BaseModel):
    id: int  # report_id — dùng cho POST /{id}/confirm, /{id}/unconfirm
    report_date: date
    branch_code: str
    status: str  # 'pending' (vàng) | 'confirmed' (xanh)
    vnd_duoi12: float  # đã gộp TK413-VND — không tách cột riêng
    vnd_tu12: float
    usd_duoi12: float
    usd_tu12: float
    tk413_usd: float
    rate_usd_to_vnd: float = 0.0  # kỳ lưu trước khi có cột này sẽ trả 0 — FE ẩn cột USD quy đổi
    file_count: int
    created_by: int   # id người tạo — FE dùng để chặn tự xác nhận kỳ chính mình
    created_by_name: str
    created_at: datetime
    updated_by: Optional[int] = None
    updated_by_name: Optional[str] = None
    updated_at: Optional[datetime] = None
    confirmed_by_name: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    class Config: from_attributes = True


class DtbbReportDetailOut(DtbbHistoryItem):
    details: List[DtbbCurrencyOut]
