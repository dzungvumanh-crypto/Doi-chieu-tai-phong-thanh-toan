"""Schemas Đối chiếu CITAD ↔ PaymentHub — Phòng Thanh toán.

Port từ `citad-fixed/server.py::SessionIn` / `ExportIn` / `CitadBufferIn`
(bản gốc là tool desktop độc lập, port sang module tích hợp TTTT).
Field giữ NGUYÊN tên/kiểu như bản gốc để không phải đổi logic tính toán ở
frontend hay `_build_xlsx()` — chỉ bỏ `user_id: str` nhập tay (bản gốc hard
code 'default') vì giờ đã có `current["id"]` từ JWT.
"""
from typing import Optional
from pydantic import BaseModel


class SessionIn(BaseModel):
    ngay: str
    lap_bang: Optional[str] = ""
    kiem_soat: Optional[str] = ""
    gD: dict = {}
    phD: dict = {}
    napas_m: float = 0
    napas_t: float = 0
    ebank_m: float = 0
    ebank_t: float = 0
    napas_di_ih_m: float = 0
    napas_di_ih_t: float = 0
    napas_di_il_m: float = 0
    napas_di_il_t: float = 0
    napas_den_il_m: float = 0
    napas_den_il_t: float = 0
    ebank_di_ih_m: float = 0
    ebank_di_ih_t: float = 0
    ebank_di_il_m: float = 0
    ebank_di_il_t: float = 0
    ebank_den_il_m: float = 0
    ebank_den_il_t: float = 0


class CitadBufferIn(BaseModel):
    key: str
    cong: str
    loai: str
    chieu: str
    tien: str
    soMon: float = 0
    soTien: float = 0
    fMon: str = ""
    fTien: str = ""
    ts: str = ""


class PaymentHubBufferIn(BaseModel):
    items: list = []
    ts: str = ""


class ExportIn(BaseModel):
    day_str: str = ""
    sheet_name: str = "Sheet1"
    lb: str = ""
    ks: str = ""
    gD: dict = {}
    phD: dict = {}
    nm: float = 0
    nt: float = 0
    em: float = 0
    et: float = 0
