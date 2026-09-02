"""Phân loại KETQUADOICHIEU cho đối chiếu HUB↔CORE — đúng trình tự Bước 1.x (core) / 2.x (hub)
tài liệu `đối chiếu Song phương.docx`, top-down, dừng ở bước đầu tiên khớp được.
"""

import pandas as pd

from . import load_core, load_osb
from .config import (
    NHAN_CORE_HUY, NHAN_CORE_KHOP_HUB, NHAN_CORE_THUA, NHAN_HUB_KHOP_CORE, NHAN_HUB_THUA,
    NHAN_QT_OSB, NHAN_QT_VON, OFFSET_CORE_KHI_XU_LY_HUB, OFFSET_HUB_KHI_XU_LY_CORE,
)

KEY_COL = "_KEY"


def _khop_min_count(khoa_nguon: pd.Series, khoa_dich: pd.Series) -> pd.Series:
    """Boolean mask (cùng index `khoa_nguon`) đánh dấu dòng khớp được với `khoa_dich`, dùng
    min(count) mỗi khoá — không phải merge 1-1 (giống `ach/b5_doi_chieu_di.py:_doi_chieu`)."""
    if len(khoa_nguon) == 0 or len(khoa_dich) == 0:
        return pd.Series(False, index=khoa_nguon.index)
    dem_nguon = khoa_nguon.value_counts()
    dem_dich = khoa_dich.value_counts()
    chung = dem_nguon.index.intersection(dem_dich.index)
    gioi_han = {k: min(dem_nguon[k], dem_dich[k]) for k in chung}
    cc = khoa_nguon.groupby(khoa_nguon).cumcount()
    han = khoa_nguon.map(gioi_han).fillna(0)
    return cc < han


def _phan_loai_chuoi_khoa(khoa: pd.Series, con_lai: pd.Series,
                           cac_buoc: list[tuple[str, pd.Series | None]], nhan: pd.Series) -> None:
    """Lần lượt thử khớp `khoa` (trên phần còn `con_lai`) với từng khoá đích trong `cac_buoc`
    (list `(nhãn, khoá_đích|None)`), gán `nhan` + cập nhật `con_lai` tại chỗ."""
    for ten_nhan, khoa_dich in cac_buoc:
        if khoa_dich is None or not con_lai.any():
            continue
        idx = con_lai[con_lai].index
        mask_khop = _khop_min_count(khoa.loc[idx], khoa_dich)
        idx_khop = mask_khop[mask_khop].index
        nhan.loc[idx_khop] = ten_nhan
        con_lai.loc[idx_khop] = False


def classify_core(core_df: pd.DataFrame, hub_theo_offset: dict[int, pd.DataFrame]) -> pd.Series:
    """Nhãn KETQUADOICHIEU cùng index `core_df` (Bước 1.2-1.10).

    `hub_theo_offset`: `{offset: hub_df}` — `hub_df` đã qua `filter_before_reconcile_core` +
    có cột `_KEY` (`build_key_hub_core`); offset thiếu file thì bỏ qua (không có key trong dict
    hoặc value `None`).
    """
    so_trace = load_core.build_so_trace(core_df)
    khoa = load_core.build_key_den(core_df, so_trace)
    nhan = pd.Series("", index=core_df.index)
    con_lai = pd.Series(True, index=core_df.index)

    mask_huy = load_core.mask_huy_cung_ngay(core_df)
    nhan.loc[mask_huy] = NHAN_CORE_HUY
    con_lai.loc[mask_huy] = False

    cac_buoc = []
    for off in OFFSET_HUB_KHI_XU_LY_CORE:
        hub_df = hub_theo_offset.get(off)
        cac_buoc.append((NHAN_CORE_KHOP_HUB[off], hub_df[KEY_COL] if hub_df is not None else None))
    _phan_loai_chuoi_khoa(khoa, con_lai, cac_buoc, nhan)

    mask_osb = con_lai & load_core.mask_qt_osb(core_df)
    nhan.loc[mask_osb] = NHAN_QT_OSB
    con_lai.loc[mask_osb] = False

    mask_von = con_lai & load_core.mask_qt_von(core_df)
    nhan.loc[mask_von] = NHAN_QT_VON
    con_lai.loc[mask_von] = False

    nhan.loc[con_lai] = NHAN_CORE_THUA
    return nhan


def classify_hub(hub_df: pd.DataFrame, core_theo_offset: dict[int, pd.DataFrame],
                  osb_df: pd.DataFrame | None) -> pd.Series:
    """Nhãn KETQUADOICHIEU cùng index `hub_df` (Bước 2.2-2.7).

    `hub_df`: đã qua `filter_before_reconcile_core`, có cột `_KEY` (`build_key_hub_core`).
    `core_theo_offset`: `{offset: core_df}` — `core_df` đã có cột `_KEY` (`build_key_den`).
    `osb_df`: DataFrame gốc từ `load_osb.load_osb_file` (chưa build khoá), hoặc `None`.
    """
    khoa = hub_df[KEY_COL]
    nhan = pd.Series("", index=hub_df.index)
    con_lai = pd.Series(True, index=hub_df.index)

    cac_buoc = []
    for off in OFFSET_CORE_KHI_XU_LY_HUB:
        core_df = core_theo_offset.get(off)
        cac_buoc.append((NHAN_HUB_KHOP_CORE[off], core_df[KEY_COL] if core_df is not None else None))
    _phan_loai_chuoi_khoa(khoa, con_lai, cac_buoc, nhan)

    if osb_df is not None and con_lai.any():
        khoa_osb = load_osb.build_key_osb(osb_df)
        khoa_hub_osb = load_osb.build_key_hub_osb(hub_df)
        idx = con_lai[con_lai].index
        mask_khop = _khop_min_count(khoa_hub_osb.loc[idx], khoa_osb)
        idx_khop = mask_khop[mask_khop].index
        if len(idx_khop):
            ngay_theo_khoa = (
                osb_df.assign(**{KEY_COL: khoa_osb})
                .drop_duplicates(KEY_COL)
                .set_index(KEY_COL)["Ngày hạch toán"]
            )
            ngay = khoa_hub_osb.loc[idx_khop].map(ngay_theo_khoa).fillna("")
            nhan.loc[idx_khop] = "OSB & " + ngay
            con_lai.loc[idx_khop] = False

    nhan.loc[con_lai] = NHAN_HUB_THUA
    return nhan
