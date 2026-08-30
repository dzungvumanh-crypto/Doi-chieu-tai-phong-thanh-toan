"""Xuất kết quả đối chiếu HUB↔CORE ra Excel — 3 sheet: tổng hợp theo nhãn KETQUADOICHIEU +
chi tiết CORE + chi tiết HUB (quyết định 2026-08-26: cần cả 2, không chỉ chi tiết).
"""

from pathlib import Path

import pandas as pd

from backend.services.ach.so_tien import doc_so_tien

from .match import KEY_COL

_TONG_HOP_COLS = ["Nhãn (KETQUADOICHIEU)", "Số dòng CORE", "Số tiền CORE", "Số dòng HUB", "Số tiền HUB"]


def build_tong_hop(core_df: pd.DataFrame, hub_df: pd.DataFrame) -> pd.DataFrame:
    core_amt = doc_so_tien(core_df["DRAMOUNT"], "core", "DRAMOUNT")
    hub_amt = doc_so_tien(hub_df["SO_TIEN"], "hub", "SO_TIEN")

    core_grp = (
        core_df.assign(_amt=core_amt)
        .groupby("KETQUADOICHIEU")
        .agg(so_dong_core=("KETQUADOICHIEU", "size"), so_tien_core=("_amt", "sum"))
    )
    hub_grp = (
        hub_df.assign(_amt=hub_amt)
        .groupby("KETQUADOICHIEU")
        .agg(so_dong_hub=("KETQUADOICHIEU", "size"), so_tien_hub=("_amt", "sum"))
    )

    tong = core_grp.join(hub_grp, how="outer").fillna(0)
    for c in ("so_dong_core", "so_tien_core", "so_dong_hub", "so_tien_hub"):
        tong[c] = tong[c].astype("int64")
    tong = tong.reset_index().rename(columns=dict(zip(
        ["KETQUADOICHIEU", "so_dong_core", "so_tien_core", "so_dong_hub", "so_tien_hub"],
        _TONG_HOP_COLS,
    ))).sort_values(_TONG_HOP_COLS[0]).reset_index(drop=True)

    tong_dong = {
        _TONG_HOP_COLS[0]: "Tổng cộng",
        _TONG_HOP_COLS[1]: int(tong[_TONG_HOP_COLS[1]].sum()),
        _TONG_HOP_COLS[2]: int(tong[_TONG_HOP_COLS[2]].sum()),
        _TONG_HOP_COLS[3]: int(tong[_TONG_HOP_COLS[3]].sum()),
        _TONG_HOP_COLS[4]: int(tong[_TONG_HOP_COLS[4]].sum()),
    }
    return pd.concat([tong, pd.DataFrame([tong_dong])], ignore_index=True)


def export_excel(ket_qua: dict, out_path: str | Path) -> Path:
    """`ket_qua` = dict trả về từ `pipeline.doi_chieu_hub_core()`."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    core_df, hub_df = ket_qua["core_df"], ket_qua["hub_df"]
    tong_hop = build_tong_hop(core_df, hub_df)

    # engine="xlsxwriter" — Core_ChiTiet/Hub_ChiTiet có thể tới ~800k dòng, xlsxwriter ghi nhanh
    # hơn openpyxl ~30% (xem ghi chú đo đạc ở doi_chieu_song_phuong_kenh/export.py). KHÔNG dùng
    # `constant_memory=True` — đã verify làm mất dữ liệu âm thầm.
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        tong_hop.to_excel(writer, sheet_name="TongHop", index=False)
        core_df.drop(columns=[KEY_COL], errors="ignore").to_excel(writer, sheet_name="Core_ChiTiet", index=False)
        hub_df.drop(columns=[KEY_COL], errors="ignore").to_excel(writer, sheet_name="Hub_ChiTiet", index=False)
    return out_path
