import pandas as pd


def phan_tich(df_npo_di_thua, df_mis_di_thua, df_npo_den_thua, df_mis_den_thua,
              n_di_khop, n_den_khop, df_timeout):
    """
    Phân tích chất lượng đối chiếu. Trả về DataFrame 4 cột:
    ('Chi tieu', 'Gia tri', 'Ghi chu', '_type')
    """
    def safe_len(df): return len(df) if df is not None else 0

    def safe_sum(df, col):
        if df is None or len(df) == 0 or col not in df.columns:
            return 0
        return int(pd.to_numeric(df[col], errors='coerce').fillna(0).sum())

    n_npo_di_thua  = safe_len(df_npo_di_thua)
    n_mis_di_thua  = safe_len(df_mis_di_thua)
    n_npo_den_thua = safe_len(df_npo_den_thua)
    n_mis_den_thua = safe_len(df_mis_den_thua)
    n_timeout      = safe_len(df_timeout)
    timeout_tien   = safe_sum(df_timeout, 'SO_TIEN')

    n_npo_di       = n_di_khop  + n_npo_di_thua
    n_mis_di       = n_di_khop  + n_mis_di_thua
    n_npo_den      = n_den_khop + n_npo_den_thua
    n_mis_den      = n_den_khop + n_mis_den_thua
    n_mis_di_total = n_di_khop  + n_mis_di_thua + n_timeout

    n_tpay_thua = 0
    if df_mis_di_thua is not None and 'TRANG_THAI_LENH' in df_mis_di_thua.columns:
        n_tpay_thua = int((df_mis_di_thua['TRANG_THAI_LENH'] == 'TPAY').sum())

    overlap_di = 0
    if (df_npo_di_thua is not None and n_npo_di_thua > 0
            and {'TRBRCD', 'CRAMOUNT'} <= set(df_npo_di_thua.columns)
            and df_mis_di_thua is not None and n_mis_di_thua > 0
            and {'CHI_NHANH', 'SO_TIEN'} <= set(df_mis_di_thua.columns)):
        npo_pairs = set(zip(
            df_npo_di_thua['TRBRCD'].astype(str).str.strip(),
            df_npo_di_thua['CRAMOUNT'].astype(str)))
        mis_pairs = set(zip(
            df_mis_di_thua['CHI_NHANH'].astype(str).str.strip(),
            df_mis_di_thua['SO_TIEN'].astype(str)))
        overlap_di = len(npo_pairs & mis_pairs)

    overlap_den = 0
    if (df_npo_den_thua is not None and n_npo_den_thua > 0
            and {'TRBRCD', 'DRAMOUNT'} <= set(df_npo_den_thua.columns)
            and df_mis_den_thua is not None and n_mis_den_thua > 0
            and {'CHI_NHANH', 'SO_TIEN'} <= set(df_mis_den_thua.columns)):
        npo_den_pairs = set(zip(
            df_npo_den_thua['TRBRCD'].astype(str).str.strip(),
            df_npo_den_thua['DRAMOUNT'].astype(str)))
        mis_den_pairs = set(zip(
            df_mis_den_thua['CHI_NHANH'].astype(str).str.strip(),
            df_mis_den_thua['SO_TIEN'].astype(str)))
        overlap_den = len(npo_den_pairs & mis_den_pairs)

    rows = []

    def add(label, val='', note='', typ='data'):
        rows.append((label, val, note, typ))

    # ─── Cảnh báo tự động ──────────────────────────────────────────
    warnings = []
    if n_tpay_thua > 0:
        warnings.append((f'[!] MIS_DI_THUA có {n_tpay_thua:,} lệnh TPAY chưa xử lý',
                         f'{n_tpay_thua:,} lệnh',
                         'Kiểm tra MIS_DI_THUA, lọc TRANG_THAI_LENH = TPAY'))
    if n_timeout > 0:
        warnings.append((f'[!] Timeout không kênh: {n_timeout:,} lệnh',
                         f'{timeout_tien:,} VND',
                         'Lệnh TPAY vượt GW — xem sheet TIMEOUT_KHONG_KENH'))
    if overlap_di > 0:
        warnings.append((f'[!] DI: {overlap_di:,} cặp (CN+TIỀN) có cả 2 phía nhưng TRACE khác',
                         f'{overlap_di:,} cặp',
                         'Có thể sai số trace — cần kiểm tra thủ công'))
    if overlap_den > 0:
        warnings.append((f'[!] DEN: {overlap_den:,} cặp (CN+TIỀN) có cả 2 phía nhưng TRACE khác',
                         f'{overlap_den:,} cặp',
                         'Có thể sai số trace — cần kiểm tra thủ công'))

    if warnings:
        add('--- CẢNH BÁO TỰ ĐỘNG ---', '', '', 'header')
        for w in warnings:
            add(w[0], w[1], w[2], 'canh_bao')
        add('', '', '', '')

    # ─── Section 1: Kết quả đối chiếu ─────────────────────────────
    add('--- 1. KẾT QUẢ ĐỐI CHIẾU ---', '', '', 'header')
    add('  ', 'CHIỀU ĐI', 'CHIỀU ĐẾN', 'sub_header')
    add('  Số GD khớp',           f'{n_di_khop:,}',      f'{n_den_khop:,}')
    add('  NPO chưa khớp (GL02 thừa)',
                                   f'{n_npo_di_thua:,}',  f'{n_npo_den_thua:,}')
    add('  MIS chưa khớp',        f'{n_mis_di_thua:,}',  f'{n_mis_den_thua:,}')
    add('  Timeout không kênh (TPAY)',
                                   f'{n_timeout:,} lệnh', f'{timeout_tien:,} VND')
    add('  ---', '', '')
    add('  Tổng NPO (cần đối)',    f'{n_npo_di:,}',       f'{n_npo_den:,}')
    add('  Tổng MIS (cần đối)',    f'{n_mis_di_total:,}', f'{n_mis_den:,}')
    add('', '', '', '')

    # ─── Section 2: Tổng số tiền chưa khớp ────────────────────────
    s_npo_di_thua  = safe_sum(df_npo_di_thua,  'CRAMOUNT')
    s_mis_di_thua  = safe_sum(df_mis_di_thua,  'SO_TIEN')
    s_npo_den_thua = safe_sum(df_npo_den_thua, 'DRAMOUNT')
    s_mis_den_thua = safe_sum(df_mis_den_thua, 'SO_TIEN')

    add('--- 2. TỔNG SỐ TIỀN CHƯA KHỚP (VND) ---', '', '', 'header')
    add('  ', 'Số GD', 'Số tiền (VND)', 'sub_header')
    add('  NPO_DI thừa',  f'{n_npo_di_thua:,}',  f'{s_npo_di_thua:,}')
    add('  MIS_DI thừa',  f'{n_mis_di_thua:,}',  f'{s_mis_di_thua:,}')
    add('  NPO_DEN thừa', f'{n_npo_den_thua:,}', f'{s_npo_den_thua:,}')
    add('  MIS_DEN thừa', f'{n_mis_den_thua:,}', f'{s_mis_den_thua:,}')
    add('', '', '', '')

    # ─── Section 3: MIS_DI_THUA breakdown ─────────────────────────
    add('--- 3. PHÂN TÍCH MIS_DI_THUA (theo loại lệnh) ---', '', '', 'header')
    if n_mis_di_thua > 0 and df_mis_di_thua is not None and 'TRANG_THAI_LENH' in df_mis_di_thua.columns:
        _NOTE_DI = {
            'SCNL': 'Đã thanh toán — có thể thuộc session khác, bình thường',
            'TPAY': 'Chưa được xử lý — cần theo dõi',
            'TXRT': 'Hoàn trả — cần kiểm tra',
        }
        for tt, cnt in df_mis_di_thua['TRANG_THAI_LENH'].value_counts().items():
            typ = 'canh_bao' if str(tt) in ('TPAY', 'TXRT') and cnt > 0 else 'data'
            add(f'  {tt}', f'{cnt:,}', _NOTE_DI.get(str(tt), ''), typ)
    else:
        add('  (Không có MIS_DI_THUA)')
    add('', '', '', '')

    # ─── Section 4: Top 10 chi nhánh MIS_DI_THUA ──────────────────
    add('--- 4. TOP 10 CHI_NHÁNH CÓ MIS_DI_THUA NHIỀU NHẤT ---', '', '', 'header')
    add('  CHI_NHÁNH', 'MIS_DI_THUA', 'NPO_DI_THUA', 'sub_header')
    if n_mis_di_thua > 0 and df_mis_di_thua is not None and 'CHI_NHANH' in df_mis_di_thua.columns:
        top10 = df_mis_di_thua.groupby('CHI_NHANH').size().nlargest(10)
        npo_by_cn = {}
        if df_npo_di_thua is not None and 'TRBRCD' in df_npo_di_thua.columns:
            npo_by_cn = df_npo_di_thua.groupby('TRBRCD').size().to_dict()
        for cn, cnt_mis in top10.items():
            add(f'  {cn}', f'{cnt_mis:,}', f'{npo_by_cn.get(str(cn), 0):,}')
    add('', '', '', '')

    # ─── Section 5: NPO_DI_THUA top 10 theo số tiền ───────────────
    add('--- 5. TOP 10 CHI_NHÁNH NPO_DI_THUA (theo số tiền) ---', '', '', 'header')
    if df_npo_di_thua is not None and n_npo_di_thua > 0 and 'TRBRCD' in df_npo_di_thua.columns:
        add('  CHI_NHÁNH', 'Số GD', 'Tổng CRAMOUNT (VND)', 'sub_header')
        grp = df_npo_di_thua.groupby('TRBRCD')
        cnt_npo_di = grp.size()
        if 'CRAMOUNT' in df_npo_di_thua.columns:
            amt_npo_di = grp['CRAMOUNT'].apply(
                lambda x: int(pd.to_numeric(x, errors='coerce').fillna(0).sum()))
            top10_by_amt = amt_npo_di.nlargest(10)
        else:
            top10_by_amt = cnt_npo_di.nlargest(10)
            amt_npo_di   = pd.Series(dtype='int64')
        for cn, amt in top10_by_amt.items():
            add(f'  {cn}', f'{cnt_npo_di.get(cn, 0):,}', f'{amt:,}')
    else:
        add('  (Không có NPO_DI_THUA)')
    add('', '', '', '')

    # ─── Section 6: MIS_DEN_THUA breakdown ────────────────────────
    add('--- 6. PHÂN TÍCH MIS_DEN_THUA (theo loại lệnh) ---', '', '', 'header')
    if n_mis_den_thua > 0 and df_mis_den_thua is not None and 'TRANG_THAI_LENH' in df_mis_den_thua.columns:
        for tt, cnt in df_mis_den_thua['TRANG_THAI_LENH'].value_counts().items():
            add(f'  {tt}', f'{cnt:,}', '')
        if overlap_den > 0:
            add('  Cặp (CN+TIỀN) ở cả 2 phía', f'{overlap_den:,}',
                'Cùng chi nhánh + số tiền nhưng TRACE khác — nên kiểm tra')
    else:
        add('  (Không có MIS_DEN_THUA)')
    add('', '', '', '')

    # ─── Section 7: Top 10 chi nhánh MIS_DEN_THUA ─────────────────
    add('--- 7. TOP 10 CHI_NHÁNH CÓ MIS_DEN_THUA NHIỀU NHẤT ---', '', '', 'header')
    add('  CHI_NHÁNH', 'MIS_DEN_THUA', 'NPO_DEN_THUA', 'sub_header')
    if n_mis_den_thua > 0 and df_mis_den_thua is not None and 'CHI_NHANH' in df_mis_den_thua.columns:
        top10_den = df_mis_den_thua.groupby('CHI_NHANH').size().nlargest(10)
        npo_den_by_cn = {}
        if df_npo_den_thua is not None and 'TRBRCD' in df_npo_den_thua.columns:
            npo_den_by_cn = df_npo_den_thua.groupby('TRBRCD').size().to_dict()
        for cn, cnt_mis in top10_den.items():
            add(f'  {cn}', f'{cnt_mis:,}', f'{npo_den_by_cn.get(str(cn), 0):,}')
    add('', '', '', '')

    # ─── Section 8: NPO_DEN_THUA top 10 theo số tiền ──────────────
    add('--- 8. TOP 10 CHI_NHÁNH NPO_DEN_THUA (theo số tiền) ---', '', '', 'header')
    if df_npo_den_thua is not None and n_npo_den_thua > 0 and 'TRBRCD' in df_npo_den_thua.columns:
        add('  CHI_NHÁNH', 'Số GD', 'Tổng DRAMOUNT (VND)', 'sub_header')
        grp_den = df_npo_den_thua.groupby('TRBRCD')
        cnt_npo_den = grp_den.size()
        if 'DRAMOUNT' in df_npo_den_thua.columns:
            amt_den = grp_den['DRAMOUNT'].apply(
                lambda x: int(pd.to_numeric(x, errors='coerce').fillna(0).sum()))
            top10_den_amt = amt_den.nlargest(10)
        else:
            top10_den_amt = cnt_npo_den.nlargest(10)
            amt_den       = pd.Series(dtype='int64')
        for cn, amt in top10_den_amt.items():
            add(f'  {cn}', f'{cnt_npo_den.get(cn, 0):,}', f'{amt:,}')
    else:
        add('  (Không có NPO_DEN_THUA)')

    return pd.DataFrame(rows, columns=['Chi tieu', 'Gia tri', 'Ghi chu', '_type'])
