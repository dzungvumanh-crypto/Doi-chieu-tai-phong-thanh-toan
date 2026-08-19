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
    osb_df: pd.DataFrame | None = None,
) -> Path:
    """
    Ghi file Excel với 6 sheet: hub, citad, eicp, core, osb, Tóm tắt.
    `osb_df` (tùy chọn — module OSB chưa bắt buộc): dữ liệu OSB cũ+mới đã gộp
    cho ngày đang chấm, kèm cột 'Nhóm' ('OSB mới'/'OSB cũ').
    Trả về Path đến file đã tạo.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if osb_df is None:
        osb_df = pd.DataFrame()

    # Tên file: YYYYMMDD.xlsx (e.g., 20260512.xlsx)
    out_path = output_dir / f'{ngay_int}.xlsx'

    # ── Cột xuất cho mỗi sheet ──
    hub_cols = [
        'Số giao dịch', 'Số Ref Hub', 'STC', 'Trace', 'Trace2',
        'Số tiền thực chuyển', 'Trạng thái', 'Ngày giờ kênh trả',
        'Nội dung chuyển tiền', 'ngay',
    ]
    # 'TT': '' (đã khớp Core, hoặc còn thừa chưa xử lý) | 'OSB' (Citad còn thừa
    # sau Core, khớp được với OSB — xem process.match_citad_leftover_with_osb()).
    citad_cols = ['SERIAL_NO', 'RELATION_NO', 'TRX_DATE', 'AMOUNT', 'Trace', 'Map dc', 'Ngày', 'TT']
    core_cols  = [
        'TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
        'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
        'DRAMOUNT', 'CRAMOUNT', 'CRTDTM', 'Trace', 'Trace2', 'Map dc', 'Ngày', 'TT',
    ]
    osb_cols = ['Mã giao dịch', 'CN thực hiện', 'Số tiền', 'Ngày hạch toán', 'Nhóm']

    def _safe_df(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        """Giữ cột trong danh sách, điền cột thiếu bằng rỗng."""
        out = pd.DataFrame()
        for c in cols:
            out[c] = df[c].values if c in df.columns else ''
        return out

    hub_out   = _safe_df(hub_df,   hub_cols)
    citad_out = _safe_df(citad_df, citad_cols)
    core_out  = _safe_df(core_df,  core_cols)
    osb_out   = _safe_df(osb_df,   osb_cols)

    # ── Tóm tắt TT ──
    tt_counts = core_df['TT'].fillna('').astype(str) if 'TT' in core_df.columns else pd.Series([''])
    summary = tt_counts.value_counts().reset_index()
    summary.columns = ['Tình trạng', 'Số giao dịch']
    summary = pd.concat([
        summary,
        pd.DataFrame([['TỔNG', len(core_df)]], columns=['Tình trạng', 'Số giao dịch']),
    ], ignore_index=True)

    # ── Tổng hợp số món + số tiền (Hub, Core & Citad) ──
    # .get(col, pd.Series(dtype=float)) — nếu dùng default 0 (int) thay vì Series
    # rỗng, DataFrame rỗng (VD ngày không có Hub) sẽ trả về int, .fillna() crash.
    _empty = pd.Series(dtype=float)
    hub_amt   = pd.to_numeric(hub_df.get('Số tiền thực chuyển', _empty), errors='coerce').fillna(0).sum()
    core_no   = pd.to_numeric(core_df.get('DRAMOUNT', _empty), errors='coerce').fillna(0).sum()
    core_co   = pd.to_numeric(core_df.get('CRAMOUNT', _empty), errors='coerce').fillna(0).sum()
    citad_amt = pd.to_numeric(citad_df.get('AMOUNT', _empty), errors='coerce').fillna(0).sum()
    tong_hop = pd.DataFrame([
        ['Hub',   len(hub_df),   '',      hub_amt],
        ['Core',  len(core_df),  core_no, core_co],
        ['Citad', len(citad_df), '',      citad_amt],
    ], columns=['Sheet', 'Số món', 'Tổng Nợ', 'Tổng Có / Số tiền'])

    # ── Ghi Excel ──
    # Mỗi ngày xuất riêng 1 file (`_run_one_day` gọi hàm này 1 lần/ngày) nên
    # mỗi sheet chỉ chứa dữ liệu 1 ngày (~70-75 nghìn dòng trên dữ liệu thật
    # 11-12/8/2026), không phải cả batch nhiều ngày dồn lại — không cần chế độ
    # `constant_memory` của xlsxwriter (dành cho sheet hàng triệu dòng, và bắt
    # buộc ghi dòng TĂNG DẦN — `df.to_excel()` bên dưới ghi theo CỘT, vi phạm
    # ràng buộc đó, xlsxwriter ÂM THẦM bỏ các lệnh ghi "lùi dòng" → mọi dòng
    # trừ dòng cuối mỗi sheet mất hết dữ liệu ngoài cột đầu tiên — bug thật đã
    # dính). Rủi ro OOM thật nằm ở tầng LOAD (gộp nhiều file GL02 thô trước khi
    # lọc), đã xử lý riêng ở `load_core.py::_filter_channel()`.
    with pd.ExcelWriter(str(out_path), engine='xlsxwriter') as writer:
        hdr_fmt = writer.book.add_format({
            'bold': True, 'bg_color': '#C00000', 'font_color': '#FFFFFF',
            'border': 1, 'text_wrap': True,
        })

        def _write_sheet(sheet_name: str, df_out: pd.DataFrame, startrow: int = 0) -> None:
            if sheet_name not in writer.sheets:
                writer.sheets[sheet_name] = writer.book.add_worksheet(sheet_name)
            ws = writer.sheets[sheet_name]
            for col_idx, col_name in enumerate(df_out.columns):
                ws.write(startrow, col_idx, col_name, hdr_fmt)
            df_out.to_excel(writer, sheet_name=sheet_name, index=False, header=False, startrow=startrow + 1)

        _write_sheet('hub',   hub_out)
        _write_sheet('citad', citad_out)
        _write_sheet('eicp',  eicp_df)
        _write_sheet('core',  core_out)
        _write_sheet('osb',   osb_out)
        _write_sheet('Tóm tắt', summary)
        tong_hop_startrow = len(summary) + 3
        _write_sheet('Tóm tắt', tong_hop, startrow=tong_hop_startrow)

    return out_path
