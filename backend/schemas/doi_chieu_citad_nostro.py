"""Schemas Đối chiếu CITAD ↔ PaymentHub — Phòng QLTK Nostro, Vostro.

Module SONG SONG, độc lập với `backend/schemas/doi_chieu_citad.py` (Phòng
Thanh toán) — nghiệp vụ và nguồn dữ liệu khác hẳn:
  - CITAD: trang "Tra cứu dữ liệu" (KHÔNG phải "Bảng kê giao dịch"), chỉ
    chiều ĐI, chỉ trạng thái "Giao dịch thành công", chỉ VNĐ. Vẫn tra đủ
    5 cổng (CONG_MAP giống hệt `extension_citad/content.js`), mỗi cổng tách
    2 loại dịch vụ: "gtt" (Giá trị Thấp) / "gtc" (Giá trị Cao).
  - PaymentHub: trang "Lập bảng kê phí chia sẻ CITAD", dòng "Tổng cộng",
    3 khối: "gtt", "gtc_truoc" (Trước 15h30), "gtc_tu" (Từ 15h30).
  - Công thức: Tổng CITAD (gtt/gtc) = cộng 5 cổng. Tổng HUB gtc =
    gtc_truoc + gtc_tu. Chênh lệch = Tổng CITAD − Tổng HUB (1 cặp mỗi
    loại — khác Phòng Thanh toán có 2 nguồn HUB nên có 2 cặp).

Dùng CHUNG `ExtensionTokenOut`/`ExtensionTokenStatus` từ
`backend/schemas/doi_chieu_citad.py` — cơ chế mã kết nối Extension trung
lập, không gắn riêng phòng nào (xem `doi_chieu_citad_nostro_service.py`).
"""
from typing import Optional
from pydantic import BaseModel

LOAI_CITAD = ("gtt", "gtc")
LOAI_HUB = ("gtt", "gtc_truoc", "gtc_tu")
CONGS = ("1", "9", "12", "17", "18")  # giống hệt CONG_MAP trong extension_citad/content.js


class SessionIn(BaseModel):
    ky: str  # "dd/mm/yyyy-dd/mm/yyyy" — ngày đơn thì 2 đầu trùng nhau
    lap_bang: Optional[str] = ""
    kiem_soat: Optional[str] = ""
    cD: dict = {}   # cD[cong]["gtt"|"gtc"] = {"soMon": float, "soTien": float}
    phD: dict = {}  # phD["gtt"|"gtc_truoc"|"gtc_tu"] = {"soMon": float, "soTien": float}


class CitadBufferIn(BaseModel):
    """Payload Extension gửi khi tự động lưu số liệu CITAD (trang Tra cứu
    dữ liệu). Không có field `owner` — chủ buffer suy ra từ token hợp lệ
    (header `X-Extension-Token`), giống hệt cơ chế của Phòng Thanh toán."""
    key: str
    cong: str
    loai: str  # "gtt" | "gtc"
    soMon: float = 0
    soTien: float = 0
    ts: str = ""


class PaymentHubBufferIn(BaseModel):
    """items: mỗi item {key, loai: "gtt"|"gtc_truoc"|"gtc_tu", soMon, soTien}."""
    items: list = []
    ts: str = ""


class ExportIn(BaseModel):
    tu_ngay: str = ""
    den_ngay: str = ""
    sheet_name: str = "Sheet1"
    lb: str = ""
    ks: str = ""
    cD: dict = {}
    phD: dict = {}
