from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ReconcileResultOut(BaseModel):
    n_khop: int
    n_lech: int
    total_citad: int
    total_ipcas: int
    total_hub: int
    lech: List[Dict[str, Any]]
    history_saved: bool = True
    history_error: Optional[str] = None
    # Lỗi parse ở TỪNG file riêng lẻ (VD 1/3 file CITAD hỏng định dạng) —
    # khác với lỗi 422 (chặn hẳn request khi TOÀN BỘ file đều lỗi, không có
    # dòng nào đọc được). Có phần tử ở đây nghĩa là kết quả đối soát THIẾU
    # dữ liệu từ (các) file lỗi, không phải rỗng hoàn toàn — vẫn phải hiện
    # rõ cho người dùng biết, không được coi là "đối soát xong" bình thường.
    parse_warnings: List[str] = []


class ExportIn(BaseModel):
    """Payload xuất Excel — frontend gửi lại đúng kết quả /reconcile gần
    nhất đang giữ trong state (không bắt upload lại file)."""
    ngay_cham: str = ""
    n_khop: int = 0
    lech: List[Dict[str, Any]] = []


class HistoryOut(BaseModel):
    id: int
    ngay_cham: str
    recon_date: str
    performed_by: Optional[str] = None
    citad_file_names: List[str] = []
    ipcas_file_names: List[str] = []
    hub_file_names: List[str] = []
    total_citad: int
    total_ipcas: int
    total_hub: int
    n_khop: int
    n_lech: int
