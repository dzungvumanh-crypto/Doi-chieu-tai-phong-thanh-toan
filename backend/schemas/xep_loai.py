"""Schema cho Xếp loại lao động (Phòng Tổng hợp).

Ba loại độc lập cùng một bảng (`loai`), mỗi loại chỉ hợp với một số kỳ:
- `lao_dong`  (Xếp loại lao động — mọi cán bộ): theo năm HOẶC theo quý
- `tin_nhiem` (Kết quả phiếu tín nhiệm — cán bộ có chức danh): theo năm
- `cap_uy`    (Xếp loại quý đối với Cấp ủy): theo quý

`ket_qua` là mức xếp loại — không phải chuỗi tự do, phải khớp một trong các mức
cố định của đúng loại đó (khớp theo `_fold`, bỏ dấu/hạ chữ, để chấp nhận cách gõ
khác nhau khi nhập tay hoặc từ Excel).
"""
import re
import unicodedata
from typing import Optional

from pydantic import BaseModel, model_validator

from backend.core.enums import KyXepLoai, LoaiXepLoai

_MIN_YEAR = 2000
_MAX_YEAR = 2100

MUC_LAO_DONG = [
    "Hoàn thành xuất sắc nhiệm vụ", "Hoàn thành tốt nhiệm vụ",
    "Hoàn thành nhiệm vụ", "Không hoàn thành nhiệm vụ",
]
MUC_TIN_NHIEM = ["Tín nhiệm cao", "Tín nhiệm", "Tín nhiệm thấp"]

KET_QUA_THEO_LOAI: dict[str, list[str]] = {
    LoaiXepLoai.LAO_DONG.value:  MUC_LAO_DONG,
    LoaiXepLoai.TIN_NHIEM.value: MUC_TIN_NHIEM,
    LoaiXepLoai.CAP_UY.value:    MUC_LAO_DONG,
}

KY_HOP_LE_THEO_LOAI: dict[str, set[str]] = {
    LoaiXepLoai.LAO_DONG.value:  {KyXepLoai.NAM.value, KyXepLoai.QUY.value},
    LoaiXepLoai.TIN_NHIEM.value: {KyXepLoai.NAM.value},
    LoaiXepLoai.CAP_UY.value:    {KyXepLoai.QUY.value},
}

TEN_LOAI = {
    LoaiXepLoai.LAO_DONG.value:  "Xếp loại lao động",
    LoaiXepLoai.TIN_NHIEM.value: "Kết quả phiếu tín nhiệm",
    LoaiXepLoai.CAP_UY.value:    "Xếp loại quý — Cấp ủy",
}


def _fold(s) -> str:
    """Hạ chữ + bỏ dấu + gộp khoảng trắng để so khớp bất kể cách gõ."""
    t = unicodedata.normalize("NFD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t).strip().lower()


def khop_ket_qua(loai: str, gia_tri) -> Optional[str]:
    """Trả về đúng chuỗi chuẩn trong `KET_QUA_THEO_LOAI[loai]` khớp với `gia_tri`
    (so khớp bỏ dấu/hạ chữ), hoặc None nếu không khớp mức nào."""
    f = _fold(gia_tri)
    if not f:
        return None
    for muc in KET_QUA_THEO_LOAI.get(loai, []):
        if _fold(muc) == f:
            return muc
    return None


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = unicodedata.normalize("NFC", str(v)).strip()
    return v or None


class XepLoaiIn(BaseModel):
    staff_id: int
    loai: LoaiXepLoai
    ky: KyXepLoai
    nam: int
    quy: Optional[int] = None
    ket_qua: str
    ghi_chu: Optional[str] = None

    @model_validator(mode="after")
    def _rang_buoc(self):
        if not (_MIN_YEAR <= self.nam <= _MAX_YEAR):
            raise ValueError(f"Năm không hợp lệ: {self.nam}")

        if self.ky.value not in KY_HOP_LE_THEO_LOAI[self.loai.value]:
            raise ValueError(
                f"{TEN_LOAI[self.loai.value]} không áp dụng theo "
                f"{'năm' if self.ky.value == 'nam' else 'quý'}")

        if self.ky == KyXepLoai.QUY:
            if self.quy is None or not (1 <= self.quy <= 4):
                raise ValueError("Cần chọn quý hợp lệ (1-4) khi xếp loại theo quý")
        else:
            self.quy = None

        chuan = khop_ket_qua(self.loai.value, self.ket_qua)
        if chuan is None:
            raise ValueError(
                f"Kết quả không hợp lệ cho {TEN_LOAI[self.loai.value]}: '{self.ket_qua}' "
                f"— cần là một trong: {', '.join(KET_QUA_THEO_LOAI[self.loai.value])}")
        self.ket_qua = chuan

        self.ghi_chu = _clean(self.ghi_chu)
        return self
