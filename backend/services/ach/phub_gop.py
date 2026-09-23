"""Kết quả pHub gộp nhiều ngày (Mục 3, sửa 18.09.2026, thay thế hoàn toàn file
`<ngày>_ACH_PHUBLOI.xlsx` từng ngày — Q1). Gộp `df_gw`/`df_timeout` của N ngày
(đã được NGƯỜI GỌI nạp sẵn — xem Luồng C, `phan_loai_file_gop()`) với 1
`df_phub` (`doc_phub()`), chạy đúng 1 lần `xu_ly_phub_loi()` (b16_phub_loi.py,
KHÔNG sửa) rồi xuất 1 file Excel duy nhất.

Module này KHÔNG còn tự đọc kho trên đĩa (bản-2 `phub_lichsu.py` đã bị gỡ,
Luồng A 23.09.2026 — máy chủ không đủ ổ đĩa giữ 30 ngày CSV). `gop_phub()` là
hàm THUẦN DỮ LIỆU: nhận thẳng `df_gw`/`df_timeout`, không tự đi tìm file nào.

Import `pipeline` (chỉ `_viet_sheet`/`CSV_THRESHOLD`), `b16` — KHÔNG được
`pipeline` import ngược (tránh vòng import). An toàn vì Luồng A đã gỡ chiều
`pipeline → phub_gop` (pipeline không còn import gì từ module này).
"""
import io
import os

import pandas as pd
import xlsxwriter

from .b16_phub_loi import (
    doc_phub, xu_ly_phub_loi, _tao_cn_trace_tien_phub, _tao_cn_trace_tien_timeout,
)
from .pipeline import _viet_sheet, CSV_THRESHOLD
from .so_tien import doc_so_tien

_CAM = '#FFA500'   # đồng bộ màu tab với Mục 3 cũ (pipeline.py)

__all__ = ['doc_phub', 'gop_phub', 'xuat_excel_phub_gop', 'phan_loai_file_gop']

# ─── Luồng C (bản-3, 23.09.2026) — phân loại N file người dùng nạp trong CÙNG ──
# 1 lượt gộp, theo NỘI DUNG chứ không theo tên file (feedback_nhan_dien_file_
# theo_noi_dung). GW-cho-pHub/Timeout luôn là .csv do chính pipeline này xuất
# ra (A4/Mục 8); chỉ pHub là .xlsx gốc từ Hub, chưa qua xử lý.
_COT_MSGREF        = 'MSGREF'
_COT_GHI_CHU       = 'Ghi chú'
_COLS_GW_TOI_THIEU = {_COT_MSGREF, _COT_GHI_CHU}
_COLS_TIMEOUT_TOI_THIEU = {'CHI_NHANH', 'TRACE', 'SE_TRACE', 'SO_TIEN'}
# C-N (chốt 23.09.2026) — tên cột ngày do pipeline ghi thêm vào CẢ HAI file
# TIMEOUT_KHONG_KENH_<ngày>.csv và GW_CHO_PHUB_<ngày>.csv (A4, chưa làm ở đợt
# này). Lớp đọc dưới đây CHỈ cần cột này ở file TIMEOUT (gop_phub() chỉ đọc
# df_timeout['NGAY_TIMEOUT'], không cần ngày trên file GW).
_COT_NGAY_DOI_CHIEU = 'NGAY_DOI_CHIEU'


def _doc_csv_gop(noi_dung: bytes) -> pd.DataFrame:
    """Đọc 1 file .csv (GW-cho-pHub hoặc Timeout) — dtype=str, tự dò dấu phân
    cách (cùng luật `_doc_file_thua_t2()` ở b11_doi_chieu_cheo_ngay.py: người
    giữ file trên máy mình có thể đã mở bằng Excel rồi lưu lại, đổi dấu phẩy
    thành tab mà vẫn giữ đuôi .csv)."""
    df = pd.read_csv(io.BytesIO(noi_dung), dtype=str, encoding='utf-8-sig',
                     sep=None, engine='python')
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _la_file_phub(noi_dung: bytes) -> bool:
    """.xlsx có dòng header chứa 'Số thành công' (dò 30 dòng đầu — đủ cho cấu
    trúc thật: dòng 0 tiêu đề gộp, dòng 1 header, xem `doc_phub()`/b16)."""
    try:
        raw = pd.read_excel(io.BytesIO(noi_dung), header=None, dtype=str,
                            engine='calamine', nrows=30)
    except Exception:
        return False
    return bool(raw.isin(['Số thành công']).any().any())


def phan_loai_file_gop(
    danh_sach: list[tuple[str, bytes]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Phân loại N file người dùng vừa nạp trong 1 lượt Gộp (Luồng C bản-3) —
    theo NỘI DUNG, không theo tên file:
      - .xlsx có dòng header chứa 'Số thành công'  → pHub (bắt buộc đúng 1 file)
      - .csv có cột MSGREF + Ghi chú                → GW-cho-pHub
      - .csv có cột CHI_NHANH/TRACE/SE_TRACE/SO_TIEN → Timeout không đi kênh

    Trả `(df_phub, df_gw, df_timeout, canh_bao)`. `df_timeout['NGAY_TIMEOUT']`
    lấy từ cột `NGAY_DOI_CHIEU` (C-N) của từng file Timeout.

    File lạ (không khớp loại nào) → raise ngay, nêu tên — KHÔNG âm thầm bỏ
    qua (tinh thần dự án: dữ liệu tài chính không được rơi rụng lặng lẽ).
    File Timeout THIẾU cột `NGAY_DOI_CHIEU` (định dạng cũ, trước khi A4 xuất
    cột ngày) → KHÔNG đoán ngày, dữ liệu file đó bị loại khỏi lượt gộp, kèm
    1 dòng cảnh báo nêu đích danh file — các file/ngày khác còn hợp lệ vẫn
    gộp bình thường (không raise cho cả lượt)."""
    phub_files:  list[tuple[str, bytes]] = []
    gw_dfs:      list[pd.DataFrame] = []
    timeout_dfs: list[pd.DataFrame] = []
    canh_bao:    list[str] = []
    la:          list[str] = []

    for ten, noi_dung in danh_sach:
        duoi = ten.lower().rsplit('.', 1)[-1] if '.' in ten else ''

        if duoi == 'xlsx' and _la_file_phub(noi_dung):
            phub_files.append((ten, noi_dung))
            continue

        if duoi == 'csv':
            try:
                df = _doc_csv_gop(noi_dung)
            except Exception as e:
                la.append(f"{ten} (không đọc được CSV: {e})")
                continue
            cols = set(df.columns)

            if _COLS_GW_TOI_THIEU.issubset(cols):
                df = df[[_COT_MSGREF, _COT_GHI_CHU]].copy()
                df[_COT_MSGREF]  = df[_COT_MSGREF].astype(str).str.strip().str.lstrip("'")
                df[_COT_GHI_CHU] = df[_COT_GHI_CHU].fillna('').astype(str)
                gw_dfs.append(df)
                continue

            if _COLS_TIMEOUT_TOI_THIEU.issubset(cols):
                if _COT_NGAY_DOI_CHIEU not in df.columns:
                    canh_bao.append(
                        f"File Timeout '{ten}' thiếu cột {_COT_NGAY_DOI_CHIEU} (định dạng cũ) "
                        "— KHÔNG đoán ngày, dữ liệu của file này bị BỎ QUA khỏi lượt gộp. Tải "
                        "lại bằng file TIMEOUT_KHONG_KENH_*.csv mới nhất do chương trình xuất ra."
                    )
                    continue
                df = df.copy()
                df['SO_TIEN'] = doc_so_tien(
                    df['SO_TIEN'], f'Timeout gộp: {ten}', ten_cot='SO_TIEN').astype(str)
                df['NGAY_TIMEOUT'] = df[_COT_NGAY_DOI_CHIEU].astype(str).str.strip()
                timeout_dfs.append(df)
                continue

        la.append(ten)

    if la:
        raise ValueError(
            f"{len(la)} file không nhận diện được loại (không phải pHub .xlsx / "
            f"GW-cho-pHub .csv / Timeout .csv): {la}"
        )

    if len(phub_files) != 1:
        if not phub_files:
            raise ValueError(
                "Không tìm thấy file pHub nào (.xlsx có cột 'Số thành công') trong lượt nạp này."
            )
        raise ValueError(
            f"Tìm thấy {len(phub_files)} file pHub hợp lệ, cần đúng 1: "
            f"{[t for t, _ in phub_files]}"
        )

    ten_phub, noi_dung_phub = phub_files[0]
    try:
        df_phub = doc_phub(io.BytesIO(noi_dung_phub))
    except ValueError as e:
        raise ValueError(f"File pHub '{ten_phub}': {e}") from e

    df_gw = (pd.concat(gw_dfs, ignore_index=True) if gw_dfs
             else pd.DataFrame(columns=[_COT_MSGREF, _COT_GHI_CHU]))
    df_timeout = (pd.concat(timeout_dfs, ignore_index=True) if timeout_dfs
                  else pd.DataFrame(columns=['CHI_NHANH', 'TRACE', 'SE_TRACE', 'SO_TIEN', 'NGAY_TIMEOUT']))

    return df_phub, df_gw, df_timeout, canh_bao


def _to_yyyymmdd_display(ngay: str) -> str:
    """'20260915' -> '15/09/2026'."""
    return f'{ngay[6:8]}/{ngay[4:6]}/{ngay[:4]}' if len(ngay) == 8 else ngay


def _tinh_thong_ke(df_ketqua: pd.DataFrame) -> dict:
    dem = df_ketqua['TRANG_THAI_CAP_NHAT'].value_counts()
    return {
        'hoan_thanh':      int(dem.get('Hoàn thành', 0)),
        'tt_lenh_loi':     int(dem.get('TT lệnh lỗi ngày T', 0)),
        'trang_thai_khac': int(dem.get('Trạng thái khác', 0)),
        'tong':            len(df_ketqua),
    }


def gop_phub(df_phub: pd.DataFrame, df_gw: pd.DataFrame, df_timeout: pd.DataFrame,
             ngay_list: list[str], log_callback=None) -> tuple[pd.DataFrame, dict]:
    """Gộp `df_phub` (`doc_phub()`) với `df_gw`/`df_timeout` của N ngày đã được
    NGƯỜI GỌI nạp sẵn (Luồng C — `phan_loai_file_gop()`). `df_timeout` phải có
    cột `NGAY_TIMEOUT` (YYYYMMDD) do người gọi gắn — trước đây do
    `phub_lichsu.nap_nguyen_lieu()` gắn, nay là việc của lớp đọc file ở Luồng C.
    Cảnh báo "ngày thiếu GW-cho-pHub" KHÔNG còn sinh ra ở đây (hàm này chỉ nhận
    dữ liệu đã gộp sẵn, không biết ngày nào thiếu file gì) — đó là việc của
    `phan_loai_file_gop()` (Luồng C), nơi biết chính xác bộ file người dùng vừa
    nạp. Trả (df_ketqua, thong_ke)."""
    _log = log_callback or print

    df_ketqua = xu_ly_phub_loi(df_phub, df_gw, df_timeout, _log)

    # Q5 — cột NGAY_TIMEOUT_KHOP: chỉ điền cho dòng 'TT lệnh lỗi ngày T', khớp
    # nhiều ngày thì nối bằng '|'. Import lại đúng 2 helper PRIVATE của b16 —
    # KHÔNG chép lại công thức khoá CN trace tiền (xem PLAN.md mục 2.2/7).
    cn_phub = _tao_cn_trace_tien_phub(df_ketqua)
    cn_to   = _tao_cn_trace_tien_timeout(df_timeout)

    ngay_theo_cn: dict[str, set[str]] = {}
    for cn, ngay in zip(cn_to, df_timeout['NGAY_TIMEOUT']):
        ngay_theo_cn.setdefault(cn, set()).add(ngay)

    def _ngay_khop(cn: str) -> str:
        s = ngay_theo_cn.get(cn)
        if not s:
            return ''
        return '|'.join(_to_yyyymmdd_display(n) for n in sorted(s))

    df_ketqua['NGAY_TIMEOUT_KHOP'] = ''
    mask_loi = df_ketqua['TRANG_THAI_CAP_NHAT'] == 'TT lệnh lỗi ngày T'
    df_ketqua.loc[mask_loi, 'NGAY_TIMEOUT_KHOP'] = cn_phub[mask_loi].map(_ngay_khop)

    thong_ke = _tinh_thong_ke(df_ketqua)
    _log(f'[PHUB_GOP] Gộp {len(ngay_list)} ngày: Hoàn thành={thong_ke["hoan_thanh"]:,} | '
         f'TT lệnh lỗi ngày T={thong_ke["tt_lenh_loi"]:,} | '
         f'Trạng thái khác={thong_ke["trang_thai_khac"]:,} / tổng {thong_ke["tong"]:,}')
    return df_ketqua, thong_ke


def _khoa_sap_xep_ngay(ngay_dmy: str) -> str:
    """'15/09/2026' -> '20260915' — khoá sắp xếp theo thời gian, không theo chữ."""
    phan = ngay_dmy.split('/')
    if len(phan) == 3:
        d, m, y = phan
        return f'{y}{m.zfill(2)}{d.zfill(2)}'
    return ngay_dmy


def _ngay_gui_lenh(df: pd.DataFrame) -> pd.Series:
    """Tách phần ngày (dd/mm/yyyy) từ cột 'Ngày giờ gửi lệnh' của file pHub —
    Q11 (chốt 18.09.2026, người dùng xác nhận). Định dạng gốc 'dd/mm/yyyy HH:MM:SS'."""
    return df['Ngày giờ gửi lệnh'].fillna('').astype(str).str.strip().str.split(' ').str[0]


def _viet_tong_ket_gop(workbook, ws, ngay_list: list[str], df_ketqua: pd.DataFrame,
                        canh_bao: list[str]) -> None:
    """Sheet TONG_KET (Q7) — bảng tổng chung + bảng tách theo từng ngày (Q11) +
    cảnh báo ngày thiếu GW-cho-pHub (Q6)."""
    fmt_header = workbook.add_format({'bold': True, 'font_size': 10,
                                      'bg_color': '#DDEBF7', 'border': 1})
    fmt_label  = workbook.add_format({'bold': True, 'font_size': 10})
    fmt_num    = workbook.add_format({'font_size': 10, 'num_format': '#,##0'})
    fmt_val    = workbook.add_format({'font_size': 10})
    fmt_warn   = workbook.add_format({'font_size': 10, 'font_color': '#C00000', 'bold': True})

    ws.set_column(0, 0, 45)
    ws.set_column(1, 4, 18)
    row = 0

    ws.write(row, 0, 'Chỉ tiêu (tổng chung)', fmt_header)
    ws.write(row, 1, 'Số giao dịch', fmt_header)
    row += 1

    dem = df_ketqua['TRANG_THAI_CAP_NHAT'].value_counts()
    data = [
        ('Số ngày đã gộp', len(ngay_list)),
        ('', ''),
        ('Hoàn thành (khớp GW, Ghi chú ACSP/ACSC)',   int(dem.get('Hoàn thành', 0))),
        ('TT lệnh lỗi ngày T (khớp TO ko đi kênh)',   int(dem.get('TT lệnh lỗi ngày T', 0))),
        ('Trạng thái khác (không khớp bên nào)',      int(dem.get('Trạng thái khác', 0))),
        ('', ''),
        ('TỔNG',                                      len(df_ketqua)),
    ]
    for label, val in data:
        ws.write_string(row, 0, str(label), fmt_label)
        if isinstance(val, int):
            ws.write(row, 1, val, fmt_num)
        else:
            ws.write(row, 1, val, fmt_val)
        row += 1

    row += 1
    if canh_bao:
        for c in canh_bao:
            ws.write_string(row, 0, f'⚠ {c}', fmt_warn)
            row += 1
        row += 1

    ws.write_string(row, 0, "Theo ngày (cột 'Ngày giờ gửi lệnh' trên file pHub)", fmt_header)
    row += 1
    for col, label in enumerate(['Ngày', 'Hoàn thành', 'TT lệnh lỗi ngày T',
                                  'Trạng thái khác', 'TỔNG']):
        ws.write_string(row, col, label, fmt_header)
    row += 1

    ngay_gui = _ngay_gui_lenh(df_ketqua)
    for ngay_str in sorted((n for n in ngay_gui.unique() if n), key=_khoa_sap_xep_ngay):
        sub = df_ketqua[ngay_gui == ngay_str]
        d   = sub['TRANG_THAI_CAP_NHAT'].value_counts()
        ws.write_string(row, 0, ngay_str, fmt_val)
        ws.write(row, 1, int(d.get('Hoàn thành', 0)), fmt_num)
        ws.write(row, 2, int(d.get('TT lệnh lỗi ngày T', 0)), fmt_num)
        ws.write(row, 3, int(d.get('Trạng thái khác', 0)), fmt_num)
        ws.write(row, 4, len(sub), fmt_num)
        row += 1


def xuat_excel_phub_gop(output_dir: str, ngay_list: list[str], df_ketqua: pd.DataFrame,
                        canh_bao: list[str], log_callback=None) -> str:
    """Xuất 1 file duy nhất `GOP_PHUBLOI_<ngaydau>_<ngaycuoi>.xlsx` — sheet
    TONG_KET + sheet PHUB_KET_QUA (đúng phong cách các exporter khác của module
    này, xem `xuat_excel_gw_den()`)."""
    _log       = log_callback or print
    ngay_sorted = sorted(ngay_list)
    output_path = os.path.join(
        output_dir, f'GOP_PHUBLOI_{ngay_sorted[0]}_{ngay_sorted[-1]}.xlsx')

    workbook = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False})

    ws0 = workbook.add_worksheet('TONG_KET')
    _viet_tong_ket_gop(workbook, ws0, ngay_list, df_ketqua, canh_bao)

    ws1 = workbook.add_worksheet('PHUB_KET_QUA')
    ws1.set_tab_color(_CAM)
    if len(df_ketqua) > CSV_THRESHOLD:
        csv_path = os.path.join(output_dir, 'GOP_PHUBLOI_KET_QUA.csv')
        df_ketqua.to_csv(csv_path, index=False, encoding='utf-8-sig')
        ws1.write(0, 0, f'[Dữ liệu lớn - xem file: {os.path.basename(csv_path)}]')
        ws1.write(1, 0, f'Tổng số dòng: {len(df_ketqua):,}')
        ws1.write(2, 0, 'LƯU Ý: Mở file CSV qua Excel > Data > Từ Văn bản/CSV (không double-click trực tiếp).')
        _log(f'[CSV] GOP_PHUBLOI_KET_QUA: {len(df_ketqua):,} dòng → {csv_path}')
    else:
        _viet_sheet(workbook, ws1, df_ketqua, _CAM)

    workbook.close()
    _log(f'[DONE] File pHub gộp: {output_path}')
    return output_path
