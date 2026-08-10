"""B8 — Dựng bảng PHAN_TICH: cảnh báo tự động + thống kê chất lượng đối chiếu."""
import pandas as pd


def phan_tich(df_npo_di_thua, df_mis_di_thua, df_npo_den_thua, df_mis_den_thua,
              n_di_khop, n_den_khop, df_timeout):
    """Trả DataFrame 4 cột ('Chi tieu', 'Gia tri', 'Ghi chu', '_type').

    _type: 'header' | 'sub_header' | 'canh_bao' | 'data' | '' — engine dùng để tô
    màu khi ghi Excel rồi bỏ cột này đi.
    Không dùng tỷ lệ phần trăm: chỉ số tuyệt đối để số liệu cân đối chính xác.
    """
    def safe_len(df):
        return len(df) if df is not None else 0

    def safe_sum(df, col):
        if df is None or len(df) == 0 or col not in df.columns:
            return 0
        return int(pd.to_numeric(df[col], errors='coerce').fillna(0).sum())

    n_npo_di_thua = safe_len(df_npo_di_thua)
    n_mis_di_thua = safe_len(df_mis_di_thua)
    n_npo_den_thua = safe_len(df_npo_den_thua)
    n_mis_den_thua = safe_len(df_mis_den_thua)
    n_timeout = safe_len(df_timeout)
    timeout_tien = safe_sum(df_timeout, 'SO_TIEN')

    n_npo_di = n_di_khop + n_npo_di_thua
    n_npo_den = n_den_khop + n_npo_den_thua
    n_mis_den = n_den_khop + n_mis_den_thua
    n_mis_di_total = n_di_khop + n_mis_di_thua + n_timeout   # MIS trước khi bỏ timeout

    # ── Số liệu cảnh báo ──
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

    # ═══ Cảnh báo tự động ═══
    warnings = []
    if n_tpay_thua > 0:
        warnings.append((f'[!] MIS_DI_THUA co {n_tpay_thua:,} lenh TPAY chua xu ly',
                         f'{n_tpay_thua:,} lenh',
                         'Kiem tra MIS_DI_THUA, loc TRANG_THAI_LENH = TPAY'))
    if n_timeout > 0:
        warnings.append((f'[!] Timeout khong kenh: {n_timeout:,} lenh',
                         f'{timeout_tien:,} VND',
                         'Lenh TPAY vuot GW — xem sheet TIMEOUT_KHONG_KENH'))
    if overlap_di > 0:
        warnings.append((f'[!] DI: {overlap_di:,} cap (CN+TIEN) co ca 2 phia nhung TRACE khac',
                         f'{overlap_di:,} cap',
                         'Co the sai so trace — can kiem tra thu cong'))
    if overlap_den > 0:
        warnings.append((f'[!] DEN: {overlap_den:,} cap (CN+TIEN) co ca 2 phia nhung TRACE khac',
                         f'{overlap_den:,} cap',
                         'Co the sai so trace — can kiem tra thu cong'))

    if warnings:
        add('--- CANH BAO TU DONG ---', '', '', 'header')
        for w in warnings:
            add(w[0], w[1], w[2], 'canh_bao')
        add('', '', '', '')

    # ═══ 1. Kết quả đối chiếu ═══
    add('--- 1. KET QUA DOI CHIEU ---', '', '', 'header')
    add('  ', 'CHIEU DI', 'CHIEU DEN', 'sub_header')
    add('  So giao dich khop', f'{n_di_khop:,}', f'{n_den_khop:,}')
    add('  NPO chua khop (GL02 thua)', f'{n_npo_di_thua:,}', f'{n_npo_den_thua:,}')
    add('  MIS chua khop', f'{n_mis_di_thua:,}', f'{n_mis_den_thua:,}')
    add('  Timeout khong kenh (TPAY)', f'{n_timeout:,} lenh', f'{timeout_tien:,} VND')
    add('  ---', '', '')
    add('  Tong NPO (can doi: khop + thua)', f'{n_npo_di:,}', f'{n_npo_den:,}')
    add('  Tong MIS (can doi: khop + thua + TO)', f'{n_mis_di_total:,}', f'{n_mis_den:,}')
    add('', '', '', '')

    # ═══ 2. Tổng số tiền chưa khớp ═══
    s_npo_di_thua = safe_sum(df_npo_di_thua, 'CRAMOUNT')
    s_mis_di_thua = safe_sum(df_mis_di_thua, 'SO_TIEN')
    s_npo_den_thua = safe_sum(df_npo_den_thua, 'DRAMOUNT')
    s_mis_den_thua = safe_sum(df_mis_den_thua, 'SO_TIEN')

    add('--- 2. TONG SO TIEN CHUA KHOP (VND) ---', '', '', 'header')
    add('  ', 'So giao dich', 'So tien (VND)', 'sub_header')
    add('  NPO_DI thua (GL02 DI chua khop)',   f'{n_npo_di_thua:,}',  f'{s_npo_di_thua:,}')
    add('  MIS_DI thua (MIS DI chua khop)',    f'{n_mis_di_thua:,}',  f'{s_mis_di_thua:,}')
    add('  NPO_DEN thua (GL02 DEN chua khop)', f'{n_npo_den_thua:,}', f'{s_npo_den_thua:,}')
    add('  MIS_DEN thua (MIS DEN chua khop)',  f'{n_mis_den_thua:,}', f'{s_mis_den_thua:,}')
    add('', '', '', '')

    # ═══ 3. MIS_DI_THUA theo loại lệnh ═══
    add('--- 3. PHAN TICH MIS_DI_THUA (theo loai lenh) ---', '', '', 'header')
    total_mis_di = n_mis_di_thua
    if total_mis_di > 0 and df_mis_di_thua is not None and 'TRANG_THAI_LENH' in df_mis_di_thua.columns:
        _NOTE_DI = {
            'SCNL': 'Da thanh toan — co the thuoc session khac, binh thuong',
            'TPAY': 'Chua duoc xu ly — can theo doi',
            'TXRT': 'Hoan tra — can kiem tra',
        }
        for tt, cnt in df_mis_di_thua['TRANG_THAI_LENH'].value_counts().items():
            typ = 'canh_bao' if str(tt) in ('TPAY', 'TXRT') and cnt > 0 else 'data'
            add(f'  {tt}', f'{cnt:,}', _NOTE_DI.get(str(tt), ''), typ)
    else:
        add('  (Khong co MIS_DI_THUA)')
    add('', '', '', '')

    # ═══ 4. Top 10 chi nhánh MIS_DI_THUA ═══
    add('--- 4. TOP 10 CHI_NHANH CO MIS_DI_THUA NHIEU NHAT ---', '', '', 'header')
    add('  CHI_NHANH', 'MIS_DI_THUA', 'NPO_DI_THUA', 'sub_header')
    if total_mis_di > 0 and df_mis_di_thua is not None and 'CHI_NHANH' in df_mis_di_thua.columns:
        top10 = df_mis_di_thua.groupby('CHI_NHANH').size().nlargest(10)
        npo_by_cn = {}
        if df_npo_di_thua is not None and 'TRBRCD' in df_npo_di_thua.columns:
            npo_by_cn = df_npo_di_thua.groupby('TRBRCD').size().to_dict()
        for cn, cnt_mis in top10.items():
            add(f'  {cn}', f'{cnt_mis:,}', f'{npo_by_cn.get(str(cn), 0):,}')
    add('', '', '', '')

    # ═══ 5. NPO_DI_THUA theo số tiền ═══
    add('--- 5. PHAN TICH NPO_DI_THUA — GL02 DI CHUA KHOP (top 10 theo so tien) ---', '', '', 'header')
    if df_npo_di_thua is not None and n_npo_di_thua > 0 and 'TRBRCD' in df_npo_di_thua.columns:
        add('  CHI_NHANH', 'So giao dich', 'Tong CRAMOUNT (VND)', 'sub_header')
        grp = df_npo_di_thua.groupby('TRBRCD')
        cnt_npo_di = grp.size()
        if 'CRAMOUNT' in df_npo_di_thua.columns:
            amt_npo_di = grp['CRAMOUNT'].apply(
                lambda x: int(pd.to_numeric(x, errors='coerce').fillna(0).sum()))
            top10_by_amt = amt_npo_di.nlargest(10)
        else:
            top10_by_amt = cnt_npo_di.nlargest(10)
        for cn, amt in top10_by_amt.items():
            add(f'  {cn}', f'{cnt_npo_di.get(cn, 0):,}', f'{amt:,}')
    else:
        add('  (Khong co NPO_DI_THUA)')
    add('', '', '', '')

    # ═══ 6. MIS_DEN_THUA theo loại lệnh ═══
    add('--- 6. PHAN TICH MIS_DEN_THUA (theo loai lenh) ---', '', '', 'header')
    total_mis_den = n_mis_den_thua
    if total_mis_den > 0 and df_mis_den_thua is not None and 'TRANG_THAI_LENH' in df_mis_den_thua.columns:
        for tt, cnt in df_mis_den_thua['TRANG_THAI_LENH'].value_counts().items():
            add(f'  {tt}', f'{cnt:,}', '')
        if overlap_den > 0:
            add('  Cap (CN+TIEN) co mat o ca 2 phia', f'{overlap_den:,}',
                'Cung chi nhanh + so tien nhung TRACE khac — Nen kiem tra')
    else:
        add('  (Khong co MIS_DEN_THUA)')
    add('', '', '', '')

    # ═══ 7. Top 10 chi nhánh MIS_DEN_THUA ═══
    add('--- 7. TOP 10 CHI_NHANH CO MIS_DEN_THUA NHIEU NHAT ---', '', '', 'header')
    add('  CHI_NHANH', 'MIS_DEN_THUA', 'NPO_DEN_THUA', 'sub_header')
    if total_mis_den > 0 and df_mis_den_thua is not None and 'CHI_NHANH' in df_mis_den_thua.columns:
        top10_den = df_mis_den_thua.groupby('CHI_NHANH').size().nlargest(10)
        npo_den_by_cn = {}
        if df_npo_den_thua is not None and 'TRBRCD' in df_npo_den_thua.columns:
            npo_den_by_cn = df_npo_den_thua.groupby('TRBRCD').size().to_dict()
        for cn, cnt_mis in top10_den.items():
            add(f'  {cn}', f'{cnt_mis:,}', f'{npo_den_by_cn.get(str(cn), 0):,}')
    add('', '', '', '')

    # ═══ 8. NPO_DEN_THUA theo số tiền ═══
    add('--- 8. PHAN TICH NPO_DEN_THUA — GL02 DEN CHUA KHOP (top 10 theo so tien) ---', '', '', 'header')
    if df_npo_den_thua is not None and n_npo_den_thua > 0 and 'TRBRCD' in df_npo_den_thua.columns:
        add('  CHI_NHANH', 'So giao dich', 'Tong DRAMOUNT (VND)', 'sub_header')
        grp_den = df_npo_den_thua.groupby('TRBRCD')
        cnt_npo_den = grp_den.size()
        if 'DRAMOUNT' in df_npo_den_thua.columns:
            amt_npo_den = grp_den['DRAMOUNT'].apply(
                lambda x: int(pd.to_numeric(x, errors='coerce').fillna(0).sum()))
            top10_den_amt = amt_npo_den.nlargest(10)
        else:
            top10_den_amt = cnt_npo_den.nlargest(10)
        for cn, amt in top10_den_amt.items():
            add(f'  {cn}', f'{cnt_npo_den.get(cn, 0):,}', f'{amt:,}')
    else:
        add('  (Khong co NPO_DEN_THUA)')

    return pd.DataFrame(rows, columns=['Chi tieu', 'Gia tri', 'Ghi chu', '_type'])
