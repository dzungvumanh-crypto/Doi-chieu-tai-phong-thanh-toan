"""Schemas Đối chiếu CITAD ↔ PaymentHub — Phòng QLTK Nostro, Vostro.

Module SONG SONG, độc lập với `backend/schemas/doi_chieu_citad.py` (Phòng
Thanh toán) — nghiệp vụ và nguồn dữ liệu khác hẳn:
  - CITAD: trang "Tra cứu dữ liệu" (VNĐ, KHÔNG phải "Bảng kê giao dịch"),
    chỉ chiều ĐI, chỉ trạng thái "Giao dịch thành công". Vẫn tra đủ 5 cổng
    (CONG_MAP giống hệt `extension_citad/content.js`), mỗi cổng tách 2 loại
    dịch vụ: "gtt" (Giá trị Thấp) / "gtc" (Giá trị Cao). Từ 14/09/2026 có
    thêm trang RIÊNG "Tra cứu dữ liệu ngoại tệ" (module TraCuuDuLieuNgoaiTe,
    quét bởi `extension_citad_nv/content_citad_nostro_fx.js`) cho USD/EUR —
    trang đó CHỈ có "Chuyển Có giá trị cao" (không có giá trị thấp), nên
    "gtt" của USD/EUR luôn = 0 (khớp thực tế PaymentHub: cột GTT cũng luôn
    ra 0 khi lọc USD/EUR).
  - PaymentHub: trang "Lập bảng kê phí chia sẻ CITAD", dòng "Tổng cộng",
    3 khối: "gtt", "gtc_truoc" (Trước 15h30), "gtc_tu" (Từ 15h30). 1 trang
    DUY NHẤT cho cả 3 loại tiền — chỉ đổi dropdown Loại tiền (`#ccy`) rồi
    Truy vấn lại, không có trang riêng như CITAD.
  - Công thức: Tổng CITAD (gtt/gtc) = cộng 5 cổng. Tổng HUB gtc =
    gtc_truoc + gtc_tu. Chênh lệch = Tổng CITAD − Tổng HUB (1 cặp mỗi
    loại — khác Phòng Thanh toán có 2 nguồn HUB nên có 2 cặp). CÙNG công
    thức áp dụng riêng cho mỗi loại tiền — 3 loại tiền KHÔNG cộng chung với
    nhau (khác đơn vị tiền, cộng chung vô nghĩa).

Dùng CHUNG `ExtensionTokenOut`/`ExtensionTokenStatus` từ
`backend/schemas/doi_chieu_citad.py` — cơ chế mã kết nối Extension trung
lập, không gắn riêng phòng nào (xem `doi_chieu_citad_nostro_service.py`).
"""
from typing import Optional
from pydantic import BaseModel

LOAI_CITAD = ("gtt", "gtc")
LOAI_HUB = ("gtt", "gtc_truoc", "gtc_tu")
CONGS = ("1", "9", "12", "17", "18")  # giống hệt CONG_MAP trong extension_citad/content.js
# Tên cổng hiển thị — phải khớp CONG_LABEL ở frontend/pages/doi_chieu_citad_nostro.py:
# báo cáo Excel và màn hình gọi cùng một cổng bằng cùng một tên, không thể
# trên màn là "Cổng 4818" mà xuất ra Excel thành "Cổng 18".
CONG_LABEL = {
    "1": "Cổng 001",
    "9": "Cổng CITAD (9)",
    "12": "Cổng 9212",
    "17": "Cổng 7917",
    "18": "Cổng 4818",
}

# 3 loại tiền chấm trong CÙNG 1 kỳ (3 tab trên 1 bảng, không phải 3 bảng
# riêng) — quyết định nghiệp vụ 14/09/2026. Thứ tự cũng là thứ tự hiển thị
# tab ở frontend và thứ tự sheet khi xuất Excel.
LOAI_TIEN = ("VND", "USD", "EUR")
CCY_LABEL = {"VND": "VNĐ", "USD": "USD", "EUR": "EUR"}


class SessionIn(BaseModel):
    ky: str  # "dd/mm/yyyy-dd/mm/yyyy" — ngày đơn thì 2 đầu trùng nhau
    lap_bang: Optional[str] = ""
    kiem_soat: Optional[str] = ""
    # cD[ccy][cong]["gtt"|"gtc"] = {"soMon": float, "soTien": float}
    # phD[ccy]["gtt"|"gtc_truoc"|"gtc_tu"] = {"soMon": float, "soTien": float}
    # ccy in LOAI_TIEN ("VND"/"USD"/"EUR") — 1 kỳ có cả 3, lap_bang/kiem_soat
    # dùng CHUNG cho cả 3 (cùng người lập/kiểm soát 1 bảng, chỉ khác số liệu
    # theo tab). Bảng lưu TRƯỚC 14/09/2026 không có lớp `ccy` này (cD/phD cũ
    # phẳng theo cong/loai luôn) — svc.get_ccy_slice() tự coi bảng cũ là dữ
    # liệu VNĐ khi đọc lại, không cần migrate DB.
    cD: dict = {}
    phD: dict = {}
    # None = LUÔN tạo bảng MỚI của chính người gọi. Có giá trị = đang lưu
    # tiếp ĐÚNG bảng đó (`id` cụ thể) — mirror SessionIn.session_id của
    # doi_chieu_citad.py (Phòng Thanh toán), từ 11/09/2026 (nhiều bảng/kỳ).
    session_id: Optional[int] = None


class CitadBufferIn(BaseModel):
    """Payload Extension gửi khi tự động lưu số liệu CITAD (trang Tra cứu
    dữ liệu VNĐ hoặc ngoại tệ). Không có field `owner` — chủ buffer suy ra
    từ token hợp lệ (header `X-Extension-Token`), giống hệt cơ chế của
    Phòng Thanh toán."""
    key: str
    cong: str
    loai: str  # "gtt" | "gtc"
    # Mặc định "VND" — content_citad_nostro.js (trang VNĐ, viết TRƯỚC
    # 14/09/2026) không gửi field này, phải mặc định đúng loại tiền của nó
    # thì mới không phải sửa lại script cũ đang chạy trên máy người dùng.
    ccy: str = "VND"
    soMon: float = 0
    soTien: float = 0
    ts: str = ""


class PaymentHubBufferIn(BaseModel):
    """items: mỗi item {key, loai: "gtt"|"gtc_truoc"|"gtc_tu", ccy: "VND"|
    "USD"|"EUR", soMon, soTien}. `ccy` không ép kiểu ở tầng schema (items
    là list tự do, giống cấu trúc cũ) — svc.buffer_save_ph() lưu nguyên,
    frontend tự bỏ qua item thiếu/sai `ccy` khi nạp vào đúng tab."""
    items: list = []
    ts: str = ""


class ExportIn(BaseModel):
    tu_ngay: str = ""
    den_ngay: str = ""
    sheet_name: str = "Sheet1"
    lb: str = ""
    ks: str = ""
    # Cùng cấu trúc lồng theo `ccy` như SessionIn.cD/phD — build_xlsx_nostro()
    # xuất 1 sheet riêng cho mỗi loại tiền có trong LOAI_TIEN.
    cD: dict = {}
    phD: dict = {}


class MonthSummaryIn(BaseModel):
    """Xem trước tổng tháng (không xuất Excel) — người dùng tick/bỏ tick
    bảng nào tính vào tổng, gọi lại endpoint này để cập nhật số liệu hiển
    thị trên màn "Tổng hợp tháng" mỗi lần đổi tick."""
    session_ids: list[int] = []


class MonthSummaryExportIn(BaseModel):
    """Xuất Excel tổng hợp tháng — cộng dồn cD/phD của các bảng
    (`session_ids`) người dùng đã tick chọn, xem
    `svc.combine_sessions_cD_phD()`."""
    nam: int
    thang: int
    session_ids: list[int] = []
    lb: str = ""
    ks: str = ""
