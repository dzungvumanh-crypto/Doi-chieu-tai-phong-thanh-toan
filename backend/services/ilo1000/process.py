"""Logic đối chiếu ILO1000: tính Trace, Map dc, phát hiện Hủy, điền TT."""

import pandas as pd

from .config import (
    HUB_COL_SO_GD, HUB_COL_STC, HUB_COL_TRACE, HUB_COL_TRACE2_RAW,
    HUB_COL_TRANG_THAI, HUB_COL_NGAY_GIO, HUB_COL_NOI_DUNG, HUB_COL_SO_TIEN,
)


def _safe_str(s) -> pd.Series:
    return s.fillna('').astype(str).str.strip()


def _first_match(keys: pd.Series, values: pd.Series) -> dict:
    """Giữ lần xuất hiện ĐẦU TIÊN của key — hành vi VLOOKUP của Excel."""
    mask = keys.astype(bool) & ~keys.duplicated(keep='first')
    return dict(zip(keys[mask], values[mask]))


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

    if df.empty:
        empty_dicts = {k: {} for k in ('stc_to_trace', 'trace_trangthai', 'trace_sotien')}
        return df, empty_dicts

    hub_to_core: dict = eicp_maps.get('hub_to_core', {})

    # ── Tính Trace ──
    # Theo tài liệu gốc: chỉ giao dịch có "Số giao dịch" chứa 'S' mới qua bước
    # BFX/EICP. Giao dịch KHÔNG chứa 'S' (chủ yếu loại "OT" — hoàn trả lệnh gốc)
    # dùng thẳng "Số Trace 2" — xác nhận qua đối chiếu dữ liệu thật 06/07/2026:
    # nhóm không chứa 'S' khớp 96,5% qua Số Trace 2 (so với chỉ 50% qua Số Trace 1);
    # riêng OT khớp 100% qua Số Trace 2.
    so_gd = _safe_str(df[HUB_COL_SO_GD])
    noi_dung = _safe_str(df[HUB_COL_NOI_DUNG])
    s_mask = so_gd.str.contains('S', case=False, na=False)
    bfx_mask = noi_dung.str.contains('BFX', case=False, na=False)
    # "Số giao dịch" chứa 'SMF' → không qua BFX/EICP (EICP xác nhận không có
    # entry nào cho SMF — build_eicp_maps() không tạo map_hub nào chứa 'SMF',
    # tra lúc nào cũng rỗng). Trước đây giữ nguyên Số Trace 1 (xác nhận từ
    # người dùng 2026-07-16) — SỬA 2026-09-07: dữ liệu thật batch 29/8-3/9
    # (người chấm Việt phát hiện) cho thấy rule đó SAI. Đối chiếu trực tiếp
    # pHub gốc cho 1 dòng SMF: Core REFERENCE "1000API200192551" nhưng Số
    # Trace 1 = "209326125" (không khớp gì), Số Trace 2 = "200192551" (khớp
    # đúng). Verify toàn batch: đổi SMF sang dùng Trace 2 giải quyết đúng
    # 155/156 dòng "chưa khớp" còn lại (130 → Hoàn thành, 25 → Chờ đi kênh),
    # không tạo lệch mới, không đổi số dòng khớp Citad. SMF giờ xử lý giống
    # nhóm không chứa 'S' — dùng thẳng Số Trace 2, không qua BFX/EICP.
    smf_mask = so_gd.str.contains('SMF', case=False, na=False)

    # Giá trị Trace ban đầu (Số Trace 1, từ pHub)
    trace = _safe_str(df[HUB_COL_TRACE]).copy()

    if HUB_COL_TRACE2_RAW in df.columns:
        trace2_raw = _safe_str(df[HUB_COL_TRACE2_RAW])
        use_trace2 = (~s_mask | smf_mask) & (trace2_raw != '')
        trace.loc[use_trace2] = trace2_raw.loc[use_trace2]

    # BFX (chỉ trong nhóm "Số giao dịch" chứa 'S'): right(nội dung, 16)
    bfx_apply_mask = s_mask & bfx_mask & ~smf_mask
    trace.loc[bfx_apply_mask] = noi_dung.loc[bfx_apply_mask].str[-16:]

    # Non-BFX trong nhóm 'S' (trừ SMF): lookup qua EICP, giữ nguyên Số Trace 1
    # nếu không tìm thấy. Map toàn bộ so_gd để tránh vấn đề index alignment khi
    # df đã bị filter.
    eicp_apply_mask = s_mask & ~bfx_mask & ~smf_mask
    eicp_all = so_gd.map(hub_to_core).fillna('')
    update_mask = eicp_apply_mask & (eicp_all != '')
    trace.loc[update_mask] = eicp_all.loc[update_mask]

    df['Trace'] = trace.values

    # Trace thuần chữ số có thể có số 0 thừa ở đầu tùy đợt export pHub (VD "063403118"
    # vs "63403118" — cùng 1 giá trị nhưng khác text) — Core tính Trace độc lập từ
    # REFERENCE không có số 0 đầu, khiến Map dc (ghép chuỗi) không khớp dù cùng giao dịch.
    # Chỉ strip cho Trace toàn chữ số — không đụng Trace BFX/EICP (có ký tự chữ, có ý nghĩa).
    numeric_mask = df['Trace'].str.match(r'^\d+$', na=False)
    stripped = df['Trace'].str.lstrip('0')
    stripped = stripped.mask(stripped == '', '0')
    df.loc[numeric_mask, 'Trace'] = stripped[numeric_mask]

    df['Trace2'] = pd.to_numeric(df['Trace'], errors='coerce')

    # ── Ngày (ngày trong tháng) — parse đầy đủ vì ngày đơn digit "5/05/..." bị lỗi khi dùng str[:2] ──
    ngay_gio = _safe_str(df[HUB_COL_NGAY_GIO])
    df['Ngày'] = pd.to_datetime(ngay_gio, dayfirst=True, errors='coerce').dt.day.astype(float)

    # ── Flag "Chờ đi kênh": ngày > ngày đối chiếu (giao dịch xử lý sau ngày đối chiếu) ──
    ngay_dc_day = ngay_int % 100  # DD
    after_mask = df['Ngày'].fillna(0) > ngay_dc_day
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
    # Fix chính đã chạy sớm hơn, ở load_citad.py::_load_one() (TRƯỚC khi gộp
    # 5 cổng + dedup theo SERIAL_NO — bắt buộc theo đúng thứ tự nghiệp vụ, xem
    # comment ở đó). Giữ lại ở đây làm lưới an toàn cho caller không qua
    # load_citad() — no-op nếu AMOUNT đã sạch.
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

def detect_huy(df: pd.DataFrame) -> dict:
    """
    Phát hiện giao dịch Hủy: gom theo (REFERENCE, TRBRCD). Hai tín hiệu ĐỘC
    LẬP, kết hợp OR (một mình tín hiệu (1) không đủ — xem lý do dưới):

    1. Tổng Nợ = tổng Có trong batch (net-zero) — bắt được khi CẢ vế gốc lẫn vế
       hủy cùng nằm trong batch đang xử lý (`df` nên là Core GỘP TOÀN BỘ các
       ngày trong batch, không phải chỉ 1 ngày).
    2. Có ít nhất 1 dòng CRAMOUNT < 0 — bản dịch trực tiếp quy tắc docx gốc
       "nếu Số tiền (-) thì là hủy lệnh ngày cũ". Bắt được cả khi vế gốc (+X)
       nằm ở một ngày KHÔNG được nạp trong batch hiện tại — Core (khác
       Hub/Eicp) không có carryover T-1, nên khi đó net ≠ 0 và tín hiệu (1)
       một mình bỏ sót ca này. Xác nhận qua dữ liệu thật 11-12/8/2026: 91
       REFERENCE có CRAMOUNT âm, 47/91 (52%) không có vế gốc dương cùng
       REFERENCE trong batch 2 ngày đó — đúng số ca tín hiệu (1) bỏ sót.

    Xác nhận nghiệp vụ 2026-07-16: "Hủy" và "Đã hủy" là 2 trạng thái KHÁC NHAU
    (không phải lỗi gõ tay như từng nhầm tưởng trước đó):
    - 'Hủy'    — net-zero VÀ ngày lập/ngày hủy CÙNG 1 ngày (TRDATE)
    - 'Đã hủy' — mọi trường hợp còn lại (khác ngày, hoặc thiếu vế gốc trong batch)

    Gộp thêm TRBRCD vào khóa nhóm (không chỉ REFERENCE) — xác nhận qua phản
    hồi người chấm + dữ liệu thật 26/8/2026: các lệnh chi trả trợ cấp xã hội
    hàng loạt (REFERENCE dạng "1000OTT...") dùng CHUNG một REFERENCE giữa
    NHIỀU chi nhánh khác nhau trong cùng batch (VD "1000OTT261006174" xuất
    hiện ở cả 3 chi nhánh 1410/2008/5708). Chỉ 1 chi nhánh (2008) có cặp
    Nợ/Có net-zero thật sự là hủy lệnh; nếu gom theo REFERENCE một mình, tín
    hiệu hủy của chi nhánh đó lây lan sai sang 2 chi nhánh còn lại (giao dịch
    bình thường, khớp Hub "Hoàn thành") — khiến core bị gắn nhầm 'Đã hủy'.

    Trả về dict (REFERENCE, TRBRCD) → 'Hủy' | 'Đã hủy'.
    """
    if df.empty or 'REFERENCE' not in df.columns:
        return {}

    ref    = _safe_str(df['REFERENCE'])
    brcd   = _safe_str(df.get('TRBRCD', pd.Series('', index=df.index)))
    dr     = pd.to_numeric(df.get('DRAMOUNT', 0), errors='coerce').fillna(0)
    cr     = pd.to_numeric(df.get('CRAMOUNT', 0), errors='coerce').fillna(0)
    trdate = _safe_str(df.get('TRDATE', pd.Series('', index=df.index)))

    tmp = pd.DataFrame({'REFERENCE': ref, 'TRBRCD': brcd, '_DR': dr, '_CR': cr, '_TRDATE': trdate})
    tmp = tmp[tmp['REFERENCE'] != '']
    tmp['_KEY'] = list(zip(tmp['REFERENCE'], tmp['TRBRCD']))

    sums   = tmp.groupby('_KEY', sort=False)[['_DR', '_CR']].sum()
    n_days = tmp.groupby('_KEY', sort=False)['_TRDATE'].nunique()

    net_zero_keys = set(sums[sums['_CR'] - sums['_DR'] == 0].index)
    neg_cr_keys   = set(tmp.loc[tmp['_CR'] < 0, '_KEY'])
    huy_keys      = net_zero_keys | neg_cr_keys

    def _label(k) -> str:
        if k in net_zero_keys and n_days.get(k, 1) <= 1:
            return 'Hủy'
        return 'Đã hủy'

    return {k: _label(k) for k in huy_keys}


def process_core(
    core_df: pd.DataFrame,
    citad_mapdc: dict,
    hub_lookups: dict,
    ngay_int: int,
    huy_map: dict | None = None,
) -> pd.DataFrame:
    """
    Điền Trace, Map dc, TT cho sheet Core.
    `huy_map` ((REFERENCE, TRBRCD) → 'Hủy'/'Đã hủy') nên được tính trước trên
    Core GỘP toàn batch bằng detect_huy() rồi truyền vào, để bắt được cả Hủy
    khác ngày. Nếu không truyền (VD gọi lẻ trong test), tự tính trên chính
    core_df này — khi đó chỉ phát hiện được Hủy cùng ngày (đúng theo dữ liệu
    đang có).
    """
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

    if huy_map is None:
        huy_map = detect_huy(df)

    # ── Tính TT theo thứ tự ưu tiên ──
    tt = pd.Series('', index=df.index)

    # 1. Hủy / Đã hủy — khóa (REFERENCE, TRBRCD), xem detect_huy()
    huy_key   = pd.Series(list(zip(ref, brcd)), index=df.index)
    huy_label = huy_key.map(huy_map)
    huy_mask  = huy_label.notna()
    tt[huy_mask] = huy_label[huy_mask]

    # 1.5. HI type (Quyết toán) — giao dịch quyết toán, không cần tra Hub/Citad
    qt_mask = (tt == '') & (df['Trace'] == 'Quyết toán')
    tt[qt_mask] = 'quyết toán'

    # 1.6. Kênh OSB — REMARK chứa "IBPSILO" là giao dịch kênh OSB, không thuộc
    # phạm vi đối chiếu Citad/Hub của ILO1000 (sẽ có module Chấm TK OSB riêng
    # sau này). Xác nhận qua dữ liệu thật 04-06/7/2026: 3/3 dòng IBPSILO đều
    # được bài chấm tay ghi TT = "OSB", không dòng nào trùng điều kiện Hủy —
    # nên chỉ gán cho dòng CHƯA có TT, không ghi đè Hủy/Quyết toán.
    remark = _safe_str(df.get('REMARK', pd.Series('', index=df.index)))
    osb_mask = (tt == '') & remark.str.contains('IBPSILO', case=False, na=False)
    tt[osb_mask] = 'OSB'

    # 2. Khớp CITAD qua Map dc (TRBRCD + Trace + AMOUNT)
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


def used_citad_keys(core_out: pd.DataFrame, citad_mapdc: dict) -> set:
    """
    Tập các `Map dc` Citad đã thực sự được ít nhất 1 dòng Core CHỌN TRÚNG để
    gán TT — không phải mọi key có mặt trong `citad_mapdc` (dict chứa TOÀN BỘ
    Citad, kể cả những dòng không có Core nào tra tới, hoặc có tra tới nhưng
    bị ưu tiên cao hơn — Hủy/Quyết toán/OSB — ghi đè trước bước khớp Citad).

    Chỉ dựa vào `core_out` (đã có TT) + `citad_mapdc`, không cần sửa
    `process_core()` — tránh đổi chữ ký hàm đang được gọi ở rất nhiều test.
    """
    if core_out.empty or 'Map dc' not in core_out.columns:
        return set()
    map_dc = core_out['Map dc'].astype(str)
    citad_label = map_dc.map(citad_mapdc)
    really_used = core_out['TT'].astype(str) == citad_label.fillna('\0__none__')
    return set(map_dc[really_used])


def match_citad_leftover_with_osb(
    citad_df: pd.DataFrame,
    used_citad_mapdc: set,
    osb_key: 'pd.Series | None' = None,
) -> pd.DataFrame:
    """
    Với các dòng Citad CÒN THỪA (Map dc KHÔNG nằm trong `used_citad_mapdc` —
    Core không khớp trúng), so trực tiếp với tập khóa OSB (`osb_key`, xem
    `load_osb.build_osb_key()`). Thêm cột 'TT': 'OSB' nếu khớp; để RỖNG nếu
    vẫn còn thừa sau cả Core lẫn OSB — không tự suy luận thêm, xuất cho người
    chấm tay xem xét (đúng nguyên tắc "không có định danh đáng tin → xuất
    toàn bộ nhóm cho người dùng chấm tay").

    Dòng Citad ĐÃ khớp Core (Map dc nằm trong `used_citad_mapdc`) không đụng
    tới cột 'TT' (giữ rỗng) — đã được coi là xử lý xong ở sheet Core.

    Giữ nguyên hàm này (không đụng) cho tương thích ngược — pipeline thật đã
    chuyển sang dùng `label_citad_provenance()` (đầy đủ hơn: phân biệt được
    khớp Core hôm nay / khớp pool Core thừa cũ / khớp OSB hôm nay / khớp pool
    OSB thừa cũ / không khớp gì), xem module docstring phần "Pool tồn đọng
    xuyên batch" bên dưới.
    """
    df = citad_df.copy()
    df['TT'] = ''

    if df.empty or 'Map dc' not in df.columns:
        return df

    map_dc = df['Map dc'].astype(str)
    leftover_mask = ~map_dc.isin(used_citad_mapdc)
    if not leftover_mask.any() or osb_key is None or osb_key.empty:
        return df

    osb_key_set = set(osb_key.astype(str))
    matched = leftover_mask & map_dc.isin(osb_key_set)
    df.loc[matched, 'TT'] = 'OSB'
    return df


# ── Pool tồn đọng xuyên batch (Core thừa / OSB thừa) ─────────────────────────
# Bổ sung theo tài liệu "CÁC BƯỚC LÀM ĐỐI CHIẾU ILO" (mục "Tại bảng chấm"
# B1-B3) + đối chiếu dữ liệu chấm tay thật 09.09.2026 của người chấm Việt.
#
# Người chấm tay giữ 2 file "Core thừa {nhãn}.xlsx" / "OSB thừa {nhãn}.xlsx"
# SỐNG XUYÊN NHIỀU LẦN CHẤM (nhiều batch input khác nhau) — mỗi lần chấm 1
# batch mới, các dòng Core/OSB của batch TRƯỚC chưa kịp đi kênh được nạp lại
# làm input phụ, so với Citad của batch MỚI; dòng nào khớp thì coi là xong,
# dòng nào chưa khớp thì tiếp tục mang sang batch sau nữa (có thể mang qua
# NHIỀU batch liên tiếp — xác nhận qua dữ liệu thật: pool "Core thừa 5-8.9"
# vẫn còn lẫn 9 dòng TRDATE 25/08 và 28/08, tức đã tồn đọng qua hơn 1 lần
# chấm trước đó, không phải chỉ mới sinh từ batch 5-8/9).
#
# QUYẾT ĐỊNH THIẾT KẾ (xem docs/Implementation-notes.html): nhãn dải ngày
# ("5-8.9", "9.9"...) tính từ NGÀY CỦA BATCH ĐANG XỬ LÝ (input đưa vào lần
# chấm đó), KHÔNG PHẢI từ TRDATE thật của các dòng còn tồn đọng bên trong —
# xác nhận qua dữ liệu thật: pool "Core thừa 5-8.9.xlsx" chứa 16.658 dòng
# nhưng TRDATE phân bố {25/08: 1, 28/08: 8, 07/09: 4, 08/09: 16.645} — nếu
# tính nhãn theo min-max TRDATE thực tế sẽ ra "25.8-8.9", sai với nhãn thật
# "5-8.9" (đúng bằng dải ngày batch 5-8/9 đã được chấm, bất kể trong đó có
# lẫn stragglers rất cũ từ nhiều batch trước nữa).


def build_pool_label(days: 'list' = None) -> str:
    """
    Nhãn dải ngày kiểu "5-8.9" (nhiều ngày cùng tháng), "9.9" (1 ngày), hoặc
    "25.8-8.9" (khác tháng) — tính từ danh sách `datetime.date` của các ngày
    ĐÃ XỬ LÝ trong batch (không phải từ TRDATE của dữ liệu tồn đọng, xem
    comment ở trên). `days` rỗng/None → trả chuỗi rỗng.
    """
    if not days:
        return ''
    days = sorted(days)
    lo, hi = days[0], days[-1]
    if lo == hi:
        return f'{lo.day}.{lo.month}'
    if lo.month == hi.month:
        return f'{lo.day}-{hi.day}.{lo.month}'
    return f'{lo.day}.{lo.month}-{hi.day}.{hi.month}'


def build_mapdc_label_map(df: pd.DataFrame, mapdc_col: str, label: str) -> dict:
    """
    {Map dc → `label`} cho TOÀN BỘ dòng của 1 pool (Core thừa hoặc OSB thừa
    hoặc OSB hôm nay) — cả pool dùng CHUNG 1 nhãn (không phải tính riêng theo
    từng dòng), nên không cần giữ "lần đầu tiên" như `_first_match()`.
    """
    if df is None or df.empty or mapdc_col not in df.columns:
        return {}
    keys = df[mapdc_col].astype(str)
    keys = keys[keys != '']
    if keys.empty:
        return {}
    return dict.fromkeys(keys, label)


# TT của Core coi là ĐÃ XỬ LÝ XONG (không phải "còn chờ đi kênh") — mọi giá
# trị khác (kể cả rỗng, kể cả nhãn Trạng thái thô từ Hub như "Chờ đi kênh"
# HOẶC "Hoàn thành") vẫn phải mang sang pool "Core thừa" của batch sau. Xem
# process_core(): nhãn 'citad {d}.{m}' sinh ở bước khớp Citad, 'Hủy'/'Đã
# hủy'/'quyết toán'/'OSB' sinh ở bước 1/1.5/1.6 — CHỈ 4 GIÁ TRỊ NÀY coi là
# xong, không thêm bất kỳ giá trị Trạng thái thô nào khác của Hub.
#
# 'Hoàn thành' CỐ Ý KHÔNG nằm trong danh sách — xác nhận trực tiếp từ người
# chấm Việt (2026-09-13): Trạng thái Hub phản ánh TÌNH TRẠNG TẠI THỜI ĐIỂM
# TRA CỨU, không phải tại thời điểm đang chấm. "Chấm ngày 3, những lệnh đi
# SAU ngày 3 (cả 'hoàn thành' hay 'chờ đi kênh') đều phải theo dõi, vì ngày 4
# đi là ngày chờ đi kênh CỦA NGÀY 3, nhưng tại thời điểm tra cứu nó ĐÃ hoàn
# thành." Và: "Nếu chấm hàng ngày, sáng tra dữ liệu ngay thì ít tình trạng
# lung tung; để 1-2 ngày mới tra thì 'chờ đi kênh' sẽ tự chuyển thành 'hoàn
# thành'." Tức 'Hoàn thành' KHÔNG chứng minh giao dịch đã đi kênh ĐÚNG NGÀY
# đang chấm — chỉ chứng minh nó đã đi kênh TRƯỚC thời điểm tra cứu (có thể là
# hôm sau, hôm sau nữa). Coi 'Hoàn thành' là "xong" sẽ làm mất dấu các giao
# dịch thật sự thuộc phiên "chờ đi kênh" của ngày đang chấm.
#
# (Từng có 1 lần SỬA SAI thêm 'Hoàn thành' vào đây — suy diễn từ việc 2 dòng
# 'Hoàn thành' không xuất hiện trong 1 mẫu pool CỦA BATCH KHÁC, KHÔNG PHẢI
# bằng chứng đủ mạnh. Đã tự sửa lại đúng khi được Việt xác nhận trực tiếp —
# bài học: không suy diễn ý nghĩa 1 giá trị dữ liệu thô từ 1 mẫu nhỏ, phải
# hỏi khi chưa chắc, xem SKILL.md.)
#
# 'Đã hủy' CŨNG có thể cần xem lại tương tự (Việt: "nhiều khi tổng Đã hủy
# không bằng 0... làm sau [khác ngày] có thể 2-3 ngày sau mới hủy... tổng
# không bằng 0 cũng phải tìm [nguyên nhân]") — tức 1 dòng 'Đã hủy' riêng lẻ
# không chắc đã "xong" nếu group (REFERENCE, TRBRCD) của nó chưa net về 0.
# CHƯA SỬA phần này — Việt đang xem lại, sẽ xác nhận thêm; xem
# project_ilo1000_pool_ton_dong_xuyen_batch_2026-09-13 (memory).
_CORE_TT_DA_XONG = {'Hủy', 'Đã hủy', 'quyết toán', 'OSB'}


def is_core_tt_resolved(tt) -> bool:
    """True nếu dòng Core này đã coi là xử lý xong, không cần mang sang pool
    'Core thừa' nữa (đã khớp Citad hôm nay, hoặc Hủy/Đã hủy/quyết toán/OSB —
    CỐ Ý KHÔNG gồm 'Hoàn thành', xem cảnh báo ở `_CORE_TT_DA_XONG`)."""
    s = ('' if tt is None else str(tt)).strip()
    if s in _CORE_TT_DA_XONG:
        return True
    return s.lower().startswith('citad ')


def build_core_thua_pool(core_out: pd.DataFrame) -> pd.DataFrame:
    """Lọc `core_out` (đã có cột 'TT' từ `process_core()`) về đúng các dòng
    còn CHỜ ĐI KÊNH thật sự — nguyên liệu để gộp vào pool 'Core thừa' mang
    sang batch chấm sau (xem `build_core_thua_forward()`)."""
    if core_out.empty or 'TT' not in core_out.columns:
        return core_out.iloc[0:0].copy()
    resolved = core_out['TT'].map(is_core_tt_resolved)
    return core_out.loc[~resolved].copy()


def build_core_thua_forward(
    old_pool_df: pd.DataFrame,
    new_leftover_df: pd.DataFrame,
    doi_chieu_col: str = 'Đối chiếu',
) -> pd.DataFrame:
    """
    Pool 'Core thừa' MỚI mang sang batch kế tiếp = (dòng pool CŨ mà cột
    `doi_chieu_col` VẪN CÒN chưa khớp — rỗng hoặc '#N/A') HỢP (dòng Core mới
    còn chờ đi kênh của chính batch vừa chấm, xem `build_core_thua_pool()`).
    Dòng pool cũ ĐÃ khớp (có `doi_chieu_col` là 1 ngày cụ thể) bị LOẠI — coi
    là xử lý xong, không mang tiếp.
    """
    old_unresolved = pd.DataFrame()
    if old_pool_df is not None and not old_pool_df.empty:
        if doi_chieu_col in old_pool_df.columns:
            col = old_pool_df[doi_chieu_col]
            dc = col.where(col.notna(), '').astype(str).str.strip()
            old_unresolved = old_pool_df.loc[(dc == '') | (dc == '#N/A')].copy()
        else:
            # Pool cũ chưa từng qua vòng đối chiếu nào (chưa có cột này) —
            # coi như toàn bộ còn tồn đọng, không loại dòng nào.
            old_unresolved = old_pool_df.copy()

    parts = [d for d in (old_unresolved, new_leftover_df) if d is not None and not d.empty]
    if not parts:
        return pd.DataFrame()
    result = pd.concat(parts, ignore_index=True)

    # BẮT BUỘC cột `doi_chieu_col` luôn có mặt trong kết quả, kể cả khi
    # `old_pool_df` rỗng (lần đầu bật tính năng, hoặc pool vừa sạch) — dòng
    # Core/OSB leftover mới phát sinh trong CHÍNH batch này chưa từng có cột
    # này (đến từ `process_core()`/dữ liệu OSB thô). Thiếu cột này thì file
    # xuất ra ở round này sẽ KHÔNG được `detect.py::_sniff_pool_xlsx()` nhận
    # diện là pool ở round SAU (yêu cầu bắt buộc có cột 'Đối chiếu') — toàn bộ
    # tồn đọng của round này lặng lẽ biến mất khỏi pool, không log không lỗi
    # (phát hiện qua phản biện Agent vòng 2, 2026-09-13, tái lập được bằng
    # code thật — xem docs/Implementation-notes.html card 122).
    if doi_chieu_col not in result.columns:
        result[doi_chieu_col] = '#N/A'
    else:
        result[doi_chieu_col] = result[doi_chieu_col].where(result[doi_chieu_col].notna(), '#N/A')
        blank_mask = result[doi_chieu_col].astype(str).str.strip() == ''
        result.loc[blank_mask, doi_chieu_col] = '#N/A'

    return result


def mark_pool_doi_chieu(
    map_dc: pd.Series,
    existing: 'pd.Series | None',
    citad_mapdc_keys: set,
    ngay_int: int,
) -> pd.Series:
    """
    Điền cột 'Đối chiếu' cho pool tồn đọng (Core thừa/OSB thừa): dòng nào
    CHƯA khớp (`existing` rỗng hoặc '#N/A') mà `map_dc` nằm trong
    `citad_mapdc_keys` (Map dc của Citad batch đang chấm) → ghi `ngay_int`;
    còn lại → '#N/A'. Dòng ĐÃ khớp từ trước (`existing` là 1 ngày cụ thể)
    giữ NGUYÊN, không bị ghi đè lại thành '#N/A' — 1 khi đã xác nhận đi kênh
    thành công thì không "quên" ở lần chấm sau.
    """
    map_dc = map_dc.astype(str)
    if existing is None:
        existing = pd.Series([''] * len(map_dc), index=map_dc.index)
    existing_s = existing.where(existing.notna(), '').astype(str).str.strip()
    already_resolved = ~existing_s.isin(('', '#N/A'))

    result = pd.Series(index=map_dc.index, dtype=object)
    result.loc[already_resolved] = existing.loc[already_resolved]

    pending = ~already_resolved
    matched = pending & map_dc.isin(citad_mapdc_keys)
    result.loc[matched] = ngay_int
    result.loc[pending & ~matched] = '#N/A'
    return result


def used_label_map_keys(tt: pd.Series, map_dc: pd.Series, label_map: dict) -> set:
    """
    Tổng quát hóa `used_citad_keys()` cho hướng ngược lại: tập các Map dc
    trong `label_map` THỰC SỰ được ít nhất 1 dòng (của `tt`/`map_dc`, cùng
    index) chọn trúng — tức `tt == label_map[map_dc]`. Dùng để biết dòng OSB
    hôm nay/pool nào đã bị 1 dòng Citad "tiêu thụ" (gán TT bằng đúng nhãn của
    nó), tránh nhầm với key có mặt trong `label_map` nhưng bị nhãn ưu tiên cao
    hơn (Core hôm nay, Core thừa pool) ghi đè trước — xem `label_citad_provenance()`.
    """
    if tt is None or len(tt) == 0 or not label_map:
        return set()
    mapped = map_dc.astype(str).map(label_map)
    really_used = tt.astype(str) == mapped.fillna('\0__none__')
    return set(map_dc.astype(str)[really_used])


def label_citad_provenance(
    citad_df: pd.DataFrame,
    used_citad_mapdc: set,
    ngay_int: int,
    core_pool_label_map: 'dict | None' = None,
    osb_today_label_map: 'dict | None' = None,
    osb_pool_label_map: 'dict | None' = None,
) -> pd.Series:
    """
    Cột TT của SHEET CITAD (khác nghĩa cột TT của sheet Core) — cho biết mỗi
    dòng Citad khớp trúng nguồn nào: (1) Core hôm nay → ghi `ngay_int`; (2)
    pool Core thừa cũ → nhãn có sẵn trong `core_pool_label_map` (VD "Core
    5-8.9"); (3) OSB hôm nay → nhãn trong `osb_today_label_map`; (4) pool OSB
    thừa cũ → nhãn trong `osb_pool_label_map`; còn lại → RỖNG (= "Citad thừa"
    của ngày này, xuất riêng cho người chấm tay điều tra tiếp — không tự suy
    luận thêm).

    Bước (1)→(2) ĐÚNG thứ tự tài liệu gốc (mục "Tại bảng chấm" B1: lọc N/A
    rồi mới Vlookup Core thừa). Thứ tự (3) trước (4) — OSB hôm nay ưu tiên
    hơn pool OSB cũ — là LỰA CHỌN CỦA CODE, KHÔNG PHẢI mô tả trong tài liệu:
    docx chỉ có 1 bước Vlookup duy nhất trên 1 sheet đã DÁN GỘP OSB cũ+mới
    làm chung ("Tạo cột Đối chiếu: Copy Phần OSB ngày T-1... sang"), không
    tách 2 mức ưu tiên riêng. Phản biện Agent vòng 2 (2026-09-13) xác nhận:
    dữ liệu mẫu thật (`Cham OSB` 09.09) có 0 khóa Map dc trùng giữa OSB hôm
    nay và pool OSB cũ — nên thứ tự (3)/(4) CHƯA từng ảnh hưởng kết quả thật,
    nhưng CHƯA được Việt xác nhận nếu có va chạm thật trong tương lai (xem
    câu hỏi A2 gửi Việt).
    """
    if citad_df.empty or 'Map dc' not in citad_df.columns:
        return pd.Series(dtype=object)

    map_dc = citad_df['Map dc'].astype(str)
    tt = pd.Series('', index=citad_df.index, dtype=object)

    remaining = ~map_dc.isin(used_citad_mapdc)
    tt.loc[~remaining] = ngay_int

    for label_map in (core_pool_label_map, osb_today_label_map, osb_pool_label_map):
        if not label_map or not remaining.any():
            continue
        found = remaining & map_dc.isin(label_map)
        if found.any():
            tt.loc[found] = map_dc.loc[found].map(label_map)
            remaining = remaining & ~found

    return tt
