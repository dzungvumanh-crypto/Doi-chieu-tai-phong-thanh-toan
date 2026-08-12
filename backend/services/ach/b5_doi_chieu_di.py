import pandas as pd


def _doi_chieu(df_npo: pd.DataFrame, key_npo: str,
               df_mis: pd.DataFrame, key_mis: str,
               label: str, log_callback=None):
    """
    Đối chiếu theo count (vectorized cumcount).
    Trả về (df_npo_khop, df_mis_khop, df_npo_thua, df_mis_thua).
    """
    grp_npo = df_npo.groupby(key_npo, sort=False)
    grp_mis = df_mis.groupby(key_mis, sort=False)
    cnt_npo = grp_npo.size()
    cnt_mis = grp_mis.size()

    common   = set(cnt_npo.index) & set(cnt_mis.index)
    dict_min = {k: min(int(cnt_npo[k]), int(cnt_mis[k])) for k in common}

    cc_npo      = grp_npo.cumcount()
    npo_min     = df_npo[key_npo].map(dict_min).fillna(0).astype(int)
    df_npo_khop = df_npo[cc_npo < npo_min].copy()
    df_npo_thua = df_npo[cc_npo >= npo_min].copy()

    cc_mis      = grp_mis.cumcount()
    mis_min     = df_mis[key_mis].map(dict_min).fillna(0).astype(int)
    df_mis_khop = df_mis[cc_mis < mis_min].copy()
    df_mis_thua = df_mis[cc_mis >= mis_min].copy()

    _log = log_callback or print
    _log(
        f'[{label}] Khớp: NPO={len(df_npo_khop):,} MIS={len(df_mis_khop):,} | '
        f'NPO thừa: {len(df_npo_thua):,} | MIS thừa: {len(df_mis_thua):,}'
    )
    return df_npo_khop, df_mis_khop, df_npo_thua, df_mis_thua


def doi_chieu_di(df_npo_di: pd.DataFrame, df_mis_di_final: pd.DataFrame, log_callback=None):
    """Đối chiếu chiều DI. Trả về (df_mis_di_khop, df_npo_di_thua, df_mis_di_thua)."""
    npo_k, mis_k, npo_t, mis_t = _doi_chieu(
        df_npo_di, 'KEY_DI',
        df_mis_di_final, 'KEY_HUB',
        'B5', log_callback,
    )
    return mis_k, npo_t, mis_t
