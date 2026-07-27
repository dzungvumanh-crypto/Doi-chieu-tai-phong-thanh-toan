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
