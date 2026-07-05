from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ReconcileResultOut(BaseModel):
    """Kết quả 1 lần đối chiếu (đến hoặc đi) — trả về cho frontend hiển thị bảng."""
    summary: List[Dict[str, Any]]     # từ reconcile.summarize_counts()
    records: List[Dict[str, Any]]     # từ reconcile.build_merged_view()
    total_a: int
    total_b: int
    total_matched: int
    total_diff: int


class ExportFilteredIn(BaseModel):
    """Xuất đúng các bản ghi đang hiển thị sau khi lọc trên giao diện."""
    columns: List[str]
    records: List[Dict[str, Any]]
    filename: str = "Ban_ghi_dang_loc.xlsx"


class HistoryOut(BaseModel):
    id: int
    recon_type: str
    recon_date: str
    performed_by: Optional[str] = None
    file_saa_name: Optional[str] = None
    file_ql_name: Optional[str] = None
    total_saa: int
    total_ql: int
    total_matched: int
    total_diff: int

    class Config:
        from_attributes = True
