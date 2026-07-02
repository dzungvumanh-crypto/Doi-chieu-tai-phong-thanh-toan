"""Xuất kết quả ra file Excel (1 file / ngày)."""

from pathlib import Path

import pandas as pd


def export_excel(
    hub_df:   pd.DataFrame,
    citad_df: pd.DataFrame,
    eicp_df:  pd.DataFrame,
    core_df:  pd.DataFrame,
    ngay_int: int,
    output_dir: str | Path,
) -> Path:
    """
    Ghi file Excel với 5 sheet: hub, citad, eicp, core, Tóm tắt.
    Trả về Path đến file đã tạo.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Tên file: YYYYMMDD.xlsx (e.g., 20260512.xlsx)
    out_path = output_dir / f'{ngay_int}.xlsx'

    # ── Cột xuất cho mỗi sheet ──
    hub_cols = [
        'Số giao dịch', 'Số Ref Hub', 'STC', 'Trace', 'Trace2',
        'Số tiền thực chuyển', 'Trạng thái', 'Ngày giờ kênh trả',
        'Nội dung chuyển tiền', 'ngay',
    ]
    citad_cols = ['SERIAL_NO', 'RELATION_NO', 'TRX_DATE', 'AMOUNT', 'Trace', 'Map dc', 'Ngày']
    core_cols  = [
        'TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
        'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
        'DRAMOUNT', 'CRAMOUNT', 'CRTDTM', 'Trace', 'Trace2', 'Map dc', 'Ngày', 'TT',
    ]

    def _safe_df(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        """Giữ cột trong danh sách, điền cột thiếu bằng rỗng."""
        out = pd.DataFrame()
        for c in cols:
            out[c] = df[c].values if c in df.columns else ''
        return out

    hub_out   = _safe_df(hub_df,   hub_cols)
    citad_out = _safe_df(citad_df, citad_cols)
    core_out  = _safe_df(core_df,  core_cols)

    # ── Tóm tắt TT ──
    tt_counts = core_df['TT'].fillna('').astype(str) if 'TT' in core_df.columns else pd.Series([''])
    summary = tt_counts.value_counts().reset_index()
    summary.columns = ['Tình trạng', 'Số giao dịch']
    summary = pd.concat([
        summary,
        pd.DataFrame([['TỔNG', len(core_df)]], columns=['Tình trạng', 'Số giao dịch']),
    ], ignore_index=True)

    # ── Ghi Excel ──
    with pd.ExcelWriter(str(out_path), engine='xlsxwriter') as writer:
        hub_out.to_excel(writer,   sheet_name='hub',      index=False)
        citad_out.to_excel(writer, sheet_name='citad',    index=False)
        eicp_df.to_excel(writer,   sheet_name='eicp',     index=False)
        core_out.to_excel(writer,  sheet_name='core',     index=False)
        summary.to_excel(writer,   sheet_name='Tóm tắt', index=False)

        # Format header
        wb = writer.book
        hdr_fmt = wb.add_format({
            'bold': True, 'bg_color': '#C00000', 'font_color': '#FFFFFF',
            'border': 1, 'text_wrap': True,
        })
        for sheet_name, df_out in [
            ('hub', hub_out), ('citad', citad_out),
            ('eicp', eicp_df), ('core', core_out), ('Tóm tắt', summary),
        ]:
            ws = writer.sheets[sheet_name]
            for col_idx, col_name in enumerate(df_out.columns):
                ws.write(0, col_idx, col_name, hdr_fmt)

    return out_path
