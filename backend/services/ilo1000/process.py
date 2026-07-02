"""Logic đối chiếu ILO1000: tính Trace, Map dc, phát hiện Hủy, điền TT."""

import pandas as pd

from .config import (
    HUB_COL_SO_GD, HUB_COL_STC, HUB_COL_TRACE,
    HUB_COL_TRANG_THAI, HUB_COL_NGAY_GIO, HUB_COL_NOI_DUNG, HUB_COL_SO_TIEN,
)


def _safe_str(s) -> pd.Series:
    return s.fillna('').astype(str).str.strip()


def _first_match(keys: pd.Series, values: pd.Series) -> dict:
    """Giữ lần xuất hiện ĐẦU TIÊN của key — hành vi VLOOKUP của Excel."""
    d: dict = {}
    for k, v in zip(keys, values):
        if k and k not in d:
            d[k] = v
    return d


# ── HUB ──────────────────────────────────────────────────────────────────────

def process_hub(hub_df: pd.DataFrame, eicp_maps: dict, ngay_int: int) -> tuple[pd.DataFrame, dict]:
    """
    Trả về (hub_df đã xử lý, lookup_dicts).
    lookup_dicts = {
        'stc_to_trace':    {STC → Trace text}  ← để citad dùng
        'trace_trangthai': {Trace text → Trạng thái}
        'trace_sotien':    {Trace text → Số tiền}
    }
    """
    df = hub_df.copy()

    # ── Filter: Số giao dịch contains 'S' ──
    so_gd = _safe_str(df[HUB_COL_SO_GD])
    df = df[so_gd.str.contains('S', na=False)].copy()

    if df.empty:
        empty_dicts = {k: {} for k in ('stc_to_trace', 'trace_trangthai', 'trace_sotien')}
        return df, empty_dicts

    hub_to_core: dict = eicp_maps.get('hub_to_core', {})

    # ── Tính Trace ──
    noi_dung = _safe_str(df[HUB_COL_NOI_DUNG])
    bfx_mask = noi_dung.str.contains('BFX', case=False, na=False)

    # Giá trị Trace ban đầu (từ pHub)
    trace = _safe_str(df[HUB_COL_TRACE])

    # BFX: right(nội dung, 16)
    trace.loc[bfx_mask] = noi_dung.loc[bfx_mask].str[-16:]

    # Non-BFX: lookup qua EICP, giữ nguyên nếu không tìm thấy
    # Map toàn bộ so_gd để tránh vấn đề index alignment khi df đã bị filter
    not_bfx = ~bfx_mask
    eicp_all = _safe_str(df[HUB_COL_SO_GD]).map(hub_to_core).fillna('')
    update_mask = not_bfx & (eicp_all != '')
    trace = trace.copy()
    trace.loc[update_mask] = eicp_all.loc[update_mask]

    df['Trace'] = trace.values
    df['Trace2'] = pd.to_numeric(df['Trace'], errors='coerce')

    # ── Ngày (ngày trong tháng, lấy 2 ký tự đầu của cột Ngày giờ kênh trả) ──
    ngay_gio = _safe_str(df[HUB_COL_NGAY_GIO])
    df['Ngày'] = pd.to_numeric(ngay_gio.str[:2], errors='coerce')

    # ── Flag "Chờ đi kênh": ngày > ngày đối chiếu + 1 ──
    ngay_dc_day = ngay_int % 100  # DD
    after_mask = df['Ngày'].fillna(0) > ngay_dc_day + 1
    df.loc[after_mask, HUB_COL_TRANG_THAI] = 'Chờ đi kênh'

    df['ngay'] = ngay_int

    # ── Build lookup dicts ──
    stc   = _safe_str(df[HUB_COL_STC])
    trace_col  = df['Trace'].fillna('').astype(str)
    tt_col     = _safe_str(df[HUB_COL_TRANG_THAI])
    sotien_col = _safe_str(df[HUB_COL_SO_TIEN])

    # Giữ lần xuất hiện đầu tiên — VLOOKUP behavior
    stc_to_trace    = _first_match(stc,       trace_col)
    trace_trangthai = _first_match(trace_col, tt_col)
    trace_sotien    = _first_match(trace_col, sotien_col)

    lookups = {
        'stc_to_trace':    stc_to_trace,
        'trace_trangthai': trace_trangthai,
        'trace_sotien':    trace_sotien,
    }
    return df, lookups


# ── CITAD ─────────────────────────────────────────────────────────────────────

def process_citad(citad_df: pd.DataFrame, hub_lookups: dict, ngay_int: int) -> tuple[pd.DataFrame, dict]:
    """
    Trả về (citad_df đã xử lý, citad_mapdc_to_ngay dict).
    """
    df = citad_df.copy()

    # ── Clean AMOUNT: "ltd" → lấy từ TRX_STATUS ──
    amount_str = _safe_str(df['AMOUNT'])
    ltd_mask = amount_str.str.lower().str.contains('ltd', na=False)
    df.loc[ltd_mask, 'AMOUNT'] = _safe_str(df.loc[ltd_mask, 'TRX_STATUS'])
    df['AMOUNT'] = pd.to_numeric(df['AMOUNT'], errors='coerce').fillna(0)

    # ── Trace: vlookup(SERIAL_NO, hub!STC→Trace) ──
    stc_to_trace = hub_lookups.get('stc_to_trace', {})
    serial = _safe_str(df['SERIAL_NO'])
    df['Trace'] = serial.map(stc_to_trace).fillna('')

    # ── Map đối chiếu: LEFT(RELATION_NO, 4) & Trace & AMOUNT ──
    rel4 = _safe_str(df['RELATION_NO']).str[:4]
    trace_s = df['Trace'].fillna('').astype(str)
    amount_s = df['AMOUNT'].fillna(0).astype(int).astype(str)
    df['Map dc'] = rel4 + trace_s + amount_s

    df['Ngày'] = ngay_int

    # Label TT cho citad match: 'citad {day}.{month}' — khớp format thủ công
    day   = ngay_int % 100
    month = (ngay_int // 100) % 100
    citad_label = f'citad {day}.{month}'

    # ── Build lookup: Map dc → label citad (để core tra TT) — giữ first match ──
    citad_label_series = pd.Series(citad_label, index=df.index)
    mapdc_to_ngay = _first_match(df['Map dc'], citad_label_series)

    return df, mapdc_to_ngay


# ── CORE ──────────────────────────────────────────────────────────────────────

def process_core(
    core_df: pd.DataFrame,
    citad_mapdc: dict,
    hub_lookups: dict,
    ngay_int: int,
) -> pd.DataFrame:
    """Điền Trace, Map dc, TT cho sheet Core."""
    df = core_df.copy()

    ref  = _safe_str(df.get('REFERENCE', pd.Series('', index=df.index)))
    brcd = _safe_str(df.get('TRBRCD',    pd.Series('', index=df.index)))

    # ── Tính Trace từ REFERENCE ──
    api_mask = ref.str.contains('API', case=False, na=False)
    ott_mask = ref.str.contains('OTT', case=False, na=False) & ~api_mask
    bfx_mask = ref.str.contains('BFX', case=False, na=False) & ~api_mask & ~ott_mask
    hi_mask  = ref.str.contains('HI', na=False) & ~api_mask & ~ott_mask & ~bfx_mask

    trace = pd.Series('', index=df.index)
    trace[api_mask] = ref[api_mask].str[7:23]
    trace[ott_mask] = brcd[ott_mask] + ref[ott_mask].str[4:16]
    trace[bfx_mask] = brcd[bfx_mask] + ref[bfx_mask].str[4:16]
    trace[hi_mask]  = 'Quyết toán'

    df['Trace']  = trace
    df['Trace2'] = pd.to_numeric(trace, errors='coerce')

    # ── Map đối chiếu: TRBRCD & Trace & CRAMOUNT ──
    cramount = pd.to_numeric(df.get('CRAMOUNT', 0), errors='coerce').fillna(0).astype(int)
    df['Map dc']  = brcd + trace + cramount.astype(str)
    df['Ngày']    = ngay_int

    # ── Phát hiện "Hủy" (pivot: CRAMOUNT_sum - DRAMOUNT_sum == 0) ──
    dr = pd.to_numeric(df.get('DRAMOUNT', 0), errors='coerce').fillna(0)
    cr = pd.to_numeric(df.get('CRAMOUNT', 0), errors='coerce').fillna(0)
    df['_DR'] = dr
    df['_CR'] = cr

    grp = df.groupby('REFERENCE', sort=False)[['_DR', '_CR']].sum()
    huy_set = set(grp[grp['_CR'] - grp['_DR'] == 0].index)
    df.drop(columns=['_DR', '_CR'], inplace=True)

    # ── Tính TT theo thứ tự ưu tiên ──
    tt = pd.Series('', index=df.index)

    # 1. Hủy
    huy_mask = df['REFERENCE'].isin(huy_set)
    tt[huy_mask] = 'Hủy'

    # 1.5. HI type (Quyết toán) — giao dịch quyết toán, không cần tra Hub/Citad
    qt_mask = (tt == '') & (df['Trace'] == 'Quyết toán')
    tt[qt_mask] = 'quyết toán'

    # 2. Khớp CITAD qua Map dc
    mask = tt == ''
    if mask.any():
        citad_result = df.loc[mask, 'Map dc'].astype(str).map(citad_mapdc)
        found_idx = citad_result.dropna().index
        tt.loc[found_idx] = citad_result.loc[found_idx].astype(str)

    # 3. Khớp Hub qua Trace → Trạng thái
    trace_tt   = hub_lookups.get('trace_trangthai', {})
    trace_sot  = hub_lookups.get('trace_sotien',    {})

    mask = tt == ''
    if mask.any():
        hub_result = df.loc[mask, 'Trace'].astype(str).map(trace_tt)
        found_idx  = hub_result.dropna().index
        tt.loc[found_idx] = hub_result.loc[found_idx].astype(str)

    # 4. Khớp Hub qua Trace → Số tiền (fallback cuối)
    mask = tt == ''
    if mask.any():
        hub_result2 = df.loc[mask, 'Trace'].astype(str).map(trace_sot)
        found_idx   = hub_result2.dropna().index
        tt.loc[found_idx] = hub_result2.loc[found_idx].astype(str)

    df['TT'] = tt
    return df
