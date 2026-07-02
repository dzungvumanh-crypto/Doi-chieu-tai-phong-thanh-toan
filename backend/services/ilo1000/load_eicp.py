"""Đọc file EICP (.XLS format cũ) → DataFrame + build lookup maps."""

from pathlib import Path

import pandas as pd

from .config import EICP_COL_BRCD, EICP_COL_MSGKEY, EICP_COL_TRSEQ


def load_eicp(paths: list[Path]) -> pd.DataFrame:
    """
    Đọc một hoặc nhiều file EICP .XLS (Excel 97-2003).
    Ghép lại thành 1 DataFrame.
    """
    if not paths:
        return pd.DataFrame()

    frames = []
    for p in paths:
        ext = p.suffix.lower()
        if ext in ('.xls',):
            # .XLS (Excel 97-2003): dùng calamine vì xlrd < 2.0 không được pandas hỗ trợ
            try:
                df = pd.read_excel(p, dtype=str, engine='calamine')
            except Exception:
                df = pd.read_excel(p, dtype=str, engine='xlrd')
        else:
            df = pd.read_excel(p, dtype=str, engine='openpyxl')
        df.columns = df.columns.str.strip()
        frames.append(df)

    return pd.concat(frames, ignore_index=True)


def build_eicp_maps(eicp_df: pd.DataFrame) -> dict:
    """
    Tạo 2 lookup dict từ EICP:
    - map_hub_to_core: {BRCD+MSGKEY → BRCD+"OTT"+TRSEQ}
      (Số giao dịch Hub → Trace dùng cho đối chiếu Core)
    """
    if eicp_df.empty:
        return {'hub_to_core': {}}

    brcd   = eicp_df.get(EICP_COL_BRCD,   pd.Series('', index=eicp_df.index)).fillna('').astype(str)
    msgkey = eicp_df.get(EICP_COL_MSGKEY, pd.Series('', index=eicp_df.index)).fillna('').astype(str)
    trseq  = eicp_df.get(EICP_COL_TRSEQ,  pd.Series('', index=eicp_df.index)).fillna('').astype(str)

    map_hub  = (brcd + msgkey).str.strip()
    map_core = (brcd + 'OTT' + trseq).str.strip()

    # Giữ lần XuẤT HIỆN ĐẦU TIÊN — đúng với hành vi VLOOKUP của Excel
    hub_to_core: dict[str, str] = {}
    for k, v in zip(map_hub, map_core):
        if k and k not in hub_to_core:
            hub_to_core[k] = v

    # Lưu 2 cột vào DataFrame để export sau
    eicp_df['map chung hub']  = map_hub
    eicp_df['Map chung core'] = map_core

    return {'hub_to_core': hub_to_core}
