"""Schemas Chuẩn hoá văn bản theo QĐ 979/QyĐ-NHNo-PC."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class CauHinhIn(BaseModel):
    """Cấu hình quy chuẩn do người dùng gửi lên.

    Cố tình để kiểu lỏng (`dict[str, Any]`): cấu trúc quy chuẩn nằm ở
    `quy_chuan.QUY_CHUAN_MAC_DINH`, khai lại toàn bộ 28 thành phần thể thức
    dưới dạng model Pydantic là chép cùng một cây thành hai bản — thêm một
    thuộc tính trình bày là phải sửa hai chỗ và chúng sẽ lệch nhau. Việc lọc
    khoá lạ do `quy_chuan.hop_nhat()` đảm nhiệm (nó chỉ nhận khoá đã biết).
    """

    trang: Optional[dict[str, Any]] = None
    chung: Optional[dict[str, Any]] = None
    thanh_phan: Optional[dict[str, Any]] = None
    lien_dong: Optional[dict[str, Any]] = None
    viet_hoa: Optional[dict[str, Any]] = None
    danh_so: Optional[dict[str, Any]] = None
    danh_dau: Optional[dict[str, Any]] = None


class CauHinhOut(BaseModel):
    cau_hinh: dict            # đã hợp nhất với mặc định — thứ đang thực sự áp dụng
    mac_dinh: dict            # bản gốc theo QĐ 979, để nút "Khôi phục mặc định"
    nhan: dict[str, str]      # mã thành phần → nhãn tiếng Việt
    dai_co_chu: dict[str, list[float]]
    mau_danh_dau: dict[str, str]
    cap_nhat_luc: Optional[str] = None
    cap_nhat_boi: Optional[str] = None


class KetQuaChuanHoa(BaseModel):
    token: str
    ten_file: str
    sua_chung: list[str]
    doan: list[dict]
    luu_y: list[str]
    thong_ke: dict


class MauVB(BaseModel):
    """Một mẫu trình bày sẵn của Phụ lục V, để người dùng tải bản trắng."""

    so: int
    ten: str
